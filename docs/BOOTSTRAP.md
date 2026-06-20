## Bootstrap

### Purpose

This document covers the minimum steps required to bring `umbra` up on a new
machine for local development and use.

### Prerequisites

- macOS or Linux shell environment
- Git
- Python 3.13
- `uv`
- Google Chrome installed locally

`umbra` uses Playwright, but it launches your installed Google Chrome with
`channel="chrome"` rather than Playwright's bundled Chromium browser.

### Clone The Repository

```bash
git clone https://github.com/bradagy/umbra.git
cd umbra
```

### Install Dependencies

```bash
uv sync
```

This creates or updates the local `.venv` and installs both runtime and dev
dependencies from `pyproject.toml` / `uv.lock`.

### Verify The Environment

Check that the CLI is available:

```bash
uv run umbra --help
```

Check that tests run:

```bash
./.venv/bin/python -m pytest
```

Run lint checks:

```bash
./.venv/bin/ruff check .
```

### First Interactive Run

```bash
uv run umbra
```

This should:

- render the `UMBRA` banner
- launch the interactive wizard
- open Google Chrome only when a real search, query, batch chunk, or daily run is executed

Interactive mode only starts when stdin is a TTY. If `umbra` is run without a
subcommand in a non-interactive context, it falls back to the normal CLI usage
error.

### Common Commands

Search by entity ID:

```bash
uv run umbra search --id 1234567
```

Search by business name:

```bash
uv run umbra search --name "Acme Holdings" --match exact
```

Query today's newly formed active LLCs:

```bash
uv run umbra query --today
```

Query active LLCs formed on one exact date:

```bash
uv run umbra query --date 03-15-2026
```

Write large CSV output directly to file:

```bash
uv run umbra --csv --output today.csv query --today
```

Run a large range as smaller sequential chunks and merge the CSV:

```bash
uv run umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025
```

Resume a compatible unfinished batch run:

```bash
uv run umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025 --resume
```

Inspect a saved batch run without opening Chrome:

```bash
uv run umbra batch --run data/runs/<run-id> --status
```

Preview the batch chunks without opening Chrome:

```bash
uv run umbra batch --from 01-01-2025 --to 12-31-2025 --dry-run
```

Run the daily trailing-window check for LLCs not seen in earlier runs:

```bash
uv run umbra --csv --output new-llcs.csv daily
```

Preview the daily window and ledger without opening Chrome:

```bash
uv run umbra daily --dry-run
```

Back up an existing file before overwrite:

```bash
uv run umbra --csv --output today.csv --backup query --today
```

### Output Behavior

- Output files are written to `data/`
- Any path components in `--output` are stripped, so outputs stay inside `data/`
- CIS CSV exports are normalized before output
- Normalization removes CIS's unnamed trailing column
- Duplicate entity IDs are collapsed into one row, preferring `Legal Name`
- Batch output is one merged CSV deduped by `Entity ID`
- Batch manifests are written to `data/runs/<run-id>/manifest.json`
- Per-chunk CSVs are written to `data/runs/<run-id>/chunks/<chunk-id>.csv`
- Resumed batch runs reuse the same run directory and skip chunks that already succeeded
- `--run DIR --status` reads the saved manifest without opening Chrome
- Daily runs write only previously unseen entities to the output CSV
- The daily ledger lives at `data/ledger.csv` by default and records each entity ID with its first-seen date
- Backup files are written to `data/backups/`
- Backups are versioned with timestamped names
- The app keeps only the 5 newest backups per original filename
- `--backup` only has an effect when the chosen output file already exists

### Environment Variables

- `UMBRA_DELAY`
  - default: `2`
  - seconds to wait before follow-up CIS requests and retries
- `UMBRA_USER_AGENT`
  - default: Chrome default
  - overrides the browser user agent
- `UMBRA_TIMING`
  - default: unset / false
  - prints runtime phase timings and reCAPTCHA retry count
- `NO_COLOR`
  - disables colored terminal status output when set

Example:

```bash
UMBRA_DELAY=0 uv run umbra --csv --output today.csv query --today
UMBRA_TIMING=1 uv run umbra --csv --output today.csv query --today
```

### Troubleshooting

If Chrome is missing:

- install Google Chrome locally
- rerun:

```bash
uv run umbra --help
```

If CIS rejects requests or is slow:

- retry later
- reduce the queried time range
- keep `UMBRA_DELAY` at its default unless you are intentionally optimizing for
  speed

If output files are being overwritten during testing:

- use `--backup`
- or choose a different output filename in interactive mode

### Repo Notes

- `README.md` documents the user-facing CLI behavior
- `docs/visual/index.html` provides a local visual overview of the project
- `AGENTS.md` documents repo-specific agent guidance and project context
- `tests/` contains regression coverage for CLI, interactive, packaging, and
  runtime behaviors
