import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import View, make_panorama, shoot
from visite360 import capture, stitch
from visite360.adjust import rotation_from_vector
from visite360.spherical import camera_rotation, rotation_y

WIDTH = 1024


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    return make_panorama(2048)


@pytest.fixture(scope="module")
def views(truth: np.ndarray) -> list[View]:
    return shoot(truth)


def write_point(root: Path, views: list[View]) -> Path:
    point = root / "visite" / "salon"
    folder = point / "photos"
    folder.mkdir(parents=True)
    for number, view in enumerate(views):
        cv2.imwrite(str(folder / f"IMG_{number:02d}.jpg"), view.image)
    return point


def sensor_rotations(views: list[View], noise_deg: float, seed: int = 0) -> list[np.ndarray]:
    """Orientations comme les mesurerait un téléphone : cap de départ quelconque et petit bruit."""
    rng = np.random.default_rng(seed)
    heading = rotation_y(np.radians(37.0))
    return [
        rotation_from_vector(rng.normal(0, np.radians(noise_deg), 3))
        @ heading
        @ camera_rotation(view.yaw, view.pitch)
        for view in views
    ]


def write_capture(point: Path, rotations: list[np.ndarray], skip: int | None = None) -> Path:
    photos = [
        {"fichier": f"IMG_{number:02d}.jpg", "rotation": np.round(R, 6).tolist()}
        for number, R in enumerate(rotations)
        if number != skip
    ]
    path = point / capture.FILE_NAME
    path.write_text(json.dumps({"format": 1, "appareil": "iPhone15,4", "photos": photos}))
    return path


def run_stitch(point: Path, force: bool = False) -> tuple[int, dict, str]:
    out = io.StringIO()
    code = stitch.run(point, WIDTH, force, out)
    report = json.loads((point / "rapport.json").read_text(encoding="utf-8"))
    return code, report, out.getvalue()


