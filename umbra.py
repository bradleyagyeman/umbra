#!/usr/bin/env python3
"""umbra — detect newly formed Virginia LLCs before the scammers reach them.

Usage:
  umbra search --name "Acme Holdings" --match exact
  umbra search --id 1234567
  umbra query --today --csv --output today.csv
  umbra query --days 7 --json
  umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025
  umbra --csv --output new-llcs.csv daily

Commands:
  search    Look up an entity by name or ID
  query     Find formations by exact date or date range
  batch     Find formations across chunked date ranges
  daily     Find LLCs in a recent trailing window that are new since the last run

Run 'umbra <command> --help' for command-specific usage.
"""

__version__ = "0.3.1"

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import batch_runner
import ledger
from cis_client import CISClient, CISError, MATCH_MAP
from interactive import (
    prompt_run_again,
    run_interactive_wizard,
    should_use_interactive_mode,
)
import output

BACKUP_RETENTION = 5


def non_negative_int(value: str) -> int:
    """Argparse type that rejects negative integers."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def positive_int(value: str) -> int:
    """Argparse type that rejects non-positive integers."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    delay = float(os.environ.get("UMBRA_DELAY", "2"))
    user_agent = os.environ.get("UMBRA_USER_AGENT", "")
    client = CISClient(delay=delay, user_agent=user_agent)
    client.timing = env_flag("UMBRA_TIMING")
    command_started = False
    try:
        if should_use_interactive_mode(raw_argv):
            command_started = True
            return run_interactive_session(client)

        args = parse_args(raw_argv)
        command_started = True
        result = run_command(client, args)
        return finish_command(args, result)
    except CISError as exc:
        output.error(str(exc))
        return 1
    except KeyboardInterrupt:
        output.info("\nInterrupted.")
        return 1
    except Exception as exc:
        output.error(f"Unexpected error: {exc}")
        output.info("If this persists, please open an issue.")
        return 1
    finally:
        client.close()
        if client.timing and command_started:
            output.info(f"[timing] total: {time.perf_counter() - started:.2f}s")

    return 0


def run_interactive_session(client: CISClient) -> int:
    """Handle multiple interactive commands inside one browser session."""
    while True:
        args = run_interactive_wizard()
        result = run_command(client, args)
        exit_code = finish_command(args, result)
        if exit_code != 0:
            return exit_code
        if not prompt_run_again():
            output.info("Closing browser...")
            return 0
        print("")


def run_command(
    client: CISClient, args
) -> tuple[int, str | None, int | None, str | None]:
    """Dispatch a parsed command to its implementation."""
    if args.command == "search":
        return cmd_search(client, args)
    if args.command == "query":
        return cmd_query(client, args)
    if args.command == "batch":
        return cmd_batch(client, args)
    if args.command == "daily":
        return cmd_daily(client, args)
    return 0, None, None, None


def finish_command(
    args, result: tuple[int, str | None, int | None, str | None]
) -> int:
    """Emit any post-command status messages after browser work is done."""
    exit_code, output_path, result_count, backup_path = result
    if result_count is not None and not args.quiet:
        output.success(f"Found {result_count} result(s).")
    if backup_path and not args.quiet:
        output.info(f"Backed up existing file to {backup_path}")
    if output_path and not args.quiet:
        output.info(f"Written to {output_path}")
    return exit_code


def cmd_search(
    client: CISClient, args
) -> tuple[int, str | None, int | None, str | None]:
    """Execute a name or ID search."""
    client.connect()

    if args.csv and args.output:
        output_path, result_count, backup_path = run_search_csv_export(client, args)
        return 0, output_path, result_count, backup_path

    if args.name:
        match_type = MATCH_MAP[args.match]
        results = client.search_by_name(args.name, match_type)
    else:
        results = client.search_by_id(args.id)

    output_path, backup_path = write_results(results, args)
    return 0, output_path, len(results), backup_path


def cmd_query(
    client: CISClient, args
) -> tuple[int, str | None, int | None, str | None]:
    """Find entities formed on an exact date or within a date range."""
    date_from, date_to = resolve_dates(args)

    announce_query_range(args, date_from, date_to)

    client.connect()

    if args.csv and args.output:
        output_path, result_count, backup_path = run_query_csv_export(
            client, args, date_from, date_to
        )
        return 0, output_path, result_count, backup_path

    results = client.search_by_date_range(date_from, date_to)

    output_path, backup_path = write_results(results, args)
    return 0, output_path, len(results), backup_path


