# Container batch deployment

The weekly job is intentionally a one-shot process:

```text
scheduler -> container -> Crunchyroll forecast -> ICS attachment -> SMTP relay -> exit
```

The image contains the application and its checked-in watchlist/language configuration. It does not clone GitHub at runtime, run a cron daemon, or retain a database. Build and publish a new image when either code or configuration changes.

## SMTP is the delivery boundary

Email cannot be delivered without an SMTP server. Reuse an SMTP relay you already operate or trust for your domain. Do not attempt direct-to-MX delivery from a disposable container: cloud and residential networks commonly block port 25, and deliverability requires DNS and IP reputation work that does not belong in this project.

The batch command only needs the Python standard library. It supports TLS for normal SMTP relays. `plain` is only appropriate for a private, trusted network hop such as the internal Postfix Service installed by this project's Helm chart; it must never point at a public SMTP endpoint.

| Variable | Required | Example |
| --- | --- | --- |
| `CRUNCHY_CALENDAR_MAIL_FROM` | yes | `calendar-bot@example.com` |
| `CRUNCHY_CALENDAR_MAIL_TO` | yes | `you@example.com,other@example.com` |
| `CRUNCHY_CALENDAR_SMTP_HOST` | yes | `mail.example.com` |
| `CRUNCHY_CALENDAR_SMTP_PORT` | no | `587` |
| `CRUNCHY_CALENDAR_SMTP_SECURITY` | no | `starttls`, `ssl`, or trusted-local `plain` |
| `CRUNCHY_CALENDAR_SMTP_USERNAME` | if relay authenticates | `calendar-bot@example.com` |
| `CRUNCHY_CALENDAR_SMTP_PASSWORD_FILE` | with username | `/run/secrets/smtp-password` |
| `CRUNCHY_CALENDAR_SMTP_TIMEOUT_SECONDS` | no | `30` |

Authentication is optional only for a trusted local relay. Username and password-file settings must be supplied together. The process rejects malformed addresses, unsafe newlines, relative password paths, and invalid ports before it fetches Crunchyroll.

Every message has a week-specific Message-ID and the existing week-specific ICS event UIDs. This makes a manual re-send less disruptive to mail and calendar clients, but it is not a database-backed exactly-once guarantee. The supplied schedulers deliberately avoid automatic retry after a mail attempt; rerun the job manually after investigating a failure.

## Build and manually prove the image

```sh
docker build -t crunchy-calendar:local .

docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  crunchy-calendar:local --date 2026-08-31 --dry-run > schedule.ics
```

Inspect `schedule.ics` before configuring SMTP. A real send uses a root-readable password file and an env file that is not committed:

```sh
install -d -m 0700 /etc/crunchy-calendar
install -m 0600 deploy/docker/runtime.env.example /etc/crunchy-calendar/runtime.env
install -m 0600 /path/to/your/smtp-password /etc/crunchy-calendar/smtp-password

docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  --env-file /etc/crunchy-calendar/runtime.env \
  --mount type=bind,src=/etc/crunchy-calendar/smtp-password,dst=/run/secrets/smtp-password,readonly \
  crunchy-calendar:local --date 2026-08-31
```

The image should be referenced by a release tag or immutable digest in scheduled deployments. Docker's `--rm` removes the completed short-lived container; `--read-only` and the small `/tmp` tmpfs limit writable state. See the [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run).

## Docker host: systemd timer

Copy `deploy/docker/crunchy-calendar.service` to `/etc/systemd/system/` and set `CRUNCHY_CALENDAR_IMAGE` in `/etc/crunchy-calendar/runtime.env` to an immutable image reference. Copy `deploy/docker/crunchy-calendar.timer` beside it. The timer uses the host's local timezone, so set the host timezone to the timezone in which Monday 06:00 should occur.

```sh
systemctl daemon-reload
systemctl enable --now crunchy-calendar.timer
systemctl start crunchy-calendar.service
systemctl status crunchy-calendar.timer
journalctl -u crunchy-calendar.service
```

The systemd timer is the default Docker-host recommendation because it provides normal service logs and a persistent missed-run policy without adding another container. A host crontab that invokes the same `docker run` command is also valid when systemd is unavailable.

## Kubernetes: Helm chart

The publishable chart in [`charts/crunchy-calendar`](../charts/crunchy-calendar) replaces the old standalone manifests. It creates a restricted CronJob and a private Postfix relay Service, with all installation-specific settings supplied through a values file. See [the chart README](../charts/crunchy-calendar/README.md) for a complete values file, relay credential Secret, install command, and manual Job test.

## Failure behavior

- Invalid settings, failure to fetch Crunchyroll, invalid ICS, TLS failure, SMTP authentication failure, and recipient rejection exit with code `2`.
- Kubernetes records the failed Job; systemd records the service failure in the journal.
- No background retry is performed after a send attempt because SMTP acknowledgement can be ambiguous and duplicate mail is worse than a visible failed run.
- A Cloudflare challenge or other Crunchyroll network block is a failed run, never an empty calendar. Fix egress before enabling the schedule.