def assert_matches(truth: np.ndarray, point: Path) -> None:
    panorama = cv2.imread(str(point / "panorama.jpg"))
    expected = cv2.resize(truth, (WIDTH, WIDTH // 2), interpolation=cv2.INTER_AREA)
    band = slice(WIDTH // 2 * 15 // 100, WIDTH // 2 * 85 // 100)
    gray = [
        cv2.cvtColor(image[band], cv2.COLOR_BGR2GRAY).astype(np.float32)
        for image in (expected, panorama)
    ]
    (shift_x, shift_y), _ = cv2.phaseCorrelate(gray[0], gray[1])
    assert abs(shift_x) < 1.0 and abs(shift_y) < 1.0
    assert np.abs(panorama[band].astype(int) - expected[band].astype(int)).mean() < 15


def test_phone_orientations_are_used(tmp_path: Path, truth: np.ndarray, views: list[View]) -> None:
    point = write_point(tmp_path, views)
    write_capture(point, sensor_rotations(views, noise_deg=1.0))

    code, report, out = run_stitch(point)

    assert code == 0
    assert report["orientations"] == {"source": "capteurs", "detail": None}
    assert "mesurées par le téléphone" in out
    assert all(photo["used"] for photo in report["photos"])
    assert report["coverage"] > 0.999
    assert_matches(truth, point)


def test_wrong_orientations_fall_back_to_photos(
    tmp_path: Path, truth: np.ndarray, views: list[View]
) -> None:
    point = write_point(tmp_path, views)
    rng = np.random.default_rng(3)
    write_capture(point, [rotation_from_vector(rng.normal(0, 2, 3)) for _ in views])

    code, report, _ = run_stitch(point)

    assert code == 0
    assert report["orientations"]["source"] == "photos"
    assert "ignorées" in report["orientations"]["detail"]
    assert_matches(truth, point)


def test_photo_missing_from_capture_is_reported(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views)
    write_capture(point, sensor_rotations(views, noise_deg=1.0), skip=4)

    code, report, _ = run_stitch(point)

    assert code == 0
    assert report["orientations"]["source"] == "photos"
    assert "1 photo(s) absente(s) de capture.json" in report["orientations"]["detail"]


def test_changed_capture_triggers_a_new_run(tmp_path: Path, views: list[View]) -> None:
    point = write_point(tmp_path, views)
    assert run_stitch(point)[0] == 0
    assert run_stitch(point)[2].startswith("Panorama déjà à jour")

    write_capture(point, sensor_rotations(views, noise_deg=1.0))
    _, report, out = run_stitch(point)

    assert not out.startswith("Panorama déjà à jour")
    assert report["orientations"]["source"] == "capteurs"


def test_broken_capture_is_a_clear_error(
    tmp_path: Path, views: list[View], capsys: pytest.CaptureFixture[str]
) -> None:
    point = write_point(tmp_path, views[:2])
    (point / capture.FILE_NAME).write_text("{ pas du json")

    assert stitch.run(point, WIDTH, False, io.StringIO()) == 1
    error = capsys.readouterr().err
    assert "n'est pas un JSON valide" in error
    assert "Supprimer" in error


def test_valid_capture_is_read(tmp_path: Path) -> None:
    R = camera_rotation(30.0, 45.0)
    data = {
        "format": 1,
        "appareil": "iPhone15,4",
        "inconnu": True,
        "photos": [{"fichier": "IMG_0001.jpg", "rotation": np.round(R, 4).tolist(), "cap": 30}],
    }

    found = capture.parse(data, tmp_path / capture.FILE_NAME)

    assert found.device == "iPhone15,4"
    rotation = found.rotations["IMG_0001.jpg"]
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
    assert np.allclose(rotation, R, atol=1e-3)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "doit contenir un objet JSON"),
        ({"format": 2, "photos": []}, "format 2 inconnu"),
        ({"format": 1}, "« photos » doit être une liste"),
        ({"format": 1, "photos": [{"rotation": np.eye(3).tolist()}]}, "« fichier »"),
        ({"format": 1, "photos": [{"fichier": "../a.jpg", "rotation": []}]}, "« fichier »"),
        ({"format": 1, "photos": [{"fichier": "a.jpg", "rotation": [[1, 0], [0, 1]]}]}, "3 lignes"),
        (
            {"format": 1, "photos": [{"fichier": "a.jpg", "rotation": (2 * np.eye(3)).tolist()}]},
            "pas une rotation valide",
        ),
        (
            {"format": 1, "photos": [{"fichier": "a.jpg", "rotation": (-np.eye(3)).tolist()}]},
            "miroir",
        ),
        (
            {
                "format": 1,
                "photos": [
                    {"fichier": "a.jpg", "rotation": np.eye(3).tolist()},
                    {"fichier": "a.jpg", "rotation": np.eye(3).tolist()},
                ],
            },
            "déclarée deux fois",
        ),
    ],
)
def test_invalid_capture(tmp_path: Path, data: object, message: str) -> None:
    with pytest.raises(capture.CaptureError, match=message):
        capture.parse(data, tmp_path / capture.FILE_NAME)


def test_neighbour_mask_keeps_overlapping_photos_only() -> None:
    rotations = [camera_rotation(0, 0), camera_rotation(30, 0), camera_rotation(180, 0)]

    mask = stitch.neighbour_mask(rotations)

    assert mask.tolist() == [[1, 1, 0], [1, 1, 0], [0, 0, 1]]


def test_align_to_sensors_recovers_the_horizon() -> None:
    sensors = [camera_rotation(yaw, pitch) for yaw, pitch in ((0, 0), (90, 20), (200, -45))]
    tilt = rotation_from_vector(np.radians([8.0, -3.0, 5.0]))

    leveled = stitch.align_to_sensors([tilt @ R for R in sensors], sensors)

    for R, S in zip(leveled, sensors, strict=True):
        assert np.allclose(R, S, atol=1e-9)
