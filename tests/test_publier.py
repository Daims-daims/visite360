import hashlib
import io
import json
import socket
import threading
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import cv2
import pytest

from synthetic import make_panorama
from visite360 import publier, visite
from visite360.cli import main

SETTINGS = publier.Settings("SCWTESTACCESS", "secret-de-test", "visites-test")


class FakeStorage:
    """Stockage en mémoire : garde le contenu et le type de chaque fichier, compte les appels."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []

    def list(self, prefix: str) -> dict[str, str]:
        return {
            key: hashlib.md5(data).hexdigest()
            for key, (data, _) in self.files.items()
            if key.startswith(prefix)
        }

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = (data, content_type)
        self.puts.append(key)

    def delete(self, key: str) -> None:
        del self.files[key]
        self.deletes.append(key)


def make_tour(root: Path, names: tuple[str, ...] = ("salon", "cuisine")) -> Path:
    """Visite de synthèse, avec autour des panoramas les fichiers qui ne doivent pas partir."""
    folder = root / "appartement"
    for name in names:
        point = folder / name
        (point / "photos").mkdir(parents=True)
        cv2.imwrite(str(point / "panorama.jpg"), make_panorama(1024))
        (point / "photos" / "IMG_0001.jpg").write_bytes(b"photo d'origine")
        (point / "capture.json").write_text("{}")
        (point / "rapport.json").write_text("{}")
        (point / "piece.json").write_text("{}")
        (point / "modifications").mkdir()
        (point / "modifications" / "selection-1.json").write_text("{}")
    content = {
        "version": 1,
        "nom": "Appartement",
        "points": [{"id": name} for name in names],
        "liens": [{"de": names[0], "vers": names[-1], "angle": 30}] if len(names) > 1 else [],
    }
    (folder / visite.FILE_NAME).write_text(json.dumps(content), encoding="utf-8")
    return folder


def published(folder: Path, storage: FakeStorage) -> publier.Report:
    tour, _ = visite.open_tour(folder)
    return publier.publish(tour, folder, storage, SETTINGS, io.StringIO())


def identifier(folder: Path) -> str:
    state = publier.read_state(folder)
    assert state is not None
    return state["identifiant"]


def test_published_files_are_a_closed_list(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    tour, _ = visite.open_tour(folder)

    names = [file.name for file in publier.published_files(tour)]

    assert sorted(names) == sorted(
        [
            "index.html",
            "info.json",
            "status.json",
            "pannellum/pannellum.js",
            "pannellum/pannellum.css",
            "p/0/panorama.jpg",
            "p/0/panorama-mobile.jpg",
            "p/1/panorama.jpg",
            "p/1/panorama-mobile.jpg",
        ]
    )
    assert names[-1] == "index.html"  # la page part en dernier, après ses panoramas
    assert not any(
        word in name for name in names for word in ("photos", "modifications", "capture", "piece")
    )


def test_published_info_is_relative_and_read_only(tmp_path: Path) -> None:
    tour, _ = visite.open_tour(make_tour(tmp_path))
    files = {file.name: file for file in publier.published_files(tour)}

    info = json.loads(files["info.json"].data)

    assert info["publiee"] is True
    assert info["points"][0]["full"]["url"] == "p/0/panorama.jpg"
    assert info["points"][1]["mobile"]["url"] == "p/1/panorama-mobile.jpg"
    assert info["points"][0]["links"][0]["to"] == "cuisine"
    assert json.loads(files["status.json"].data)["status"] == "ready"
    page = files["index.html"].data.decode("utf-8")
    assert '<meta name="robots" content="noindex, nofollow">' in page
    assert 'src="pannellum/pannellum.js"' in page and 'fetch("info.json")' in page
    # Toute la barre d'outils disparaît en ligne, y compris les boutons ajoutés plus tard.
    assert 'for (const id of ["cap", "outils"])' in page


def test_publish_sends_everything_under_a_random_identifier(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    storage = FakeStorage()

    report = published(folder, storage)

    ident = identifier(folder)
    assert len(ident) >= 22  # 16 octets tirés au hasard, soit 128 bits
    assert report.link == f"https://visites-test.s3.fr-par.scw.cloud/{ident}/index.html"
    assert set(storage.files) == {publier.ROBOTS_KEY} | {f"{ident}/{n}" for n in report.sent}
    assert storage.files[f"{ident}/index.html"][1].startswith("text/html")
    assert storage.files[f"{ident}/p/0/panorama.jpg"][1] == "image/jpeg"
    assert storage.files[publier.ROBOTS_KEY][0] == b"User-agent: *\nDisallow: /\n"
    assert not any(data == b"photo d'origine" for data, _ in storage.files.values())


def test_identifier_is_stable_and_differs_between_visits(tmp_path: Path) -> None:
    first = make_tour(tmp_path / "a")
    second = make_tour(tmp_path / "b")
    storage = FakeStorage()

    published(first, storage)
    ident = identifier(first)
    published(first, storage)
    published(second, storage)

    assert identifier(first) == ident
    assert identifier(second) != ident
    assert len({publier.new_identifier() for _ in range(1000)}) == 1000


def test_republish_sends_only_what_changed(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    storage = FakeStorage()
    published(folder, storage)
    storage.puts.clear()

    again = published(folder, storage)
    assert again.sent == () and again.deleted == () and storage.puts == []

    cv2.imwrite(str(folder / "cuisine" / "panorama.jpg"), make_panorama(1024, seed=7))
    changed = published(folder, storage)
    assert set(changed.sent) == {"p/1/panorama.jpg", "p/1/panorama-mobile.jpg"}


def test_republish_removes_files_of_a_removed_point(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    storage = FakeStorage()
    published(folder, storage)
    content = json.loads((folder / visite.FILE_NAME).read_text())
    content["points"], content["liens"] = [{"id": "salon"}], []
    (folder / visite.FILE_NAME).write_text(json.dumps(content))

    report = published(folder, storage)

    assert set(report.deleted) == {"p/1/panorama.jpg", "p/1/panorama-mobile.jpg"}
    assert not any(key.endswith("p/1/panorama.jpg") for key in storage.files)


def test_unpublish_removes_everything_and_forgets_the_link(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    other = make_tour(tmp_path / "autre")
    storage = FakeStorage()
    published(folder, storage)
    published(other, storage)
    ident = identifier(folder)

    count = publier.unpublish(folder, storage, SETTINGS)

    assert count == 9
    assert not any(key.startswith(ident) for key in storage.files)
    assert any(key.startswith(identifier(other)) for key in storage.files)
    assert publier.ROBOTS_KEY in storage.files
    assert not (folder / publier.STATE_NAME).exists()
    assert publier.unpublish(folder, storage, SETTINGS) is None


def test_missing_panorama_is_a_clear_error(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    (folder / "cuisine" / "panorama.jpg").unlink()
    tour, _ = visite.open_tour(folder)

    with pytest.raises(publier.PublishError, match="visite360 serve"):
        publier.publish(tour, folder, FakeStorage(), SETTINGS, io.StringIO())
    assert not (folder / publier.STATE_NAME).exists()


def test_other_bucket_is_refused(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    published(folder, FakeStorage())
    tour, _ = visite.open_tour(folder)
    other = publier.Settings("A", "B", "autre-bucket")

    with pytest.raises(publier.PublishError, match="visites-test"):
        publier.publish(tour, folder, FakeStorage(), other, io.StringIO())


# --- Réglages et clés ---------------------------------------------------------------------------


def test_missing_keys_give_a_french_message_and_exit_code(tmp_path: Path) -> None:
    folder = make_tour(tmp_path)
    err = io.StringIO()

    code = publier.run_publish(
        folder, tmp_path / "absent.json", {}, lambda s: FakeStorage(), io.StringIO(), err
    )

    assert code == 1
    assert "clé d'accès, clé secrète, nom du stockage (bucket)" in err.getvalue()
    assert "visite360 publier --configurer" in err.getvalue()
    assert "Traceback" not in err.getvalue()
    assert not (folder / publier.STATE_NAME).exists()


def test_environment_overrides_the_file(tmp_path: Path) -> None:
    config = tmp_path / "scaleway.json"
    publier.save_settings(config, "SCWFICHIER", "secret", "bucket-fichier")
    environ = {"SCW_ACCESS_KEY": "SCWENV", "SCW_SECRET_KEY": "secret-env"}

    settings = publier.load_settings(config, environ)

    assert (settings.access_key, settings.secret_key, settings.bucket) == (
        "SCWENV",
        "secret-env",
        "bucket-fichier",
    )


def test_configure_writes_a_private_file(tmp_path: Path) -> None:
    config = tmp_path / "config" / "scaleway.json"
    answers = iter(["SCWABC", "mon-bucket"])

    code = publier.run_configure(
        config, lambda _: next(answers), lambda _: "tres-secret", io.StringIO()
    )

    assert code == 0
    assert config.stat().st_mode & 0o777 == 0o600
    assert not publier.readable_by_others(config)
    settings = publier.load_settings(config, {})
    assert (settings.access_key, settings.secret_key, settings.bucket) == (
        "SCWABC",
        "tres-secret",
        "mon-bucket",
    )


def test_custom_address_changes_the_link(tmp_path: Path) -> None:
    config = tmp_path / "scaleway.json"
    config.write_text(
        json.dumps(
            {
                "cle_acces": "A",
                "cle_secrete": "B",
                "bucket": "c",
                "adresse": "https://v.exemple.fr/",
            }
        )
    )

    settings = publier.load_settings(config, {})

    assert publier.link(settings, "abc") == "https://v.exemple.fr/abc/index.html"


def test_cli_publish_then_unpublish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_tour(tmp_path)
    storage = FakeStorage()
    monkeypatch.setenv("SCW_ACCESS_KEY", "SCWTEST")
    monkeypatch.setenv("SCW_SECRET_KEY", "secret")
    monkeypatch.setenv("VISITE360_BUCKET", "visites-test")
    monkeypatch.setattr(publier, "S3Storage", lambda settings: storage)

    assert main(["publier", str(folder)]) == 0
    assert "Visite en ligne : https://visites-test.s3.fr-par.scw.cloud/" in capsys.readouterr().out
    assert main(["publier", str(folder)]) == 0
    assert "Rien n'a changé" in capsys.readouterr().out
    assert main(["depublier", str(folder)]) == 0
    assert "Visite retirée : 9 fichier(s)" in capsys.readouterr().out
    assert main(["depublier", str(folder)]) == 0
    assert "pas publiée" in capsys.readouterr().out
    assert list(storage.files) == [publier.ROBOTS_KEY]


# --- Signature et protocole S3 ------------------------------------------------------------------


def test_signature_matches_the_published_aws_example() -> None:
    # Exemple « GET Object » de la documentation d'Amazon (Signature Version 4, en-tête
    # Authorization), avec ses clés d'exemple publiques.
    headers = publier.sign(
        "GET",
        "https://examplebucket.s3.amazonaws.com/test.txt",
        {"Range": "bytes=0-9"},
        publier.EMPTY_SHA256,
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "us-east-1",
        datetime(2013, 5, 24, tzinfo=UTC),
    )

    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


class FakeS3:
    """Faux service S3 local : vérifie chaque signature, range les fichiers en mémoire."""

    PAGE = 3

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.objects: dict[str, dict[str, Any]] = {}

    def handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _check(self, payload: bytes) -> str | None:
                authorization = self.headers.get("Authorization", "")
                fields = dict(part.strip().split("=", 1) for part in authorization[17:].split(","))
                names = fields["SignedHeaders"].split(";")
                given = {name: self.headers[name] for name in names if name != "host"}
                url = f"http://{self.headers['Host']}{self.path}"
                stamp = datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ")
                expected = publier.sign(
                    self.command,
                    url,
                    given,
                    hashlib.sha256(payload).hexdigest(),
                    fields["Credential"].split("/")[0],
                    fake.secret,
                    "fr-par",
                    stamp.replace(tzinfo=UTC),
                )
                if expected["authorization"] != authorization:
                    return "SignatureDoesNotMatch"
                return None

            def _reply(self, status: int, body: bytes = b"") -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, code: str) -> None:
                self._reply(status, f"<Error><Code>{code}</Code></Error>".encode())

            def _key(self) -> tuple[str, str]:
                parts = urllib.parse.urlsplit(self.path)
                bucket, _, key = parts.path.lstrip("/").partition("/")
                return bucket, urllib.parse.unquote(key)

            def do_PUT(self) -> None:
                data = self.rfile.read(int(self.headers["Content-Length"]))
                problem = self._check(data)
                if problem:
                    self._error(403, problem)
                    return
                bucket, key = self._key()
                if bucket != "visites-test":
                    self._error(404, "NoSuchBucket")
                    return
                fake.objects[key] = {
                    "data": data,
                    "type": self.headers["Content-Type"],
                    "acl": self.headers["x-amz-acl"],
                    "md5": self.headers["Content-MD5"],
                }
                self._reply(200)

            def do_DELETE(self) -> None:
                problem = self._check(b"")
                if problem:
                    self._error(403, problem)
                    return
                fake.objects.pop(self._key()[1], None)
                self._reply(204)

            def do_GET(self) -> None:
                problem = self._check(b"")
                if problem:
                    self._error(403, problem)
                    return
                query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                keys = sorted(k for k in fake.objects if k.startswith(query.get("prefix", "")))
                start = int(query.get("continuation-token", "0"))
                page = keys[start : start + fake.PAGE]
                more = start + fake.PAGE < len(keys)
                items = "".join(
                    f"<Contents><Key>{k}</Key><ETag>&quot;"
                    f"{hashlib.md5(fake.objects[k]['data']).hexdigest()}&quot;</ETag></Contents>"
                    for k in page
                )
                token = f"<NextContinuationToken>{start + fake.PAGE}</NextContinuationToken>"
                body = (
                    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{items}"
                    f"{token if more else ''}</ListBucketResult>"
                )
                self._reply(200, body.encode())

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler


@pytest.fixture
def fake_s3() -> Iterator[tuple[FakeS3, str]]:
    fake = FakeS3("secret-de-test")
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def s3(endpoint: str, secret: str = "secret-de-test", bucket: str = "visites-test") -> Any:
    settings = publier.Settings("SCWTEST", secret, bucket, endpoint=endpoint)
    return publier.S3Storage(settings)


def test_s3_storage_round_trip(fake_s3: tuple[FakeS3, str], tmp_path: Path) -> None:
    fake, endpoint = fake_s3
    storage = s3(endpoint)
    folder = make_tour(tmp_path)
    tour, _ = visite.open_tour(folder)

    publier.publish(tour, folder, storage, storage.settings, io.StringIO())
    ident = identifier(folder)

    page = fake.objects[f"{ident}/index.html"]
    assert page["acl"] == "public-read" and page["type"].startswith("text/html")
    # Plus de fichiers qu'une page de la liste : la suite est demandée avec le jeton.
    listed = storage.list(ident + "/")
    assert len(listed) == 9 > FakeS3.PAGE
    assert (
        listed[f"{ident}/info.json"]
        == hashlib.md5(fake.objects[f"{ident}/info.json"]["data"]).hexdigest()
    )
    report = publier.publish(tour, folder, storage, storage.settings, io.StringIO())
    assert report.sent == ()

    assert publier.unpublish(folder, storage, storage.settings) == 9
    assert list(fake.objects) == [publier.ROBOTS_KEY]


def test_names_with_spaces_and_accents_are_signed(fake_s3: tuple[FakeS3, str]) -> None:
    fake, endpoint = fake_s3
    storage = s3(endpoint)

    storage.put("id/p/0/chambre d'été.jpg", b"x", "image/jpeg")

    assert "id/p/0/chambre d'été.jpg" in storage.list("id/")


def test_refused_keys_give_a_clear_message(fake_s3: tuple[FakeS3, str]) -> None:
    _, endpoint = fake_s3

    with pytest.raises(publier.PublishError, match="refuse les clés"):
        s3(endpoint, secret="mauvais-secret").list("x/")


def test_missing_bucket_gives_a_clear_message(fake_s3: tuple[FakeS3, str]) -> None:
    _, endpoint = fake_s3

    with pytest.raises(publier.PublishError, match="n'existe pas"):
        s3(endpoint, bucket="inconnu").put("a.txt", b"x", "text/plain")


def test_no_network_gives_a_clear_message_and_exit_code(tmp_path: Path) -> None:
    with socket.socket() as probe:  # port libre, sur lequel personne n'écoute
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    folder = make_tour(tmp_path)
    environ = {
        "SCW_ACCESS_KEY": "SCWTEST",
        "SCW_SECRET_KEY": "secret",
        "VISITE360_BUCKET": "visites-test",
        "VISITE360_S3_ENDPOINT": f"http://127.0.0.1:{port}",
    }
    err = io.StringIO()

    code = publier.run_publish(folder, tmp_path / "absent.json", environ, None, io.StringIO(), err)

    assert code == 1
    assert "Scaleway est injoignable" in err.getvalue()
    assert "Traceback" not in err.getvalue()
