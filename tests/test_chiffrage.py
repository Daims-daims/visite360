import copy
import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from test_generation import RECT, SCREEN, add_generation
from test_piece import CEILING, L_SHAPE, LENS, RECTANGLE, both
from visite360 import chiffrage, couleur, piece, selection, stitch
from visite360.chiffrage import ChiffrageError, guess_category
from visite360.generation import Request
from visite360.spherical import equirect_directions

WIDTH = 2048


def room_of(corners: list[tuple[float, float]]) -> piece.Room:
    return piece.compute(piece.parse_clicks(both(corners)), LENS, None)


def directions(width: int = WIDTH) -> np.ndarray:
    height = width // 2
    return equirect_directions(width, height, np.arange(height), np.arange(width)).astype(
        np.float64
    )


def patch_on_plane(
    axis: int, value: float, span: tuple[float, float], heights: tuple[float, float]
):
    """Masque d'un rectangle peint sur le mur vertical `x = value` (axis 0) ou `z = value`
    (axis 2) : de span[0] à span[1] le long du mur, de heights[0] à heights[1] au-dessus du sol.
    Calcul indépendant du module : intersection de chaque direction avec le plan du mur."""
    d = directions()
    with np.errstate(divide="ignore", invalid="ignore"):
        t = value / d[..., axis]
    along = t * d[..., 2 - axis]
    above_floor = LENS - t * d[..., 1]  # y vers le bas, objectif à LENS du sol
    inside = (
        (t > 0)
        & (along >= span[0])
        & (along <= span[1])
        & (above_floor >= heights[0])
        & (above_floor <= heights[1])
    )
    return inside.astype(np.float32)


@pytest.mark.parametrize("corners", [RECTANGLE, L_SHAPE])
def test_whole_panorama_gives_every_surface_of_the_room(corners) -> None:
    room = room_of(corners)
    areas = chiffrage.surface_areas(np.ones((WIDTH // 2, WIDTH), np.float32), room)
    for number, (_, expected) in enumerate(room.walls, start=1):
        assert areas[f"mur-{number}"] == pytest.approx(expected, rel=0.03)
    assert areas["sol"] == pytest.approx(room.floor_area, rel=0.01)
    assert areas["plafond"] == pytest.approx(room.floor_area, rel=0.01)


def test_a_painted_rectangle_gives_its_area() -> None:
    # Mur 1 du rectangle : le plan z = 1,9 m. Rectangle de 2 m × 1 m, de 0,2 à 1,2 m du sol.
    mask = patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2))
    areas = chiffrage.surface_areas(mask, room_of(RECTANGLE))
    assert set(areas) == {"mur-1"}
    assert areas["mur-1"] == pytest.approx(2.0, rel=0.02)


def test_a_selection_across_a_corner_is_split_between_walls() -> None:
    # Le coin (2,6 ; 1,9) : 1 m de chaque côté, sur toute la hauteur.
    mask = np.maximum(
        patch_on_plane(2, 1.9, (1.6, 2.6), (0.0, CEILING)),
        patch_on_plane(0, 2.6, (0.9, 1.9), (0.0, CEILING)),
    )
    areas = chiffrage.surface_areas(mask, room_of(RECTANGLE))
    assert areas["mur-1"] == pytest.approx(CEILING, rel=0.03)
    assert areas["mur-2"] == pytest.approx(CEILING, rel=0.03)
    assert areas.get("sol", 0.0) + areas.get("plafond", 0.0) < 0.05


def test_a_lens_outside_the_room_is_refused() -> None:
    # Coins tous devant l'objectif : il n'est pas dans la pièce dessinée.
    corners = [(-1.0, 1.0), (1.0, 1.0), (1.0, 3.0), (-1.0, 3.0)]
    with pytest.raises(ChiffrageError, match="hors du contour"):
        chiffrage.surface_areas(np.ones((256, 512), np.float32), room_of(corners))


# --- Grille --------------------------------------------------------------------------------


def test_default_grid_is_valid_and_has_its_sources() -> None:
    grid = chiffrage.parse_grid(chiffrage.DEFAULT_GRID)
    assert set(grid["surfaces"]) == {"mur", "plafond", "sol"}
    assert grid["sources"] and all(s["adresse"].startswith("https://") for s in grid["sources"])
    for item in [*grid["surfaces"].values(), *grid["meubles"]]:
        assert 0 < item["bas"] <= item["haut"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda g: g["surfaces"]["mur"].update(bas=60), "prix bas dépasse"),
        (lambda g: g["surfaces"].pop("sol"), "« mur », « plafond » et « sol »"),
        (lambda g: g["surfaces"]["mur"].update(haut=-5), "hors limites"),
        (lambda g: g["surfaces"]["mur"].update(haut="cher"), "nombre d'euros"),
        (lambda g: g["meubles"].pop(), "« autre »"),
        (lambda g: g["meubles"].append(dict(g["meubles"][0])), "en double"),
        (lambda g: g.update(version=9), "format inconnu"),
    ],
)
def test_malformed_grids_are_refused(change, message) -> None:
    grid = copy.deepcopy(chiffrage.DEFAULT_GRID)
    change(grid)
    with pytest.raises(ChiffrageError, match=message):
        chiffrage.parse_grid(grid)


