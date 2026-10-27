import base64
import hashlib
import http.client
import io
import json
import re
import threading
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from test_publier import FakeStorage
from visite360 import depot, publier, registre, reglages, serveur, stitch, traitement
from visite360.registre import Registre, SQLiteDatabase

PUBLIC = publier.Settings("SCWTEST", "secret", "visites-test")


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class Mailbox:
    """Faux service d'e-mail : garde les messages au lieu de les envoyer."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, text))

    def last_code(self, to: str) -> str:
        text = next(text for address, text in reversed(self.sent) if address == to)
        match = re.search(r"(\d{3}) (\d{3})", text)
        assert match
        return match.group(1) + match.group(2)


class Launcher:
    def __init__(self) -> None:
        self.wakes = 0
        self.fail = False

    def wake(self) -> None:
        self.wakes += 1
        if self.fail:
            raise traitement.LaunchError("injoignable")


@dataclass
class Env:
    app: serveur.App
    port: int
    mailbox: Mailbox
    launcher: Launcher
    public: FakeStorage
    clock: Clock
    context: traitement.Context
    out: io.StringIO
    stitched: list[str] = field(default_factory=list)

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = None,
        guard: bool = True,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> tuple[int, dict[str, Any], http.client.HTTPResponse]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        sent = {"Content-Length": str(len(data)), **(headers or {})}
        if token:
            sent["Authorization"] = f"Bearer {token}"
        if guard:
            sent[serveur.GUARD_HEADER] = "1"
        try:
            connection.request(method, path, body=data, headers=sent)
            response = connection.getresponse()
            content = response.read()
            try:
                parsed = json.loads(content or b"{}")
            except ValueError:
                parsed = {"_texte": content.decode("utf-8", "replace")}
            return response.status, parsed, response
        finally:
            connection.close()

    def login(self, email: str) -> str:
        self.app.registre.add_agent(email)
        status, _, _ = self.request("POST", "/api/connexion/code", {"email": email})
        assert status == 200
        code = self.mailbox.last_code(email)
        status, answer, _ = self.request("POST", "/api/connexion", {"email": email, "code": code})
        assert status == 200, answer
        self.clock.now += registre.CODE_INTERVAL
        return str(answer["jeton"])

    def upload(self, url: str, data: bytes, headers: dict[str, str]) -> int:
        parts = urllib.parse.urlsplit(url)
        path = parts.path + "?" + parts.query
        status, _, _ = self.request("PUT", path, raw=data, headers=headers, guard=False)
        return status


def tour_files(points: list[str], seed: int = 0) -> dict[str, bytes]:
    """Fichiers d'une visite comme les enverrait l'app (photos : octets quelconques)."""
    rng = np.random.default_rng(seed)
    files: dict[str, bytes] = {}
    for point in points:
        photos = []
        for number in (1, 2):
            name = f"IMG_{number:04d}.jpg"
            files[f"{point}/photos/{name}"] = rng.bytes(3000)
            photos.append({"fichier": name, "rotation": np.eye(3).tolist()})
        files[f"{point}/capture.json"] = json.dumps(
            {"format": 1, "cap_depart": 0, "photos": photos}
        ).encode()
    files["visite.json"] = json.dumps(
        {
            "version": 1,
            "nom": "Appartement",
            "depart": points[0],
            "points": [{"id": p, "nom": p.capitalize()} for p in points],
            "liens": [],
        }
    ).encode()
    return files


def manifest(name: str, files: dict[str, bytes]) -> dict[str, Any]:
    return {
        "format": 1,
        "visite": name,
        "fichiers": [
            {
                "chemin": path,
                "taille": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "md5": hashlib.md5(data).hexdigest(),
            }
            for path, data in files.items()
        ],
    }


def send(
    env: Env,
    token: str,
    name: str,
    files: dict[str, bytes],
    skip: set[str] = frozenset(),  # type: ignore[assignment]
) -> tuple[int, dict[str, Any], list[str]]:
    """Envoi complet comme le fait l'app. Renvoie la réponse finale et les fichiers demandés."""
    status, answer, _ = env.request("POST", "/api/envois", manifest(name, files), token)
    if status != 200:
        return status, answer, []
    asked = [entry["chemin"] for entry in answer["depots"]]
    for entry in answer["depots"]:
        if entry["chemin"] not in skip:
            data = files[entry["chemin"]]
            assert env.upload(entry["adresse"], data, entry["en_tetes"]) == 200
    status, answer, _ = env.request("POST", f"/api/envois/{answer['visite']}/fin", token=token)
    return status, answer, asked


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    clock = Clock()
    reg = Registre(SQLiteDatabase(tmp_path / "registre.sqlite"), clock)
    reg.create_schema()
    private = depot.FolderDepot(tmp_path / "depot", "", b"secret-local", clock)
    public = FakeStorage()
    mailbox, launcher, out = Mailbox(), Launcher(), io.StringIO()
    context = traitement.Context(reg, private, public, PUBLIC, out, tmp_path)
    app = serveur.App(reg, private, public, PUBLIC, mailbox, launcher, out, secure_cookie=False)
    server = serveur.make_server(app, "127.0.0.1", 0)
    port = server.server_address[1]
    private.base_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    instance = Env(app, port, mailbox, launcher, public, clock, context, out)

    # Assemblage simulé : un panorama de synthèse à la place du vrai calcul.
    def fake_stitch(folders: stitch.Folders, width: int, force: bool, out: Any) -> None:
        instance.stitched.append(folders.point.name)
        assert sorted(p.name for p in folders.photos.iterdir()) == ["IMG_0001.jpg", "IMG_0002.jpg"]
        cv2.imwrite(str(folders.panorama), make_panorama(512))
        folders.report.write_text("{}")
        out.write("Assemblage de 2 photos\n")
        return None

    monkeypatch.setattr(stitch, "stitch", fake_stitch)
    yield instance
    server.shutdown()
    server.server_close()


