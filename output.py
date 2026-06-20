"""Output formatting for umbra.

Handles three output modes:
  - human: key-value pairs, colored status on stderr
  - csv: RFC 4180 CSV to stdout
  - json: JSON array to stdout
"""

import csv
import json
import os
import sys

# CSV columns in the order CIS returns them
COLUMNS = [
    "Entity ID",
    "Entity Name",
    "Name Type",
    "Entity Type",
    "Principal Office Address",
    "RA Name",
    "Status",
]


def use_color() -> bool:
    """Check if stderr supports color output."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if use_color() else text


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if use_color() else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if use_color() else text


def info(msg: str) -> None:
    """Print an informational message to stderr."""
    print(msg, file=sys.stderr)


def success(msg: str) -> None:
    """Print a success message to stderr."""
    print(_green(msg), file=sys.stderr)


def warn(msg: str) -> None:
    """Print a warning to stderr."""
    print(_yellow(f"warning: {msg}"), file=sys.stderr)


def error(msg: str) -> None:
    """Print an error to stderr."""
    print(_red(f"error: {msg}"), file=sys.stderr)


def format_human(results: list[dict], out) -> None:
    """Write results as human-readable key-value pairs."""
    for entity in results:
        for key in COLUMNS:
            value = entity.get(key, "").strip()
            print(f"  {key:<28} {value}", file=out)
        print(file=out)


def format_csv(results: list[dict], out) -> None:
    """Write results as CSV."""
    writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        writer.writerow({k: v.strip() for k, v in row.items() if k in COLUMNS})


def format_json(results: list[dict], out) -> None:
    """Write results as JSON array."""
    cleaned = [
        {k: v.strip() for k, v in row.items() if k in COLUMNS}
        for row in results
    ]
    json.dump(cleaned, out, indent=2)
    out.write("\n")
