# GitHub-backed n8n workflows

These exports keep the application in GitHub. Each execution uses n8n's built-in
Git node to clone the repository into a unique temporary directory, invokes the
existing Python CLI with Execute Command, and removes the checkout. There is no
second scraper in the workflow and no custom n8n image.

## Requirements

- Self-hosted n8n. Execute Command is unavailable on n8n Cloud.
- `git` and `python3` must be available to the process that executes the
  workflow. In queue mode, that means every relevant worker.
- Execute Command must be enabled. n8n 2.x blocks it by default; remove
  `n8n-nodes-base.executeCommand` from `NODES_EXCLUDE` and restart the existing
  n8n service using its normal deployment procedure.
- The GitHub repository must contain `crunchy_calendar/`, `data/watching.json`,
  and `data/languages.json` on its default branch.

No Python packages are installed. Crunchy Calendar uses the Python standard
library.

## Import directly from GitHub

For a public repository, open a workflow in n8n and choose **three dots ->
Import from URL**. Use one of these raw URLs:

```text
https://raw.githubusercontent.com/OWNER/REPOSITORY/BRANCH/n8n/github/weekly-forecast.json
https://raw.githubusercontent.com/OWNER/REPOSITORY/BRANCH/n8n/github/season-discovery.json
```

GitHub's raw URL for a private repository requires authentication that n8n's
editor URL importer can't supply. In that case, download the export while
signed in to GitHub and use **Import from File** instead.

The exports are inactive and already point at
`https://github.com/lukeaurio/crunchy_calendar.git`.

For a public source repository, leave Authentication set to **None**. For a private
repository, create an n8n Git credential using the GitHub username and a
read-only personal access token as the password, then select that credential in
the clone node. Do not put a token in the repository URL or exported JSON.

The Git node clones the default branch on every run, so a newly pushed version
is picked up automatically. Pinning a release requires adding a Git **Switch
Branch** node after the clone and selecting a tag or branch explicitly.

## Weekly forecast

[`weekly-forecast.json`](weekly-forecast.json) runs each Monday at 06:00 in the
workflow timezone. The CLI receives no `--date`, so it predicts the current week
from the previous week's Crunchyroll calendar. The final node parses stdout and
rejects empty, malformed, or incompatible output.

The temporary checkout is `/tmp/crunchy-calendar-<execution-id>`. The command
validates the execution ID and required repository files before running Python.
An exit trap removes the checkout on success, ordinary failure, or cancellation.

## Seasonal discovery

[`season-discovery.json`](season-discovery.json) uses the same temporary checkout
and runs the CLI's existing `--discover` mode monthly. Only its discovery ledger
persists locally; application source does not.

Set `CRUNCHY_CALENDAR_STATE_DIR` on the existing n8n service to a dedicated,
writable, persistent absolute directory. For example:

```text
CRUNCHY_CALENDAR_STATE_DIR=/srv/n8n-state/crunchy-calendar
```

The workflow rejects a missing, relative, or broad state directory and writes
`discovery.json` beneath it. Do not point it at `/`, `/tmp`, `/var`, `/home`, or
the checkout directory. In queue mode, workers must share this state directory
or discovery must be pinned to one worker.

## First-run checks

Keep each workflow inactive while testing:

1. Run the clone node and confirm it returns `success: true`.
2. Run the Python node and confirm exit code `0` with JSON in `stdout`.
3. Confirm the parser returns `contract_version: 1`.
4. For discovery, run twice; the second run should move previously returned
   titles from `new_shows` to `seen_shows`.
5. Publish only after selecting the Git credential, timezone, and downstream
   calendar or notification node.

If the clone succeeds but Execute Command cannot start, its temporary checkout
may remain. The per-execution path prevents collisions; it can be removed after
confirming no execution with that ID is running.