# --- Connexion ------------------------------------------------------------------------------------


def test_login_with_a_code_sent_by_email(env: Env) -> None:
    token = env.login("agent@exemple.fr")
    status, answer, _ = env.request("GET", "/api/moi", token=token)
    assert status == 200 and answer["email"] == "agent@exemple.fr"


def test_unknown_address_gets_the_same_answer_and_no_email(env: Env) -> None:
    env.app.registre.add_agent("connu@exemple.fr")
    _, known, _ = env.request("POST", "/api/connexion/code", {"email": "connu@exemple.fr"})
    _, unknown, _ = env.request("POST", "/api/connexion/code", {"email": "autre@exemple.fr"})
    assert known == unknown == {"message": serveur.NEUTRAL}
    assert [to for to, _ in env.mailbox.sent] == ["connu@exemple.fr"]


def test_wrong_code_is_refused(env: Env) -> None:
    env.app.registre.add_agent("a@exemple.fr")
    env.request("POST", "/api/connexion/code", {"email": "a@exemple.fr"})
    code = env.mailbox.last_code("a@exemple.fr")
    wrong = "000000" if code != "000000" else "111111"
    status, answer, _ = env.request(
        "POST", "/api/connexion", {"email": "a@exemple.fr", "code": wrong}
    )
    assert status == 403 and "Code faux" in answer["message"]


def test_not_connected_is_refused(env: Env) -> None:
    for method, path in (("GET", "/api/visites"), ("POST", "/api/envois")):
        status, answer, _ = env.request(method, path, {"format": 1})
        assert status == 401 and "Connexion nécessaire" in answer["message"]
    status, _, _ = env.request("GET", "/api/visites", token="faux-jeton")
    assert status == 401


def test_writes_need_the_guard_header(env: Env) -> None:
    token = env.login("a@exemple.fr")
    status, answer, _ = env.request("POST", "/api/deconnexion", token=token, guard=False)
    assert status == 403 and serveur.GUARD_HEADER in answer["message"]
    assert env.request("GET", "/api/moi", token=token)[0] == 200


def test_web_login_uses_a_private_cookie(env: Env) -> None:
    env.app.registre.add_agent("a@exemple.fr")
    env.request("POST", "/api/connexion/code", {"email": "a@exemple.fr"})
    code = env.mailbox.last_code("a@exemple.fr")
    _, _, response = env.request("POST", "/api/connexion", {"email": "a@exemple.fr", "code": code})
    cookie = response.getheader("Set-Cookie") or ""
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    value = cookie.split(";", 1)[0]
    status, answer, _ = env.request("GET", "/api/moi", headers={"Cookie": value}, guard=False)
    assert status == 200 and answer["email"] == "a@exemple.fr"
    env.request("POST", "/api/deconnexion", headers={"Cookie": value})
    assert env.request("GET", "/api/moi", headers={"Cookie": value}, guard=False)[0] == 401


def test_space_page_is_served_with_a_strict_policy(env: Env) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", env.port, timeout=10)
    connection.request("GET", "/")
    response = connection.getresponse()
    body = response.read().decode()
    connection.close()
    assert response.status == 200 and "Mes visites" in body
    assert "default-src 'self'" in (response.getheader("Content-Security-Policy") or "")
    assert response.getheader("X-Frame-Options") == "DENY"


