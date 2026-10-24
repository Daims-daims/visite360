import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from visite360 import selection, stitch, visite
from visite360.selection import Click, SelectionError, ViewSpec
from visite360.spherical import equirect_directions, project


class FakeSegmenter:
    """Modèle simulé : un disque autour de chaque clic « en plus », moins un disque autour de
    chaque clic « en moins », et un point isolé dans un coin comme la frange de SAM 2."""

    def __init__(self) -> None:
        self.images: list[tuple[int, ...]] = []

    def set_image(self, rgb: np.ndarray) -> None:
        self.images.append(rgb.shape)
        self.size = rgb.shape[0]

    def predict(self, points: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, float]:
        mask = np.zeros((self.size, self.size), dtype=np.uint8)
        for (x, y), label in zip(points, labels, strict=True):
            if label == 1:
                cv2.circle(mask, (int(x), int(y)), 150, 1, -1)
        for (x, y), label in zip(points, labels, strict=True):
            if label == 0:
                cv2.circle(mask, (int(x), int(y)), 60, 0, -1)
        mask[5:8, 5:8] = 1
        return mask > 0, 0.9


def lon_lat(directions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    d = directions / np.linalg.norm(directions, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(d[..., 0], d[..., 2])), np.degrees(np.arcsin(-d[..., 1]))


def in_box(lon: np.ndarray, lat: np.ndarray, center: float, half: float, lat_range: tuple) -> Any:
    relative = (lon - center + 180.0) % 360.0 - 180.0
    return (np.abs(relative) <= half) & (lat >= lat_range[0]) & (lat <= lat_range[1])


def test_view_spec_rejects_bad_values() -> None:
    with pytest.raises(SelectionError):
        ViewSpec(0.0, 95.0, 90.0)
    with pytest.raises(SelectionError):
        ViewSpec(0.0, 0.0, 10.0)
    with pytest.raises(SelectionError):
        ViewSpec(float("nan"), 0.0, 90.0)
    with pytest.raises(SelectionError):
        ViewSpec("0", 0.0, 90.0)  # type: ignore[arg-type]


def test_view_center_looks_where_asked() -> None:
    spec = ViewSpec(40.0, -20.0, 90.0)

    yaw, pitch = spec.angles(spec.size / 2 - 0.5, spec.size / 2 - 0.5)

    assert yaw == pytest.approx(40.0, abs=1e-6)
    assert pitch == pytest.approx(-20.0, abs=1e-6)


def test_extract_view_matches_panorama_at_center() -> None:
    panorama = make_panorama(2048)
    spec = ViewSpec(0.0, 0.0, 60.0, size=256)

    view = selection.extract_view(panorama, spec)

    assert view.shape == (256, 256, 3)
    center = view[127:129, 127:129].astype(float).mean(axis=(0, 1))
    expected = panorama[511:513, 1023:1025].astype(float).mean(axis=(0, 1))
    assert np.abs(center - expected).max() < 12


@pytest.mark.parametrize(
    ("yaw", "pitch", "fov"),
    [(0.0, 0.0, 90.0), (175.0, 10.0, 90.0), (30.0, 75.0, 100.0), (-60.0, -80.0, 60.0)],
)
def test_footprint_contains_every_visible_pixel(yaw: float, pitch: float, fov: float) -> None:
    width, height = 720, 360
    spec = ViewSpec(yaw, pitch, fov, size=200)
    rows, cols = selection.footprint(spec, width, height)
    x, y, front = project(
        equirect_directions(width, height, np.arange(height), np.arange(width)),
        spec.intrinsics(),
        spec.rotation(),
    )
    visible = front & (x >= 0) & (x <= spec.size) & (y >= 0) & (y <= spec.size)
    covered = np.zeros_like(visible)
    covered[np.ix_(rows, cols % width)] = True

    assert visible.any()
    assert not (visible & ~covered).any()


@pytest.mark.parametrize(
    ("yaw", "pitch", "fov", "box"),
    [
        (0.0, 0.0, 90.0, (10.0, 20.0, (-15.0, 25.0))),
        (178.0, 5.0, 90.0, (-176.0, 15.0, (-20.0, 30.0))),  # à cheval sur la couture à 180°
        (30.0, 70.0, 100.0, (60.0, 40.0, (55.0, 80.0))),  # près du plafond
    ],
)
def test_mask_round_trip_without_shift(
    yaw: float, pitch: float, fov: float, box: tuple[float, float, tuple]
) -> None:
    """Une zone connue du panorama, vue dans la vue puis reportée, retombe à sa place."""
    width, height = 2048, 1024
    spec = ViewSpec(yaw, pitch, fov, size=1024)
    center, half, lat_range = box
    centers = np.arange(spec.size) + 0.5
    xs, ys = np.meshgrid(centers, centers)
    view_mask = in_box(*lon_lat(spec.directions(xs, ys)), center, half, lat_range)

    result = selection.to_panorama(view_mask.astype(np.uint8) * 255, spec, width, height) > 0

    directions = equirect_directions(width, height, np.arange(height), np.arange(width))
    expected = in_box(*lon_lat(directions), center, half, lat_range)
    x, y, front = project(directions, spec.intrinsics(), spec.rotation())
    visible = front & (x > 2) & (x < spec.size - 2) & (y > 2) & (y < spec.size - 2)
    expected &= visible
    kernel = np.ones((3, 3), np.uint8)
    inner = cv2.erode(expected.astype(np.uint8), kernel) > 0
    outer = cv2.dilate(expected.astype(np.uint8), kernel) > 0
    assert expected.sum() > 1000
    assert (result & inner).sum() == inner.sum()  # rien ne manque à l'intérieur
    # Rien ne déborde de plus d'un pixel, sauf de rares pixels près du plafond, où un pixel de
    # la vue couvre plusieurs pixels du panorama.
    assert (result & ~outer).sum() <= 0.001 * expected.sum()
    assert abs(int(result.sum()) - int(expected.sum())) < 0.02 * expected.sum()


def test_clean_mask_removes_specks_and_small_holes() -> None:
    mask = np.zeros((1024, 1024), dtype=np.uint8)
    cv2.circle(mask, (500, 500), 200, 255, -1)
    mask[10:13, 10:13] = 255  # point isolé
    mask[495:500, 495:500] = 0  # petit trou : oubli du modèle
    mask[600:660, 450:510] = 0  # grand trou : une prise électrique, à garder
    mask[400:405, 400:405] = 0  # petit trou où l'on a cliqué « en moins »

    cleaned = selection.clean_mask(mask, [Click(500, 300, True), Click(402, 402, False)])

    assert cleaned[11, 11] == 0
    assert cleaned[497, 497] == 255
    assert cleaned[630, 480] == 0
    assert cleaned[402, 402] == 0
    assert cleaned[500, 300] == 255


def test_clean_mask_keeps_largest_piece_when_click_falls_outside() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[20:40, 20:40] = 255
    mask[100:180, 100:180] = 255

    cleaned = selection.clean_mask(mask, [Click(5, 5, True)])

    assert cleaned[140, 140] == 255 and cleaned[30, 30] == 0


def test_parse_clicks_validates_input() -> None:
    assert selection.parse_clicks([{"x": 10, "y": 20.5, "ajout": True}]) == [
        Click(10.0, 20.5, True)
    ]
    for bad in (
        [],
        "x",
        [{"x": 10, "y": 20}],
        [{"x": "10", "y": 20, "ajout": True}],
        [{"x": 5000, "y": 20, "ajout": True}],
        [{"x": 10, "y": 20, "ajout": False}],
        [{"x": 1, "y": 1, "ajout": True}] * (selection.MAX_CLICKS + 1),
    ):
        with pytest.raises(SelectionError):
            selection.parse_clicks(bad)


def write_point(root: Path, width: int = 2048) -> stitch.Folders:
    point = root / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(width))
    return stitch.resolve_folders(point)