def cmd_batch(
    client: CISClient, args
) -> tuple[int, str | None, int | None, str | None]:
    """Run chunked formation-date queries and write merged CSV output."""
    if getattr(args, "status", False):
        run_dir = resolve_existing_run_dir(args.run)
        manifest = batch_runner.load_manifest(run_dir)
        print_batch_status(run_dir, manifest)
        return 0, None, None, None

    if getattr(args, "run", None):
        date_from = date_to = None
        chunks = []
    else:
        date_from, date_to = resolve_batch_dates(args)
        chunks = build_date_chunks(date_from, date_to, args.chunk)

    if getattr(args, "dry_run", False):
        print_batch_plan(chunks)
        return 0, None, None, None

    filepath, backup_path = prepare_output_path(args.output, backup=args.backup)
    run_dir, manifest = prepare_batch_manifest(
        args, filepath, date_from, date_to, chunks
    )
    if not args.quiet:
        output.info(f"Batch run: {run_dir}")

    run_batch_chunks(client, args, run_dir, manifest)

    merged_rows = batch_runner.merge_succeeded_chunks(run_dir, manifest)
    with open(filepath, "w", newline="", encoding="utf-8") as out:
        output.format_csv(merged_rows, out)

    return 0, filepath, len(merged_rows), backup_path


def cmd_daily(
    client: CISClient, args
) -> tuple[int, str | None, int | None, str | None]:
    """Search a trailing window and report LLCs not yet in the ledger."""
    date_from, date_to = resolve_daily_dates(args)
    ledger_path = resolve_ledger_path(args.ledger)

    if not args.quiet:
        output.info(
            f"Daily window: {format_cli_date(date_from)} to "
            f"{format_cli_date(date_to)} ({args.window} day(s))"
        )
        output.info(f"Ledger: {ledger_path}")

    if args.dry_run:
        return 0, None, None, None

    filepath, backup_path = prepare_output_path(args.output, backup=args.backup)

    client.connect()
    rows = client.search_by_date_range(date_from, date_to)
    merged_rows = batch_runner.merge_entity_rows(rows)

    seen_ids = ledger.load_seen_ids(ledger_path)
    new_rows, known_count = ledger.split_new_rows(merged_rows, seen_ids)

    with open(filepath, "w", newline="", encoding="utf-8") as out:
        output.format_csv(new_rows, out)

    total_entities = ledger.record_entities(
        ledger_path, new_rows, first_seen=date_to.strftime("%Y-%m-%d")
    )

    if not args.quiet:
        output.info(
            f"Window entities: {len(merged_rows)}; already in ledger: "
            f"{known_count}; new: {len(new_rows)}"
        )
        output.info(f"Ledger now tracks {total_entities} entities.")

    return 0, filepath, len(new_rows), backup_path


def resolve_daily_dates(args) -> tuple[datetime, datetime]:
    """Convert the daily trailing window into a (from, to) date pair."""
    today = datetime.now()
    return today - timedelta(days=args.window - 1), today


def resolve_ledger_path(filename: str) -> Path:
    """Resolve the ledger file into the repo's data directory."""
    return resolve_data_dir() / os.path.basename(filename)


def prepare_batch_manifest(
    args,
    output_path: str,
    date_from: datetime | None,
    date_to: datetime | None,
    chunks: list[tuple[datetime, datetime]],
) -> tuple[Path, dict]:
    """Load, resume, or create a batch manifest."""
    runs_dir = resolve_runs_dir()
    output_name = os.path.basename(output_path)

    if getattr(args, "run", None):
        run_dir = resolve_existing_run_dir(args.run)
        manifest = batch_runner.load_manifest(run_dir)
        return run_dir, manifest

    if date_from is None or date_to is None:
        raise CISError("Batch date range is required.")

    if getattr(args, "resume", False):
        found = batch_runner.find_latest_compatible_run(
            runs_dir, output_name, date_from, date_to, args.chunk
        )
        if found is not None:
            return found

    manifest = batch_runner.create_manifest(
        runs_dir,
        output_name,
        date_from,
        date_to,
        args.chunk,
        chunks,
    )
    run_dir = runs_dir / manifest["run_id"]
    batch_runner.save_manifest(run_dir, manifest)
    return run_dir, manifest


