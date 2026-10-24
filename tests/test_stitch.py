import io
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import FULL_ROWS, View, make_panorama, shoot
from visite360 import photos, stitch
from visite360.cli import main
from visite360.spherical import camera_rotation

WIDTH = 1024
NO_FLOOR_PHOTO = tuple(row for row in FULL_ROWS if row[0] != -90.0)
HORIZON_AND_UP = ((0.0, 12), (45.0, 8), (90.0, 1))


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    return make_panorama(2048)


@pytest.fixture(scope="module")
def views(truth: np.ndarray) -> list[View]:
    return shoot(truth)


def write_point(root: Path, views: list[View], pitches: set[float] | None = None) -> Path:
    point = root / "visite" / "salon"
    folder = point / "photos"
    folder.mkdir(parents=True)
    for number, view in enumerate(views):
        if pitches is None or view.pitch in pitches:
            path = folder / f"IMG_{number:02d}.jpg"
            cv2.imwrite(str(path), view.image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return point


def run_stitch(point: Path, force: bool = False) -> tuple[int, dict]:
    code = stitch.run(point, WIDTH, force, io.StringIO())
    report = json.loads((point / "rapport.json").read_text(encoding="utf-8"))
    return code, report


def test_full_point_matches_original(tmp_path: Path, truth: np.ndarray, views: list[View]) -> None:
    point = write_point(tmp_path, views)

    code, report = run_stitch(point)

    assert code == 0
    panorama = cv2.imread(str(point / "panorama.jpg"))
    assert panorama.shape == (WIDTH // 2, WIDTH, 3)
    assert all(photo["used"] for photo in report["photos"])
    assert report["coverage"] > 0.999
    assert report["missing_areas"] == []
    # La première photo regarde la longitude 0 et l'horizon est au milieu : le panorama se
    # superpose à l'original, sans décalage.
    expected = cv2.resize(truth, (WIDTH, WIDTH // 2), interpolation=cv2.INTER_AREA)
    band = slice(WIDTH // 2 * 15 // 100, WIDTH // 2 * 85 // 100)
    gray = [
        cv2.cvtColor(image[band], cv2.COLOR_BGR2GRAY).astype(np.float32)
        for image in (expected, panorama)
    ]
    (shift_x, shift_y), _ = cv2.phaseCorrelate(gray[0], gray[1])
    assert abs(shift_x) < 1.0 and abs(shift_y) < 1.0
    error = np.abs(panorama[band].astype(int) - expected[band].astype(int)).mean()
    assert error < 15


def test_unmatched_and_unreadable_photos_are_rejected(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {0.0, 45.0, -45.0})
    noise = np.random.default_rng(1).integers(0, 256, (600, 400, 3), dtype=np.uint8)
    cv2.imwrite(str(point / "photos" / "ZZ_bruit.png"), noise)
    (point / "photos" / "ZZ_casse.jpg").write_bytes(b"pas une image")

    code, report = run_stitch(point)

    assert code == 0
    rejected = {photo["file"]: photo["reason"] for photo in report["photos"] if not photo["used"]}
    assert rejected == {
        "ZZ_bruit.png": stitch.REJECTED_UNMATCHED,
        "ZZ_casse.jpg": stitch.REJECTED_UNREADABLE,
    }


def test_missing_floor_photo_is_blurred(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {pitch for pitch, _ in NO_FLOOR_PHOTO})

    code, report = run_stitch(point)

    assert code == 0
    holes = report["missing_areas"]
    assert [hole["kind"] for hole in holes] == ["sol"]
    assert holes[0]["fill"] == "flou"
    assert holes[0]["lat_max"] < -60
    panorama = cv2.imread(str(point / "panorama.jpg"))
    assert not np.all(np.abs(panorama[-1].astype(int) - stitch.HOLE_GRAY) < 3)


def test_missing_lower_rows_are_reported_in_gray(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {pitch for pitch, _ in HORIZON_AND_UP})

    code, report = run_stitch(point)

    assert code == 0
    holes = report["missing_areas"]
    assert [hole["kind"] for hole in holes] == ["sol"]
    assert holes[0]["fill"] == "gris"
    assert -45 < holes[0]["lat_max"] < -20
    assert report["coverage"] < 0.85
    panorama = cv2.imread(str(point / "panorama.jpg"))
    assert np.all(np.abs(panorama[-1].astype(int) - stitch.HOLE_GRAY) < 3)


def test_second_run_does_nothing_unless_forced(
    tmp_path: Path, views: list[View], monkeypatch: pytest.MonkeyPatch
) -> None:
    point = write_point(tmp_path, views, {0.0})
    assert run_stitch(point)[0] == 0
    before = (point / "panorama.jpg").stat().st_mtime_ns

    def fail(*args: object) -> None:
        raise AssertionError("l'assemblage n'aurait pas dû être relancé")

    monkeypatch.setattr(stitch, "align", fail)
    out = io.StringIO()
    assert stitch.run(point, WIDTH, False, out) == 0
    assert "déjà à jour" in out.getvalue()
    assert (point / "panorama.jpg").stat().st_mtime_ns == before

    monkeypatch.undo()
    assert run_stitch(point, force=True)[0] == 0
    assert (point / "panorama.jpg").stat().st_mtime_ns != before


def test_changed_photos_trigger_a_new_run(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {0.0})
    assert run_stitch(point)[0] == 0
    (point / "photos" / "IMG_00.jpg").unlink()

    assert not stitch.is_up_to_date(
        stitch.resolve_folders(point), photos.list_photos(point / "photos"), WIDTH
    )


def test_photos_folder_can_be_given_directly(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {0.0})

    assert stitch.run(point / "photos", WIDTH, False, io.StringIO()) == 0
    assert (point / "panorama.jpg").is_file()


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("empty", "Aucune photo"),
        ("layout", "Organisation attendue"),
        ("one_photo", "au moins 2 photos"),
        ("unrelated", "pas assez de points communs"),
    ],
)
def test_errors_are_clear(
    tmp_path: Path,
    views: list[View],
    capsys: pytest.CaptureFixture[str],
    setup: str,
    message: str,
) -> None:
    point = tmp_path / "salon"
    (point / "photos").mkdir(parents=True)
    rng = np.random.default_rng(2)
    if setup == "layout":
        point = tmp_path / "ailleurs"
        point.mkdir()
    elif setup == "one_photo":
        cv2.imwrite(str(point / "photos" / "a.jpg"), views[0].image)
    elif setup == "unrelated":
        for name in ("a.png", "b.png"):
            image = rng.integers(0, 256, (300, 200, 3), dtype=np.uint8)
            cv2.imwrite(str(point / "photos" / name), image)

    assert stitch.run(point, WIDTH, False, io.StringIO()) == 1
    error = capsys.readouterr().err
    assert error.startswith("Erreur : ")
    assert message in error
    assert "Traceback" not in error


@pytest.mark.parametrize("width", [1023, 100, 40000])
def test_invalid_width(tmp_path: Path, views: list[View], width: int) -> None:
    point = write_point(tmp_path, views, {0.0})

    assert stitch.run(point, width, False, io.StringIO()) == 1


def test_level_and_anchor_turns_upside_down_set_back() -> None:
    upright = [camera_rotation(yaw, 0) for yaw in (40, 70, 100)]
    upside_down = [np.diag([-1.0, -1.0, 1.0]) @ R for R in upright]

    result = stitch.level_and_anchor(upside_down)

    for R, expected_yaw in zip(result, (0, 30, 60), strict=True):
        assert np.allclose(R, camera_rotation(expected_yaw, 0), atol=1e-9)


def test_holes_across_the_seam_are_one_area() -> None:
    covered = np.ones((512, 1024), bool)
    covered[200:260, :20] = False
    covered[200:260, -20:] = False

    holes, blur = stitch.find_holes(cv2, covered)

    assert len(holes) == 1
    assert holes[0].kind == "trou" and holes[0].fill == "gris"
    assert holes[0].lon_min > 170 and holes[0].lon_max < -170
    assert not blur.any()


def test_describe_hole_in_french() -> None:
    hole = stitch.Hole("sol", 0.0213, -90, -71, -180, 180, "flou")

    assert stitch.describe_hole(hole) == "sol, sous -71° (2,1 % de la sphère), remplie par un flou"


def test_heic_photos_are_converted_once(
    tmp_path: Path, views: list[View], monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "photos"
    folder.mkdir()
    source = folder / "IMG_0001.HEIC"
    source.write_bytes(b"heic")
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        cv2.imwrite(args[-1], views[0].image)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(photos.sys, "platform", "darwin")
    monkeypatch.setattr(photos.shutil, "which", lambda name: "/usr/bin/sips")
    monkeypatch.setattr(photos.subprocess, "run", fake_run)
    cache = tmp_path / "cache"

    first = photos.prepare_photos([source], cache)
    second = photos.prepare_photos([source], cache)

    assert first == second == [photos.Photo(source, cache / "IMG_0001.jpg")]
    assert len(calls) == 1
    assert calls[0][:3] == ["/usr/bin/sips", "-s", "format"]
    assert source.read_bytes() == b"heic"


def test_heic_outside_macos_is_a_clear_error(tmp_path: Path) -> None:
    source = tmp_path / "IMG_0001.heic"
    source.write_bytes(b"heic")

    with pytest.raises(photos.PhotoError, match="Le plus compatible"):
        photos.convert_heic(source, tmp_path / "out.jpg", platform="linux")


def test_sips_failure_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "IMG_0001.heic"
    source.write_bytes(b"heic")
    monkeypatch.setattr(photos.shutil, "which", lambda name: "/usr/bin/sips")
    monkeypatch.setattr(
        photos.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="", stderr="erreur"),
    )

    with pytest.raises(photos.PhotoError, match="code de sortie 1"):
        photos.convert_heic(source, tmp_path / "out.jpg", platform="darwin")


def test_cli_stitch_passes_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    received = {}

    def fake_run(target: Path, width: int, force: bool) -> int:
        received.update(target=target, width=width, force=force)
        return 0

    monkeypatch.setattr(stitch, "run", fake_run)

    assert main(["stitch", str(tmp_path), "--largeur", "4096", "--force"]) == 0
    assert received == {"target": tmp_path, "width": 4096, "force": True}


def test_original_photos_are_untouched(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views, {0.0})
    copy = tmp_path / "copie"
    shutil.copytree(point / "photos", copy)

    run_stitch(point)

    for original in copy.iterdir():
        assert (point / "photos" / original.name).read_bytes() == original.read_bytes()


def test_horizon_photos_have_priority() -> None:
    def camera(yaw: float, pitch: float) -> stitch.Camera:
        focal = 300 / np.tan(np.radians(25))
        K = np.array([[focal, 0, 200], [0, focal, 300], [0, 0, 1.0]])
        return stitch.Camera(0, K, camera_rotation(yaw, pitch), (400, 600))

    horizon, up = camera(0, 0), camera(0, 45)
    width = 256
    full = np.ones((width // 2, width), bool)

    masks = stitch.horizon_priority([horizon, up], [full, full], width)

    center = (width // 4, width // 2)  # latitude 0, longitude 0
    above = (width // 2 * 20 // 180, width // 2)  # latitude 70°
    assert masks[0][center] and not masks[1][center]
    assert masks[1][above]
    assert stitch.is_horizon(horizon) and not stitch.is_horizon(up)
