import runpy
from pathlib import Path
import tomllib

import pytest

import umbra


ROOT = Path(__file__).resolve().parents[1]


def test_main_wrapper_delegates_to_umbra_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_main() -> int:
        return 17

    monkeypatch.setattr(umbra, "main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(ROOT / "main.py"), run_name="__main__")

    assert exc_info.value.code == 17


def test_pyproject_declares_cli_script_and_dynamic_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["project"]["scripts"]["umbra"] == "umbra:main"
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "umbra.py"


def test_pyproject_packages_all_runtime_modules() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    included = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"][
        "only-include"
    ]

    assert included == [
        "batch_runner.py",
        "cis_client.py",
        "interactive.py",
        "ledger.py",
        "main.py",
        "output.py",
        "umbra.py",
    ]
