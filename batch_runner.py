"""Resumable batch-run helpers for Umbra."""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

import output

DATE_FORMAT = "%m-%d-%Y"
MANIFEST_VERSION = 1

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_SKIPPED = "skipped"

RETRYABLE_FAILURES = {
    "BOT_REJECTED",
    "SEARCH_TIMEOUT",
    "EXPORT_TIMEOUT",
    "NAVIGATION_TIMEOUT",
    "UNKNOWN",
}


class BatchRunError(Exception):
    """Raised when a batch manifest cannot be used safely."""


def build_date_chunks(
    date_from: datetime,
    date_to: datetime,
    chunk_size: str = "monthly",
) -> list[tuple[datetime, datetime]]:
    """Split an inclusive date range into monthly or weekly chunks."""
    if date_from > date_to:
        raise BatchRunError("Chunk start date must be before or equal to end date.")

    chunks: list[tuple[datetime, datetime]] = []
    cursor = date_from
    while cursor <= date_to:
        if chunk_size == "monthly":
            month_end_day = calendar.monthrange(cursor.year, cursor.month)[1]
            chunk_end = cursor.replace(day=month_end_day)
        elif chunk_size == "weekly":
            chunk_end = cursor + timedelta(days=6)
        else:
            raise BatchRunError(f"Unsupported batch chunk size: {chunk_size}")

        chunk_end = min(chunk_end, date_to)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def format_cli_date(value: datetime) -> str:
    """Format a date for CLI output."""
    return value.strftime(DATE_FORMAT)


def chunk_id(date_from: str, date_to: str) -> str:
    """Return a stable chunk ID for display-date strings."""
    start = datetime.strptime(date_from, DATE_FORMAT).strftime("%Y-%m-%d")
    end = datetime.strptime(date_to, DATE_FORMAT).strftime("%Y-%m-%d")
    return f"{start}__{end}"


def utc_now() -> str:
    """Return an ISO timestamp in UTC."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_manifest(
    runs_dir: Path,
    output_name: str,
    date_from: datetime,
    date_to: datetime,
    chunk_size: str,
    chunks: Iterable[tuple[datetime, datetime]],
) -> dict:
    """Create a new manifest dictionary for a batch run."""
    now = datetime.now()
    run_id = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{safe_stem(output_name)}"
    run_dir = unique_run_dir(runs_dir, run_id)
    created_at = utc_now()
    manifest_chunks = []

    for index, (chunk_from, chunk_to) in enumerate(chunks, start=1):
        date_from_text = format_cli_date(chunk_from)
        date_to_text = format_cli_date(chunk_to)
        manifest_chunks.append(
            {
                "index": index,
                "chunk_id": chunk_id(date_from_text, date_to_text),
                "date_from": date_from_text,
                "date_to": date_to_text,
                "state": STATE_PENDING,
                "attempt_count": 0,
                "row_count": None,
                "unique_entity_ids": None,
                "csv_path": None,
                "csv_sha256": None,
                "failure_class": None,
                "failure_message": None,
                "started_at": None,
                "finished_at": None,
            }
        )

    return {
        "schema_version": MANIFEST_VERSION,
        "run_id": run_dir.name,
        "created_at": created_at,
        "updated_at": created_at,
        "output_name": Path(output_name).name,
        "chunk_size": chunk_size,
        "date_from": format_cli_date(date_from),
        "date_to": format_cli_date(date_to),
        "state": STATE_PENDING,
        "chunks_dir": "chunks",
        "chunks": manifest_chunks,
    }


def unique_run_dir(runs_dir: Path, run_id: str) -> Path:
    """Return an unused run directory path."""
    candidate = runs_dir / run_id
    counter = 1
    while candidate.exists():
        candidate = runs_dir / f"{run_id}-{counter}"
        counter += 1
    return candidate


def safe_stem(filename: str) -> str:
    """Return a filesystem-safe stem for run IDs."""
    stem = Path(filename).stem or "batch"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip("-")
    return safe or "batch"


def manifest_path(run_dir: Path) -> Path:
    """Return the manifest path for a run directory."""
    return run_dir / "manifest.json"


def save_manifest(run_dir: Path, manifest: dict) -> None:
    """Persist a manifest atomically enough for local CLI use."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / manifest.get("chunks_dir", "chunks")).mkdir(exist_ok=True)
    manifest["updated_at"] = utc_now()
    temp_path = manifest_path(run_dir).with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(manifest_path(run_dir))


