# Umbra Human Operating Guide

This is the short version of how to run Umbra as the project owner.

Umbra has several commands because it also has debugging and backfill tools.
Most days, you only need `daily`.

## The Command You Usually Use

Run this when you want the newest LLCs Umbra has not seen before:

```bash
uv run umbra --csv --output new-llcs.csv daily
```

This does four things:

- Searches CIS for active Virginia LLCs in the recent trailing window.
- Compares those LLCs against `data/ledger.csv`.
- Writes only newly seen LLCs to `data/new-llcs.csv`.
- Updates the ledger so the same LLCs do not appear again next time.

If you run it twice in a row, the second CSV may have zero rows. That is good:
it means Umbra remembered the LLCs from the first run.

## If You Missed A Few Days

Use a wider daily window:

```bash
uv run umbra --csv --output catchup.csv daily --window 7
```

Use this when you skipped a weekend, were away for a few days, or want extra
overlap because CIS may have posted records later than expected.

The ledger keeps this safe. Umbra can look back over dates it already searched
and still only output LLCs it has not seen before.

## If You Missed A Few Weeks

Use a larger window, but keep it reasonable:

```bash
uv run umbra --csv --output catchup.csv daily --window 21
```

This is still one CIS search. It is the simplest catch-up path when the gap is
measured in days or weeks.

If this starts timing out, hits a large-results prompt, or repeatedly gets a
bot rejection, stop and use a batch backfill instead.

## If You Missed Months

Use `batch` for a historical catch-up:

```bash
uv run umbra --csv --output backfill.csv batch --from 01-01-2026 --to 05-31-2026
```

Batch mode splits a big date range into smaller monthly chunks and saves
progress under `data/runs/`. If the run is interrupted, resume it:

```bash
uv run umbra --csv --output backfill.csv batch --from 01-01-2026 --to 05-31-2026 --resume
```

Important: `daily` is the command that uses the persistent ledger to output
only newly seen LLCs. `batch` is for pulling a large date range reliably. Treat
batch output as a backfill/export file to inspect or reconcile.

## Monthly Or Yearly Maintenance

You do not need a special monthly or yearly command if you have been running
`daily` regularly.

Useful maintenance checks:

```bash
uv run umbra daily --dry-run
```

Shows what the next daily run would search without opening Chrome.

```bash
uv run umbra batch --from 01-01-2026 --to 12-31-2026 --dry-run
```

Shows how Umbra would split a large historical range before you run it.

## Debugging A Saved Batch Run

If a batch run stops or you want to see what happened, inspect it without
opening Chrome:

```bash
uv run umbra batch --run data/runs/<run-id> --status
```

This only reads the saved manifest from disk. It does not contact CIS, does
not launch Chrome, and does not change the run.

## Which Files Matter

- `data/new-llcs.csv`: latest newly seen LLCs from a daily run.
- `data/catchup.csv`: newly seen LLCs from a wider daily catch-up run.
- `data/backfill.csv`: larger historical export from batch mode.
- `data/ledger.csv`: Umbra's memory of entity IDs it has already seen.
- `data/runs/<run-id>/manifest.json`: saved status for a batch run.

Do not delete `data/ledger.csv` unless you intentionally want Umbra to forget
everything it has already seen.

## Simple Rule

Use this decision tree:

```text
Running normally?
  use daily

Missed days or a couple weeks?
  use daily --window N

Missed months or need history?
  use batch, then resume if interrupted

Something failed in batch?
  use batch --run ... --status
```
