import copy
import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from test_chiffrage import folders, paint, patch_on_plane  # noqa: F401 (fixture)
from test_generation import add_generation
from test_piece import RECTANGLE, both
from test_selection import FakeSegmenter
from test_selection_api import request, start
from visite360 import chiffrage, piece, selection, stitch, visite


@pytest.fixture
def server(folders: stitch.Folders) -> Iterator[ThreadingHTTPServer]:  # noqa: F811
    tour = visite.single_point(folders)
    running = start(tour, selection.Selector(tour, FakeSegmenter, "simulé"))
    yield running
    running.shutdown()
    running.server_close()


def test_estimate_of_the_visit(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:  # noqa: F811
    status, body, _ = request(server, "/api/chiffrage")
    assert status == 200
    empty = json.loads(body)
    assert empty["points"][0]["lignes"] == [] and empty["tarifs_par_defaut"]

    piece.save(folders.point, folders.panorama, both(RECTANGLE), None)
    paint(folders, patch_on_plane(2, 1.9, (0.0, 2.0), (0.2, 1.2)), "Mur du fond")
    record = add_generation(folders)
    status, body, _ = request(server, "/api/chiffrage")
    result = json.loads(body)
    assert [line["poste"] for line in result["points"][0]["lignes"]] == ["mur", "meuble"]
    assert result["complet"] and result["bas"] > 500

    status, body, _ = request(
        server, "/api/chiffrage/meuble", {"point": 0, "id": record["id"], "categorie": "tapis"}
    )
    assert status == 200
    assert json.loads(body)["points"][0]["lignes"][1]["categorie"] == "tapis"

    # Supprimer l'objet remplacé oublie aussi le type choisi.
    request(server, "/api/generation/supprimer", {"point": 0, "id": record["id"]})
    assert chiffrage.load_overrides(folders.point) == {}


def test_grid_is_edited_and_reset(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:  # noqa: F811
    status, body, _ = request(server, "/api/tarifs")
    answer = json.loads(body)
    assert status == 200 and answer["par_defaut"]

    grid = copy.deepcopy(answer["tarifs"])
    grid["surfaces"]["mur"]["haut"] = 10
    status, body, _ = request(server, "/api/tarifs/enregistrer", {"tarifs": grid})
    assert status == 400 and "prix bas dépasse" in json.loads(body)["erreur"]
    assert not (folders.point / "tarifs.json").exists()

    grid["surfaces"]["mur"]["bas"] = 8
    status, body, _ = request(server, "/api/tarifs/enregistrer", {"tarifs": grid})
    assert status == 200 and (folders.point / "tarifs.json").is_file()
    assert json.loads(request(server, "/api/tarifs")[1])["tarifs"]["surfaces"]["mur"]["haut"] == 10

    status, body, _ = request(server, "/api/tarifs/reinitialiser", {})
    assert status == 200 and json.loads(body)["par_defaut"]
    assert not (folders.point / "tarifs.json").exists()


def test_errors_are_explained(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:  # noqa: F811
    (folders.point / "tarifs.json").write_text("{", encoding="utf-8")
    status, body, _ = request(server, "/api/chiffrage")
    assert status == 400 and "tarifs.json illisible" in json.loads(body)["erreur"]
    status, _, _ = request(server, "/api/tarifs/inconnue", {})
    assert status == 404
