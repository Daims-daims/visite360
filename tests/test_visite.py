import json
from pathlib import Path
from typing import Any

import pytest

from visite360 import visite
from visite360.cli import main


def make_tour(root: Path, names: tuple[str, ...] = ("1", "2", "10")) -> Path:
    folder = root / "appart"
    for name in names:
        (folder / name / "photos").mkdir(parents=True)
    return folder


def write_json(folder: Path, content: dict[str, Any]) -> None:
    (folder / visite.FILE_NAME).write_text(json.dumps(content), encoding="utf-8")


def valid(**changes: Any) -> dict[str, Any]:
    content: dict[str, Any] = {
        "points": [{"id": "1", "nom": "Salon"}, {"id": "2"}],
        "liens": [{"de": "1", "vers": "2", "angle": 90}],
    }
    content.update(changes)
    return content


def test_skeleton_lists_point_folders_in_natural_order(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    (folder / "notes").mkdir()  # pas un point : ni photos/ ni panorama.jpg

    tour, created = visite.open_tour(folder)

    assert created
    assert [point.id for point in tour.points] == ["1", "2", "10"]
    assert tour.start == "1" and tour.links == ()
    written = json.loads((folder / visite.FILE_NAME).read_text(encoding="utf-8"))
    assert written["liens"] == [] and len(written["points"]) == 3


def test_existing_file_is_never_rewritten(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, valid())
    before = (folder / visite.FILE_NAME).read_bytes()

    tour, created = visite.open_tour(folder)

    assert not created and (folder / visite.FILE_NAME).read_bytes() == before
    assert tour.ignored == ("10",)  # dossier présent mais non déclaré
    with pytest.raises(visite.VisiteError, match="existe déjà"):
        visite.write_skeleton(folder)


def test_valid_file_gives_links_names_and_defaults(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, valid(depart="2"))

    tour = visite.load(folder)

    assert tour.start == "2" and [p.name for p in tour.points] == ["Salon", "2"]
    (link,) = tour.links_from("1")
    assert link.target == "2" and link.angle == 90 and link.text == "2"
    assert link.pitch == visite.DEFAULT_LINK_PITCH
    assert tour.links_from("2") == []


def test_angle_is_wrapped_into_half_turn(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, valid(liens=[{"de": "1", "vers": "2", "angle": 270}]))

    assert visite.load(folder).links[0].angle == -90


def test_optional_app_fields_are_read(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, valid(points=[{"id": "1", "nord": 30, "position": [1.5, 2]}, {"id": "2"}]))

    point = visite.load(folder).points[0]

    assert point.north == 30 and point.position == (1.5, 2.0)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (valid(liens=[{"de": "1", "vers": "9", "angle": 0}]), "n'existe pas"),
        (valid(liens=[{"de": "7", "vers": "1", "angle": 0}]), "n'existe pas"),
        (valid(liens=[{"de": "1", "vers": "1", "angle": 0}]), "lui-même"),
        (valid(liens=[{"de": "1", "vers": "2"}]), "angle"),
        (valid(liens=[{"de": "1", "vers": "2", "angle": "droite"}]), "nombre"),
        (valid(liens=[{"de": "1", "vers": "2", "angle": 500}]), "plage"),
        (valid(liens=[{"de": "1", "vers": "2", "angel": 5}]), "clé inconnue"),
        (valid(points=[{"id": "1"}, {"id": "1"}]), "deux fois"),
        (valid(points=[{"id": "1"}, {"id": "absent"}]), "n'existe pas"),
        (valid(points=[{"id": "../x"}]), "nom d'un dossier"),
        (valid(points=[]), "au moins un point"),
        (valid(depart="9"), "depart"),
        (valid(version=2), "version"),
        (valid(points=[{"id": "1", "position": [1]}]), "position"),
    ],
)
def test_invalid_files_give_clear_messages(
    tmp_path: Path, content: dict[str, Any], message: str
) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, content)

    with pytest.raises(visite.VisiteError, match=message):
        visite.load(folder)


def test_broken_json_gives_line_and_hint(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    (folder / visite.FILE_NAME).write_text('{"points": [,]}', encoding="utf-8")

    with pytest.raises(visite.VisiteError, match="ligne 1"):
        visite.load(folder)


def test_point_folder_is_not_taken_for_a_tour(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)

    assert visite.looks_like_tour(folder)
    assert not visite.looks_like_tour(folder / "1")
    assert not visite.looks_like_tour(folder / "1" / "photos")
    tour, created = visite.open_tour(folder / "1")
    assert not created and [p.id for p in tour.points] == ["1"]
    assert not (folder / "1" / visite.FILE_NAME).exists()


def test_cli_reports_invalid_file_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_tour(tmp_path)
    write_json(folder, valid(liens=[{"de": "1", "vers": "9", "angle": 0}]))

    assert main(["serve", str(folder), "--local"]) == 1
    assert "Erreur" in capsys.readouterr().err
