import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from test_selection import FakeSegmenter
from test_selection_api import request, start
from visite360 import selection, stitch, visite
from visite360.selection import Click, ViewSpec


@pytest.fixture
def folders(tmp_path: Path) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(2048))
    folders = stitch.resolve_folders(point)
    mask = np.zeros((1024, 2048), dtype=np.uint8)
    mask[300:700, 200:800] = 255
    selection.save(
        point, folders.panorama, mask, ViewSpec(0, 0, 90), [Click(512, 512, True)], "simulé", 0.9
    )
    return folders


@pytest.fixture
def server(folders: stitch.Folders) -> Iterator[ThreadingHTTPServer]:
    tour = visite.single_point(folders)
    running = start(tour, selection.Selector(tour, FakeSegmenter, "simulé"))
    yield running
    running.shutdown()
    running.server_close()


def decode(body: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)


def test_full_color_round(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:
    original = folders.panorama.read_bytes()
    status, body, _ = request(server, "/p/0/couleurs.json")
    assert status == 200 and json.loads(body) == {"couleurs": [], "version": None}
    assert request(server, "/p/0/apres.jpg")[0] == 400

    trial = {"point": 0, "selection": "selection-1", "couleur": "#8fa58a"}
    status, body, kind = request(server, "/api/couleur/apercu", trial)
    assert status == 200 and kind == "image/jpeg" and decode(body).shape == (1024, 2048, 3)
    assert json.loads(request(server, "/p/0/couleurs.json")[1])["couleurs"] == []

    status, body, _ = request(server, "/api/couleur/appliquer", trial)
    assert status == 200 and json.loads(body)["id"] == "couleur-1"
    state = json.loads(request(server, "/p/0/couleurs.json")[1])
    assert state["version"] and state["couleurs"][0]["couleur"] == "#8fa58a"

    status, body, kind = request(server, "/p/0/apres.jpg")
    assert status == 200 and kind == "image/jpeg" and decode(body).shape == (1024, 2048, 3)
    status, body, _ = request(server, "/p/0/apres-mobile.jpg")
    assert status == 200 and decode(body).shape == (1024, 2048, 3)

    status, _, _ = request(server, "/api/couleur/annuler", {"point": 0, "id": "couleur-1"})
    assert status == 200
    assert json.loads(request(server, "/p/0/couleurs.json")[1])["version"] is None
    assert folders.panorama.read_bytes() == original


def test_palette_is_served_and_shade_is_saved(server: ThreadingHTTPServer) -> None:
    status, body, kind = request(server, "/nuancier.json")
    assert status == 200 and kind.startswith("application/json")
    first = json.loads(body)["familles"][0]["teintes"][0]

    trial = {"point": 0, "selection": "selection-1", "couleur": first["couleur"]}
    status, body, _ = request(server, "/api/couleur/appliquer", {**trial, "teinte": first["nom"]})

    assert status == 200 and json.loads(body)["teinte"] == first["nom"]
    state = json.loads(request(server, "/p/0/couleurs.json")[1])
    assert state["couleurs"][0]["teinte"] == first["nom"]


def test_deleting_a_selection_removes_its_color(
    server: ThreadingHTTPServer, folders: stitch.Folders
) -> None:
    trial = {"point": 0, "selection": "selection-1", "couleur": "#c0603a"}
    assert request(server, "/api/couleur/appliquer", trial)[0] == 200

    status, _, _ = request(server, "/api/selection/supprimer", {"point": 0, "id": "selection-1"})

    assert status == 200
    assert not (folders.point / "modifications" / "couleur-1.json").exists()
    assert json.loads(request(server, "/p/0/couleurs.json")[1])["couleurs"] == []


@pytest.mark.parametrize(
    ("path", "body", "code"),
    [
        ("/api/couleur/appliquer", {"point": 0, "selection": "selection-1", "couleur": "x"}, 400),
        (
            "/api/couleur/appliquer",
            {"point": 0, "selection": "selection-4", "couleur": "#fff000"},
            400,
        ),
        ("/api/couleur/apercu", {"point": 0, "selection": "../../x", "couleur": "#fff000"}, 400),
        (
            "/api/couleur/appliquer",
            {"point": 3, "selection": "selection-1", "couleur": "#fff000"},
            400,
        ),
        ("/api/couleur/annuler", {"point": 0, "id": "couleur-1"}, 400),
        ("/api/couleur/annuler", {"point": 0, "id": "../visite.json"}, 400),
        ("/api/couleur/autre", {"point": 0}, 404),
    ],
)
def test_bad_color_requests_get_clear_errors(
    server: ThreadingHTTPServer, path: str, body: object, code: int
) -> None:
    status, answer, _ = request(server, path, body)

    assert status == code
    assert json.loads(answer)["erreur"]


def test_color_files_stay_hidden(server: ThreadingHTTPServer) -> None:
    assert request(server, "/p/0/modifications/couleur-1.json")[0] == 404
    assert request(server, "/p/0/cache/apres.jpg")[0] == 404
    assert request(server, "/p/0/apres-autre.jpg")[0] == 404
    assert request(server, "/p/5/couleurs.json")[0] == 400
