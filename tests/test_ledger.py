from pathlib import Path

import ledger


def make_row(entity_id: str, name: str = "Acme LLC") -> dict:
    return {
        "Entity ID": entity_id,
        "Entity Name": name,
        "Name Type": "Legal Name",
        "Entity Type": "Limited Liability Company",
        "Principal Office Address": "Somewhere",
        "RA Name": "Agent",
        "Status": "Active",
    }


def test_load_seen_ids_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert ledger.load_seen_ids(tmp_path / "ledger.csv") == set()


def test_record_entities_round_trips_through_load(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"

    total = ledger.record_entities(path, [make_row("1")], first_seen="2026-06-11")

    assert total == 1
    assert ledger.load_seen_ids(path) == {"1"}
    entries = ledger.load_entries(path)
    assert entries == [
        {"Entity ID": "1", "Entity Name": "Acme LLC", "First Seen": "2026-06-11"}
    ]


def test_record_entities_keeps_first_seen_and_skips_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.csv"
    ledger.record_entities(path, [make_row("1")], first_seen="2026-06-10")

    total = ledger.record_entities(
        path,
        [make_row("1"), make_row("2", "Beta LLC")],
        first_seen="2026-06-11",
    )

    assert total == 2
    entries = {entry["Entity ID"]: entry for entry in ledger.load_entries(path)}
    assert entries["1"]["First Seen"] == "2026-06-10"
    assert entries["2"]["First Seen"] == "2026-06-11"


def test_record_entities_ignores_blank_entity_ids(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"

    total = ledger.record_entities(path, [make_row("")], first_seen="2026-06-11")

    assert total == 0
    assert ledger.load_seen_ids(path) == set()


def test_split_new_rows_filters_known_ids_and_keeps_blank_ids() -> None:
    rows = [make_row("1"), make_row("2", "Beta LLC"), make_row("", "No ID LLC")]

    new_rows, known_count = ledger.split_new_rows(rows, {"1"})

    assert known_count == 1
    assert [row["Entity Name"] for row in new_rows] == ["Beta LLC", "No ID LLC"]