def test_save_list_preview_and_delete(tmp_path: Path) -> None:
    folders = write_point(tmp_path)
    before = selection.file_sha256(folders.panorama)
    mask = np.zeros((1024, 2048), dtype=np.uint8)
    mask[300:500, 900:1200] = 255
    spec = ViewSpec(0.0, 0.0, 90.0)

    first = selection.save(
        folders.point, folders.panorama, mask, spec, [Click(1, 2, True)], "simulé", 0.9, " Mur "
    )
    second = selection.save(
        folders.point, folders.panorama, mask, spec, [Click(1, 2, True)], "simulé", 0.8
    )

    assert (first["id"], first["nom"]) == ("selection-1", "Mur")
    assert (second["id"], second["nom"]) == ("selection-2", "Sélection 2")
    saved = cv2.imread(str(folders.point / "modifications" / "selection-1.png"), 0)
    assert np.array_equal(saved > 0, mask > 0)
    record = json.loads((folders.point / "modifications" / "selection-1.json").read_text())
    assert record["vue"] == {"cap": 0.0, "hauteur": 0.0, "champ": 90.0, "taille": 1024}
    assert record["clics"] == [{"x": 1.0, "y": 2.0, "ajout": True}]

    listed = selection.list_all(folders.point, folders.panorama)
    assert [r["id"] for r in listed] == ["selection-1", "selection-2"]
    assert not any(r["perimee"] for r in listed)

    image = selection.preview(folders.point, folders.panorama, "selection-1")
    assert image == folders.cache / "selection-1.jpg"
    assert cv2.imread(str(image)).shape == (1024, 2048, 3)

    selection.delete(folders.point, "selection-1")
    assert [r["id"] for r in selection.list_all(folders.point, folders.panorama)] == ["selection-2"]
    assert not image.exists()
    assert selection.file_sha256(folders.panorama) == before  # D9 : l'original ne change pas
    with pytest.raises(SelectionError):
        selection.delete(folders.point, "selection-1")
    with pytest.raises(SelectionError):
        selection.delete(folders.point, "../visite.json")


