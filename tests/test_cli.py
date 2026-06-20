import sys
from datetime import timedelta
from pathlib import Path

import pytest

import batch_runner
import ledger
import umbra


def parse_args(monkeypatch: pytest.MonkeyPatch, *argv: str):
    monkeypatch.setattr(sys, "argv", ["umbra", *argv])
    return umbra.parse_args()


def test_query_days_zero_maps_to_today(monkeypatch: pytest.MonkeyPatch) -> None:
    args = parse_args(monkeypatch, "query", "--days", "0")

    date_from, date_to = umbra.resolve_dates(args)

    assert date_from.date() == date_to.date()
    assert date_to.date() == umbra.datetime.now().date()


def test_query_days_positive_keeps_requested_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(monkeypatch, "query", "--days", "3")

    date_from, date_to = umbra.resolve_dates(args)

    assert date_to - date_from == timedelta(days=3)


def test_query_days_rejects_negative_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "query", "--days", "-1"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_query_date_exact_maps_to_single_day(monkeypatch: pytest.MonkeyPatch) -> None:
    args = parse_args(monkeypatch, "query", "--date", "03-15-2026")

    date_from, date_to = umbra.resolve_dates(args)

    assert date_from == umbra.datetime(2026, 3, 15)
    assert date_to == umbra.datetime(2026, 3, 15)


def test_batch_parse_defaults_to_monthly_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch,
        "--csv",
        "--output",
        "year.csv",
        "batch",
        "--from",
        "01-01-2025",
        "--to",
        "12-31-2025",
    )

    assert args.command == "batch"
    assert args.chunk == "monthly"
    assert args.dry_run is False


def test_batch_requires_csv_output_for_real_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["umbra", "batch", "--from", "01-01-2025", "--to", "12-31-2025"],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_batch_dry_run_allows_no_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch,
        "batch",
        "--from",
        "01-01-2025",
        "--to",
        "12-31-2025",
        "--dry-run",
    )

    assert args.dry_run is True
    assert args.output is None


def test_batch_status_allows_run_without_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch,
        "batch",
        "--run",
        "data/runs/example",
        "--status",
    )

    assert args.command == "batch"
    assert args.run == "data/runs/example"
    assert args.status is True


def test_batch_resume_accepts_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch,
        "--csv",
        "--output",
        "year.csv",
        "batch",
        "--from",
        "01-01-2025",
        "--to",
        "12-31-2025",
        "--resume",
        "--max-attempts",
        "3",
    )

    assert args.resume is True
    assert args.max_attempts == 3


def test_batch_run_requires_resume_unless_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "umbra",
            "--csv",
            "--output",
            "year.csv",
            "batch",
            "--run",
            "data/runs/example",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_batch_rejects_inverted_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "umbra",
            "--csv",
            "--output",
            "year.csv",
            "batch",
            "--from",
            "12-31-2025",
            "--to",
            "01-01-2025",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_build_date_chunks_splits_monthly_across_year_boundary() -> None:
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 12, 15),
        umbra.datetime(2026, 2, 10),
    )

    assert chunks == [
        (umbra.datetime(2025, 12, 15), umbra.datetime(2025, 12, 31)),
        (umbra.datetime(2026, 1, 1), umbra.datetime(2026, 1, 31)),
        (umbra.datetime(2026, 2, 1), umbra.datetime(2026, 2, 10)),
    ]


def test_build_date_chunks_splits_weekly() -> None:
    chunks = umbra.build_date_chunks(
        umbra.datetime(2026, 3, 1),
        umbra.datetime(2026, 3, 15),
        "weekly",
    )

    assert chunks == [
        (umbra.datetime(2026, 3, 1), umbra.datetime(2026, 3, 7)),
        (umbra.datetime(2026, 3, 8), umbra.datetime(2026, 3, 14)),
        (umbra.datetime(2026, 3, 15), umbra.datetime(2026, 3, 15)),
    ]


def test_merge_entity_rows_dedupes_and_prefers_legal_name() -> None:
    rows = [
        {
            "Entity ID": "1",
            "Entity Name": "Acme",
            "Name Type": "Reserved Name",
            "Entity Type": "Limited Liability Company",
            "Principal Office Address": "Somewhere",
            "RA Name": "Agent",
            "Status": "Active",
        },
        {
            "Entity ID": "1",
            "Entity Name": "Acme LLC",
            "Name Type": "Legal Name",
            "Entity Type": "Limited Liability Company",
            "Principal Office Address": "Somewhere",
            "RA Name": "Agent",
            "Status": "Active",
        },
    ]

    assert umbra.merge_entity_rows(rows)[0]["Entity Name"] == "Acme LLC"


