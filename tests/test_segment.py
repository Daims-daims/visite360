import hashlib
import io
from pathlib import Path

import pytest

from visite360 import doctor, segment


def test_models_folder_can_be_moved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VISITE360_MODELES", str(tmp_path))

    assert segment.weights_path() == tmp_path / segment.WEIGHTS_FILE


def test_missing_names_absent_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(segment.importlib.util, "find_spec", lambda name: None)

    assert segment.missing() == "PyTorch et SAM 2 absents"


def test_missing_names_absent_weights(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(segment.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("VISITE360_MODELES", str(tmp_path))

    assert "poids absents" in (segment.missing() or "")

    (tmp_path / segment.WEIGHTS_FILE).write_bytes(b"poids")
    assert segment.missing() is None


def test_segmenter_without_sam2_gives_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(segment, "missing", lambda: "PyTorch absent")

    with pytest.raises(segment.SegmentError, match="installer-sam2.sh"):
        segment.Sam2Segmenter()


def test_download_checks_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"poids de test")
    good = hashlib.sha256(b"poids de test").hexdigest()
    target = tmp_path / "modeles" / "poids.pt"
    out = io.StringIO()

    assert segment.download_weights(source.as_uri(), good, target, out) == target
    assert target.read_bytes() == b"poids de test"

    source.unlink()  # déjà là et intact : rien n'est retéléchargé
    segment.download_weights(source.as_uri(), good, target, out)
    assert "déjà présents" in out.getvalue()


def test_download_refuses_wrong_file(tmp_path: Path) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"autre chose")
    target = tmp_path / "poids.pt"

    with pytest.raises(segment.SegmentError, match="ne correspondent pas"):
        segment.download_weights(source.as_uri(), "0" * 64, target, io.StringIO())
    assert not target.exists()
    assert not list(tmp_path.glob("*.partiel"))


def test_download_failure_is_reported(tmp_path: Path) -> None:
    with pytest.raises(segment.SegmentError, match="a échoué"):
        segment.download_weights(
            (tmp_path / "absent.pt").as_uri(), "0" * 64, tmp_path / "p.pt", io.StringIO()
        )


def test_doctor_sam2_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.segment, "missing", lambda: "PyTorch absent")

    result = doctor.check_sam2()

    assert not result.ok and not result.required
    assert result.hint and "installer-sam2.sh" in result.hint


def test_doctor_sam2_checks_weights(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor.segment, "missing", lambda: None)
    monkeypatch.setenv("VISITE360_MODELES", str(tmp_path))
    (tmp_path / segment.WEIGHTS_FILE).write_bytes(b"pas les bons poids")

    assert "abîmés" in doctor.check_sam2().detail

    monkeypatch.setattr(
        doctor.segment, "WEIGHTS_SHA256", segment.file_sha256(segment.weights_path())
    )
    assert doctor.check_sam2().ok