def run_batch_chunks(
    client: CISClient,
    args,
    run_dir: Path,
    manifest: dict,
) -> None:
    """Run unfinished chunks and update the manifest after each transition."""
    max_attempts = getattr(args, "max_attempts", 2)
    stop_on_failure = getattr(args, "stop_on_failure", True)
    for chunk in manifest["chunks"]:
        if chunk.get("state") == batch_runner.STATE_SUCCEEDED:
            if not args.quiet:
                output.info(
                    f"Skipping succeeded chunk {chunk['index']}/"
                    f"{len(manifest['chunks'])}: {chunk['date_from']} "
                    f"to {chunk['date_to']}"
            )
            continue

        if (
            chunk.get("state") == batch_runner.STATE_FAILED
            and int(chunk.get("attempt_count") or 0) >= max_attempts
        ):
            if stop_on_failure:
                raise CISError(
                    f"Chunk {chunk['chunk_id']} already failed after "
                    f"{chunk['attempt_count']} attempt(s). Increase "
                    "--max-attempts to retry it."
                )
            continue

        while int(chunk.get("attempt_count") or 0) < max_attempts:
            batch_runner.start_chunk(chunk)
            batch_runner.mark_run_state(manifest)
            batch_runner.save_manifest(run_dir, manifest)

            if not args.quiet:
                output.info(
                    f"Searching chunk {chunk['index']}/{len(manifest['chunks'])}: "
                    f"{chunk['date_from']} to {chunk['date_to']} "
                    f"(attempt {chunk['attempt_count']}/{max_attempts})"
                )

            try:
                client.connect()
                rows = client.search_by_date_range(
                    datetime.strptime(chunk["date_from"], "%m-%d-%Y"),
                    datetime.strptime(chunk["date_to"], "%m-%d-%Y"),
                )
                csv_path = batch_runner.chunk_csv_path(run_dir, manifest, chunk)
                batch_runner.write_chunk_csv(csv_path, rows)
                batch_runner.succeed_chunk(chunk, csv_path, rows)
                batch_runner.mark_run_state(manifest)
                batch_runner.save_manifest(run_dir, manifest)
                break
            except Exception as exc:
                failure_class = batch_runner.fail_chunk(chunk, exc)
                batch_runner.mark_run_state(manifest)
                batch_runner.save_manifest(run_dir, manifest)
                client.close()

                can_retry = (
                    int(chunk.get("attempt_count") or 0) < max_attempts
                    and batch_runner.is_retryable_failure(failure_class)
                )
                if can_retry:
                    output.warn(
                        f"chunk {chunk['chunk_id']} failed with "
                        f"{failure_class}; retrying"
                    )
                    continue

                if stop_on_failure:
                    raise CISError(
                        f"Chunk {chunk['chunk_id']} failed with "
                        f"{failure_class}: {exc}"
                    ) from exc
                break


def print_batch_status(run_dir: Path, manifest: dict) -> None:
    """Print a human-readable batch manifest status."""
    summary = batch_runner.summarize_manifest(manifest)
    print(f"Run: {run_dir}")
    print(f"State: {manifest.get('state', batch_runner.STATE_PENDING)}")
    print(f"Output: {manifest.get('output_name')}")
    print(
        "Range: "
        f"{manifest.get('date_from')} to {manifest.get('date_to')} "
        f"({manifest.get('chunk_size')})"
    )
    for state in [
        batch_runner.STATE_PENDING,
        batch_runner.STATE_RUNNING,
        batch_runner.STATE_SUCCEEDED,
        batch_runner.STATE_FAILED,
        batch_runner.STATE_SKIPPED,
    ]:
        print(f"{state}: {summary.get(state, 0)}")
    if summary.get(batch_runner.STATE_FAILED, 0):
        print("next action: rerun with --resume")


def run_search_csv_export(client: CISClient, args) -> tuple[str, int, str | None]:
    """Save normalized CSV search results directly to file."""
    filepath, backup_path = prepare_output_path(args.output, backup=args.backup)
    if args.name:
        match_type = MATCH_MAP[args.match]
        client.search_by_name(args.name, match_type)
    else:
        client.search_by_id(args.id)
    output_path, result_count = client.save_csv_export(filepath)
    return output_path, result_count, backup_path


