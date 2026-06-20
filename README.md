# umbra

Detect newly formed Virginia business entities before the scammers reach them.

Named after the darkest part of a shadow, where the scams hide.

For a local visual overview, open [docs/visual/index.html](docs/visual/index.html)
in a browser.

## What is CIS?

The Clerk's Information System (CIS) is Virginia's public database for business entity filings, maintained by the State Corporation Commission (SCC). Every LLC, corporation, and partnership registered in Virginia is recorded here, including formation dates, registered agent details, and principal office addresses. CIS is freely searchable at [cis.scc.virginia.gov](https://cis.scc.virginia.gov). Umbra queries CIS to find newly formed entities by formation date, the same data source that solicitation companies use to target new business owners.

## What this does

Companies like "Virginia Business Filing Center" and "CFSD" scrape Virginia's public business records and send official-looking mailers to new LLCs within days of formation, charging $115–$200 for services that are free or cost $6 from the state. This tool uses the same public data source (Virginia SCC's CIS) so you can warn new business owners first. The query flow filters formation-date searches to active limited liability companies.

## Setup

### Requirements

Install these before running Umbra:

- macOS or Linux shell environment
- Git
- Python 3.13
- `uv`
- Google Chrome

Umbra uses Playwright to drive your locally installed headed Google Chrome.
CIS uses reCAPTCHA v3 and tends to reject headless/browser-bundle automation
paths, so the normal supported path is local Chrome.

### Install

```bash
uv sync
```

This creates the local `.venv` and installs Umbra's Python dependencies from
`pyproject.toml` and `uv.lock`.

### Verify

```bash
uv run umbra --help
uv run umbra daily --dry-run
```

For more detailed new-machine setup instructions, see
[docs/BOOTSTRAP.md](docs/BOOTSTRAP.md).

For day-to-day owner usage, see
[docs/HUMAN_OPERATING_GUIDE.md](docs/HUMAN_OPERATING_GUIDE.md).

## Interactive mode

Run Umbra with no subcommand to launch the guided terminal flow:

```bash
uv run umbra
```

Interactive mode only starts when stdin is a TTY. If you run `umbra` with no
subcommand in a non-interactive context, it falls back to the normal CLI usage
error instead of hanging.

The interactive mode shows a startup banner, walks through the same `search`,
`query`, `batch`, and `daily` options exposed by the regular CLI, prints the
equivalent command before executing it, and can stay open for another run
without restarting Chrome each time. If you choose an output file that already exists,
interactive mode lets you overwrite it, back it up before overwriting, or pick
another name. You can also type `q` or `quit` at any prompt to cancel
immediately. For batch runs, the wizard prompts for chunk size and whether to
resume a compatible unfinished run before printing the equivalent command.

## Commands

### `uv run umbra search`

Look up an entity by name or SCC entity ID.

| Flag | Description |
|------|-------------|
| `--id ID` | SCC entity ID (e.g. `1234567`) |
| `--name NAME` | Business name to search for |
| `--match TYPE` | Name match type: `exact` (default), `contains`, `startswith` |

`--id` and `--name` are mutually exclusive (one is required).

```bash
uv run umbra search --id 1234567
uv run umbra search --name "Acme Holdings"
uv run umbra search --name "Acme" --match contains
```

### `uv run umbra query`

Find active limited liability companies formed on an exact date or within a date range.

| Flag | Description |
|------|-------------|
| `--today` | Formed today |
| `--yesterday` | Formed yesterday |
| `--days N` | Formed in the last N days (`0` means today) |
| `--date MM-DD-YYYY` | Formed on an exact date |
| `--from MM-DD-YYYY` | Start date |
| `--to MM-DD-YYYY` | End date (defaults to today) |

`--today`, `--yesterday`, `--days`, `--date`, and `--from` are mutually exclusive (one is required). `--days 0` is equivalent to `--today`.

If `--from` is provided without `--to`, the end date defaults to today.

```bash
uv run umbra query --today
uv run umbra query --date 03-15-2026
uv run umbra query --days 7
uv run umbra query --from 03-15-2026 --to 03-22-2026
```

### `uv run umbra batch`

Find active limited liability companies across a large date range by splitting
the range into smaller sequential CIS searches and writing one merged CSV.
Each real batch run writes `data/runs/<run-id>/manifest.json` plus
`data/runs/<run-id>/chunks/<chunk-id>.csv` files so interrupted runs can be
resumed without refetching completed chunks.

| Flag | Description |
|------|-------------|
| `--from MM-DD-YYYY` | Start date |
| `--to MM-DD-YYYY` | End date |
| `--chunk TYPE` | Chunk size: `monthly` (default) or `weekly` |
| `--dry-run` | Print planned chunks without opening Chrome |
| `--resume` | Resume a compatible unfinished run from `data/runs/` |
| `--run DIR` | Existing batch run directory under `data/runs/` |
| `--status` | Print run status without opening Chrome |
| `--max-attempts N` | Maximum attempts per chunk (`2` by default) |
| `--keep-going` | Continue after failed chunks and merge succeeded chunks |

Real batch runs require `--csv --output FILE`. `--resume` looks for a
compatible unfinished run under `data/runs/`, while `--run DIR --status`
prints the saved manifest for an existing run without opening Chrome. Batch
output is merged by `Entity ID`, preferring `Legal Name` rows when duplicates
appear across chunks.

```bash
uv run umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025
uv run umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025 --resume
uv run umbra batch --run data/runs/2026-06-07_14-30-22_year --status
uv run umbra batch --from 01-01-2025 --to 12-31-2025 --dry-run
uv run umbra --csv --output march.csv batch --from 03-01-2026 --to 03-31-2026 --chunk weekly
```