def test_batch_manifest_round_trip(tmp_path: Path) -> None:
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 2, 1),
    )
    manifest = batch_runner.create_manifest(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 2, 1),
        "monthly",
        chunks,
    )
    run_dir = tmp_path / "runs" / manifest["run_id"]

    batch_runner.save_manifest(run_dir, manifest)
    loaded = batch_runner.load_manifest(run_dir)

    assert loaded["output_name"] == "year.csv"
    assert [chunk["state"] for chunk in loaded["chunks"]] == ["pending", "pending"]


def test_find_latest_compatible_run(tmp_path: Path) -> None:
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
    )
    manifest = batch_runner.create_manifest(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
        chunks,
    )
    run_dir = tmp_path / "runs" / manifest["run_id"]
    batch_runner.save_manifest(run_dir, manifest)

    found = batch_runner.find_latest_compatible_run(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
    )

    assert found is not None
    assert found[0] == run_dir


def test_find_latest_compatible_run_prefers_unfinished(
    tmp_path: Path,
) -> None:
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
    )
    unfinished = batch_runner.create_manifest(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
        chunks,
    )
    unfinished["chunks"][0]["state"] = batch_runner.STATE_FAILED
    unfinished_dir = tmp_path / "runs" / unfinished["run_id"]
    batch_runner.save_manifest(unfinished_dir, unfinished)

    finished = batch_runner.create_manifest(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
        chunks,
    )
    finished["chunks"][0]["state"] = batch_runner.STATE_SUCCEEDED
    finished_dir = tmp_path / "runs" / finished["run_id"]
    batch_runner.save_manifest(finished_dir, finished)

    found = batch_runner.find_latest_compatible_run(
        tmp_path / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
    )

    assert found is not None
    assert found[0] == unfinished_dir


def test_daily_parse_uses_window_and_ledger_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch, "--csv", "--output", "new-llcs.csv", "daily"
    )

    assert args.command == "daily"
    assert args.window == 3
    assert args.ledger == "ledger.csv"
    assert args.dry_run is False


def test_daily_requires_csv_output_for_real_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "daily"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_daily_dry_run_allows_no_output(monkeypatch: pytest.MonkeyPatch) -> None:
    args = parse_args(monkeypatch, "daily", "--dry-run")

    assert args.dry_run is True
    assert args.output is None


def test_daily_rejects_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["umbra", "--json", "--output", "new-llcs.json", "daily"],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_daily_rejects_non_positive_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["umbra", "--csv", "--output", "new-llcs.csv", "daily", "--window", "0"],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_resolve_daily_dates_covers_trailing_window_including_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(
        monkeypatch, "--csv", "--output", "new-llcs.csv", "daily", "--window", "3"
    )

    date_from, date_to = umbra.resolve_daily_dates(args)

    assert date_to.date() == umbra.datetime.now().date()
    assert date_to - date_from == timedelta(days=2)


def daily_args(**overrides) -> "umbra.argparse.Namespace":
    args = umbra.argparse.Namespace(
        command="daily",
        quiet=False,
        csv=True,
        json=False,
        output="new-llcs.csv",
        backup=False,
        window=3,
        ledger="ledger.csv",
        dry_run=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_cmd_daily_dry_run_does_not_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))

    class FakeClient:
        def connect(self):
            raise AssertionError("dry-run should not connect")

    result = umbra.cmd_daily(FakeClient(), daily_args(dry_run=True, output=None))

    assert result == (0, None, None, None)
    stderr = capsys.readouterr().err
    assert "Daily window:" in stderr
    assert "ledger.csv" in stderr