def run_query_csv_export(
    client: CISClient,
    args,
    date_from: datetime,
    date_to: datetime,
) -> tuple[str, int, str | None]:
    """Save normalized CSV query results directly to file."""
    filepath, backup_path = prepare_output_path(args.output, backup=args.backup)
    client.search_by_date_range(date_from, date_to, fetch=False)
    output_path, result_count = client.save_csv_export(filepath)
    return output_path, result_count, backup_path


def announce_query_range(args, date_from: datetime, date_to: datetime) -> None:
    """Print the searched query range when not in quiet mode."""
    if not args.quiet:
        output.info(
            f"Searching formations: {date_from.strftime('%m-%d-%Y')} "
            f"to {date_to.strftime('%m-%d-%Y')}"
        )


def resolve_dates(args) -> tuple[datetime, datetime]:
    """Convert query flags into a (from, to) date pair."""
    today = datetime.now()

    if args.today:
        return today, today
    if args.yesterday:
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if args.days is not None:
        return today - timedelta(days=args.days), today
    if args.date_exact:
        exact_date = datetime.strptime(args.date_exact, "%m-%d-%Y")
        return exact_date, exact_date

    date_from = datetime.strptime(args.date_from, "%m-%d-%Y")
    date_to = (
        datetime.strptime(args.date_to, "%m-%d-%Y")
        if args.date_to
        else today
    )
    return date_from, date_to


def resolve_batch_dates(args) -> tuple[datetime, datetime]:
    """Convert batch date flags into a validated (from, to) date pair."""
    date_from = datetime.strptime(args.date_from, "%m-%d-%Y")
    date_to = datetime.strptime(args.date_to, "%m-%d-%Y")
    if date_from > date_to:
        raise CISError("Batch start date must be before or equal to end date.")
    return date_from, date_to


def build_date_chunks(
    date_from: datetime,
    date_to: datetime,
    chunk_size: str = "monthly",
) -> list[tuple[datetime, datetime]]:
    """Split an inclusive date range into monthly or weekly chunks."""
    try:
        return batch_runner.build_date_chunks(date_from, date_to, chunk_size)
    except batch_runner.BatchRunError as exc:
        raise CISError(str(exc)) from exc


def merge_entity_rows(rows: list[dict]) -> list[dict]:
    """Merge chunk results by entity ID, preferring Legal Name rows."""
    return batch_runner.merge_entity_rows(rows)


def print_batch_plan(chunks: list[tuple[datetime, datetime]]) -> None:
    """Print a dry-run batch plan to stdout."""
    for index, (chunk_from, chunk_to) in enumerate(chunks, start=1):
        print(
            f"{index}: {format_cli_date(chunk_from)} to {format_cli_date(chunk_to)}"
        )


def format_cli_date(value: datetime) -> str:
    """Format a date for CLI output."""
    return batch_runner.format_cli_date(value)


def write_results(results: list[dict], args) -> tuple[str | None, str | None]:
    """Format and write results to the correct destination."""
    if not results:
        if not args.quiet:
            output.info("No results found.")
        return None, None

    if not args.quiet:
        output.success(f"Found {len(results)} result(s).")

    # Determine output destination
    if args.output:
        filepath, backup_path = prepare_output_path(args.output, backup=args.backup)
        out = open(filepath, "w", newline="", encoding="utf-8")
    else:
        filepath = None
        backup_path = None
        out = sys.stdout

    try:
        if args.csv:
            output.format_csv(results, out)
        elif args.json:
            output.format_json(results, out)
        else:
            output.format_human(results, out)
    finally:
        if args.output:
            out.close()

    return filepath, backup_path


def resolve_output_path(filename: str) -> str:
    """Resolve output paths into the repo's data directory."""
    data_dir = resolve_data_dir()
    return str(data_dir / os.path.basename(filename))


def resolve_data_dir() -> Path:
    """Return Umbra's repo-local data directory."""
    data_dir = Path(os.path.dirname(__file__) or ".") / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def resolve_runs_dir() -> Path:
    """Return Umbra's repo-local batch runs directory."""
    runs_dir = resolve_data_dir() / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


