import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from crunchy_calendar.batch import (
    BatchConfigurationError,
    SmtpConfig,
    build_message,
    load_smtp_config,
    main,
    send_message,
)
from crunchy_calendar.core import Release, make_ics


class FakeSMTP:
    def __init__(self):
        self.ehlo_calls = 0
        self.starttls_context = None
        self.login_args = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def ehlo(self):
        self.ehlo_calls += 1

    def starttls(self, *, context):
        self.starttls_context = context

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


class BatchTests(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "CRUNCHY_CALENDAR_SMTP_HOST": "smtp.example.test",
            "CRUNCHY_CALENDAR_MAIL_FROM": "calendar@example.test",
            "CRUNCHY_CALENDAR_MAIL_TO": "first@example.test, second@example.test",
            "CRUNCHY_CALENDAR_SMTP_PORT": "587",
            "CRUNCHY_CALENDAR_SMTP_SECURITY": "starttls",
        }
        values.update(overrides)
        return values

    def calendar(self):
        return make_ics(
            [
                Release(
                    title="Witch Hat Atelier",
                    language="japanese",
                    episode=11,
                    starts_at="2026-08-31T14:00:00+00:00",
                    url="https://www.crunchyroll.com/watch/example",
                    predicted=True,
                )
            ],
            calendar_name="Crunchyroll Weekly Forecast",
        )

    def test_smtp_config_requires_valid_secret_pair(self):
        with self.assertRaisesRegex(BatchConfigurationError, "must be set together"):
            load_smtp_config(self.config(CRUNCHY_CALENDAR_SMTP_USERNAME="calendar"))
        with self.assertRaisesRegex(BatchConfigurationError, "invalid email"):
            load_smtp_config(self.config(CRUNCHY_CALENDAR_MAIL_TO="not-an-address"))

        with tempfile.TemporaryDirectory() as directory:
            password = Path(directory) / "smtp-password"
            password.write_text("s3cret\n", encoding="utf-8")
            config = load_smtp_config(
                self.config(
                    CRUNCHY_CALENDAR_SMTP_USERNAME="calendar",
                    CRUNCHY_CALENDAR_SMTP_PASSWORD_FILE=str(password),
                )
            )
        self.assertEqual(config.password, "s3cret")
        self.assertEqual(config.recipients, ("first@example.test", "second@example.test"))

    def test_message_has_calendar_attachment_and_deterministic_week_marker(self):
        config = SmtpConfig(
            host="smtp.example.test",
            port=587,
            security="starttls",
            username=None,
            password=None,
            sender="calendar@example.test",
            recipients=("first@example.test",),
            timeout_seconds=30,
        )
        message = build_message(self.calendar(), date(2026, 8, 31), config)
        attachment = next(part for part in message.iter_attachments())
        self.assertEqual(attachment.get_content_type(), "text/calendar")
        self.assertEqual(attachment.get_filename(), "crunchyroll-week-of-2026-08-31.ics")
        self.assertEqual(
            message["Message-ID"],
            "<crunchy-calendar-2026-08-31@example.test>",
        )

    def test_starttls_delivery_authenticates_and_sends_message(self):
        config = SmtpConfig(
            host="smtp.example.test",
            port=587,
            security="starttls",
            username="calendar",
            password="s3cret",
            sender="calendar@example.test",
            recipients=("first@example.test",),
            timeout_seconds=30,
        )
        fake = FakeSMTP()
        with patch("crunchy_calendar.batch.smtplib.SMTP", return_value=fake):
            send_message(build_message(self.calendar(), date(2026, 8, 31), config), config)
        self.assertEqual(fake.ehlo_calls, 2)
        self.assertIsNotNone(fake.starttls_context)
        self.assertEqual(fake.login_args, ("calendar", "s3cret"))
        self.assertIsNotNone(fake.message)

    def test_plain_delivery_is_available_for_a_trusted_local_relay(self):
        config = SmtpConfig(
            host="crunchy-calendar-smtp",
            port=587,
            security="plain",
            username=None,
            password=None,
            sender="calendar@example.test",
            recipients=("first@example.test",),
            timeout_seconds=30,
        )
        fake = FakeSMTP()
        with patch("crunchy_calendar.batch.smtplib.SMTP", return_value=fake):
            send_message(build_message(self.calendar(), date(2026, 8, 31), config), config)
        self.assertEqual(fake.ehlo_calls, 0)
        self.assertIsNone(fake.starttls_context)
        self.assertIsNotNone(fake.message)

    def test_dry_run_prints_ics_without_mail_configuration(self):
        releases = [
            Release(
                title="Witch Hat Atelier",
                language="japanese",
                episode=11,
                starts_at="2026-08-31T14:00:00+00:00",
                url="https://www.crunchyroll.com/watch/example",
                predicted=True,
            )
        ]
        output = io.StringIO()
        with patch("crunchy_calendar.batch.weekly_forecast", return_value=releases), redirect_stdout(output):
            result = main(["--date", "2026-08-31", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("BEGIN:VCALENDAR", output.getvalue())


if __name__ == "__main__":
    unittest.main()