def test_cmd_daily_writes_only_new_rows_and_updates_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    ledger_path = tmp_path / "data" / "ledger.csv"
    ledger.record_entities(
        ledger_path,
        [
            {
                "Entity ID": "1",
                "Entity Name": "Acme LLC",
            }
        ],
        first_seen="2026-06-10",
    )

    class FakeClient:
        def connect(self):
            pass

        def search_by_date_range(self, date_from, date_to):
            return [
                {
                    "Entity ID": "1",
                    "Entity Name": "Acme LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Somewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                },
                {
                    "Entity ID": "2",
                    "Entity Name": "Beta",
                    "Name Type": "Reserved Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Elsewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                },
                {
                    "Entity ID": "2",
                    "Entity Name": "Beta LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Elsewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                },
            ]

    _, output_path, result_count, _ = umbra.cmd_daily(FakeClient(), daily_args(quiet=True))

    assert result_count == 1
    written = Path(output_path).read_text(encoding="utf-8")
    assert "Beta LLC" in written
    assert "Acme LLC" not in written
    assert ledger.load_seen_ids(ledger_path) == {"1", "2"}


def test_cmd_daily_second_run_finds_nothing_new(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))

    class FakeClient:
        def connect(self):
            pass

        def search_by_date_range(self, date_from, date_to):
            return [
                {
                    "Entity ID": "2",
                    "Entity Name": "Beta LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Elsewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                }
            ]

    first = umbra.cmd_daily(FakeClient(), daily_args(quiet=True))
    second = umbra.cmd_daily(FakeClient(), daily_args(quiet=True))

    assert first[2] == 1
    assert second[2] == 0
    ledger_path = tmp_path / "data" / "ledger.csv"
    assert ledger.load_seen_ids(ledger_path) == {"2"}


def test_watch_command_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "watch", "--date", "03-15-2026"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


def test_version_flag_reports_current_module_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"umbra {umbra.__version__}"


def test_search_help_examples_put_global_flags_before_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "search", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 0
    assert 'umbra --csv search --name "CFSD" --match contains' in (
        capsys.readouterr().out
    )


def test_query_help_examples_put_global_flags_before_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["umbra", "query", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "umbra --csv --output march15.csv query --date 03-15-2026" in help_text
    assert "umbra --json query --days 7" in help_text


def test_output_formats_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["umbra", "--csv", "--json", "search", "--id", "1234567"],
    )

    with pytest.raises(SystemExit) as exc_info:
        umbra.parse_args()

    assert exc_info.value.code == 2


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_env_flag_accepts_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("UMBRA_TEST_FLAG", value)

    assert umbra.env_flag("UMBRA_TEST_FLAG") is True


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_env_flag_rejects_falsey_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("UMBRA_TEST_FLAG", value)

    assert umbra.env_flag("UMBRA_TEST_FLAG", default=True) is False


def test_write_results_returns_output_path_without_status_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    args = umbra.argparse.Namespace(
        quiet=False,
        csv=True,
        json=False,
        output="results.csv",
        backup=False,
    )

    output_path, backup_path = umbra.write_results(
        [
            {
                "Entity ID": "1",
                "Entity Name": "Acme",
                "Name Type": "",
                "Entity Type": "",
                "Principal Office Address": "",
                "RA Name": "",
                "Status": "Active",
            }
        ],
        args,
    )

    assert output_path == str(tmp_path / "data" / "results.csv")
    assert backup_path is None
    assert Path(output_path).exists()
    assert "Written to" not in capsys.readouterr().err


def test_resolve_output_path_uses_data_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))

    assert umbra.resolve_output_path("../results.csv") == str(
        tmp_path / "data" / "results.csv"
    )


def test_finish_command_emits_status_messages(capsys: pytest.CaptureFixture[str]) -> None:
    args = umbra.argparse.Namespace(quiet=False)

    exit_code = umbra.finish_command(args, (0, "data/results.csv", 5, "data/backups/results--2026-04-17_21-03-45.csv"))

    assert exit_code == 0
    stderr = capsys.readouterr().err
    assert "Found 5 result(s)." in stderr
    assert "Backed up existing file to data/backups/results--2026-04-17_21-03-45.csv" in stderr
    assert "Written to data/results.csv" in stderr


def test_run_search_csv_export_uses_direct_save(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple]] = []

    class FakeClient:
        def search_by_name(self, name, match_type):
            calls.append(("search_by_name", (name, match_type)))

        def save_csv_export(self, path):
            calls.append(("save_csv_export", (path,)))
            return path, 7

    monkeypatch.setattr(
        umbra, "prepare_output_path", lambda filename, backup=False: (f"/tmp/{filename}", "/tmp/backups/results--2026-04-17_21-03-45.csv")
    )
    args = umbra.argparse.Namespace(
        name="Acme",
        id=None,
        match="contains",
        output="results.csv",
        backup=True,
    )

    output_path, result_count, backup_path = umbra.run_search_csv_export(FakeClient(), args)

    assert output_path == "/tmp/results.csv"
    assert result_count == 7
    assert backup_path == "/tmp/backups/results--2026-04-17_21-03-45.csv"
    assert calls == [
        ("search_by_name", ("Acme", "7")),
        ("save_csv_export", ("/tmp/results.csv",)),
    ]


