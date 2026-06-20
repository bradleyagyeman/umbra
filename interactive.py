"""Interactive CLI helpers for Umbra."""

import argparse
import os
import shlex
import sys
from datetime import datetime
from typing import Callable, TextIO

from pyfiglet import figlet_format


def should_use_interactive_mode(argv: list[str], stdin: TextIO | None = None) -> bool:
    """Return True when the CLI should launch the interactive wizard."""
    input_stream = stdin or sys.stdin
    return not argv and hasattr(input_stream, "isatty") and input_stream.isatty()


def run_interactive_wizard(
    input_func: Callable[[str], str] = input,
    output_stream: TextIO | None = None,
    intro_renderer: Callable[[TextIO], None] | None = None,
) -> argparse.Namespace:
    """Collect interactive choices and build argparse-compatible args."""
    output = output_stream or sys.stdout
    if intro_renderer is None:
        intro_renderer = render_intro

    intro_renderer(output)
    command = _prompt_choice(
        output,
        input_func,
        "Choose a command:",
        [("1", "search"), ("2", "query"), ("3", "batch"), ("4", "daily")],
    )

    if command == "search":
        args = _prompt_search_args(output, input_func)
    elif command == "query":
        args = _prompt_query_args(output, input_func)
    elif command == "batch":
        args = _prompt_batch_args(output, input_func)
    else:
        args = _prompt_daily_args(output, input_func)

    if args.command in {"batch", "daily"}:
        _prompt_csv_output_args(output, input_func, args)
    else:
        _prompt_output_args(output, input_func, args)

    equivalent = build_equivalent_command(args)
    print("\nAbout to run:", file=output)
    print(f"  {equivalent}", file=output)
    _prompt_confirm(output, input_func)
    return args


def prompt_run_again(
    input_func: Callable[[str], str] = input,
    output_stream: TextIO | None = None,
) -> bool:
    """Ask whether the interactive session should run another command."""
    output = output_stream or sys.stdout
    print("Run another command?", file=output)
    response = _read_response(input_func, "Proceed? [Y/n]: ", allow_blank=True)
    return response.lower() in {"", "y", "yes"}


def render_intro(output_stream: TextIO) -> None:
    """Print the interactive startup banner and portrait."""
    banner = figlet_format("UMBRA", font="standard").rstrip()
    print(banner, file=output_stream)
    print("Type q at any prompt to cancel.\n", file=output_stream)


def build_equivalent_command(args: argparse.Namespace) -> str:
    """Render the equivalent non-interactive CLI command."""
    command = ["umbra"]
    if getattr(args, "quiet", False):
        command.append("--quiet")
    if getattr(args, "json", False):
        command.append("--json")
    if getattr(args, "csv", False):
        command.append("--csv")
    if getattr(args, "no_color", False):
        command.append("--no-color")
    if getattr(args, "output", None):
        command.extend(["--output", args.output])
    if getattr(args, "backup", False):
        command.append("--backup")

    command.append(args.command)
    if args.command == "search":
        if getattr(args, "name", None):
            command.extend(["--name", args.name, "--match", args.match])
        else:
            command.extend(["--id", args.id])
    elif args.command == "query":
        if getattr(args, "today", False):
            command.append("--today")
        elif getattr(args, "yesterday", False):
            command.append("--yesterday")
        elif getattr(args, "days", None) is not None:
            command.extend(["--days", str(args.days)])
        elif getattr(args, "date_exact", None):
            command.extend(["--date", args.date_exact])
        else:
            command.extend(["--from", args.date_from])
            if getattr(args, "date_to", None):
                command.extend(["--to", args.date_to])
    elif args.command == "batch":
        command.extend(["--from", args.date_from])
        command.extend(["--to", args.date_to])
        if getattr(args, "chunk", "monthly") != "monthly":
            command.extend(["--chunk", args.chunk])
        if getattr(args, "dry_run", False):
            command.append("--dry-run")
        if getattr(args, "resume", False):
            command.append("--resume")
        if getattr(args, "max_attempts", 2) != 2:
            command.extend(["--max-attempts", str(args.max_attempts)])
        if getattr(args, "keep_going", False):
            command.append("--keep-going")
    elif args.command == "daily":
        if getattr(args, "window", 3) != 3:
            command.extend(["--window", str(args.window)])
        if getattr(args, "ledger", "ledger.csv") != "ledger.csv":
            command.extend(["--ledger", args.ledger])
        if getattr(args, "dry_run", False):
            command.append("--dry-run")

    return shlex.join(command)