### `uv run umbra daily`

Find active limited liability companies formed in a recent trailing window
that Umbra has not seen before. Each run performs one CIS search in the usual
headed Chrome session, dedupes the results against a persistent ledger of
already-seen entity IDs under `data/`, writes only the new entities to the
output CSV, and then records them in the ledger so the next run skips them.

This is the recommended steady-state cadence for fresh LLC detection: run it
once daily (or twice daily) and the overlapping window absorbs CIS indexing
lag and missed days, while the ledger keeps the output limited to genuinely
new LLCs.

| Flag | Description |
|------|-------------|
| `--window N` | Trailing window size in days, including today (`3` by default) |
| `--ledger FILE` | Entity ID ledger file under `data/` (`ledger.csv` by default) |
| `--dry-run` | Print the planned window and ledger without opening Chrome |

Real daily runs require `--csv --output FILE`. Rows without an entity ID
cannot be deduplicated, so they are always included in the output and never
recorded in the ledger. Running `daily` twice on the same day is safe: the
second run reports zero new entities.

```bash
uv run umbra --csv --output new-llcs.csv daily
uv run umbra --csv --output new-llcs.csv daily --window 7
uv run umbra daily --dry-run
```

### Global flags

These go **before** the subcommand.

| Flag | Description |
|------|-------------|
| `--csv` | Output as CSV (mutually exclusive with `--json`) |
| `--json` | Output as JSON (mutually exclusive with `--csv`) |
| `-q`, `--quiet` | Suppress all non-data output |
| `-o`, `--output FILE` | Write results to `data/FILE` instead of stdout |
| `--backup` | Back up an existing output file before overwriting it |
| `--no-color` | Disable colored output |

```bash
uv run umbra --csv --output week.csv query --days 7
uv run umbra --json query --from 03-15-2026 --to 03-22-2026
uv run umbra --csv -q --output yesterday.csv query --yesterday
uv run umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025
```

For large exports, `--csv --output FILE` is the fastest path because Umbra can
write the CIS CSV export directly after normalizing it. Normalization removes
CIS's unnamed trailing column, trims cell values, and collapses duplicate
entity IDs into one row, preferring the `Legal Name` row when CIS returns both
reserved-name and legal-name records for the same entity.

Backups are written to `data/backups/` with versioned names like
`year--2026-04-17_21-03-45.csv`. Umbra keeps only the 5 most recent backups
per original filename. `--backup` only matters when `--output` is set and the
target file already exists.

Batch run manifests and chunk CSVs are written to `data/runs/<run-id>/`. These
are runtime artifacts for retry/resume and are not committed to git.

The daily ledger (`data/ledger.csv` by default) records each entity ID with
its name and the date Umbra first saw it. It is a runtime artifact too, but
deleting it resets `daily` deduplication, so keep it if you rely on the daily
cadence.

All output paths are resolved into the repo-local `data/` directory and any
path components are stripped. For example, `--output ../week.csv` still writes
to `data/week.csv`.

## Architecture

```
umbra.py        CLI entry point. Args, routing, output dispatch.
batch_runner.py Resumable batch manifests, chunk state, and CSV merging.
ledger.py       Persistent cross-run entity ID ledger for daily runs.
interactive.py  Prompt-based interactive mode and command preview builder.
cis_client.py   Playwright browser session, reCAPTCHA, CSV export.
output.py       Formatting: human, CSV, JSON. Color on stderr.
main.py         Compatibility wrapper that delegates to umbra.main().
```

## How it works

1. Playwright launches a headed Chrome window and navigates to the CIS search page
2. The cookie consent dialog is accepted automatically
3. Search fields are populated (entity name, ID, or formation date range; date queries also set entity type to Limited Liability Company and status to Active)
4. The search button is clicked, which triggers Google reCAPTCHA v3 in the background. CIS validates the reCAPTCHA token server-side and stores the result in the ASP.NET session. If the score is too low, umbra dismisses the error and retries (up to 3 attempts)
5. Once CIS accepts the search, the page navigates to the results view
6. Umbra hits CIS's built-in CSV export endpoint (`/EntitySearch/ExportSearchResults?hgridex=5`) using the browser's authenticated session.
7. Umbra normalizes the CSV by keeping documented columns, trimming values, and collapsing duplicate entity IDs while preferring legal-name rows.
8. Batch runs repeat the date-search/export flow sequentially for each chunk in one headed Chrome session, write per-chunk CSVs and manifest state under `data/runs/<run-id>/`, then merge succeeded chunks before writing the final CSV.
9. For human/CSV/JSON output, the normalized results are reformatted and written to stdout or the requested file.
10. The browser is closed

A headed (non-headless) Chrome window is required because reCAPTCHA v3 scores headless browsers as bots (score 0.0). Headed Chrome scores 0.9, well above CIS's 0.5 threshold.

## How solicitation companies find you

1. Query CIS with a formation date filter = today, entity type = Limited Liability Company, and status = Active
2. Export results: entity name, address, registered agent
3. Feed CSV into a print-to-mail service (Lob, PostGrid, etc.)
4. Letter arrives 2–8 days after formation

This tool does steps 1 and 2. Step 3 is up to you.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UMBRA_DELAY` | `2` | Seconds to wait before follow-up CIS requests and retries |
| `UMBRA_USER_AGENT` | Chrome default | Custom User-Agent string |
| `UMBRA_TIMING` | unset / false | Print phase timing and retry diagnostics to stderr |
| `NO_COLOR` | — | Disable colored output when set |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (including zero results) |
| 1 | Runtime failure, interrupted run, or CIS/browser request failure |
| 2 | Invalid usage |