def test_run_query_csv_export_uses_direct_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    calls = []

    class FakeClient:
        def search_by_date_range(self, date_from, date_to, fetch=True):
            calls.append(("search_by_date_range", (date_from, date_to, fetch)))

        def save_csv_export(self, path):
            calls.append(("save_csv_export", path))
            Path(path).write_text(
                "Entity ID,Entity Name,Name Type,Entity Type,"
                "Principal Office Address,RA Name,Status\r\n"
                "1,Acme LLC,Legal Name,Limited Liability Company,Somewhere,Agent,Active\r\n",
                encoding="utf-8",
            )
            return str(path), 1

    args = umbra.argparse.Namespace(output="results.csv", backup=False)
    date_from = umbra.datetime(2026, 5, 28)
    date_to = umbra.datetime(2026, 5, 28)

    output_path, result_count, backup_path = umbra.run_query_csv_export(
        FakeClient(), args, date_from, date_to
    )

    assert calls == [
        ("search_by_date_range", (date_from, date_to, False)),
        ("save_csv_export", str(tmp_path / "data" / "results.csv")),
    ]
    assert output_path == str(tmp_path / "data" / "results.csv")
    assert result_count == 1
    assert backup_path is None
    assert Path(output_path).exists()


def test_cmd_batch_dry_run_does_not_connect(capsys: pytest.CaptureFixture[str]) -> None:
    class FakeClient:
        def connect(self):
            raise AssertionError("dry-run should not connect")

    args = umbra.argparse.Namespace(
        command="batch",
        quiet=False,
        csv=False,
        json=False,
        output=None,
        backup=False,
        date_from="01-15-2025",
        date_to="02-02-2025",
        chunk="monthly",
        dry_run=True,
        status=False,
        run=None,
    )

    result = umbra.cmd_batch(FakeClient(), args)

    assert result == (0, None, None, None)
    assert "1: 01-15-2025 to 01-31-2025" in capsys.readouterr().out


def test_cmd_batch_reuses_client_and_writes_merged_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    calls = []

    class FakeClient:
        def connect(self):
            calls.append(("connect",))

        def search_by_date_range(self, date_from, date_to):
            calls.append(("search_by_date_range", date_from, date_to))
            if date_from.month == 1:
                return [
                    {
                        "Entity ID": "1",
                        "Entity Name": "Acme",
                        "Name Type": "Reserved Name",
                        "Entity Type": "Limited Liability Company",
                        "Principal Office Address": "Somewhere",
                        "RA Name": "Agent",
                        "Status": "Active",
                    }
                ]
            return [
                {
                    "Entity ID": "1",
                    "Entity Name": "Acme LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Somewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                },
                {
                    "Entity ID": "2",
                    "Entity Name": "Beta LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Elsewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                },
            ]

    args = umbra.argparse.Namespace(
        command="batch",
        quiet=True,
        csv=True,
        json=False,
        output="year.csv",
        backup=False,
        date_from="01-15-2025",
        date_to="02-02-2025",
        chunk="monthly",
        dry_run=False,
        resume=False,
        run=None,
        status=False,
        max_attempts=2,
        stop_on_failure=True,
    )

    output_path, result_count, backup_path = umbra.cmd_batch(FakeClient(), args)[1:]

    assert calls.count(("connect",)) == 2
    assert len([call for call in calls if call[0] == "search_by_date_range"]) == 2
    assert result_count == 2
    assert backup_path is None
    assert Path(output_path).read_text(encoding="utf-8").count("Acme LLC") == 1


def test_cmd_batch_resume_skips_succeeded_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 2, 1),
    )
    manifest = batch_runner.create_manifest(
        tmp_path / "data" / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 2, 1),
        "monthly",
        chunks,
    )
    run_dir = tmp_path / "data" / "runs" / manifest["run_id"]
    first_chunk = manifest["chunks"][0]
    first_csv = batch_runner.chunk_csv_path(run_dir, manifest, first_chunk)
    batch_runner.write_chunk_csv(
        first_csv,
        [
            {
                "Entity ID": "1",
                "Entity Name": "Acme LLC",
                "Name Type": "Legal Name",
                "Entity Type": "Limited Liability Company",
                "Principal Office Address": "Somewhere",
                "RA Name": "Agent",
                "Status": "Active",
            }
        ],
    )
    batch_runner.succeed_chunk(first_chunk, first_csv, [{"Entity ID": "1"}])
    batch_runner.save_manifest(run_dir, manifest)
    calls = []

    class FakeClient:
        def connect(self):
            calls.append(("connect",))

        def search_by_date_range(self, date_from, date_to):
            calls.append(("search_by_date_range", date_from, date_to))
            return [
                {
                    "Entity ID": "2",
                    "Entity Name": "Beta LLC",
                    "Name Type": "Legal Name",
                    "Entity Type": "Limited Liability Company",
                    "Principal Office Address": "Elsewhere",
                    "RA Name": "Agent",
                    "Status": "Active",
                }
            ]

    args = umbra.argparse.Namespace(
        command="batch",
        quiet=True,
        csv=True,
        json=False,
        output="year.csv",
        backup=False,
        date_from="01-01-2025",
        date_to="02-01-2025",
        chunk="monthly",
        dry_run=False,
        resume=True,
        run=None,
        status=False,
        max_attempts=2,
        stop_on_failure=True,
    )

    _, output_path, result_count, _ = umbra.cmd_batch(FakeClient(), args)

    assert len([call for call in calls if call[0] == "search_by_date_range"]) == 1
    assert result_count == 2
    assert "Acme LLC" in Path(output_path).read_text(encoding="utf-8")
    assert "Beta LLC" in Path(output_path).read_text(encoding="utf-8")


