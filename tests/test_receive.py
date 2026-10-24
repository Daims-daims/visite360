import hashlib
import http.client
import io
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from visite360 import receive

CODE = "123456"


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[ThreadingHTTPServer, Path, io.StringIO]]:
    root = tmp_path / "visites"
    root.mkdir()
    out = io.StringIO()
    instance = receive.make_server(receive.Receiver(root, CODE, out), "127.0.0.1", 0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, root, out
    instance.shutdown()
    instance.server_close()


def request(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    body: bytes = b"",
    code: str = CODE,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        headers = {receive.CODE_HEADER: code, "Content-Length": str(len(body))}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        connection.close()


def tour_files(
    points: list[str], links: list[dict[str, Any]] | None = None, seed: int = 0
) -> dict[str, bytes]:
    """Fichiers d'une visite comme les enverrait l'app : visite.json, et pour chaque point
    capture.json et deux photos (des octets quelconques suffisent ici)."""
    rng = np.random.default_rng(seed)
    files: dict[str, bytes] = {}
    for point in points:
        photos = []
        for number in (1, 2):
            name = f"IMG_{number:04d}.jpg"
            files[f"{point}/photos/{name}"] = rng.bytes(5000)
            photos.append({"fichier": name, "rotation": np.eye(3).tolist()})
        capture_json = {"format": 1, "cap_depart": 0, "photos": photos}
        files[f"{point}/capture.json"] = json.dumps(capture_json).encode()
    tour = {
        "version": 1,
        "nom": "Appartement",
        "depart": points[0],
        "points": [{"id": p, "nom": p.capitalize()} for p in points],
        "liens": links or [],
    }
    files["visite.json"] = json.dumps(tour).encode()
    return files


def manifest(name: str, files: dict[str, bytes]) -> bytes:
    entries = [
        {"chemin": path, "taille": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for path, data in files.items()
    ]
    return json.dumps({"format": 1, "visite": name, "fichiers": entries}).encode()


def send(
    server: ThreadingHTTPServer, name: str, files: dict[str, bytes], skip: set[str] = frozenset()
) -> tuple[int, dict[str, Any], list[str]]:
    """Envoi complet comme le fait l'app. Renvoie la réponse finale et les fichiers demandés."""
    status, answer = request(server, "POST", "/envois", manifest(name, files))
    if status != 200:
        return status, answer, []
    upload, missing = answer["envoi"], answer["manquants"]
    for path in missing:
        if path not in skip:
            assert request(server, "PUT", f"/envois/{upload}/{path}", files[path])[0] == 200
    status, answer = request(server, "POST", f"/envois/{upload}/fin")
    return status, answer, missing


def test_a_tour_is_received_and_stored(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    instance, root, out = server
    links = [{"de": "salon", "vers": "cuisine", "angle": 90.0, "hauteur": -5.0}]
    files = tour_files(["salon", "cuisine"], links)

    status, answer, missing = send(instance, "appart", files)

    assert status == 200, answer
    assert answer["points"] == 2 and answer["nouveaux"] == 6
    assert sorted(missing) == sorted(files)
    for path, data in files.items():
        assert (root / "appart" / path).read_bytes() == data
    assert not list(root.glob(".reception-*"))
    assert "visite360 serve" in out.getvalue()


def test_wrong_code_is_refused_then_blocks(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    instance, root, _ = server

    assert request(instance, "GET", "/info")[0] == 200
    status, answer = request(instance, "GET", "/info", code="000000")
    assert status == 403 and "Code faux" in answer["message"]
    for _ in range(receive.MAX_WRONG_CODES):
        request(instance, "GET", "/info", code="000000")
    status, answer = request(instance, "GET", "/info")
    assert status == 403 and "bloquée" in answer["message"]


def test_code_with_spaces_is_accepted(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    assert request(server[0], "GET", "/info", code="123 456")[0] == 200


def test_incomplete_upload_is_refused_and_can_resume(
    server: tuple[ThreadingHTTPServer, Path, Any],
) -> None:
    instance, root, _ = server
    files = tour_files(["salon"])

    status, answer, _ = send(instance, "appart", files, skip={"salon/photos/IMG_0002.jpg"})

    assert status == 409 and "incomplet" in answer["message"]
    assert not (root / "appart").exists()
    # L'app renvoie : seul ce qui manque part.
    status, answer, missing = send(instance, "appart", files)
    assert status == 200, answer


def test_damaged_file_is_refused(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    instance, root, _ = server
    files = tour_files(["salon"])
    status, answer = request(instance, "POST", "/envois", manifest("appart", files))
    path = "salon/photos/IMG_0001.jpg"
    damaged = bytes([files[path][0] ^ 1]) + files[path][1:]

    status, answer = request(instance, "PUT", f"/envois/{answer['envoi']}/{path}", damaged)

    assert status == 400 and "abîmé" in answer["message"]


@pytest.mark.parametrize(
    "path",
    ["../etc/passwd", "salon/../../x.jpg", "salon/photos/a.exe", ".cache/x.jpg", "salon/rapport"],
)
def test_unexpected_paths_are_refused(
    server: tuple[ThreadingHTTPServer, Path, Any], path: str
) -> None:
    files = tour_files(["salon"])
    files[path] = b"x"

    status, answer, _ = send(server[0], "appart", files)

    assert status == 400 and "refusé" in answer["message"]


def test_bad_visit_name_is_refused(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    status, answer, _ = send(server[0], "../appart", tour_files(["salon"]))
    assert status == 400 and "Nom de visite" in answer["message"]


def test_invalid_visite_json_is_refused(server: tuple[ThreadingHTTPServer, Path, Any]) -> None:
    instance, root, _ = server
    files = tour_files(["salon"], [{"de": "salon", "vers": "cuisine", "angle": 0}])

    status, answer, _ = send(instance, "appart", files)

    assert status == 422 and "cuisine" in answer["message"]
    assert not (root / "appart").exists()
    assert not list(root.glob(".reception-*"))


def test_second_send_only_transfers_new_points(
    server: tuple[ThreadingHTTPServer, Path, Any],
) -> None:
    instance, root, _ = server
    first = tour_files(["salon"])
    assert send(instance, "appart", first)[0] == 200
    # Même graine : les photos du salon sont les mêmes, seul visite.json change.
    second = tour_files(["salon", "cuisine"])

    status, answer, missing = send(instance, "appart", second)

    assert status == 200, answer
    assert sorted(missing) == sorted(
        ["visite.json", "cuisine/capture.json"] + [f"cuisine/photos/IMG_000{n}.jpg" for n in (1, 2)]
    )
    assert json.loads((root / "appart" / "visite.json").read_bytes())["points"][1]["id"] == (
        "cuisine"
    )
    # L'ancien visite.json est gardé à côté.
    assert len(list((root / "appart").glob("visite-avant-*.json"))) == 1


def test_existing_point_with_other_photos_is_never_overwritten(
    server: tuple[ThreadingHTTPServer, Path, Any],
) -> None:
    instance, root, _ = server
    assert send(instance, "appart", tour_files(["salon"], seed=1))[0] == 200
    original = (root / "appart" / "salon" / "photos" / "IMG_0001.jpg").read_bytes()

    status, answer, _ = send(instance, "appart", tour_files(["salon"], seed=2))

    assert status == 409 and "jamais écrasées" in answer["message"]
    assert (root / "appart" / "salon" / "photos" / "IMG_0001.jpg").read_bytes() == original


def test_leftovers_of_interrupted_uploads_are_removed(tmp_path: Path) -> None:
    (tmp_path / ".reception-abc" / "salon").mkdir(parents=True)
    (tmp_path / "appart").mkdir()

    receive.remove_leftovers(tmp_path)

    assert [p.name for p in tmp_path.iterdir()] == ["appart"]


def test_missing_dns_sd_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receive.shutil, "which", lambda name: None)
    out = io.StringIO()

    assert receive.announce(8361, out) is None
    assert "saisir l'adresse" in out.getvalue()


def test_announce_calls_dns_sd_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(receive.shutil, "which", lambda name: "/usr/bin/dns-sd")
    monkeypatch.setattr(
        receive.subprocess, "Popen", lambda args, **kwargs: calls.append(args) or "process"
    )

    assert receive.announce(8361, io.StringIO()) == "process"
    assert calls[0][:2] == ["/usr/bin/dns-sd", "-R"]
    assert calls[0][3:] == [receive.SERVICE_TYPE, "local", "8361"]


def test_code_has_six_digits() -> None:
    assert all(len(receive.new_code()) == 6 for _ in range(50))