def load_manifest(run_dir: Path) -> dict:
    """Load and validate a batch manifest."""
    path = manifest_path(run_dir)
    if not path.exists():
        raise BatchRunError(f"Run manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BatchRunError(f"Run manifest is not valid JSON: {path}") from exc

    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise BatchRunError("Unsupported batch manifest version.")
    if not isinstance(manifest.get("chunks"), list):
        raise BatchRunError("Batch manifest is missing chunk state.")
    return manifest


def compatible_manifest(
    manifest: dict,
    output_name: str,
    date_from: datetime,
    date_to: datetime,
    chunk_size: str,
) -> bool:
    """Return True when an existing manifest matches requested batch inputs."""
    return (
        manifest.get("output_name") == Path(output_name).name
        and manifest.get("date_from") == format_cli_date(date_from)
        and manifest.get("date_to") == format_cli_date(date_to)
        and manifest.get("chunk_size") == chunk_size
    )


def find_latest_compatible_run(
    runs_dir: Path,
    output_name: str,
    date_from: datetime,
    date_to: datetime,
    chunk_size: str,
) -> tuple[Path, dict] | None:
    """Find the latest compatible manifest for --resume."""
    if not runs_dir.exists():
        return None

    candidates: list[tuple[bool, float, Path, dict]] = []
    for path in runs_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            manifest = load_manifest(path)
        except BatchRunError:
            continue
        if compatible_manifest(manifest, output_name, date_from, date_to, chunk_size):
            candidates.append(
                (
                    is_unfinished_manifest(manifest),
                    manifest_path(path).stat().st_mtime,
                    path,
                    manifest,
                )
            )

    if not candidates:
        return None

    _, _, run_dir, manifest = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    return run_dir, manifest


def is_unfinished_manifest(manifest: dict) -> bool:
    """Return True when a manifest has work that can still be resumed."""
    return any(
        chunk.get("state") not in {STATE_SUCCEEDED, STATE_SKIPPED}
        for chunk in manifest.get("chunks", [])
    )


def summarize_manifest(manifest: dict) -> dict[str, int]:
    """Return chunk counts by state."""
    summary = {
        STATE_PENDING: 0,
        STATE_RUNNING: 0,
        STATE_SUCCEEDED: 0,
        STATE_FAILED: 0,
        STATE_SKIPPED: 0,
    }
    for chunk in manifest["chunks"]:
        state = chunk.get("state", STATE_PENDING)
        summary[state] = summary.get(state, 0) + 1
    return summary


def mark_run_state(manifest: dict) -> None:
    """Update the aggregate manifest state from chunk states."""
    states = {chunk.get("state") for chunk in manifest["chunks"]}
    if STATE_FAILED in states:
        manifest["state"] = STATE_FAILED
    elif states <= {STATE_SUCCEEDED, STATE_SKIPPED}:
        manifest["state"] = STATE_SUCCEEDED
    elif STATE_RUNNING in states:
        manifest["state"] = STATE_RUNNING
    else:
        manifest["state"] = STATE_PENDING


def start_chunk(chunk: dict) -> None:
    """Mark a chunk as running."""
    chunk["state"] = STATE_RUNNING
    chunk["attempt_count"] = int(chunk.get("attempt_count") or 0) + 1
    chunk["failure_class"] = None
    chunk["failure_message"] = None
    chunk["started_at"] = utc_now()
    chunk["finished_at"] = None


def succeed_chunk(chunk: dict, csv_path: Path, rows: list[dict]) -> None:
    """Mark a chunk as succeeded after writing its CSV."""
    chunk["state"] = STATE_SUCCEEDED
    chunk["row_count"] = len(rows)
    chunk["unique_entity_ids"] = count_unique_entity_ids(rows)
    chunk["csv_path"] = str(csv_path)
    chunk["csv_sha256"] = sha256_file(csv_path)
    chunk["failure_class"] = None
    chunk["failure_message"] = None
    chunk["finished_at"] = utc_now()


def fail_chunk(chunk: dict, exc: BaseException) -> str:
    """Mark a chunk as failed and return its failure class."""
    failure_class = classify_failure(exc)
    chunk["state"] = STATE_FAILED
    chunk["failure_class"] = failure_class
    chunk["failure_message"] = str(exc)
    chunk["finished_at"] = utc_now()
    return failure_class


def is_retryable_failure(failure_class: str) -> bool:
    """Return whether a failure class should be retried for the same chunk."""
    return failure_class in RETRYABLE_FAILURES


def classify_failure(exc: BaseException) -> str:
    """Classify known CIS/browser failures from exception text."""
    message = str(exc).lower()
    if "recaptcha rejected" in message or "bot" in message:
        return "BOT_REJECTED"
    if "search timed out" in message:
        return "SEARCH_TIMEOUT"
    if "csv export did not return expected data" in message:
        return "CSV_SCHEMA_DRIFT"
    if "temporarily unavailable" in message:
        return "CIS_MAINTENANCE"
    if "export" in message and "timeout" in message:
        return "EXPORT_TIMEOUT"
    if "navigation" in message or "page.click: timeout" in message:
        return "NAVIGATION_TIMEOUT"
    if "timeout" in message:
        return "SEARCH_TIMEOUT"
    return "UNKNOWN"


def chunk_csv_path(run_dir: Path, manifest: dict, chunk: dict) -> Path:
    """Return the CSV path for a chunk."""
    return run_dir / manifest.get("chunks_dir", "chunks") / f"{chunk['chunk_id']}.csv"


def write_chunk_csv(path: Path, rows: list[dict]) -> None:
    """Write a normalized chunk CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as out:
        output.format_csv(rows, out)


def read_chunk_csv(path: Path) -> list[dict]:
    """Read a chunk CSV into row dictionaries."""
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def merge_entity_rows(rows: list[dict]) -> list[dict]:
    """Merge chunk results by entity ID, preferring Legal Name rows."""
    merged_by_id: dict[str, dict] = {}
    fallback_rows: list[dict] = []

    for row in rows:
        cleaned = {
            column: (row.get(column) or "").strip()
            for column in output.COLUMNS
        }
        entity_id = cleaned["Entity ID"]
        if not entity_id:
            fallback_rows.append(cleaned)
            continue

        previous = merged_by_id.get(entity_id)
        if previous is None or (
            previous["Name Type"] != "Legal Name"
            and cleaned["Name Type"] == "Legal Name"
        ):
            merged_by_id[entity_id] = cleaned

    return [*merged_by_id.values(), *fallback_rows]


def merge_succeeded_chunks(run_dir: Path, manifest: dict) -> list[dict]:
    """Read and merge all succeeded chunk CSVs."""
    rows: list[dict] = []
    for chunk in manifest["chunks"]:
        if chunk.get("state") != STATE_SUCCEEDED:
            continue
        csv_path = chunk.get("csv_path")
        if not csv_path:
            continue
        path = Path(csv_path)
        if not path.is_absolute():
            path = run_dir / path
        rows.extend(read_chunk_csv(path))
    return merge_entity_rows(rows)


def count_unique_entity_ids(rows: list[dict]) -> int:
    """Count non-empty unique entity IDs."""
    return len({(row.get("Entity ID") or "").strip() for row in rows if row.get("Entity ID")})


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
