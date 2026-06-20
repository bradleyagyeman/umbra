# Project State

## Current status
Public-ready snapshot of `umbra`, a Python CLI for querying Virginia SCC CIS
filings and exporting newly formed active LLC records.

## Last completed
- Scrubbed legacy repository links for the public repository namespace.
- Removed local workspace paths from visual documentation.
- Kept generated export data and browser/debug artifacts out of the snapshot.

## In progress
- Fresh public repository preparation.

## Next action
Run the Python test and lint suite in a dependency-installed environment.

## Blockers / questions
- None in the source tree.

## Important decisions
- Publish from a fresh git history.
- Keep CIS export data, local ledgers, virtual environments, browser caches, and
  debug artifacts outside git.

## How to run / verify
```bash
uv run pytest -q
uv run ruff check .
uv run umbra --help
```

## Notes for future sessions
- Playwright and Chrome are required for live CIS queries.