def test_grid_is_saved_read_and_reset(tmp_path: Path) -> None:
    assert chiffrage.load_grid(tmp_path)[1] is True
    grid = copy.deepcopy(chiffrage.DEFAULT_GRID)
    grid["surfaces"]["mur"].update(bas=25, haut=30)
    chiffrage.save_grid(tmp_path, grid)
    loaded, default = chiffrage.load_grid(tmp_path)
    assert not default and loaded["surfaces"]["mur"]["haut"] == 30
    chiffrage.reset_grid(tmp_path)
    assert chiffrage.load_grid(tmp_path)[1] is True


def test_a_broken_grid_file_is_explained(tmp_path: Path) -> None:
    (tmp_path / "tarifs.json").write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ChiffrageError, match="tarifs.json illisible"):
        chiffrage.load_grid(tmp_path)
    (tmp_path / "tarifs.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(ChiffrageError, match="tarifs.json : "):
        chiffrage.load_grid(tmp_path)


# --- Objets remplacés ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Remplace le canapé gris par un fauteuil en cuir", "fauteuil"),
        ("Remplace la table par une table basse en chêne", "table_basse"),
        ("Remplace les chaises par des tabourets", "chaise"),
        ("Remplace le canape", "canape"),
        ("Ajoute une plante verte dans le coin", "plante"),
        ("Retire le pouf", "fauteuil"),
        ("Change le truc bizarre", "autre"),
        ("Remplace la lampe par quelque chose de joli", "luminaire"),
    ],
)
def test_object_type_is_recognised(instruction: str, expected: str) -> None:
    assert guess_category(instruction, chiffrage.parse_grid(chiffrage.DEFAULT_GRID)) == expected


# --- Chiffrage d'un point ------------------------------------------------------------------


@pytest.fixture
def folders(tmp_path: Path) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(WIDTH))
    capture = {"format": 1, "photos": [], "hauteur_objectif_m": LENS}
    (point / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    return stitch.resolve_folders(point)


def paint(folders: stitch.Folders, mask: np.ndarray, name: str) -> dict:
    record = selection.save(
        folders.point,
        folders.panorama,
        (mask > 0).astype(np.uint8) * 255,
        SCREEN,
        [],
        "simulé",
        1.0,
        name,
    )
    return couleur.save(folders.point, record["id"], "#a3b09a", "Vert sauge", None)


def source(folders: stitch.Folders) -> chiffrage.PointInput:
    return chiffrage.PointInput("Salon", folders.point, folders.panorama)


def test_point_without_room_has_no_price_for_its_walls(folders: stitch.Folders) -> None:
    paint(folders, patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2)), "Mur du fond")
    add_generation(folders)
    grid = chiffrage.parse_grid(chiffrage.DEFAULT_GRID)
    result = chiffrage.estimate_point(source(folders), grid)
    wall, furniture = result["lignes"]
    assert wall["bas"] is None and "pas encore mesurée" in wall["probleme"]
    assert furniture["categorie"] == "canape" and furniture["bas"] == 500
    assert not result["complet"] and result["bas"] == 500


