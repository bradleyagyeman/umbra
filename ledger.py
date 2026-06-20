"""Persistent cross-run Entity ID ledger for daily fresh-LLC detection."""

from __future__ import annotations

import csv
from pathlib import Path

LEDGER_COLUMNS = [
    "Entity ID",
    "Entity Name",
    "First Seen",
]


def load_entries(path: str | Path) -> list[dict]:
    """Read ledger entries, returning an empty list for a missing file."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    with open(ledger_path, newline="", encoding="utf-8") as stream:
        return [
            {column: (row.get(column) or "").strip() for column in LEDGER_COLUMNS}
            for row in csv.DictReader(stream)
        ]


def load_seen_ids(path: str | Path) -> set[str]:
    """Return the set of entity IDs already recorded in the ledger."""
    return {entry["Entity ID"] for entry in load_entries(path) if entry["Entity ID"]}


def split_new_rows(
    rows: list[dict], seen_ids: set[str]
) -> tuple[list[dict], int]:
    """Split result rows into unseen rows and a count of already-known rows.

    Rows without an Entity ID cannot be deduplicated, so they always count as
    new and are never recorded in the ledger.
    """
    new_rows: list[dict] = []
    known_count = 0
    for row in rows:
        entity_id = (row.get("Entity ID") or "").strip()
        if entity_id and entity_id in seen_ids:
            known_count += 1
        else:
            new_rows.append(row)
    return new_rows, known_count


def record_entities(path: str | Path, rows: list[dict], first_seen: str) -> int:
    """Add unseen entity IDs to the ledger and return the total entry count.

    Existing entries keep their original First Seen date; duplicate and blank
    entity IDs are skipped.
    """
    ledger_path = Path(path)
    entries = load_entries(ledger_path)
    seen_ids = {entry["Entity ID"] for entry in entries}

    for row in rows:
        entity_id = (row.get("Entity ID") or "").strip()
        if not entity_id or entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        entries.append(
            {
                "Entity ID": entity_id,
                "Entity Name": (row.get("Entity Name") or "").strip(),
                "First Seen": first_seen,
            }
        )

    save_entries(ledger_path, entries)
    return len(entries)


def save_entries(path: Path, entries: list[dict]) -> None:
    """Rewrite the ledger CSV atomically enough for local CLI use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".csv.tmp")
    with open(temp_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LEDGER_COLUMNS)
        writer.writeheader()
        writer.writerows(entries)
    temp_path.replace(path)