def _prompt_search_args(
    output: TextIO,
    input_func: Callable[[str], str],
) -> argparse.Namespace:
    mode = _prompt_choice(
        output,
        input_func,
        "Search by:",
        [("1", "name"), ("2", "id")],
    )
    args = _base_namespace("search")
    if mode == "name":
        args.name = _prompt_text(output, input_func, "Business name")
        args.match = _prompt_choice(
            output,
            input_func,
            "Match type:",
            [("1", "exact"), ("2", "contains"), ("3", "startswith")],
        )
    else:
        args.id = _prompt_text(output, input_func, "SCC entity ID")
    return args


def _prompt_query_args(
    output: TextIO,
    input_func: Callable[[str], str],
) -> argparse.Namespace:
    mode = _prompt_choice(
        output,
        input_func,
        "Formation query:",
        [
            ("1", "today"),
            ("2", "yesterday"),
            ("3", "date"),
            ("4", "days"),
            ("5", "custom"),
        ],
        descriptions={
            "1": "Today",
            "2": "Yesterday",
            "3": "Exact date",
            "4": "Last N days (0 means today)",
            "5": "Custom date range",
        },
    )
    args = _base_namespace("query")
    if mode == "today":
        args.today = True
    elif mode == "yesterday":
        args.yesterday = True
    elif mode == "date":
        args.date_exact = _prompt_date(output, input_func, "Date (MM-DD-YYYY)")
    elif mode == "days":
        args.days = _prompt_non_negative_int(output, input_func, "Days")
    else:
        args.date_from = _prompt_date(output, input_func, "Start date (MM-DD-YYYY)")
        args.date_to = _prompt_date(
            output,
            input_func,
            "End date (MM-DD-YYYY, leave blank for today)",
            allow_blank=True,
        )
    return args


def _prompt_batch_args(
    output: TextIO,
    input_func: Callable[[str], str],
) -> argparse.Namespace:
    args = _base_namespace("batch")
    args.date_from = _prompt_date(output, input_func, "Start date (MM-DD-YYYY)")
    args.date_to = _prompt_date(output, input_func, "End date (MM-DD-YYYY)")
    args.chunk = _prompt_choice(
        output,
        input_func,
        "Chunk size:",
        [("1", "monthly"), ("2", "weekly")],
        descriptions={
            "1": "Monthly",
            "2": "Weekly",
        },
    )
    args.resume = _prompt_yes_no(
        output,
        input_func,
        "Resume compatible unfinished run if found?",
    )
    return args


def _prompt_daily_args(
    output: TextIO,
    input_func: Callable[[str], str],
) -> argparse.Namespace:
    args = _base_namespace("daily")
    args.window = _prompt_positive_int_with_default(
        output,
        input_func,
        "Trailing window in days",
        default=3,
    )
    return args


def _prompt_output_args(
    output: TextIO,
    input_func: Callable[[str], str],
    args: argparse.Namespace,
) -> None:
    format_choice = _prompt_choice(
        output,
        input_func,
        "Output format:",
        [("1", "human"), ("2", "csv"), ("3", "json")],
    )
    args.csv = format_choice == "csv"
    args.json = format_choice == "json"
    args.output, args.backup = _prompt_output_filename(output, input_func)


def _prompt_csv_output_args(
    output: TextIO,
    input_func: Callable[[str], str],
    args: argparse.Namespace,
) -> None:
    print(f"{args.command.capitalize()} output is CSV.", file=output)
    args.csv = True
    args.json = False
    args.output, args.backup = _prompt_required_output_filename(output, input_func)


