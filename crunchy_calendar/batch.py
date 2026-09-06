"""One-shot ICS email delivery for scheduled container runs."""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, getaddresses
from pathlib import Path

from .core import current_week_start, make_ics, parse_monday, weekly_forecast


class BatchConfigurationError(ValueError):
    """Raised when the batch process cannot safely send mail."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    security: str
    username: str | None
    password: str | None
    sender: str
    recipients: tuple[str, ...]
    timeout_seconds: float


def _required_env(name: str, environ: dict[str, str]) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise BatchConfigurationError(f"{name} must be set")
    if "\r" in value or "\n" in value:
        raise BatchConfigurationError(f"{name} must not contain newlines")
    return value


def _parse_address_list(value: str, name: str) -> tuple[str, ...]:
    if "\r" in value or "\n" in value:
        raise BatchConfigurationError(f"{name} must not contain newlines")
    addresses = tuple(address.strip() for _, address in getaddresses([value]) if address.strip())
    if not addresses:
        raise BatchConfigurationError(f"{name} must include at least one email address")
    for address in addresses:
        if address.count("@") != 1 or address.startswith("@") or address.endswith("@"):
            raise BatchConfigurationError(f"{name} contains an invalid email address")
    return addresses


def _optional_file(name: str, environ: dict[str, str]) -> str | None:
    path_value = environ.get(name, "").strip()
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        raise BatchConfigurationError(f"{name} must be an absolute path")
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BatchConfigurationError(f"could not read {name}") from exc
    value = value.rstrip("\r\n")
    if not value:
        raise BatchConfigurationError(f"{name} is empty")
    return value


def load_smtp_config(environ: dict[str, str] | None = None) -> SmtpConfig:
    environ = dict(os.environ if environ is None else environ)
    host = _required_env("CRUNCHY_CALENDAR_SMTP_HOST", environ)
    sender = _parse_address_list(_required_env("CRUNCHY_CALENDAR_MAIL_FROM", environ), "CRUNCHY_CALENDAR_MAIL_FROM")
    if len(sender) != 1:
        raise BatchConfigurationError("CRUNCHY_CALENDAR_MAIL_FROM must contain one email address")
    recipients = _parse_address_list(
        _required_env("CRUNCHY_CALENDAR_MAIL_TO", environ), "CRUNCHY_CALENDAR_MAIL_TO"
    )
    try:
        port = int(environ.get("CRUNCHY_CALENDAR_SMTP_PORT", "587"))
    except ValueError as exc:
        raise BatchConfigurationError("CRUNCHY_CALENDAR_SMTP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise BatchConfigurationError("CRUNCHY_CALENDAR_SMTP_PORT must be between 1 and 65535")
    security = environ.get("CRUNCHY_CALENDAR_SMTP_SECURITY", "starttls").strip().lower()
    if security not in {"plain", "starttls", "ssl"}:
        raise BatchConfigurationError(
            "CRUNCHY_CALENDAR_SMTP_SECURITY must be plain, starttls, or ssl"
        )
    username = environ.get("CRUNCHY_CALENDAR_SMTP_USERNAME", "").strip() or None
    password = _optional_file("CRUNCHY_CALENDAR_SMTP_PASSWORD_FILE", environ)
    if bool(username) != bool(password):
        raise BatchConfigurationError(
            "CRUNCHY_CALENDAR_SMTP_USERNAME and CRUNCHY_CALENDAR_SMTP_PASSWORD_FILE must be set together"
        )
    try:
        timeout_seconds = float(environ.get("CRUNCHY_CALENDAR_SMTP_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise BatchConfigurationError("CRUNCHY_CALENDAR_SMTP_TIMEOUT_SECONDS must be a number") from exc
    if timeout_seconds <= 0 or timeout_seconds > 300:
        raise BatchConfigurationError("CRUNCHY_CALENDAR_SMTP_TIMEOUT_SECONDS must be greater than 0 and at most 300")
    return SmtpConfig(host, port, security, username, password, sender[0], recipients, timeout_seconds)


def build_message(calendar: str, week_start: date, config: SmtpConfig) -> EmailMessage:
    if not calendar.startswith("BEGIN:VCALENDAR\r\n") or not calendar.endswith("END:VCALENDAR\r\n"):
        raise ValueError("calendar is not a complete ICS document")
    filename = f"crunchyroll-week-of-{week_start.isoformat()}.ics"
    domain = config.sender.rsplit("@", 1)[1]
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message["Subject"] = f"Crunchyroll forecast — week of {week_start.isoformat()}"
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = f"<crunchy-calendar-{week_start.isoformat()}@{domain}>"
    message.set_content(
        "Attached is the predicted Crunchyroll calendar for the coming week. "
        "Events are tentative because they are inferred from the previous week's schedule."
    )
    message.add_attachment(
        calendar.encode("utf-8"),
        maintype="text",
        subtype="calendar",
        filename=filename,
        params={"charset": "utf-8", "method": "PUBLISH"},
    )
    return message


def send_message(message: EmailMessage, config: SmtpConfig) -> None:
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if config.security == "ssl" else smtplib.SMTP
    smtp_args = (config.host, config.port)
    smtp_kwargs = {"timeout": config.timeout_seconds}
    if config.security == "ssl":
        smtp_kwargs["context"] = context
    with smtp_class(*smtp_args, **smtp_kwargs) as smtp:
        if config.security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if config.username is not None and config.password is not None:
            smtp.login(config.username, config.password)
        smtp.send_message(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and email the weekly Crunchyroll ICS forecast")
    parser.add_argument("--date", help="Monday week to predict (YYYY-MM-DD); defaults to the current week")
    parser.add_argument("--watching", type=Path, default=Path("data/watching.json"))
    parser.add_argument("--languages", type=Path, default=Path("data/languages.json"))
    parser.add_argument("--all", action="store_true", help="ignore the watchlist")
    parser.add_argument("--dry-run", action="store_true", help="write the ICS to stdout without sending mail")
    args = parser.parse_args(argv)
    try:
        target_week = parse_monday(args.date) if args.date else current_week_start()
        config = None if args.dry_run else load_smtp_config()
        calendar = make_ics(
            weekly_forecast(target_week, args.watching, args.languages, args.all),
            calendar_name="Crunchyroll Weekly Forecast",
        )
        if args.dry_run:
            sys.stdout.write(calendar)
            return 0
        message = build_message(calendar, target_week, config)
        send_message(message, config)
        print(f"sent {len(config.recipients)} recipient(s) the ICS for {target_week.isoformat()}")
        return 0
    except (BatchConfigurationError, OSError, RuntimeError, ValueError, smtplib.SMTPException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
