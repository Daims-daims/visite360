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


def write_capture(
    point: Path,
    rotations: list[np.ndarray],
    skip: int | None = None,
    start_yaw: float | None = None,
) -> Path:
    photos = [
        {"fichier": f"IMG_{number:02d}.jpg", "rotation": np.round(R, 6).tolist()}
        for number, R in enumerate(rotations)
        if number != skip
    ]
    data = {"format": 1, "appareil": "iPhone15,4", "photos": photos}
    if start_yaw is not None:
        data["cap_depart"] = start_yaw
    path = point / capture.FILE_NAME
    path.write_text(json.dumps(data))
    return path


def run_stitch(point: Path, force: bool = False) -> tuple[int, dict, str]:
    out = io.StringIO()
    code = stitch.run(point, WIDTH, force, out)
    report = json.loads((point / "rapport.json").read_text(encoding="utf-8"))
    return code, report, out.getvalue()


def assert_matches(truth: np.ndarray, point: Path) -> None:
    """Le panorama assemblé est le panorama de synthèse, sans décalage."""
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


def test_start_yaw_is_the_centre_of_the_panorama(
    tmp_path: Path, truth: np.ndarray, views: list[View]
) -> None:
    # Le téléphone a commencé face à la direction à 45° à droite de la première photo : c'est
    # elle qui doit être au centre du panorama, quelle que soit la première photo retenue.
    point = write_point(tmp_path, views)
    heading = 37.0  # cap de départ arbitraire des capteurs, voir sensor_rotations
    write_capture(point, sensor_rotations(views, noise_deg=1.0), start_yaw=heading + 45.0)

    code, _, _ = run_stitch(point)

    assert code == 0
    shift = truth.shape[1] // 8  # 45° en pixels du panorama de synthèse
    assert_matches(np.roll(truth, -shift, axis=1), point)


def test_plain_photo_is_placed_by_the_phone(tmp_path: Path, views: list[View]) -> None:
    # Plafond tout blanc : aucun point commun avec les autres photos.
    ceiling = next(n for n, view in enumerate(views) if view.pitch == 90.0)
    plain = [
        View(np.full_like(view.image, 230), view.yaw, view.pitch) if n == ceiling else view
        for n, view in enumerate(views)
    ]
    point = write_point(tmp_path, plain)
    write_capture(point, sensor_rotations(plain, noise_deg=1.0))

    code, report, out = run_stitch(point)

    assert code == 0
    photo = report["photos"][ceiling]
    assert photo["used"] and photo["placed_by_sensors"]
    assert sum(p["placed_by_sensors"] for p in report["photos"]) == 1
    assert f"Placée par les capteurs : IMG_{ceiling:02d}.jpg" in out
    assert not any(hole["kind"] == "plafond" for hole in report["missing_areas"])


def test_plain_photo_is_rejected_without_the_phone(tmp_path: Path, views: list[View]) -> None:
    ceiling = next(n for n, view in enumerate(views) if view.pitch == 90.0)
    plain = [
        View(np.full_like(view.image, 230), view.yaw, view.pitch) if n == ceiling else view
        for n, view in enumerate(views)
    ]
    point = write_point(tmp_path, plain)

    _, report, _ = run_stitch(point)

    assert not report["photos"][ceiling]["used"]
    assert not report["photos"][ceiling]["placed_by_sensors"]


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
    assert found.start_yaw is None
    assert capture.parse({**data, "cap_depart": -12.5}, tmp_path).start_yaw == -12.5
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
        ({"format": 1, "photos": [], "cap_depart": "nord"}, "cap_depart"),
        ({"format": 1, "photos": [], "cap_depart": 400}, "cap_depart"),
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


def test_drift_correction_is_interpolated_between_neighbours() -> None:
    corrections = {10: rotation_y(np.radians(2.0)), 20: rotation_y(np.radians(4.0))}

    middle = stitch.drift_corrected(15, corrections)
    first = stitch.drift_corrected(3, corrections)
    last = stitch.drift_corrected(25, corrections)

    assert np.allclose(middle, rotation_y(np.radians(3.0)), atol=1e-12)
    assert np.allclose(first, corrections[10]) and np.allclose(last, corrections[20])


def test_plain_photo_follows_the_gyroscope_drift(
    tmp_path: Path, truth: np.ndarray, views: list[View]
) -> None:
    # Le cap mesuré dérive de 0,3° par photo : 9° d'écart entre la première et la dernière.
    ceiling = next(n for n, view in enumerate(views) if view.pitch == 90.0)
    plain = [
        View(np.full_like(view.image, 230), view.yaw, view.pitch) if n == ceiling else view
        for n, view in enumerate(views)
    ]
    point = write_point(tmp_path, plain)
    drifting = [
        rotation_y(np.radians(0.3 * n)) @ R
        for n, R in enumerate(sensor_rotations(plain, noise_deg=0.2))
    ]
    write_capture(point, drifting)

    code, report, _ = run_stitch(point)

    assert code == 0
    assert report["orientations"]["source"] == "capteurs"
    assert report["photos"][ceiling]["placed_by_sensors"]
    assert_matches(truth, point)