def test_cmd_batch_status_does_not_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    chunks = umbra.build_date_chunks(
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
    )
    manifest = batch_runner.create_manifest(
        tmp_path / "data" / "runs",
        "year.csv",
        umbra.datetime(2025, 1, 1),
        umbra.datetime(2025, 1, 31),
        "monthly",
        chunks,
    )
    run_dir = tmp_path / "data" / "runs" / manifest["run_id"]
    batch_runner.save_manifest(run_dir, manifest)

    class FakeClient:
        def connect(self):
            raise AssertionError("status should not connect")

    args = umbra.argparse.Namespace(
        command="batch",
        quiet=False,
        status=True,
        run=str(run_dir),
    )

    result = umbra.cmd_batch(FakeClient(), args)

    assert result == (0, None, None, None)
    assert "pending: 1" in capsys.readouterr().out


def test_run_interactive_session_reuses_client(monkeypatch: pytest.MonkeyPatch) -> None:
    args1 = umbra.argparse.Namespace(command="search", quiet=False)
    args2 = umbra.argparse.Namespace(command="query", quiet=False)
    seen_args = []

    monkeypatch.setattr(umbra, "run_interactive_wizard", lambda: args1 if not seen_args else args2)

    def fake_run_command(client, args):
        seen_args.append((client, args))
        return 0, None, None, None

    responses = iter([True, False])
    monkeypatch.setattr(umbra, "run_command", fake_run_command)
    monkeypatch.setattr(umbra, "finish_command", lambda args, result: result[0])
    monkeypatch.setattr(umbra, "prompt_run_again", lambda: next(responses))

    client = object()
    exit_code = umbra.run_interactive_session(client)

    assert exit_code == 0
    assert seen_args == [(client, args1), (client, args2)]


def test_prepare_output_path_creates_backup_and_trims_old_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(umbra, "__file__", str(tmp_path / "umbra.py"))
    output_path = tmp_path / "data" / "year.csv"
    output_path.parent.mkdir()
    output_path.write_text("current", encoding="utf-8")

    backups_dir = tmp_path / "data" / "backups"
    backups_dir.mkdir()
    for index in range(6):
        backup = backups_dir / f"year--2026-04-17_21-03-4{index}.csv"
        backup.write_text(str(index), encoding="utf-8")

    _, backup_path = umbra.prepare_output_path("year.csv", backup=True)

    remaining = sorted(path.name for path in backups_dir.iterdir())
    assert backup_path is not None
    assert len(remaining) == umbra.BACKUP_RETENTION
    assert any(name.startswith("year--") for name in remaining)
