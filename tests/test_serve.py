import io
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from visite360 import serve, stitch
from visite360.cli import main


def write_point(root: Path, width: int) -> Path:
    point = root / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(width))
    return point


def fetch(server: ThreadingHTTPServer, path: str) -> tuple[int, bytes, str]:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read(), response.headers["Content-Type"]
    except urllib.error.HTTPError as error:
        return error.code, b"", ""


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[ThreadingHTTPServer, Path]]:
    point = write_point(tmp_path, 8192)
    server = serve.make_server(stitch.resolve_folders(point), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, point
    server.shutdown()
    server.server_close()


def test_serves_page_viewer_and_panorama(running: tuple[ThreadingHTTPServer, Path]) -> None:
    server, point = running

    status, body, kind = fetch(server, "/")
    assert status == 200 and b"pannellum" in body and kind.startswith("text/html")
    assert fetch(server, "/pannellum/pannellum.js")[0] == 200
    assert fetch(server, "/pannellum/pannellum.css")[0] == 200
    status, body, kind = fetch(server, "/panorama.jpg")
    assert status == 200 and kind == "image/jpeg"
    assert body == (point / "panorama.jpg").read_bytes()


def test_info_announces_full_and_mobile_widths(running: tuple[ThreadingHTTPServer, Path]) -> None:
    server, _ = running
    info = json.loads(fetch(server, "/info.json")[1])

    assert info["name"] == "salon"
    assert info["full"]["width"] == 8192
    assert info["mobile"]["width"] == serve.MOBILE_WIDTH
    status, body, _ = fetch(server, info["mobile"]["url"])
    decoded = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    assert status == 200 and decoded.shape[:2] == (2048, 4096)


def test_other_paths_are_not_served(running: tuple[ThreadingHTTPServer, Path]) -> None:
    server, _ = running

    for path in ("/rapport.json", "/photos/", "/../../etc/passwd", "/cache/panorama-mobile.jpg"):
        assert fetch(server, path)[0] == 404


def test_original_panorama_is_never_rewritten(tmp_path: Path) -> None:
    point = write_point(tmp_path, 8192)
    before = (point / "panorama.jpg").read_bytes()

    serve.make_server(stitch.resolve_folders(point), "127.0.0.1", 0).server_close()

    assert (point / "panorama.jpg").read_bytes() == before


def test_mobile_copy_is_not_rebuilt_when_up_to_date(tmp_path: Path) -> None:
    point = write_point(tmp_path, 8192)
    folders = stitch.resolve_folders(point)
    serve.make_server(folders, "127.0.0.1", 0).server_close()
    copy = point / "cache" / serve.MOBILE_NAME
    first = copy.stat().st_mtime_ns

    serve.make_server(folders, "127.0.0.1", 0).server_close()

    assert copy.stat().st_mtime_ns == first


def test_small_panorama_needs_no_copy(tmp_path: Path) -> None:
    point = write_point(tmp_path, 2048)

    serve.make_server(stitch.resolve_folders(point), "127.0.0.1", 0).server_close()

    assert not (point / "cache" / serve.MOBILE_NAME).exists()


def test_no_panorama_and_no_photo_gives_clear_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)

    assert main(["serve", str(point)]) == 1
    assert "Aucune photo" in capsys.readouterr().err


def write_photos_only(root: Path) -> stitch.Folders:
    point = root / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "photos" / "a.jpg"), make_panorama(256))
    return stitch.resolve_folders(point)


def fake_stitch(folders: stitch.Folders, width: int, force: bool, out: TextIO) -> dict[str, Any]:
    print("Assemblage de 2 photos", file=out, flush=True)
    print("  Alignement des photos", file=out, flush=True)
    print("  Rendu de la photo 1 sur 2", file=out, flush=True)
    cv2.imwrite(str(folders.panorama), make_panorama(8192))
    return {}


