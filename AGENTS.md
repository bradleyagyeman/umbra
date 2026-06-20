# Repository Guidelines

## Project Structure & Module Organization

Umbra is a Python CLI for querying Virginia SCC CIS filings.

- `umbra.py`: main CLI entry point, argument parsing, command dispatch, output paths, backups.
- `cis_client.py`: Playwright browser automation and CIS CSV export handling.
- `interactive.py`: guided terminal flow used when `uv run umbra` is run in a TTY with no subcommand.
- `output.py`: human, CSV, and JSON formatting.
- `main.py`: compatibility wrapper delegating to `umbra.main()`.
- `tests/`: pytest coverage for CLI parsing, interactive flows, runtime helpers, and packaging.
- `docs/`: bootstrap instructions and local visual documentation.
- `docs/visual/ai-generated-images/`: generated visual assets referenced by the HTML brief.

Runtime data exports are written under `data/`, which is gitignored.

## Build, Test, and Development Commands

- `uv sync`: install runtime and development dependencies from `pyproject.toml` / `uv.lock`.
- `uv run umbra --help`: verify the CLI entry point.
- `uv run umbra`: launch interactive mode in a TTY.
- `uv run umbra --csv --output week.csv query --days 7`: run a formation-date query and write normalized CSV to `data/week.csv`.
- `./.venv/bin/python -m pytest`: run the test suite.
- `./.venv/bin/ruff check .`: run lint checks.

Google Chrome must be installed locally because Umbra launches headed Chrome through Playwright.

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation, explicit imports, and focused modules. Prefer small functions with direct names such as `resolve_dates`, `prepare_output_path`, and `run_query_csv_export`. Keep CLI behavior in `umbra.py`, browser/session behavior in `cis_client.py`, and presentation formatting in `output.py`.

## Testing Guidelines

Use `pytest`. Add or update tests for meaningful CLI, runtime, data-cleaning, or interactive behavior changes. Test files follow `tests/test_*.py`, and test functions use descriptive `test_*` names. Prefer repository-defined commands before ad hoc checks.

## Commit & Pull Request Guidelines

Use short scoped commit subjects in imperative mood, for example `cli: validate query dates` or `docs: update bootstrap guide`. Keep subjects under 80 characters. Pull requests should describe the change, list validation run, link relevant issues, and include screenshots for visual documentation changes.

## Versioning & Releases

`umbra.py` is the version source of truth; `pyproject.toml` reads the package version dynamically from it. Keep release tags and `umbra.py` in sync: `__version__ = "0.3.1"` must pair with annotated tag `v0.3.1`. Before tagging, verify the intended version, ensure the tag does not already exist, and confirm user-facing docs match the released CLI surface. Use patch bumps for bug fixes and docs tied to released behavior, minor bumps for new commands, flags, or workflow improvements, and major bumps for intentional breaking changes.

## Security & Configuration Tips

Treat CIS responses and all external input as untrusted. Do not write output outside repo-local `data/`; path components in `--output` should remain stripped. Avoid committing generated exports, secrets, local caches, or `.DS_Store` files.
