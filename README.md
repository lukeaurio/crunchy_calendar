# Crunchy Calendar

Crunchy Calendar turns Crunchyroll release data into filtered JSON or ICS. It uses Python's standard library and makes direct HTTPS requests. There is no Playwright, Chromium, browser profile, account login, or third-party tracking service.

The weekly schedule comes from the server-rendered [release calendar](https://www.crunchyroll.com/simulcastcalendar). Seasonal discovery uses the anonymous JSON request made by Crunchyroll's own [simulcast page](https://www.crunchyroll.com/simulcasts/seasons/summer-2026). The seasonal HTML currently returns an error shell, so parsing that shell cannot produce the catalog.

## Run it

```sh
nix develop

# Previous completed week, filtered through data/watching.json
python -m crunchy_calendar

# A specific Monday, including every enabled language
python -m crunchy_calendar --date 2026-08-24 --all

# ICS output
python -m crunchy_calendar --date 2026-08-24 --format ics > schedule.ics

# Record new and previously seen shows for a season
python -m crunchy_calendar --season summer-2026 --discover \
  --discovery-state data/discovery.json
```

The date must be a Monday. Omitting it selects the previous completed Monday-to-Sunday week. Omitting `--season` selects the current winter, spring, summer, or fall slug.

## Watching and languages

Edit `data/watching.json` by hand:

```json
{
  "shows": [
    "The Apothecary Diaries",
    {"title": "One Piece", "aliases": ["ONE PIECE"]}
  ]
}
```

Language rules live in `data/languages.json`. Unsuffixed calendar entries are the Japanese/original track. A title ending in `(English)` is the English track. Add another language by adding its suffix patterns and its key to `enabled`; remove a language by deleting its key from `enabled`.

Discovery writes only to its observation ledger. A new seasonal title appears under `new_shows` on the first run and `seen_shows` later. It never edits the watchlist.

## Tests

```sh
# Parser, validation, storage, filtering, and ICS tests
python -m unittest tests.test_core -v

# Real HTTPS requests to both Crunchyroll sources
python -m unittest tests.test_live -v

# Everything
python -m unittest discover -v
```

The live tests require network access. They fail if Crunchyroll blocks the requests, changes the response shape, or stops returning real releases and series.

## n8n

Self-hosted n8n can run the CLI with an Execute Command node. Import `n8n/season-discovery.json` for the discovery workflow, then check its `/opt/crunchyCalendar` and `/var/lib/crunchy-calendar` paths before enabling it. The workflow validates its season input and output before touching the persistent ledger.

See [docs/n8n-implementation-plan.md](docs/n8n-implementation-plan.md) for the weekly calendar, discovery ledger, and rolling-average plan.
