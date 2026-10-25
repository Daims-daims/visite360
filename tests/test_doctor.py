import io
import subprocess
import sys
import types

import pytest

from visite360 import doctor
from visite360.cli import main

SIPS_FORMATS = "public.heic                  heic  Writable\npublic.jpeg  jpeg  Writable\n"


BUILD_WITHOUT_FFMPEG = "  Video I/O:\n    FFMPEG:                      NO\n"
BUILD_WITH_FFMPEG = "  Video I/O:\n    FFMPEG:                      YES (61.19.101)\n"


def fake_cv2(
    monkeypatch: pytest.MonkeyPatch, version: str, build: str = BUILD_WITHOUT_FFMPEG
) -> None:
    module = types.SimpleNamespace(__version__=version, getBuildInformation=lambda: build)
    monkeypatch.setitem(sys.modules, "cv2", module)


def fake_sips(
    monkeypatch: pytest.MonkeyPatch,
    *,
    found: bool = True,
    stdout: str = SIPS_FORMATS,
    returncode: int = 0,
    error: Exception | None = None,
) -> list[list[str]]:
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        return "/usr/bin/sips" if found and name == "sips" else None

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(doctor.shutil, "which", which)
    monkeypatch.setattr(doctor.subprocess, "run", run)
    return calls


@pytest.mark.parametrize(
    ("text", "expected"),
    [("4.10.0", (4, 10, 0)), ("4.12.0-dev", (4, 12, 0)), ("5.0", (5, 0)), ("inconnue", None)],
)
def test_parse_version(text: str, expected: tuple[int, ...] | None) -> None:
    assert doctor.parse_version(text) == expected


def test_python_recent_enough() -> None:
    result = doctor.check_python((3, 11, 0))

    assert result.ok
    assert result.detail == "3.11.0"


def test_python_too_old() -> None:
    result = doctor.check_python((3, 9, 6))

    assert not result.ok
    assert result.required
    assert "trop ancienne" in result.detail


def test_opencv_present(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2(monkeypatch, "4.12.0")

    result = doctor.check_opencv()

    assert result.ok
    assert result.detail == "4.12.0, compilé sans FFmpeg"


def test_opencv_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_module(name: str) -> types.ModuleType:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(doctor.importlib, "import_module", import_module)

    result = doctor.check_opencv()

    assert not result.ok
    assert result.detail == "absent"
    assert result.hint is not None and "scripts/installer-opencv.sh" in result.hint


def test_opencv_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_module(name: str) -> types.ModuleType:
        raise ImportError("libopencv introuvable")

    monkeypatch.setattr(doctor.importlib, "import_module", import_module)

    result = doctor.check_opencv()

    assert not result.ok
    assert "impossible à charger" in result.detail


def test_opencv_too_old(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2(monkeypatch, "4.5.5")

    result = doctor.check_opencv()

    assert not result.ok
    assert "trop ancienne" in result.detail
    assert result.hint is not None and "scripts/installer-opencv.sh" in result.hint


def test_opencv_from_pypi_with_ffmpeg_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2(monkeypatch, "4.14.0", BUILD_WITH_FFMPEG)

    result = doctor.check_opencv()

    assert not result.ok
    assert "FFmpeg" in result.detail


def test_opencv_unreadable_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2(monkeypatch, "")

    assert not doctor.check_opencv().ok


def test_heic_with_sips(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_sips(monkeypatch)

    result = doctor.check_heic("darwin")

    assert result.ok
    assert calls == [["/usr/bin/sips", "--formats"]]


def test_heic_sips_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sips(monkeypatch, found=False)

    result = doctor.check_heic("darwin")

    assert not result.ok
    assert result.required


def test_heic_sips_without_heic(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sips(monkeypatch, stdout="public.jpeg  jpeg  Writable\n")

    assert not doctor.check_heic("darwin").ok


def test_heic_sips_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sips(monkeypatch, returncode=1)

    assert "code de sortie 1" in doctor.check_heic("darwin").detail


def test_heic_sips_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sips(monkeypatch, error=subprocess.TimeoutExpired(["sips"], 10))

    assert "ne répond pas" in doctor.check_heic("darwin").detail


def test_heic_outside_macos_is_optional() -> None:
    result = doctor.check_heic("linux")

    assert not result.ok
    assert not result.required


def test_hugin_absent_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    result = doctor.check_hugin()

    assert not result.ok
    assert not result.required


def test_hugin_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/opt/bin/{name}")

    assert doctor.check_hugin().ok


def test_generation_absent_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.generation, "missing", lambda: "mflux absent")

    result = doctor.check_generation()

    assert not result.ok
    assert not result.required
    assert result.hint and "installer-generation.sh" in result.hint


def test_generation_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.generation, "missing", lambda: None)

    assert doctor.check_generation().ok


def test_report_all_ok() -> None:
    out = io.StringIO()
    results = [doctor.CheckResult("Python", True, True, "3.13.0")]

    assert doctor.report(results, out) == 0
    assert "Tout est prêt." in out.getvalue()


def test_report_missing_optional_only_succeeds() -> None:
    out = io.StringIO()
    results = [
        doctor.CheckResult("Python", True, True, "3.13.0"),
        doctor.CheckResult("Hugin", False, False, "absent", "conseil"),
    ]

    assert doctor.report(results, out) == 0
    assert "Hugin (facultatif) : absent" in out.getvalue()


def test_report_missing_required_fails() -> None:
    out = io.StringIO()
    results = [doctor.CheckResult("OpenCV", False, True, "absent", "pip install x")]

    assert doctor.report(results, out) == 1
    text = out.getvalue()
    assert "✗ OpenCV : absent" in text
    assert "→ pip install x" in text
    assert "1 élément obligatoire à corriger." in text


def test_cli_doctor_returns_report_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        doctor, "run_checks", lambda: [doctor.CheckResult("OpenCV", False, True, "absent")]
    )

    assert main(["doctor"]) == 1
    assert "OpenCV" in capsys.readouterr().out
