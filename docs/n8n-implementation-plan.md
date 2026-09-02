# n8n Implementation Plan

## Goal

Run one weekly Crunchyroll schedule job and one separate seasonal discovery job. Python owns fetching, parsing, language classification, title matching, and ICS generation. n8n owns scheduling, durable storage, notifications, and calendar delivery.

The Python process has one runtime dependency: Python itself. It sends direct HTTPS requests with the standard library. Seasonal discovery obtains an anonymous short-lived token and requests the same seasonal JSON used by Crunchyroll's simulcast page. No browser state or Crunchyroll account is involved.

## Persistent data

Start with files mounted into the n8n worker:

- `data/watching.json`: titles deliberately marked as currently watching.
- `data/languages.json`: enabled language keys and recognized title suffixes.
- `/var/lib/crunchy-calendar/discovery.json`: first-seen seasonal titles.
- `/var/lib/crunchy-calendar/snapshots/YYYY-MM-DD.json`: successful weekly results.

The discovery ledger and watchlist need separate write permissions. Discovery must never promote a title into the watchlist.

If multiple workers need shared state, move the discovery ledger to DynamoDB. Use normalized `show_key` as the partition key and store `title`, `url`, `season`, `first_seen`, and `last_seen`. A conditional put with `attribute_not_exists(show_key)` identifies a first sighting.

## Weekly schedule workflow

```text
Schedule Trigger
  -> calculate previous Monday
  -> Execute Command
  -> validate JSON
  -> store immutable snapshot
  -> split releases
  -> upsert calendar events
  -> alert on failure
```

1. Run after the target week has finished. Set the workflow timezone explicitly.
2. Calculate the previous Monday as `YYYY-MM-DD`. Reject malformed values in the Code node; the CLI validates Monday alignment again.
3. Run:

   ```sh
   nix develop path:/opt/crunchyCalendar -c python -m crunchy_calendar \
     --date '{{$json.week_start}}' \
     --watching /opt/crunchyCalendar/data/watching.json \
     --languages /opt/crunchyCalendar/data/languages.json \
     --format json
   ```

4. Parse `stdout` as JSON. Require `week_start`, `languages`, and `releases`. Every release must contain non-empty `title`, `language`, `starts_at`, and `url` values.
5. Save the complete response under its week key. Refuse to overwrite an existing snapshot unless the run is explicitly marked as a repair.
6. Split `releases` into n8n items. Upsert events with a key derived from title, episode, start time, and language. Rerunning the workflow should update the same event.
7. Route a non-zero exit, malformed JSON, or empty source result to an alert. Include the target week and n8n execution URL.

ICS can be the first destination. Google Calendar and Home Assistant can consume individual release items later. Home Assistant should remain a destination rather than the workflow database.

## Seasonal discovery workflow

Import [`n8n/season-discovery.json`](../n8n/season-discovery.json). It is inactive after import.

```text
Monthly Schedule Trigger
  -> resolve and validate season
  -> Execute Command
  -> validate discovery JSON
  -> notify about new_shows
```

The command is:

```sh
nix develop path:/opt/crunchyCalendar -c python -m crunchy_calendar \
  --season '{{$json.season}}' \
  --discover \
  --discovery-state /var/lib/crunchy-calendar/discovery.json
```

Accept only `spring-YYYY`, `summer-YYYY`, `fall-YYYY`, or `winter-YYYY`. Keep filesystem paths fixed in the node configuration; do not build paths from incoming workflow data.

The response contains:

- `season`: validated season slug.
- `show_count`: number of real Crunchyroll series returned.
- `new_shows`: titles absent from the ledger before this run.
- `seen_shows`: titles already present.

Require `show_count > 0` and verify that it equals the lengths of both arrays combined. A candidate can trigger a notification or review task. Adding it to `watching.json` remains a separate approval.

## Language handling

The default configuration keeps Japanese/original and English releases:

```json
{
  "enabled": ["japanese", "english"],
  "patterns": {
    "japanese": ["Japanese", "日本語"],
    "english": ["English"]
  }
}
```

Crunchyroll's weekly calendar leaves the original Japanese entry unsuffixed. Localized audio tracks carry a suffix. The rolling language scan can sample 20 dates across 90 days with `discover()` and record every observed suffix before a new language rule is enabled.

## Rolling-average follow-up

Calculate viewing load from the four latest successful weekly snapshots:

```text
snapshots -> releases per watched title -> four-week average -> watch blocks
```

Release events and personal watch blocks need different event keys. A failed scrape must not alter existing watch blocks. Only advance the rolling window after a weekly snapshot passes validation.

## Deployment checks

- Use self-hosted n8n; Execute Command is unavailable on n8n Cloud. Review the [Execute Command node documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/) before enabling it.
- Mount the repository read-only when possible. Grant the n8n user write access only to the ledger, snapshot, and output directories.
- Store calendar, AWS, and notification credentials in n8n credentials.
- Set an execution timeout longer than the CLI's 30-second per-request timeout.
- Prevent overlapping discovery jobs from writing the same local ledger. DynamoDB conditional writes remove this single-worker limitation.
- Preserve stderr and the exit code in failed executions.

## Delivery order

1. Import and run seasonal discovery once. Confirm real titles and series URLs are stored.
2. Build the weekly JSON workflow and preserve one snapshot.
3. Add idempotent calendar writes and failure alerts.
4. Collect four weekly snapshots, then add watch-block averaging.
5. Move the ledger to DynamoDB if more than one n8n worker needs it.

This phase is done when rerunning either workflow produces no duplicate calendar events, discovery reports new versus seen titles without editing the watchlist, and both live scraper tests pass from the n8n host.
