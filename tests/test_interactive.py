import argparse
import io
from pathlib import Path

import pytest

from interactive import (
    build_equivalent_command,
    prompt_run_again,
    run_interactive_wizard,
    should_use_interactive_mode,
)


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class FakePipe(io.StringIO):
    def isatty(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def isolate_interactive_output_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "interactive._resolve_output_path",
        lambda filename: str(tmp_path / Path(filename).name),
    )


def test_should_use_interactive_mode_requires_tty() -> None:
    assert should_use_interactive_mode([], stdin=FakeTTY()) is True
    assert should_use_interactive_mode([], stdin=FakePipe()) is False
    assert should_use_interactive_mode(["query"], stdin=FakeTTY()) is False


def test_run_interactive_wizard_builds_search_args() -> None:
    responses = iter(["1", "1", "Acme Holdings", "2", "3", "", "y"])
    output = io.StringIO()

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=output,
        intro_renderer=lambda stream: print("INTRO", file=stream),
    )

    assert args == argparse.Namespace(
        command="search",
        quiet=False,
        json=True,
        csv=False,
        no_color=False,
        output=None,
        backup=False,
        name="Acme Holdings",
        id=None,
        match="contains",
        today=False,
        yesterday=False,
        days=None,
        date_exact=None,
        date_from=None,
        date_to=None,
        chunk="monthly",
        dry_run=False,
        resume=False,
        run=None,
        status=False,
        max_attempts=2,
        keep_going=False,
        stop_on_failure=True,
        window=3,
        ledger="ledger.csv",
    )
    assert "umbra --json search --name 'Acme Holdings' --match contains" in output.getvalue()


def test_run_interactive_wizard_builds_query_args() -> None:
    responses = iter(["2", "4", "0", "2", "today.csv", ""])

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=io.StringIO(),
        intro_renderer=lambda stream: None,
    )

    assert args.command == "query"
    assert args.days == 0
    assert args.csv is True
    assert args.output == "today.csv"
    assert args.backup is False


def test_run_interactive_wizard_builds_batch_args() -> None:
    responses = iter(
        [
            "3",
            "01-01-2025",
            "12-31-2025",
            "1",
            "y",
            "year.csv",
            "",
        ]
    )
    output = io.StringIO()

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=output,
        intro_renderer=lambda stream: None,
    )

    assert args.command == "batch"
    assert args.date_from == "01-01-2025"
    assert args.date_to == "12-31-2025"
    assert args.chunk == "monthly"
    assert args.resume is True
    assert args.csv is True
    assert args.output == "year.csv"
    assert (
        "umbra --csv --output year.csv batch --from 01-01-2025 --to 12-31-2025 --resume"
        in output.getvalue()
    )


def test_run_interactive_wizard_builds_daily_args() -> None:
    responses = iter(["4", "", "new-llcs.csv", ""])
    output = io.StringIO()

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=output,
        intro_renderer=lambda stream: None,
    )

    assert args.command == "daily"
    assert args.window == 3
    assert args.ledger == "ledger.csv"
    assert args.csv is True
    assert args.output == "new-llcs.csv"
    assert "umbra --csv --output new-llcs.csv daily" in output.getvalue()


def test_run_interactive_wizard_builds_daily_args_with_custom_window() -> None:
    responses = iter(["4", "7", "new-llcs.csv", ""])
    output = io.StringIO()

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=output,
        intro_renderer=lambda stream: None,
    )

    assert args.window == 7
    assert (
        "umbra --csv --output new-llcs.csv daily --window 7" in output.getvalue()
    )


def test_build_equivalent_command_for_daily_defaults_omits_flags() -> None:
    args = argparse.Namespace(
        command="daily",
        quiet=False,
        json=False,
        csv=True,
        no_color=False,
        output="new-llcs.csv",
        backup=False,
        window=3,
        ledger="ledger.csv",
        dry_run=False,
    )

    assert (
        build_equivalent_command(args)
        == "umbra --csv --output new-llcs.csv daily"
    )


def test_build_equivalent_command_for_custom_range() -> None:
    args = argparse.Namespace(
        command="query",
        quiet=False,
        json=False,
        csv=False,
        no_color=False,
        output=None,
        backup=False,
        name=None,
        id=None,
        match="exact",
        today=False,
        yesterday=False,
        days=None,
        date_exact=None,
        date_from="03-15-2026",
        date_to="03-22-2026",
    )

    assert (
        build_equivalent_command(args)
        == "umbra query --from 03-15-2026 --to 03-22-2026"
    )


def test_build_equivalent_command_for_exact_date() -> None:
    args = argparse.Namespace(
        command="query",
        quiet=False,
        json=False,
        csv=False,
        no_color=False,
        output=None,
        backup=False,
        name=None,
        id=None,
        match="exact",
        today=False,
        yesterday=False,
        days=None,
        date_exact="03-15-2026",
        date_from=None,
        date_to=None,
    )

    assert build_equivalent_command(args) == "umbra query --date 03-15-2026"


def test_build_equivalent_command_for_batch_weekly() -> None:
    args = argparse.Namespace(
        command="batch",
        quiet=False,
        json=False,
        csv=True,
        no_color=False,
        output="march.csv",
        backup=False,
        date_from="03-01-2026",
        date_to="03-31-2026",
        chunk="weekly",
        dry_run=False,
        resume=False,
        max_attempts=2,
        keep_going=False,
    )

    assert (
        build_equivalent_command(args)
        == "umbra --csv --output march.csv batch --from 03-01-2026 "
        "--to 03-31-2026 --chunk weekly"
    )


def test_interactive_batch_requires_output_filename() -> None:
    responses = iter(
        [
            "3",
            "01-01-2025",
            "12-31-2025",
            "1",
            "",
            "",
            "year.csv",
            "",
        ]
    )

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=io.StringIO(),
        intro_renderer=lambda stream: None,
    )

    assert args.output == "year.csv"


def test_run_interactive_wizard_can_cancel() -> None:
    responses = iter(["q"])

    with pytest.raises(KeyboardInterrupt):
        run_interactive_wizard(
            input_func=lambda _: next(responses),
            output_stream=io.StringIO(),
            intro_renderer=lambda stream: None,
        )


def test_prompt_run_again_accepts_blank_yes() -> None:
    assert prompt_run_again(input_func=lambda _: "", output_stream=io.StringIO()) is True
    assert prompt_run_again(input_func=lambda _: "n", output_stream=io.StringIO()) is False


def test_run_interactive_wizard_confirms_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "today.csv").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        "interactive._resolve_output_path",
        lambda filename: str(data_dir / filename),
    )
    responses = iter(["2", "1", "2", "today.csv", "3", "today-2.csv", ""])

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=io.StringIO(),
        intro_renderer=lambda stream: None,
    )

    assert args.output == "today-2.csv"


def test_run_interactive_wizard_can_choose_backup_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "today.csv").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        "interactive._resolve_output_path",
        lambda filename: str(data_dir / filename),
    )
    responses = iter(["2", "1", "2", "today.csv", "2", ""])

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=io.StringIO(),
        intro_renderer=lambda stream: None,
    )

    assert args.output == "today.csv"
    assert args.backup is True


def test_run_interactive_wizard_builds_exact_date_query_args() -> None:
    responses = iter(["2", "3", "03-15-2026", "1", "", ""])

    args = run_interactive_wizard(
        input_func=lambda _: next(responses),
        output_stream=io.StringIO(),
        intro_renderer=lambda stream: None,
    )

    assert args.command == "query"
    assert args.date_exact == "03-15-2026"
    assert args.csv is False
    assert args.json is False