def resolve_existing_run_dir(run: str) -> Path:
    """Resolve a batch run directory safely within data/runs."""
    runs_dir = resolve_runs_dir().resolve()
    candidate = Path(run)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(runs_dir)
    except ValueError as exc:
        raise CISError("Batch run directories must be inside data/runs.") from exc

    if not candidate.is_dir():
        raise CISError(f"Batch run directory does not exist: {candidate}")
    return candidate


def prepare_output_path(filename: str, backup: bool = False) -> tuple[str, str | None]:
    """Resolve the output path and optionally back up an existing file first."""
    output_path = resolve_output_path(filename)
    backup_path = None
    if backup and os.path.exists(output_path):
        backup_path = create_backup(output_path)
        trim_backups(output_path)
    return output_path, backup_path


def create_backup(output_path: str) -> str:
    """Create a versioned backup for an existing output file."""
    destination = Path(output_path)
    backup_dir = destination.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    stem = destination.stem
    suffix = destination.suffix
    candidate = backup_dir / f"{stem}--{timestamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = backup_dir / f"{stem}--{timestamp}-{counter}{suffix}"
        counter += 1

    shutil.copy2(destination, candidate)
    return str(candidate)


def trim_backups(output_path: str, keep: int = BACKUP_RETENTION) -> None:
    """Keep only the newest N backups for the given output filename."""
    destination = Path(output_path)
    backup_dir = destination.parent / "backups"
    if not backup_dir.exists():
        return

    prefix = f"{destination.stem}--"
    suffix = destination.suffix
    backups = sorted(
        [
            path
            for path in backup_dir.iterdir()
            if path.is_file() and path.name.startswith(prefix) and path.suffix == suffix
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[keep:]:
        old_backup.unlink()


# -- arg parsing ------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="umbra",
        description=(
            "Detect newly formed Virginia LLCs before the scammers reach them."
        ),
        epilog=(
            "Examples:\n"
            "  umbra search --id 1234567\n"
            "  umbra search --name \"Acme Holdings\"\n"
            "  umbra query --today --csv --output today.csv\n"
            "  umbra query --date 03-15-2026 --json\n"
            "  umbra query --from 03-15-2026 --to 03-22-2026\n"
            "  umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025\n"
            "  umbra --csv --output new-llcs.csv daily\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"umbra {__version__}"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress all non-data output",
    )
    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument(
        "--json", action="store_true",
        help="output as JSON",
    )
    format_group.add_argument(
        "--csv", action="store_true",
        help="output as CSV",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="disable colored output",
    )
    parser.add_argument(
        "-o", "--output", metavar="FILE",
        help="write results to file instead of stdout",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="back up an existing output file before overwriting it",
    )

    sub = parser.add_subparsers(dest="command")

    # -- search --
    search = sub.add_parser(
        "search",
        help="look up an entity by name or ID",
        description="Look up a Virginia business entity by name or SCC entity ID.",
        epilog=(
            "Examples:\n"
            "  umbra search --id 1234567\n"
            "  umbra search --name \"Acme Holdings\"\n"
            "  umbra --csv search --name \"CFSD\" --match contains\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sg = search.add_mutually_exclusive_group(required=True)
    sg.add_argument("--name", help="business name to search for")
    sg.add_argument("--id", help="SCC entity ID (e.g. 1234567)")
    search.add_argument(
        "-m", "--match",
        choices=["exact", "contains", "startswith"],
        default="exact",
        help="name match type (default: exact)",
    )

    # -- query --
    query = sub.add_parser(
        "query",
        help="find formations by exact date or date range",
        description="Find Virginia business entities formed on a specific date or within a date range.",
        epilog=(
            "Examples:\n"
            "  umbra query --today\n"
            "  umbra --csv --output march15.csv query --date 03-15-2026\n"
            "  umbra --json query --days 7\n"
            "  umbra query --from 03-15-2026 --to 03-22-2026\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_query_arguments(query)

    # -- batch --
    batch = sub.add_parser(
        "batch",
        help="find formations across chunked date ranges",
        description=(
            "Find active Virginia LLC formations across a large date range by "
            "running smaller sequential date chunks."
        ),
        epilog=(
            "Examples:\n"
            "  umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025\n"
            "  umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025 --resume\n"
            "  umbra batch --run data/runs/2026-06-07_14-30-22_year --status\n"
            "  umbra batch --from 01-01-2025 --to 12-31-2025 --dry-run\n"
            "  umbra --csv --output march.csv batch --from 03-01-2026 --to 03-31-2026 --chunk weekly\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    batch.add_argument(
        "--from",
        dest="date_from",
        metavar="MM-DD-YYYY",
        help="start date",
    )
    batch.add_argument(
        "--to",
        dest="date_to",
        metavar="MM-DD-YYYY",
        help="end date",
    )
    batch.add_argument(
        "--chunk",
        choices=["monthly", "weekly"],
        default="monthly",
        help="chunk size for sequential searches (default: monthly)",
    )
    batch.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned chunks without opening Chrome",
    )
    batch.add_argument(
        "--resume",
        action="store_true",
        help="resume a compatible unfinished batch run",
    )
    batch.add_argument(
        "--run",
        metavar="DIR",
        help="batch run directory under data/runs",
    )
    batch.add_argument(
        "--status",
        action="store_true",
        help="print batch run status without opening Chrome",
    )
    batch.add_argument(
        "--max-attempts",
        type=positive_int,
        default=2,
        metavar="N",
        help="maximum attempts per chunk (default: 2)",
    )
    batch.add_argument(
        "--keep-going",
        action="store_true",
        help="continue after failed chunks and merge succeeded chunks",
    )

    # -- daily --
    daily = sub.add_parser(
        "daily",
        help="find LLCs in a recent trailing window that are new since the last run",
        description=(
            "Search a trailing formation-date window for active Virginia LLCs "
            "and report only entities not yet recorded in the local ledger."
        ),
        epilog=(
            "Examples:\n"
            "  umbra --csv --output new-llcs.csv daily\n"
            "  umbra --csv --output new-llcs.csv daily --window 7\n"
            "  umbra daily --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    daily.add_argument(
        "--window",
        type=positive_int,
        default=3,
        metavar="N",
        help="trailing window size in days, including today (default: 3)",
    )
    daily.add_argument(
        "--ledger",
        default="ledger.csv",
        metavar="FILE",
        help="entity ID ledger file under data/ (default: ledger.csv)",
    )
    daily.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned window and ledger without opening Chrome",
    )

    args = parser.parse_args(argv)

    # Handle --no-color by setting env var (output module checks it)
    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    if not args.command:
        parser.print_help(sys.stderr)
        raise SystemExit(2)

    validate_args(parser, args)
    return args


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate cross-argument CLI rules that argparse cannot express."""
    if args.command == "daily":
        if args.json:
            parser.error("daily only supports CSV output in this version")
        if not args.dry_run and (not args.csv or not args.output):
            parser.error("daily requires --csv and --output unless --dry-run is used")
        return

    if args.command != "batch":
        return

    if args.json:
        parser.error("batch only supports CSV output in this version")

    args.stop_on_failure = not args.keep_going

    if args.status:
        if not args.run:
            parser.error("batch --status requires --run DIR")
        return

    if args.run and not args.resume:
        parser.error("batch --run requires --resume unless --status is used")

    if not args.run and (not args.date_from or not args.date_to):
        parser.error("batch requires --from and --to unless --run --status is used")

    if args.date_from or args.date_to:
        if not args.date_from or not args.date_to:
            parser.error("batch requires both --from and --to")
        try:
            resolve_batch_dates(args)
        except ValueError:
            parser.error("batch dates must use MM-DD-YYYY")
        except CISError as exc:
            parser.error(str(exc))

    if not args.dry_run and (not args.csv or not args.output):
        parser.error("batch requires --csv and --output unless --dry-run is used")


def add_query_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the shared date-selection options for the query command."""
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--today", action="store_true", help="formed today")
    group.add_argument("--yesterday", action="store_true", help="formed yesterday")
    group.add_argument(
        "--days",
        type=non_negative_int,
        metavar="N",
        help="formed in the last N days (0 means today)",
    )
    group.add_argument(
        "--date",
        dest="date_exact",
        metavar="MM-DD-YYYY",
        help="formed on an exact date",
    )
    group.add_argument(
        "--from",
        dest="date_from",
        metavar="MM-DD-YYYY",
        help="start date",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        metavar="MM-DD-YYYY",
        help="end date (default: today)",
    )


if __name__ == "__main__":
    sys.exit(main())