def _prompt_choice(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
    choices: list[tuple[str, str]],
    descriptions: dict[str, str] | None = None,
) -> str:
    descriptions = descriptions or {}
    choice_map = {key: value for key, value in choices}
    print(prompt, file=output)
    for key, value in choices:
        label = descriptions.get(key, value.replace("_", " ").title())
        print(f"  {key}. {label}", file=output)
    while True:
        response = _read_response(input_func, "> ")
        if response in choice_map:
            return choice_map[response]
        print("Enter one of the numbered options above.", file=output)


def _prompt_text(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
    allow_blank: bool = False,
) -> str:
    while True:
        response = _read_response(input_func, f"{prompt}: ")
        if response or allow_blank:
            return response
        print("A value is required.", file=output)


def _prompt_non_negative_int(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
) -> int:
    while True:
        response = _read_response(input_func, f"{prompt}: ")
        try:
            value = int(response)
        except ValueError:
            print("Enter a whole number.", file=output)
            continue
        if value < 0:
            print("Enter 0 or a positive integer.", file=output)
            continue
        return value


def _prompt_positive_int_with_default(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
    default: int,
) -> int:
    while True:
        response = _read_response(
            input_func,
            f"{prompt} (leave blank for {default}): ",
            allow_blank=True,
        )
        if not response:
            return default
        try:
            value = int(response)
        except ValueError:
            print("Enter a whole number.", file=output)
            continue
        if value < 1:
            print("Enter a positive integer.", file=output)
            continue
        return value


def _prompt_date(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
    allow_blank: bool = False,
) -> str | None:
    while True:
        response = _read_response(input_func, f"{prompt}: ")
        if not response and allow_blank:
            return None
        try:
            datetime.strptime(response, "%m-%d-%Y")
        except ValueError:
            print("Use MM-DD-YYYY.", file=output)
            continue
        return response


def _prompt_confirm(output: TextIO, input_func: Callable[[str], str]) -> None:
    response = _read_response(input_func, "Proceed? [Y/n]: ", allow_blank=True)
    if response.lower() not in {"", "y", "yes"}:
        raise KeyboardInterrupt
    print("", file=output)


def _prompt_yes_no(
    output: TextIO,
    input_func: Callable[[str], str],
    prompt: str,
    default: bool = False,
) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    response = _read_response(input_func, f"{prompt} {suffix}: ", allow_blank=True)
    if not response:
        return default
    return response.lower() in {"y", "yes"}


def _prompt_output_filename(
    output: TextIO,
    input_func: Callable[[str], str],
) -> tuple[str | None, bool]:
    while True:
        filename = _prompt_text(
            output,
            input_func,
            "Enter a file name to save the results, or leave blank to show them on screen",
            allow_blank=True,
        )
        if not filename:
            return None, False

        resolved_path = _resolve_output_path(filename)
        if not os.path.exists(resolved_path):
            return filename, False

        print(f"{resolved_path} already exists.", file=output)
        action = _prompt_choice(
            output,
            input_func,
            "Choose how to proceed:",
            [("1", "overwrite"), ("2", "backup"), ("3", "rename")],
            descriptions={
                "1": "Overwrite existing file",
                "2": "Back up existing file and overwrite",
                "3": "Choose a different file name",
            },
        )
        if action == "overwrite":
            return filename, False
        if action == "backup":
            return filename, True


def _prompt_required_output_filename(
    output: TextIO,
    input_func: Callable[[str], str],
) -> tuple[str, bool]:
    while True:
        filename, backup = _prompt_output_filename(output, input_func)
        if filename:
            return filename, backup
        print("This command requires an output file.", file=output)


def _read_response(
    input_func: Callable[[str], str],
    prompt: str,
    allow_blank: bool = False,
) -> str:
    response = input_func(prompt).strip()
    if response.lower() in {"q", "quit"}:
        raise KeyboardInterrupt
    if response or allow_blank:
        return response
    return ""


def _base_namespace(command: str) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
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


def _resolve_output_path(filename: str) -> str:
    return os.path.join(
        os.path.dirname(__file__) or ".",
        "data",
        os.path.basename(filename),
    )
