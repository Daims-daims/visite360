import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from visite360 import capture, piece
from visite360.spherical import directions_to_equirect

LENS = 1.45
CEILING = 2.50
# Rectangle de 4,20 × 3,10 m, objectif décentré : à 1,6 m du mur de gauche, 1,2 m du mur du fond.
RECTANGLE = [(-1.6, 1.9), (2.6, 1.9), (2.6, -1.2), (-1.6, -1.2)]
# Pièce en L : 5 × 4 m moins un carré de 2 × 2 m, objectif hors du prolongement des murs.
L_SHAPE = [(-2.0, 2.3), (1.0, 2.3), (1.0, 0.3), (3.0, 0.3), (3.0, -1.7), (-2.0, -1.7)]


def angles(x: float, z: float, y: float) -> dict[str, float]:
    """Cap et hauteur sous lesquels l'objectif voit le point (x, z) à y mètres au-dessus de lui."""
    distance = math.hypot(x, z)
    return {"cap": math.degrees(math.atan2(x, z)), "hauteur": math.degrees(math.atan2(y, distance))}


def floor_click(x: float, z: float) -> dict[str, float]:
    return angles(x, z, -LENS)


def ceiling_click(x: float, z: float) -> dict[str, float]:
    return angles(x, z, CEILING - LENS)


def both(corners: list[tuple[float, float]]) -> list[dict[str, float]]:
    clicks = []
    for x, z in corners:
        clicks += [floor_click(x, z), ceiling_click(x, z)]
    return clicks


def lengths(corners: list[tuple[float, float]]) -> list[float]:
    return [math.dist(corners[i], corners[(i + 1) % len(corners)]) for i in range(len(corners))]


def test_rectangle_is_measured_exactly() -> None:
    room = piece.compute(piece.parse_clicks(both(RECTANGLE)), LENS, None)
    result = room.to_json()
    assert result["hauteur_plafond_m"] == pytest.approx(CEILING, abs=0.01)
    assert result["source_hauteur_plafond"] == "coins"
    assert [w["longueur_m"] for w in result["murs"]] == pytest.approx(lengths(RECTANGLE), abs=0.01)
    assert result["murs"][0]["surface_m2"] == pytest.approx(4.2 * CEILING, abs=0.1)
    assert result["surface_sol_m2"] == pytest.approx(4.2 * 3.1, abs=0.1)
    assert result["perimetre_m"] == pytest.approx(2 * (4.2 + 3.1), abs=0.02)
    assert result["ecart_hauteur_plafond_m"] == pytest.approx(0.0, abs=0.01)


def test_hidden_corners_are_clicked_at_the_ceiling() -> None:
    # Un coin cliqué aux deux, les autres au sol ou au plafond seulement.
    corners = L_SHAPE
    clicks = [floor_click(*corners[0]), ceiling_click(*corners[0])]
    clicks += [ceiling_click(*corners[1]), floor_click(*corners[2]), ceiling_click(*corners[3])]
    clicks += [floor_click(*corners[4]), ceiling_click(*corners[5])]
    room = piece.compute(piece.parse_clicks(clicks), LENS, None)
    assert len(room.corners) == 6
    assert [length for length, _ in room.walls] == pytest.approx(lengths(corners), abs=0.01)
    assert room.floor_area == pytest.approx(5 * 4 - 2 * 2, abs=0.05)


def test_without_app_height_the_ceiling_height_is_typed() -> None:
    room = piece.compute(piece.parse_clicks(both(RECTANGLE)), None, CEILING)
    assert room.lens_height == pytest.approx(LENS, abs=0.005)
    assert room.lens_source == "plafond_saisi"
    assert [length for length, _ in room.walls] == pytest.approx(lengths(RECTANGLE), abs=0.01)


def test_typed_ceiling_is_used_when_no_corner_has_both_clicks() -> None:
    clicks = [floor_click(x, z) for x, z in RECTANGLE]
    room = piece.compute(piece.parse_clicks(clicks), LENS, CEILING)
    assert room.ceiling_source == "saisie"
    assert room.walls[0][1] == pytest.approx(4.2 * CEILING, abs=0.05)


def test_effect_of_a_one_degree_error() -> None:
    # Horizon penché d'un degré vers le bas : tous les clics paraissent un degré plus bas.
    clicks = [dict(c, hauteur=c["hauteur"] - 1.0) for c in both(RECTANGLE)]
    room = piece.compute(piece.parse_clicks(clicks), LENS, None)
    errors = [abs(a - b) / b for (a, _), b in zip(room.walls, lengths(RECTANGLE), strict=True)]
    # Documenté dans docs/dimensions.md : quelques pour cent sur la longueur d'un mur.
    assert max(errors) < 0.10
    # Une erreur d'un centimètre sur la hauteur de l'objectif : moins de 1 % sur les longueurs.
    room = piece.compute(piece.parse_clicks(both(RECTANGLE)), LENS + 0.01, None)
    errors = [abs(a - b) / b for (a, _), b in zip(room.walls, lengths(RECTANGLE), strict=True)]
    assert max(errors) < 0.01