# --- Envoi --------------------------------------------------------------------------------------


def test_a_tour_is_received_assembled_and_published(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon", "cuisine"])

    status, answer, asked = send(env, token, "appart", files)

    assert status == 200, answer
    assert sorted(asked) == sorted(files)
    assert answer["etat"] == "en_attente" and env.launcher.wakes == 1
    assert traitement.process_all(env.context) == 1
    assert sorted(env.stitched) == ["cuisine", "salon"]
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    (visit,) = listing["visites"]
    assert visit["etat"] == "prete" and visit["nom"] == "appart"
    identifier = visit["lien"].split("/")[-2]
    assert visit["lien"] == publier.link(PUBLIC, identifier)
    published = {key.split("/", 1)[1] for key in env.public.files if key.startswith(identifier)}
    assert {"index.html", "info.json", "p/0/panorama.jpg", "p/1/panorama.jpg"} <= published
    # Les photos d'origine ne sortent jamais du stockage privé.
    assert not any("photos" in key or "capture" in key for key in env.public.files)


def test_interrupted_upload_resumes_with_only_the_missing_files(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon"])
    skipped = {"salon/photos/IMG_0002.jpg"}

    status, answer, _ = send(env, token, "appart", files, skip=skipped)
    assert status == 409 and "Envoi incomplet" in answer["message"]
    assert env.launcher.wakes == 0

    status, answer, asked = send(env, token, "appart", files)
    assert status == 200, answer
    assert asked == sorted(skipped)


def test_damaged_file_is_refused_by_the_storage(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon"])
    _, answer, _ = env.request("POST", "/api/envois", manifest("appart", files), token)
    entry = answer["depots"][0]
    assert env.upload(entry["adresse"], b"abime", entry["en_tetes"]) == 403
    forged = entry["adresse"].replace("exp=", "exp=9")
    assert env.upload(forged, files[entry["chemin"]], entry["en_tetes"]) == 403


def test_expired_upload_address_is_refused(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon"])
    _, answer, _ = env.request("POST", "/api/envois", manifest("appart", files), token)
    entry = answer["depots"][0]
    env.clock.now += depot.UPLOAD_LIFETIME + 1
    assert env.upload(entry["adresse"], files[entry["chemin"]], entry["en_tetes"]) == 403


def test_bad_manifest_is_refused(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon"])
    bad = manifest("appart", files)
    bad["fichiers"][0]["chemin"] = "../../etc/passwd"
    status, answer, _ = env.request("POST", "/api/envois", bad, token)
    assert status == 400 and "refusé" in answer["message"]
    no_md5 = manifest("appart", files)
    del no_md5["fichiers"][0]["md5"]
    assert env.request("POST", "/api/envois", no_md5, token)[0] == 400


def test_invalid_visit_file_is_refused_at_the_end(env: Env) -> None:
    token = env.login("a@exemple.fr")
    files = tour_files(["salon"])
    files["visite.json"] = b'{"version": 1, "points": [}'
    status, answer, _ = send(env, token, "appart", files)
    assert status == 422 and "visite.json" in answer["message"]
    assert str(env.context.work_root) not in answer["message"]


def test_another_take_of_the_same_point_is_refused(env: Env) -> None:
    token = env.login("a@exemple.fr")
    assert send(env, token, "appart", tour_files(["salon"]))[0] == 200
    traitement.process_all(env.context)
    status, answer, _ = send(env, token, "appart", tour_files(["salon"], seed=1))
    assert status == 409 and "autre prise de vue" in answer["message"]


def test_adding_a_point_assembles_only_the_new_one(env: Env) -> None:
    token = env.login("a@exemple.fr")
    assert send(env, token, "appart", tour_files(["salon"]))[0] == 200
    traitement.process_all(env.context)
    env.stitched.clear()

    status, answer, asked = send(env, token, "appart", tour_files(["salon", "cuisine"]))
    assert status == 200, answer
    assert "salon/photos/IMG_0001.jpg" not in asked and "visite.json" in asked
    traitement.process_all(env.context)
    assert env.stitched == ["cuisine"]
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    assert listing["visites"][0]["lien"]  # même lien, mis à jour


def test_processing_again_redoes_nothing(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon", "cuisine"]))
    traitement.process_all(env.context)
    env.stitched.clear()
    puts_before = len(env.public.puts)
    visit = env.app.registre.visits(env.app.registre.agent_by_email("a@exemple.fr").id)[0]  # type: ignore[union-attr]

    env.app.registre.queue(visit.id)
    assert traitement.process_all(env.context) == 1
    assert env.stitched == []
    assert len(env.public.puts) == puts_before


def test_failed_assembly_is_reported_to_the_agent(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any) -> None:
        raise stitch.StitchError("Il faut au moins 2 photos lisibles pour assembler un panorama.")

    monkeypatch.setattr(stitch, "stitch", broken)
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    traitement.process_all(env.context)
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    (visit,) = listing["visites"]
    assert visit["etat"] == "echec" and "2 photos lisibles" in visit["message"]
    assert visit["lien"] is None


def test_launch_failure_keeps_the_visit_waiting(env: Env) -> None:
    env.launcher.fail = True
    token = env.login("a@exemple.fr")
    status, answer, _ = send(env, token, "appart", tour_files(["salon"]))
    assert status == 200 and answer["etat"] == "en_attente"
    assert "prochain passage" in answer["message"]
    assert traitement.process_all(env.context) == 1


# --- Visites d'un agent -------------------------------------------------------------------------


def test_an_agent_cannot_see_or_touch_another_agents_visit(env: Env) -> None:
    alice = env.login("alice@exemple.fr")
    bob = env.login("bob@exemple.fr")
    send(env, alice, "appart", tour_files(["salon"]))
    traitement.process_all(env.context)
    _, listing, _ = env.request("GET", "/api/visites", token=alice)
    visit_id = listing["visites"][0]["id"]

    assert env.request("GET", "/api/visites", token=bob)[1] == {"visites": []}
    for method, path in (
        ("GET", f"/api/visites/{visit_id}"),
        ("POST", f"/api/visites/{visit_id}/depublier"),
        ("POST", f"/api/visites/{visit_id}/publier"),
        ("DELETE", f"/api/visites/{visit_id}"),
        ("POST", f"/api/envois/{visit_id}/fin"),
    ):
        status, answer, _ = env.request(method, path, token=bob)
        assert status == 404 and answer["message"] == serveur.NOT_FOUND, (method, path)
    assert env.request("GET", f"/api/visites/{visit_id}", token=alice)[0] == 200


def test_same_visit_name_for_two_agents_are_two_visits(env: Env) -> None:
    alice = env.login("alice@exemple.fr")
    bob = env.login("bob@exemple.fr")
    assert send(env, alice, "appart", tour_files(["salon"]))[0] == 200
    status, _, asked = send(env, bob, "appart", tour_files(["salon"], seed=1))
    assert status == 200 and len(asked) == 4


def test_unpublish_then_publish_gives_a_new_link(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    traitement.process_all(env.context)
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    visit = listing["visites"][0]
    old = visit["lien"].split("/")[-2]

    status, answer, _ = env.request("POST", f"/api/visites/{visit['id']}/depublier", token=token)
    assert status == 200 and answer["lien"] is None
    assert not any(key.startswith(old) for key in env.public.files)

    env.request("POST", f"/api/visites/{visit['id']}/publier", token=token)
    traitement.process_all(env.context)
    _, answer, _ = env.request("GET", f"/api/visites/{visit['id']}", token=token)
    assert answer["lien"] and old not in answer["lien"]


def test_delete_removes_everything(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    traitement.process_all(env.context)
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    visit_id = listing["visites"][0]["id"]

    status, answer, _ = env.request("DELETE", f"/api/visites/{visit_id}", token=token)
    assert status == 200 and "supprimée" in answer["message"]
    assert env.public.files == {} or set(env.public.files) == {publier.ROBOTS_KEY}
    assert env.app.depot.list(f"{visit_id}/") == {}
    assert env.request("GET", "/api/visites", token=token)[1] == {"visites": []}


def test_busy_visit_cannot_be_changed(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    job = env.app.registre.claim()
    assert job is not None
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    visit_id = listing["visites"][0]["id"]
    assert listing["visites"][0]["etat"] == "en_cours"
    status, answer, _ = env.request("DELETE", f"/api/visites/{visit_id}", token=token)
    assert status == 409 and "en cours" in answer["message"]
    assert send(env, token, "appart", tour_files(["salon"]))[0] == 409


def test_old_photos_are_deleted_after_thirty_days(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    traitement.process_all(env.context)
    env.clock.now += registre.PHOTOS_KEPT + 1
    traitement.process_all(env.context)
    _, listing, _ = env.request("GET", "/api/visites", token=token)
    visit = listing["visites"][0]
    assert visit["photos_effacees"] and visit["lien"]
    kept = sorted(key.split("/", 1)[1] for key in env.app.depot.list(f"{visit['id']}/"))
    assert kept == ["salon/capture.json", "salon/panorama.jpg", "salon/rapport.json", "visite.json"]

    # Renvoyer la visite ne redemande pas les photos d'un point déjà assemblé.
    env.clock.now += registre.CODE_INTERVAL
    status, answer, asked = send(env, token, "appart", tour_files(["salon"]))
    assert status == 200 and asked == []


def test_retired_agent_is_disconnected_but_keeps_visits(env: Env) -> None:
    token = env.login("a@exemple.fr")
    send(env, token, "appart", tour_files(["salon"]))
    env.app.registre.retire_agent("a@exemple.fr")
    assert env.request("GET", "/api/visites", token=token)[0] == 401
    agent = env.app.registre.agent_by_email("a@exemple.fr")
    assert agent is not None and env.app.registre.visit_count(agent.id) == 1


# --- Stockage S3 et réglages -------------------------------------------------------------------


def test_presigned_url_matches_the_published_aws_example() -> None:
    # Exemple « GET Object » avec signature dans l'adresse, de la documentation d'Amazon.
    url = depot.presign(
        "GET",
        "https://examplebucket.s3.amazonaws.com/test.txt",
        {},
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "us-east-1",
        datetime(2013, 5, 24, tzinfo=UTC),
        86400,
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )
    assert "X-Amz-SignedHeaders=host" in url


def test_s3_upload_url_binds_the_md5() -> None:
    settings = publier.Settings("SCWTEST", "secret", "photos-test")
    when = datetime(2026, 10, 27, tzinfo=UTC)
    store = depot.S3Depot(settings, lambda: when)
    md5 = hashlib.md5(b"photo").hexdigest()
    url = store.upload_url("v/salon/photos/IMG_0001.jpg", md5)
    assert url.startswith("https://s3.fr-par.scw.cloud/photos-test/v/salon/photos/IMG_0001.jpg?")
    assert "X-Amz-SignedHeaders=content-md5%3Bhost" in url
    assert depot.md5_base64(md5) == base64.b64encode(hashlib.md5(b"photo").digest()).decode()
    assert url != store.upload_url("v/salon/photos/IMG_0001.jpg", hashlib.md5(b"x").hexdigest())


def test_missing_setting_is_named() -> None:
    with pytest.raises(reglages.SettingsError, match="VISITE360_BASE"):
        reglages.from_env({})
    environ = {
        "VISITE360_BASE": "sqlite://:memory:",
        "SCW_ACCESS_KEY": "a",
        "SCW_SECRET_KEY": "b",
        "VISITE360_DEPOT": "photos",
        "VISITE360_BUCKET": "visites",
        "VISITE360_ADRESSE_API": "https://api.exemple.test/",
    }
    with pytest.raises(reglages.SettingsError, match="VISITE360_JOB"):
        reglages.from_env(environ)
    settings = reglages.from_env(environ, need_job=False)
    assert settings.address == "https://api.exemple.test" and settings.port == 8080


def test_server_without_settings_gives_a_clear_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert serveur.run(environ={}) == 1
    assert "VISITE360_BASE" in capsys.readouterr().err


def test_no_address_bucket_or_key_is_written_in_the_code() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = [
        re.compile(r"hesti-scan", re.IGNORECASE),
        re.compile(r"SCW[A-Z0-9]{17}"),  # clé d'accès Scaleway
        re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),  # clé, tâche
        re.compile(r"rg\.fr-par\.scw\.cloud/\w"),  # espace d'images nommé
        re.compile(r"\.pg\.sdb\.fr-par\.scw\.cloud"),  # base nommée
    ]
    folders = ["src", "espace", "visionneuse", "app/Visite360Capture", "app/Config", "deploiement"]
    checked = 0
    for folder in folders:
        for path in (root / folder).rglob("*"):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".js",
                ".html",
                ".css",
                ".swift",
                ".xcconfig",
                ".sh",
                ".toml",
                "",
            }:
                continue
            if "pannellum" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            checked += 1
            for pattern in forbidden:
                assert not pattern.search(text), f"{path.relative_to(root)} : {pattern.pattern}"
    assert checked > 20


def test_local_launcher_runs_again_when_woken_during_a_run() -> None:
    started, release, runs = threading.Event(), threading.Event(), []

    def process() -> None:
        runs.append(1)
        started.set()
        release.wait(5)

    launcher = traitement.ThreadLauncher(process)
    launcher.wake()
    assert started.wait(5)
    launcher.wake()  # pendant le premier passage : un second suivra
    release.set()
    launcher.join(5)
    deadline = 50
    while launcher.thread is not None and deadline:
        launcher.join(0.1)
        deadline -= 1
    assert len(runs) == 2