def test_point_is_priced_from_its_room_and_grid(folders: stitch.Folders) -> None:
    piece.save(folders.point, folders.panorama, both(RECTANGLE), None)
    paint(folders, patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2)), "Mur du fond")
    add_generation(folders)
    grid = chiffrage.parse_grid(chiffrage.DEFAULT_GRID)
    result = chiffrage.estimate_point(source(folders), grid)
    wall, furniture = result["lignes"]
    assert wall["nom"] == "Mur du fond" and wall["poste"] == "mur" and wall["detail"] == "mur 1"
    assert wall["quantite"] == pytest.approx(2.0, abs=0.1)
    assert wall["bas"] == pytest.approx(2.0 * 20, rel=0.03)
    assert wall["haut"] == pytest.approx(2.0 * 50, rel=0.03)
    assert result["complet"]
    assert result["bas"] == pytest.approx(wall["bas"] + furniture["bas"])
    # Surfaces mises de côté, puis relues sans recalcul.
    assert (folders.point / "cache" / "chiffrage.json").is_file()
    assert chiffrage.estimate_point(source(folders), grid) == result


def test_wall_and_floor_parts_are_separate_lines(folders: stitch.Folders) -> None:
    piece.save(folders.point, folders.panorama, both(RECTANGLE), None)
    d = directions()
    floor = (d[..., 1] > 0.8).astype(np.float32)  # un disque de sol sous l'objectif
    paint(folders, np.maximum(floor, patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2))), "Mur et sol")
    result = chiffrage.estimate_point(source(folders), chiffrage.parse_grid(chiffrage.DEFAULT_GRID))
    assert [line["poste"] for line in result["lignes"]] == ["mur", "sol"]


def test_agent_corrects_the_object_type(folders: stitch.Folders) -> None:
    record = add_generation(folders)
    grid = chiffrage.parse_grid(chiffrage.DEFAULT_GRID)
    chiffrage.set_category(folders.point, grid, record["id"], "fauteuil")
    line = chiffrage.estimate_point(source(folders), grid)["lignes"][0]
    assert line["categorie"] == "fauteuil" and line["categorie_reconnue"] == "canape"
    with pytest.raises(ChiffrageError, match="inconnu"):
        chiffrage.set_category(folders.point, grid, record["id"], "fusee")
    chiffrage.forget(folders.point, record["id"])
    assert chiffrage.load_overrides(folders.point) == {}


def test_command_prints_the_estimate(folders: stitch.Folders) -> None:
    piece.save(folders.point, folders.panorama, both(RECTANGLE), None)
    paint(folders, patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2)), "Mur du fond")
    request = Request.parse(SCREEN, list(RECT), "Remplace le lit par un bureau", None)
    add_generation(folders, request)
    out = io.StringIO()
    assert chiffrage.run(folders.point, out) == 0
    text = out.getvalue()
    assert "Mur du fond : Peinture des murs" in text and "Bureau, 150 € à 700 €" in text
    assert "Total : de 190 € à 800 €" in text
    assert "Prix indicatifs par défaut" in text


def test_command_explains_a_broken_grid(folders: stitch.Folders, capsys) -> None:
    (folders.point / "tarifs.json").write_text("[]", encoding="utf-8")
    assert chiffrage.run(folders.point, io.StringIO()) == 1
    assert "tarifs.json" in capsys.readouterr().err


def test_amounts_are_rounded_as_an_order_of_magnitude() -> None:
    assert chiffrage.euros(1234.0) == "1 230 €"
    assert chiffrage.euros(47.4) == "47 €"