def test_selection_becomes_stale_when_panorama_changes(tmp_path: Path) -> None:
    folders = write_point(tmp_path)
    mask = np.zeros((1024, 2048), dtype=np.uint8)
    selection.save(
        folders.point, folders.panorama, mask, ViewSpec(0, 0, 90), [Click(1, 1, True)], "m", 1
    )

    cv2.imwrite(str(folders.panorama), make_panorama(2048, seed=3))

    assert selection.list_all(folders.point, folders.panorama)[0]["perimee"] is True


def test_selector_open_mask_and_validate(tmp_path: Path) -> None:
    folders = write_point(tmp_path)
    before = selection.file_sha256(folders.panorama)
    fake = FakeSegmenter()
    selector = selection.Selector(visite.single_point(folders), lambda: fake, "simulé")

    token = selector.open_view(0, 20.0, 0.0, 90.0)
    clicks = [{"x": 512, "y": 512, "ajout": True}, {"x": 512, "y": 400, "ajout": False}]
    view_mask, score = selector.mask(token, clicks)

    assert fake.images == [(1024, 1024, 3)]
    assert view_mask[512, 512] == 255 and view_mask[400, 512] == 0
    assert view_mask[6, 6] == 0  # point isolé effacé par le nettoyage
    assert score == pytest.approx(0.9)

    record = selector.validate(token, clicks, "Mur")
    mask = cv2.imread(str(folders.point / "modifications" / "selection-1.png"), 0)
    assert mask.shape == (1024, 2048)
    # Le centre de la vue (cap 20°, horizon) est sélectionné dans le panorama.
    assert mask[511, int((20 + 180) / 360 * 2048)] == 255
    assert mask[511, 0] == 0
    assert record["modele"] == "simulé" and record["nom"] == "Mur"
    assert selection.file_sha256(folders.panorama) == before

    with pytest.raises(SelectionError):
        selector.mask("autre", clicks)
    with pytest.raises(SelectionError):
        selector.open_view(3, 0.0, 0.0, 90.0)


def test_selector_refuses_empty_selection(tmp_path: Path) -> None:
    folders = write_point(tmp_path)

    class Empty(FakeSegmenter):
        def predict(self, points: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, float]:
            return np.zeros((self.size, self.size), dtype=bool), 0.1

    selector = selection.Selector(visite.single_point(folders), Empty, "simulé")
    token = selector.open_view(0, 0.0, 0.0, 90.0)

    with pytest.raises(SelectionError, match="vide"):
        selector.validate(token, [{"x": 10, "y": 10, "ajout": True}])
    assert not (folders.point / "modifications" / "selection-1.json").exists()


def test_view_angles_follow_pixel_grid() -> None:
    spec = ViewSpec(0.0, 0.0, 90.0, size=100)

    yaw, _ = spec.angles(99.5, 49.5)

    assert yaw == pytest.approx(math.degrees(math.atan(1.0)), abs=1e-6)