def test_clicks_are_grouped_into_corners() -> None:
    a, b = floor_click(*RECTANGLE[0]), ceiling_click(*RECTANGLE[0])
    far = ceiling_click(*RECTANGLE[1])
    corners = piece.group_corners(piece.parse_clicks([a, b, far]))
    assert len(corners) == 2
    assert corners[0].floor is not None and corners[0].ceiling is not None
    assert corners[1].floor is None and corners[1].ceiling is not None
    # Deux clics au sol de suite font deux coins, même proches.
    near = dict(a, cap=a["cap"] + 2)
    assert len(piece.group_corners(piece.parse_clicks([a, near]))) == 2


@pytest.mark.parametrize(
    ("clicks", "lens", "ceiling", "message"),
    [
        (both(RECTANGLE[:2]), LENS, None, "au moins 3"),
        ([floor_click(x, z) for x, z in RECTANGLE], LENS, None, "Hauteur sous plafond inconnue"),
        ([floor_click(x, z) for x, z in RECTANGLE], None, CEILING, "au sol puis au plafond"),
        (both(RECTANGLE), None, None, "saisir la hauteur"),
        ([{"cap": 10, "hauteur": 1.0}], LENS, None, "horizon"),
        ([{"cap": "nord", "hauteur": -20}], LENS, None, "illisible"),
        (both([RECTANGLE[0], RECTANGLE[2], RECTANGLE[1], RECTANGLE[3]]), LENS, None, "croisent"),
        (both(RECTANGLE), LENS, 9.0, "hors limites"),
    ],
)
def test_bad_measurements_are_refused(
    clicks: list[dict], lens: float | None, ceiling: float | None, message: str
) -> None:
    with pytest.raises(piece.PieceError, match=message):
        piece.compute(piece.parse_clicks(clicks), lens, ceiling)


def write_point(tmp_path: Path, lens_height: float | None) -> tuple[Path, Path]:
    point = tmp_path / "salon"
    (point / "photos").mkdir(parents=True)
    panorama = point / "panorama.jpg"
    cv2.imwrite(str(panorama), make_panorama(1024))
    data: dict = {"format": 1, "photos": []}
    if lens_height is not None:
        data["hauteur_objectif_m"] = lens_height
    (point / "capture.json").write_text(json.dumps(data), encoding="utf-8")
    return point, panorama


def test_saved_room_round_trip(tmp_path: Path) -> None:
    point, panorama = write_point(tmp_path, LENS)
    saved = piece.save(point, panorama, both(RECTANGLE), None)
    assert saved["hauteur_objectif_app_m"] == LENS
    assert (point / "piece.json").is_file()
    loaded = piece.load(point, panorama)
    assert loaded is not None and loaded["perimee"] is False
    assert loaded["resultat"]["surface_sol_m2"] == pytest.approx(4.2 * 3.1, abs=0.1)
    # Le panorama refait depuis : les clics ne tombent peut-être plus sur les coins.
    cv2.imwrite(str(panorama), make_panorama(1024, seed=3))
    assert piece.load(point, panorama)["perimee"] is True
    piece.delete(point)
    assert piece.load(point, panorama) is None


def test_lens_height_comes_from_the_app(tmp_path: Path) -> None:
    point, _ = write_point(tmp_path, 1.52)
    assert piece.lens_height(point) == 1.52
    point, _ = write_point(tmp_path / "autre", None)
    assert piece.lens_height(point) is None


def test_capture_lens_height_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    assert capture.parse({"format": 1, "photos": []}, path).lens_height is None
    measured = {"format": 1, "photos": [], "hauteur_objectif_m": 1.4}
    assert capture.parse(measured, path).lens_height == 1.4
    for bad in (-1, "1,4", True, 12):
        with pytest.raises(capture.CaptureError, match="hauteur_objectif_m"):
            capture.parse({"format": 1, "photos": [], "hauteur_objectif_m": bad}, path)


def test_contour_is_drawn_on_the_walls(tmp_path: Path) -> None:
    point, panorama = write_point(tmp_path, LENS)
    image = np.full((1024, 2048, 3), 40, np.uint8)
    room = piece.compute(piece.parse_clicks(both(RECTANGLE)), LENS, None)
    drawn = piece.draw(image, [], room)
    # Milieu du premier mur, au ras du sol : la ligne jaune du sol y passe.
    (x0, z0), (x1, z1) = RECTANGLE[0], RECTANGLE[1]
    middle = np.array([[(x0 + x1) / 2, LENS, (z0 + z1) / 2]])
    col, row = np.round(directions_to_equirect(middle, 2048, 1024)[0]).astype(int)
    patch = drawn[row - 3 : row + 4, col - 3 : col + 4].reshape(-1, 3)
    assert any(tuple(pixel) == piece.FLOOR_BGR for pixel in patch)
    # Le contour enregistré est fabriqué une fois, puis resservi.
    piece.save(point, panorama, both(RECTANGLE), None)
    first = piece.contour(point, panorama, 1024)
    stamp = first.stat().st_mtime_ns
    assert piece.contour(point, panorama, 1024).stat().st_mtime_ns == stamp
    jpeg = piece.preview(panorama, point, both(RECTANGLE)[:3], None, 1024)
    assert jpeg[:2] == b"\xff\xd8"
