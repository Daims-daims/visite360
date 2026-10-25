import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from test_generation import RECT, SCREEN, FakeGenerator
from test_selection import FakeSegmenter
from test_selection_api import request
from visite360 import couleur, generation, selection, serve, stitch, visite


@pytest.fixture
def folders(tmp_path: Path) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(2048))
    return stitch.resolve_folders(point)


def start(tour: visite.Tour, unavailable: str | None = None) -> ThreadingHTTPServer:
    selector = selection.Selector(tour, FakeSegmenter, "simulé")
    painter = couleur.Painter(1024)
    jobs = generation.Generations(
        tour,
        FakeGenerator,
        lambda point: painter.base(point.folders.point, point.folders.panorama),
        unavailable,
        selector.release,
    )
    server = serve.make_server(tour, "127.0.0.1", 0, selector=selector, generations=jobs)
    server.jobs = jobs  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def server(folders: stitch.Folders) -> Iterator[ThreadingHTTPServer]:
    running = start(visite.single_point(folders))
    yield running
    running.shutdown()
    running.server_close()


LAUNCH = {
    "point": 0,
    "cap": SCREEN.yaw,
    "hauteur": SCREEN.pitch,
    "champ": SCREEN.fov,
    "cadre": list(RECT),
    "objet": "le canapé gris",
    "nouveau": "un canapé vert",
    "nom": "Canapé",
}


def launch_and_wait(server: ThreadingHTTPServer, route: str, body: dict) -> dict:
    status, answer, _ = request(server, f"/api/generation/{route}", body)
    assert status == 200, answer
    server.jobs.wait(30)  # type: ignore[attr-defined]
    status, answer, _ = request(server, "/api/generation")
    return json.loads(answer)["travail"]


def test_full_generation_round(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:
    status, body, _ = request(server, "/api/generation")
    state = json.loads(body)
    assert status == 200 and state["disponible"] is True and state["travail"] is None

    job = launch_and_wait(server, "lancer", LAUNCH)
    assert job["etat"] == "terminee" and job["passe"] == generation.STEPS
    assert job["fiche"]["nom"] == "Canapé"

    status, body, _ = request(server, "/p/0/couleurs.json")
    state = json.loads(body)
    assert [r["id"] for r in state["generations"]] == ["generation-1"]
    assert state["version"]

    status, body, kind = request(server, "/p/0/apres.jpg")
    assert status == 200 and kind == "image/jpeg"
    after = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    assert (after != cv2.imread(str(folders.panorama))).any()

    job = launch_and_wait(server, "refaire", {"point": 0, "id": "generation-1"})
    assert job["etat"] == "terminee" and job["fiche"]["id"] == "generation-1"

    status, body, _ = request(
        server, "/api/generation/supprimer", {"point": 0, "id": "generation-1"}
    )
    assert status == 200
    state = json.loads(request(server, "/p/0/couleurs.json")[1])
    assert state["generations"] == [] and state["version"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"cadre": [0, 0, 5, 5]},
        {"cadre": "partout"},
        {"objet": ""},
        {"champ": 500},
        {"point": 3},
    ],
)
def test_bad_launches_are_refused(server: ThreadingHTTPServer, change: dict) -> None:
    status, body, _ = request(server, "/api/generation/lancer", {**LAUNCH, **change})
    assert status == 400
    assert json.loads(body)["erreur"]


def test_unknown_generation_is_refused(server: ThreadingHTTPServer) -> None:
    for route in ("refaire", "supprimer"):
        status, body, _ = request(
            server, f"/api/generation/{route}", {"point": 0, "id": "generation-9"}
        )
        assert status == 400 and "introuvable" in json.loads(body)["erreur"]
    status, _, _ = request(server, "/api/generation/autre", {"point": 0})
    assert status == 404


def test_missing_model_is_explained(folders: stitch.Folders) -> None:
    running = start(visite.single_point(folders), unavailable="Installer le modèle.")
    try:
        state = json.loads(request(running, "/api/generation")[1])
        assert state["disponible"] is False and state["message"] == "Installer le modèle."
        status, body, _ = request(running, "/api/generation/lancer", LAUNCH)
        assert status == 400 and json.loads(body)["erreur"] == "Installer le modèle."
    finally:
        running.shutdown()
        running.server_close()
