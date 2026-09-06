
# Crunchy Calendar

Crunchy Calendar predicts this week's Crunchyroll releases from the previous week's calendar. It filters by watchlist and audio language, then produces calendar-ready JSON or ICS.

The scheduled deployment is a one-shot container: it generates the ICS, attaches it to an SMTP email, and exits. There is no n8n workflow, queue, database, scheduler daemon, or third-party SDK in the runtime path.

## Scheduled container delivery

Build the image once, then let the host scheduler start it every Monday:

```sh
docker build -t crunchy-calendar:local .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  --env-file /etc/crunchy-calendar/runtime.env \
  --mount type=bind,src=/etc/crunchy-calendar/smtp-password,dst=/run/secrets/smtp-password,readonly \
  crunchy-calendar:local --dry-run
```

`--dry-run` writes the ICS to stdout and never connects to SMTP. Without it, the
container sends the calendar to the configured recipients.

For a Docker host, use the included systemd service and timer. For a cluster,
use the included Helm chart, which adds a private Postfix relay alongside the
CronJob. Both invoke the same image and command.
Read [the container batch deployment guide](docs/container-batch-deployment.md)
before scheduling mail.

## Local Python CLI

The Python version is useful for local testing and ICS generation. It only uses the standard library and works with Python 3.11 or newer.

```sh
python3 -m crunchy_calendar
python3 -m crunchy_calendar --date 2026-08-31 --all
python3 -m crunchy_calendar --date 2026-08-31 --format ics > schedule.ics
python3 -m crunchy_calendar --season summer-2026 --discover \
  --discovery-state data/discovery.json
```

`--date` is the Monday of the week being predicted. Without it, the CLI uses the current week. Known episode numbers advance by one. Finished shows can leave one stale prediction.

The Nix flake remains available as an optional development shell:

```sh
nix develop path:.
```

## Configuration and output

CLI configuration lives in [`data/watching.json`](data/watching.json) and [`data/languages.json`](data/languages.json). The container image copies those files at build time, so a configuration change requires a rebuild and rollout.

Generated reports include `contract_version: 1`. Schemas and storage rules are documented in [`data/README.md`](data/README.md). Generated discovery state, snapshots, and ICS files are ignored by source control.

## Tests

```sh
python3 -m unittest tests.test_core -v
python3 -m unittest tests.test_batch -v
python3 -m unittest tests.test_live -v
python3 -m unittest discover -v
```

The live tests request the real Crunchyroll weekly calendar and anonymous seasonal website feed. They fail on blocked requests, empty responses, or incompatible response changes.
