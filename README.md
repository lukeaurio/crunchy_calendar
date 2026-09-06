
# Crunchy Calendar

Crunchy Calendar predicts this week's Crunchyroll releases from the previous week's calendar. It filters by watchlist and audio language, then produces calendar-ready JSON or ICS.

The n8n deployment pulls this repository from GitHub for each execution and runs the existing standard-library Python CLI through an Execute Command node. n8n schedules the command and parses stdout; the Python package owns scraping, language matching, watchlist filtering, prediction, ICS generation, and discovery.

## n8n

Use the GitHub-backed deployment in [`n8n/github/`](n8n/github/):

- [`n8n/github/weekly-forecast.json`](n8n/github/weekly-forecast.json) runs at 6:00 AM each Monday and returns the CLI's forecast JSON.
- [`n8n/github/season-discovery.json`](n8n/github/season-discovery.json) runs monthly and writes the CLI's seen-title ledger to a configured persistent state directory.

The earlier node-native exports remain in `n8n/` for reference, but they are superseded by the Python-backed workflows.

Read [the GitHub runtime instructions](n8n/github/README.md) and [the n8n deployment notes](docs/n8n-implementation-plan.md) before publishing either workflow. No Docker image or Compose stack is part of this project.

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

CLI configuration lives in [`data/watching.json`](data/watching.json) and [`data/languages.json`](data/languages.json). Each n8n run reads those files from its temporary GitHub checkout without translating them into workflow code.

Generated reports include `contract_version: 1`. Schemas and storage rules are documented in [`data/README.md`](data/README.md). Generated discovery state, snapshots, and ICS files are ignored by source control.

## Tests

```sh
python3 -m unittest tests.test_core tests.test_workflows -v
python3 -m unittest tests.test_live -v
python3 -m unittest discover -v
```

The live tests request the real Crunchyroll weekly calendar and anonymous seasonal website feed. They fail on blocked requests, empty responses, or incompatible response changes.
