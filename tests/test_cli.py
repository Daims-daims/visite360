import subprocess
import sys

import pytest

from visite360 import __version__
from visite360.cli import main


def test_version_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"visite360 {__version__}"


def test_no_argument_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "visite360" in capsys.readouterr().out


def test_unknown_argument_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--inconnu"])

    assert exit_info.value.code == 2


def test_module_can_be_run_directly() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "visite360", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"visite360 {__version__}"
