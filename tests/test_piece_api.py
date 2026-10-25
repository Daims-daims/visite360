import json
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import pytest

from synthetic import make_panorama
from test_piece import LENS, RECTANGLE, both
from test_selection import FakeSegmenter
from test_selection_api import request, start
from visite360 import selection, stitch, visite


@pytest.fixture
def folders(tmp_path: Path) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(2048))
    capture = {"format": 1, "photos": [], "hauteur_objectif_m": LENS}
    (point / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    return stitch.resolve_folders(point)


@pytest.fixture
def server(folders: stitch.Folders) -> Iterator[ThreadingHTTPServer]:
    tour = visite.single_point(folders)
    running = start(tour, selection.Selector(tour, FakeSegmenter, "simulé"))
    yield running
    running.shutdown()
    running.server_close()


def test_agent_address_serves_the_viewer(server: ThreadingHTTPServer) -> None:
    status, body, kind = request(server, "/agent")
    assert status == 200 and kind.startswith("text/html")
    assert body == request(server, "/")[1]


def test_full_measurement_round(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:
    status, body, _ = request(server, "/p/0/piece.json")
    assert status == 200
    assert json.loads(body) == {"piece": None, "hauteur_objectif_app_m": LENS}

    clicks = both(RECTANGLE)
    status, body, kind = request(server, "/api/piece/apercu", {"point": 0, "clics": clicks[:2]})
    assert status == 200 and kind == "image/jpeg"

    status, body, _ = request(server, "/api/piece/calculer", {"point": 0, "clics": clicks})
    assert status == 200
    assert json.loads(body)["surface_sol_m2"] == pytest.approx(4.2 * 3.1, abs=0.1)

    status, body, _ = request(server, "/api/piece/enregistrer", {"point": 0, "clics": clicks})
    assert status == 200 and (folders.point / "piece.json").is_file()
    status, body, _ = request(server, "/p/0/piece.json")
    assert json.loads(body)["piece"]["resultat"]["murs"][0]["longueur_m"] == pytest.approx(4.2)
    status, body, kind = request(server, "/p/0/piece.jpg")
    assert status == 200 and kind == "image/jpeg"

    status, body, _ = request(server, "/api/piece/supprimer", {"point": 0})
    assert status == 200 and not (folders.point / "piece.json").exists()


def test_errors_are_explained(server: ThreadingHTTPServer) -> None:
    status, body, _ = request(
        server, "/api/piece/calculer", {"point": 0, "clics": both(RECTANGLE[:2])}
    )
    assert status == 400 and "au moins 3" in json.loads(body)["erreur"]
    status, body, _ = request(server, "/p/0/piece.jpg")
    assert status == 400 and "pas encore de pièce" in json.loads(body)["erreur"]
    status, _, _ = request(server, "/api/piece/inconnue", {"point": 0})
    assert status == 404
