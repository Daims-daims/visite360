import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from test_selection import FakeSegmenter
from visite360 import selection, serve, stitch, visite


def request(
    server: ThreadingHTTPServer, path: str, body: object = None, raw: bytes | None = None
) -> tuple[int, bytes, str]:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    data = raw if raw is not None else None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read(), response.headers["Content-Type"]
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers["Content-Type"]


def start(tour: visite.Tour, selector: selection.Selector | None) -> ThreadingHTTPServer:
    server = serve.make_server(tour, "127.0.0.1", 0, selector=selector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def folders(tmp_path: Path) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(2048))
    return stitch.resolve_folders(point)


@pytest.fixture
def server(folders: stitch.Folders) -> Iterator[ThreadingHTTPServer]:
    tour = visite.single_point(folders)
    running = start(tour, selection.Selector(tour, FakeSegmenter, "simulé"))
    yield running
    running.shutdown()
    running.server_close()


def test_full_selection_round(server: ThreadingHTTPServer, folders: stitch.Folders) -> None:
    status, body, _ = request(server, "/api/selection")
    assert status == 200 and json.loads(body)["disponible"] is True

    status, body, _ = request(
        server, "/api/selection/vue", {"point": 0, "cap": 10, "hauteur": -5, "champ": 90}
    )
    assert status == 200
    view = json.loads(body)
    assert view["taille"] == 1024

    clicks = [{"x": 500, "y": 520, "ajout": True}]
    status, body, kind = request(
        server, "/api/selection/masque", {"vue": view["vue"], "clics": clicks}
    )
    assert status == 200 and kind == "image/png"
    overlay = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_UNCHANGED)
    assert overlay.shape == (1024, 1024, 4)
    assert overlay[520, 500, 3] > 0 and overlay[100, 100, 3] == 0

    status, body, _ = request(
        server, "/api/selection/valider", {"vue": view["vue"], "clics": clicks, "nom": "Mur"}
    )
    assert status == 200 and json.loads(body)["id"] == "selection-1"

    status, body, _ = request(server, "/p/0/selections.json")
    assert [record["nom"] for record in json.loads(body)] == ["Mur"]
    status, body, kind = request(server, "/p/0/selections/selection-1.jpg")
    assert status == 200 and kind == "image/jpeg" and body[:2] == b"\xff\xd8"

    status, _, _ = request(server, "/api/selection/supprimer", {"point": 0, "id": "selection-1"})
    assert status == 200
    status, body, _ = request(server, "/p/0/selections.json")
    assert json.loads(body) == []
    assert request(server, "/p/0/selections/selection-1.jpg")[0] == 400


@pytest.mark.parametrize(
    ("path", "body", "raw", "code"),
    [
        ("/api/selection/vue", {"point": 0, "cap": 0, "hauteur": 0, "champ": 5}, None, 400),
        ("/api/selection/vue", {"point": 7, "cap": 0, "hauteur": 0, "champ": 90}, None, 400),
        ("/api/selection/masque", {"vue": "inconnue", "clics": []}, None, 400),
        ("/api/selection/supprimer", {"point": 0, "id": "../../visite.json"}, None, 400),
        ("/api/selection/vue", None, b"pas du json", 400),
        ("/api/selection/vue", None, b"[1, 2]", 400),
        ("/api/selection/vue", None, b" " * (serve.MAX_BODY + 1), 413),
        ("/api/selection/autre", {}, None, 404),
        ("/api/ailleurs", {}, None, 404),
    ],
)
def test_bad_requests_get_clear_errors(
    server: ThreadingHTTPServer, path: str, body: object, raw: bytes | None, code: int
) -> None:
    status, answer, kind = request(server, path, body, raw)

    assert status == code
    if kind == serve.JSON:
        assert json.loads(answer)["erreur"]


def test_unknown_files_stay_hidden(server: ThreadingHTTPServer) -> None:
    assert request(server, "/p/0/selections/../panorama.jpg")[0] == 404
    assert request(server, "/p/0/modifications/selection-1.png")[0] == 404
    assert request(server, "/p/9/selections.json")[0] == 400


def test_selection_unavailable_without_sam2(folders: stitch.Folders) -> None:
    tour = visite.single_point(folders)
    message = "La sélection demande SAM 2.1 (PyTorch absent)."
    running = start(tour, selection.Selector(tour, FakeSegmenter, "simulé", message))
    try:
        status, body, _ = request(running, "/api/selection")
        assert json.loads(body) == {"disponible": False, "message": message}
        status, body, _ = request(
            running, "/api/selection/vue", {"point": 0, "cap": 0, "hauteur": 0, "champ": 90}
        )
        assert status == 503 and json.loads(body)["erreur"] == message
        assert request(running, "/p/0/selections.json")[0] == 200
    finally:
        running.shutdown()
        running.server_close()


def test_default_selector_reports_missing_sam2(
    folders: stitch.Folders, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(serve.segment, "missing", lambda: "PyTorch et SAM 2 absents")

    selector = serve.default_selector(visite.single_point(folders))

    assert selector.unavailable is not None
    assert "PyTorch et SAM 2 absents" in selector.unavailable
    assert "installer-sam2.sh" in selector.unavailable