def test_missing_panorama_is_generated_with_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = write_photos_only(tmp_path)
    release = threading.Event()
    seen: list[dict[str, Any]] = []

    def slow_stitch(
        folders: stitch.Folders, width: int, force: bool, out: TextIO
    ) -> dict[str, Any]:
        print("  Alignement des photos", file=out, flush=True)
        release.wait(10)
        return fake_stitch(folders, width, force, out)

    monkeypatch.setattr(stitch, "stitch", slow_stitch)
    monkeypatch.setattr(stitch, "print_report", lambda *args: None)
    server = serve.make_server(folders, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        visit: serve.Visit = server.visit  # type: ignore[attr-defined]
        generation = threading.Thread(target=visit.generate, args=(False, io.StringIO()))
        generation.start()

        deadline = time.time() + 5
        while time.time() < deadline and not seen:
            state = json.loads(fetch(server, "/status.json")[1])
            if state["message"] == "Alignement des photos":
                seen.append(state)
        assert seen and seen[0]["status"] == "generating" and 0 < seen[0]["progress"] < 1
        # Pendant la génération, la page est servie mais ni la fiche ni le panorama.
        assert fetch(server, "/")[0] == 200
        assert fetch(server, "/info.json")[0] == 404
        assert fetch(server, "/panorama.jpg")[0] == 404

        release.set()
        generation.join(15)
        state = json.loads(fetch(server, "/status.json")[1])
        assert state["status"] == "ready" and state["progress"] == 1.0
        assert fetch(server, "/panorama.jpg")[0] == 200
        assert json.loads(fetch(server, "/info.json")[1])["full"]["width"] == 8192
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def test_generation_error_is_reported_to_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = write_photos_only(tmp_path)

    def failing(folders: stitch.Folders, width: int, force: bool, out: TextIO) -> None:
        raise stitch.StitchError("Il faut au moins 2 photos lisibles pour assembler un panorama.")

    monkeypatch.setattr(stitch, "stitch", failing)
    server = serve.make_server(folders, "127.0.0.1", 0)
    try:
        server.visit.generate(False, io.StringIO())  # type: ignore[attr-defined]
        state = server.visit.status()  # type: ignore[attr-defined]
        assert state["status"] == "error" and "2 photos" in state["error"]
    finally:
        server.server_close()


def test_force_regenerates_an_existing_panorama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    point = write_point(tmp_path, 2048)
    (point / "photos" / "a.jpg").write_bytes(b"x")
    folders = stitch.resolve_folders(point)
    calls: list[bool] = []

    def recording(folders: stitch.Folders, width: int, force: bool, out: TextIO) -> dict[str, Any]:
        calls.append(force)
        return fake_stitch(folders, width, force, out)

    monkeypatch.setattr(stitch, "stitch", recording)
    monkeypatch.setattr(stitch, "print_report", lambda *args: None)

    ready = serve.make_server(folders, "127.0.0.1", 0)
    forced = serve.make_server(folders, "127.0.0.1", 0, force=True)
    try:
        assert ready.visit.status()["status"] == "ready"  # type: ignore[attr-defined]
        assert forced.visit.status()["status"] == "generating"  # type: ignore[attr-defined]
        forced.visit.generate(True, io.StringIO())  # type: ignore[attr-defined]
        assert calls == [True]
        assert forced.visit.status()["status"] == "ready"  # type: ignore[attr-defined]
    finally:
        ready.server_close()
        forced.server_close()


def test_busy_port_gives_clear_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    point = write_point(tmp_path, 2048)
    folders = stitch.resolve_folders(point)
    first = serve.make_server(folders, "127.0.0.1", 0)
    try:
        port = first.server_address[1]
        assert main(["serve", str(point), "--port", str(port), "--local"]) == 1
        assert "port" in capsys.readouterr().err
    finally:
        first.server_close()


def test_unknown_folder_gives_clear_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", str(tmp_path / "absent")]) == 1
    assert "introuvable" in capsys.readouterr().err
