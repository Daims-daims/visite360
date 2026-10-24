import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from visite360 import couleur, selection
from visite360.couleur import ColorError
from visite360.selection import Click, ViewSpec

SAGE = "#8fa58a"
TERRACOTTA = "#c0603a"


def lab(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)


def wall(height: int = 200, width: int = 300) -> np.ndarray:
    """Mur beige avec une ombre progressive de gauche à droite et un peu de grain."""
    rng = np.random.default_rng(1)
    shade = np.linspace(0.45, 1.0, width)[None, :, None]
    base = np.array([190, 215, 230], dtype=np.float32)  # BGR, beige clair
    grain = rng.normal(0.0, 3.0, (height, width, 1))
    return np.clip(base * shade + grain, 0, 255).astype(np.uint8)


def rect_mask(shape: tuple[int, ...], top: int, bottom: int, left: int, right: int) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    mask[top:bottom, left:right] = 255
    return mask


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("value", ["#c8d3c0", "#C8D3C0", "#000000"])
def test_parse_color_accepts_hex(value: str) -> None:
    assert couleur.parse_color(value) == (
        int(value[1:3], 16),
        int(value[3:5], 16),
        int(value[5:], 16),
    )


@pytest.mark.parametrize("value", ["c8d3c0", "#c8d3c", "#c8d3cg", "rouge", 12, None])
def test_parse_color_rejects_the_rest(value: object) -> None:
    with pytest.raises(ColorError):
        couleur.parse_color(value)


def linear(image: np.ndarray) -> np.ndarray:
    srgb = image.astype(np.float64) / 255.0
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def test_lighting_is_kept() -> None:
    image = wall()
    mask = rect_mask(image.shape, 20, 180, 20, 280)

    out = couleur.recolor(image, mask, couleur.parse_color(SAGE), snap=False)

    inner = rect_mask(image.shape, 30, 170, 30, 270) > 0  # loin du bord adouci
    ratio = linear(out)[inner] / linear(image)[inner]
    # Un même facteur pour tous les pixels de chaque canal : l'ombre garde sa profondeur.
    assert np.all(np.std(ratio, axis=0) / np.mean(ratio, axis=0) < 0.03)
    # La couleur typique de la surface est celle choisie.
    assert np.allclose(np.median(out[inner], axis=0), [0x8A, 0xA5, 0x8F], atol=2)
    # Le côté sombre reste plus sombre que le côté éclairé, dans le même rapport.
    left, right = linear(image)[100, 40].mean(), linear(image)[100, 260].mean()
    new_left, new_right = linear(out)[100, 40].mean(), linear(out)[100, 260].mean()
    assert new_left / new_right == pytest.approx(left / right, rel=0.1)


def test_pixels_outside_the_mask_are_untouched_without_snapping() -> None:
    rng = np.random.default_rng(2)
    image = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    mask = np.zeros((240, 320), dtype=np.uint8)
    cv2.circle(mask, (150, 110), 70, 255, -1)
    cv2.circle(mask, (150, 110), 20, 0, -1)  # un trou, comme une prise électrique

    out = couleur.recolor(image, mask, couleur.parse_color(TERRACOTTA), snap=False)

    outside = mask == 0
    assert np.array_equal(out[outside], image[outside])
    assert not np.array_equal(out[mask > 0], image[mask > 0])
    assert out is not image


def test_snapping_changes_nothing_beyond_its_radius() -> None:
    rng = np.random.default_rng(3)
    image = rng.integers(0, 256, (400, 2048, 3), dtype=np.uint8)
    mask = np.zeros((400, 2048), dtype=np.uint8)
    cv2.circle(mask, (1000, 200), 120, 255, -1)
    radius = couleur.snap_radius(2048)

    out = couleur.recolor(image, mask, couleur.parse_color(TERRACOTTA))

    size = 2 * radius + 3
    near = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))) > 0
    assert np.array_equal(out[~near], image[~near])


