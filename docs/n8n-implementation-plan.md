# n8n GitHub-backed Python deployment

The n8n layer schedules the existing Python CLI. It does not contain another Crunchyroll scraper or forecasting implementation.

## Runtime contract

Each workflow uses n8n's built-in Git node to clone the repository from GitHub into `/tmp/crunchy-calendar-<execution-id>`. It then runs these repository-owned inputs in place:

- `crunchy_calendar/`
- `data/watching.json`
- `data/languages.json`

An exit trap removes the checkout after the CLI finishes. The per-execution path avoids collisions between manual and scheduled runs. Mutable discovery state lives outside the checkout at `$CRUNCHY_CALENDAR_STATE_DIR/discovery.json`; source code is never installed into the n8n instance.

The existing self-hosted n8n execution host must provide `git` and `python3`. Execute Command is unavailable on n8n Cloud and blocked by default in n8n 2.x. Enable it through the existing deployment's `NODES_EXCLUDE` configuration; this repository does not define or replace the n8n deployment.

In queue mode, `git`, `python3`, network access to GitHub and Crunchyroll, and the discovery state directory belong on each worker that can execute these workflows.

## Weekly workflow

[`n8n/github/weekly-forecast.json`](../n8n/github/weekly-forecast.json) contains four nodes:

```text
Monday Morning
  -> Clone Crunchy Calendar
  -> Run Python Forecast
  -> Parse Forecast JSON
```

The Git node clones the repository's default branch. The command invokes `python3 -m crunchy_calendar` from that checkout. It does not pass `--date`, so the CLI selects the current week and uses the previous week as its source. The parser only converts stdout into an n8n item and checks `contract_version`, `predicted`, and `releases`.

Connect the parsed report to a Split Out node on `releases` when a destination requires one item per event. Use `starts_at` for the calendar start time. Keep predicted events tentative because a completed show can produce one final stale prediction.

For a direct ICS result, change the command to `--format ics` and remove the JSON parser. The Execute Command node's `stdout` is then the complete calendar.

## Seasonal discovery

[`n8n/github/season-discovery.json`](../n8n/github/season-discovery.json) clones the same repository and invokes the package with `--discover`. The CLI derives the current season, fetches the catalog, validates it, and updates the persistent ledger. The n8n parser checks the report contract and returns `new_shows` and `seen_shows` unchanged.

To pin a season for a one-time run, add a literal validated value such as `--season summer-2026` to the command. Do not interpolate untrusted workflow input into a shell command.

## Why this path

n8n's native Python Code node cannot access the filesystem or make HTTP requests. Self-hosted third-party Python imports also require a customized task runner. n8n's source-control environments feature syncs n8n workflows rather than application source. Git Clone followed by Execute Command is therefore the smallest path that runs this repository unchanged.

## Import and verification

Publish this repository to GitHub, then use n8n's editor **Import from URL** action with the raw URL of either export. Replace the placeholder clone URL and select a Git credential if the repository is private. The MCP workflow writer on this server rejects Execute Command as an unrecognized workflow node even though its node validator accepts the configuration, so editor URL import is the supported handoff here.

After import:

1. Keep both workflows inactive.
2. Run `Clone Crunchy Calendar` and confirm `success: true`.
3. Run `Run Python Forecast` manually and confirm exit code `0` with a versioned JSON object in `stdout`.
4. Confirm `Parse Forecast JSON` returns the forecast contract.
5. Run discovery twice and confirm the second report moves previously returned titles into `seen_shows`.
6. Publish only after the timezone and output destination are correct.

A nonzero CLI exit fails Execute Command and preserves the CLI error in `stderr`. The parser also fails on empty output, malformed JSON, or an unsupported contract version.
