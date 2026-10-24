import sys
import types

import pytest

from visite360 import opencv


def test_uses_ffmpeg() -> None:
    assert opencv.uses_ffmpeg("    FFMPEG:                      YES (61.19.101)")
    assert not opencv.uses_ffmpeg("    FFMPEG:                      NO")
    assert not opencv.uses_ffmpeg("To be built: core imgproc")


def test_load_cv2_refuses_pypi_build(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.SimpleNamespace(getBuildInformation=lambda: "FFMPEG: YES (61.19.101)")
    monkeypatch.setitem(sys.modules, "cv2", module)

    with pytest.raises(opencv.OpenCVError, match="installer-opencv.sh"):
        opencv.load_cv2()


def test_load_cv2_accepts_build_without_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.SimpleNamespace(getBuildInformation=lambda: "To be built: core stitching")
    monkeypatch.setitem(sys.modules, "cv2", module)

    assert opencv.load_cv2() is module


def test_load_cv2_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)

    with pytest.raises(opencv.OpenCVError, match="absent"):
        opencv.load_cv2()