def test_snapping_follows_a_faint_edge() -> None:
    """Porte blanche sur mur blanc : le contour approximatif se recale sur le vrai bord."""
    rng = np.random.default_rng(4)
    height, width, edge = 200, 2048, 1000
    image = np.full((height, width, 3), 205.0)
    image[:, edge:] = 188.0
    image = np.clip(image + rng.normal(0.0, 2.0, (height, width, 1)), 0, 255).astype(np.uint8)
    radius = couleur.snap_radius(width)
    mask = np.zeros((height, width), dtype=np.uint8)
    for row in range(height):
        mask[row, 200 : edge + int(rng.integers(-radius // 2, radius // 2 + 1))] = 255

    snapped = couleur.snap_mask(image, mask, radius)

    boundaries = np.array([np.flatnonzero(snapped[row])[-1] + 1 for row in range(height)])
    assert np.mean(np.abs(boundaries - edge) <= 1) > 0.95
    assert (
        np.abs(boundaries - edge).mean()
        < np.abs(
            np.array([np.flatnonzero(mask[row])[-1] + 1 for row in range(height)]) - edge
        ).mean()
    )


def test_edge_is_softened_inside_only() -> None:
    image = np.full((60, 60, 3), 230, dtype=np.uint8)
    mask = rect_mask(image.shape, 10, 50, 10, 50)

    out = couleur.recolor(image, mask, (40, 60, 160), snap=False).astype(int)

    change = np.abs(out - image.astype(int)).sum(axis=2)
    assert change[30, 9] == 0
    assert 0 < change[30, 10] < change[30, 12]
    assert change[30, 12] == change[30, 30]


def test_empty_mask_changes_nothing() -> None:
    image = wall()
    out = couleur.recolor(image, np.zeros(image.shape[:2], np.uint8), (10, 20, 30))
    assert np.array_equal(out, image)


def test_mask_of_wrong_size_is_refused() -> None:
    with pytest.raises(ColorError):
        couleur.recolor(wall(), np.zeros((10, 10), np.uint8), (10, 20, 30))


def make_point(tmp_path: Path) -> tuple[Path, Path]:
    point = tmp_path / "salon"
    point.mkdir()
    panorama = point / "panorama.jpg"
    # Murs clairs avec un éclairage qui varie : la teinte obtenue se lit sans ambiguïté.
    light = np.linspace(0.6, 1.0, 1024)[None, :, None] * np.linspace(1.0, 0.8, 512)[:, None, None]
    image = np.array([200, 210, 220], dtype=np.float32) * light
    cv2.imwrite(str(panorama), image.astype(np.uint8))
    return point, panorama


def add_selection(point: Path, panorama: Path, box: tuple[int, int, int, int]) -> str:
    mask = rect_mask((512, 1024), *box)
    record = selection.save(
        point, panorama, mask, ViewSpec(0.0, 0.0, 90.0), [Click(512, 512, True)], "simulé", 0.9
    )
    return record["id"]


def test_save_replaces_the_color_of_a_selection(tmp_path: Path) -> None:
    point, panorama = make_point(tmp_path)
    first = add_selection(point, panorama, (100, 300, 100, 400))
    second = add_selection(point, panorama, (100, 300, 600, 900))

    a = couleur.save(point, first, SAGE)
    b = couleur.save(point, second, TERRACOTTA)
    again = couleur.save(point, first, "#FFFFFF")

    assert (a["id"], b["id"], again["id"]) == ("couleur-1", "couleur-2", "couleur-1")
    records = [op.record for op in couleur.operations(point)]
    assert [(r["selection"], r["couleur"]) for r in records] == [
        (first, "#ffffff"),
        (second, TERRACOTTA),
    ]
    saved = json.loads((point / "modifications" / "couleur-1.json").read_text(encoding="utf-8"))
    assert saved["type"] == "couleur" and saved["version"] == 1


@pytest.mark.parametrize(
    ("selection_id", "color"),
    [("selection-9", SAGE), ("../visite", SAGE), (None, SAGE), ("selection-1", "vert")],
)
def test_save_refuses_bad_requests(tmp_path: Path, selection_id: object, color: str) -> None:
    point, panorama = make_point(tmp_path)
    add_selection(point, panorama, (100, 300, 100, 400))
    with pytest.raises(ColorError):
        couleur.save(point, selection_id, color)
    assert couleur.operations(point) == []


def test_after_combines_colors_and_undo_restores_original(tmp_path: Path) -> None:
    point, panorama = make_point(tmp_path)
    original_sha = sha(panorama)
    original = cv2.imread(str(panorama))
    left = add_selection(point, panorama, (100, 300, 100, 400))
    right = add_selection(point, panorama, (100, 300, 600, 900))
    painter = couleur.Painter(mobile_width=512)
    assert painter.state(point, panorama) == {"couleurs": [], "version": None}

    couleur.save(point, left, SAGE)
    green = couleur.save(point, right, TERRACOTTA)
    state = painter.state(point, panorama)
    after = cv2.imread(str(painter.after(point, panorama, mobile=False)))
    small = cv2.imread(str(painter.after(point, panorama, mobile=True)))

    assert state["version"] and len(state["couleurs"]) == 2
    assert after.shape == original.shape and small.shape == (256, 512, 3)
    hue = lambda img, x: lab(img[150:250, x : x + 100])[..., 1:].mean(axis=(0, 1))  # noqa: E731
    sage_ab = lab(np.array([[[0x8A, 0xA5, 0x8F]]], np.uint8))[0, 0, 1:]
    terracotta_ab = lab(np.array([[[0x3A, 0x60, 0xC0]]], np.uint8))[0, 0, 1:]
    assert np.allclose(hue(after, 200), sage_ab, atol=4)
    assert np.allclose(hue(after, 700), terracotta_ab, atol=4)
    # Hors des deux sélections, rien ne bouge (à la compression JPEG près).
    assert np.abs(after[400:, :].astype(int) - original[400:, :].astype(int)).mean() < 2

    couleur.delete(point, green["id"])
    assert len(painter.state(point, panorama)["couleurs"]) == 1
    couleur.delete(point, "couleur-1")
    assert painter.state(point, panorama)["version"] is None
    with pytest.raises(ColorError):
        painter.after(point, panorama, mobile=False)
    # Le panorama d'origine n'a jamais été réécrit : annuler, c'est revenir à lui.
    assert sha(panorama) == original_sha


def test_after_is_reused_then_redone_when_an_operation_changes(tmp_path: Path) -> None:
    point, panorama = make_point(tmp_path)
    wall_id = add_selection(point, panorama, (100, 300, 100, 400))
    painter = couleur.Painter(mobile_width=512)
    couleur.save(point, wall_id, SAGE)

    first = painter.after(point, panorama, mobile=False)
    stamp = first.stat().st_mtime_ns
    version = painter.state(point, panorama)["version"]
    assert painter.after(point, panorama, mobile=False).stat().st_mtime_ns == stamp

    couleur.save(point, wall_id, TERRACOTTA)
    assert painter.state(point, panorama)["version"] != version
    redone = cv2.imread(str(painter.after(point, panorama, mobile=False)))
    terracotta_ab = lab(np.array([[[0x3A, 0x60, 0xC0]]], np.uint8))[0, 0, 1:]
    assert np.allclose(
        lab(redone[150:250, 200:300])[..., 1:].mean(axis=(0, 1)), terracotta_ab, atol=4
    )


def test_operations_skip_colors_of_a_deleted_selection(tmp_path: Path) -> None:
    point, panorama = make_point(tmp_path)
    kept = add_selection(point, panorama, (100, 300, 100, 400))
    gone = add_selection(point, panorama, (100, 300, 600, 900))
    couleur.save(point, kept, SAGE)
    couleur.save(point, gone, TERRACOTTA)

    selection.delete(point, gone)
    assert [op.record["selection"] for op in couleur.operations(point)] == [kept]

    couleur.delete_for_selection(point, kept)
    assert couleur.operations(point) == []


def test_delete_refuses_unknown_ids(tmp_path: Path) -> None:
    point, _ = make_point(tmp_path)
    for bad in ("couleur-3", "../panorama", None):
        with pytest.raises(ColorError):
            couleur.delete(point, bad)


def test_preview_tries_a_color_without_saving(tmp_path: Path) -> None:
    point, panorama = make_point(tmp_path)
    wall_id = add_selection(point, panorama, (100, 300, 100, 400))
    couleur.save(point, wall_id, SAGE)

    data = couleur.preview(panorama, point, wall_id, TERRACOTTA, width=512)

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == (256, 512, 3)
    terracotta_ab = lab(np.array([[[0x3A, 0x60, 0xC0]]], np.uint8))[0, 0, 1:]
    assert np.allclose(
        lab(image[75:125, 100:150])[..., 1:].mean(axis=(0, 1)), terracotta_ab, atol=5
    )
    assert [op.record["couleur"] for op in couleur.operations(point)] == [SAGE]
    assert not (point / "cache" / couleur.AFTER_NAME).exists()
