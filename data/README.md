# Data contracts

This directory contains editable configuration and JSON Schemas. Runtime output stays out of source control.

## Configuration

- `watching.json` lists titles to include. Each entry is either a title string or an object with `title` and optional `aliases`.
- `languages.json` enables audio languages and maps each language to the suffixes Crunchyroll uses. A release title without a language suffix is treated as Japanese.

Both files point to their schemas in `contracts/`. The Python CLI validates the same required fields before making a network request.

## Runtime output

| Data | Contract | Storage |
| --- | --- | --- |
| Weekly forecast | `contracts/forecast.schema.json` | CLI stdout or `data/snapshots/YYYY-MM-DD.json` |
| Seasonal report | `contracts/seasonal-discovery.schema.json` | CLI stdout |
| Discovery ledger | `contracts/discovery-state.schema.json` | `data/discovery.json` or an explicitly mounted state directory |

All contracts use `contract_version: 1`. Consumers must reject versions they do not support. Dates are ISO 8601 strings; `week_start` and `source_week_start` are Mondays in `YYYY-MM-DD` form. A forecast release is always seven days after its `source_starts_at` value.

The ignored paths are `data/discovery.json`, `data/snapshots/`, and `/schedule.ics`. Create them at runtime. Do not add captured Crunchyroll responses or generated reports to this directory.
