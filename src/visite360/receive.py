"""Étape 6 : reçoit sur le Mac une visite envoyée par l'app de l'iPhone, par le Wi-Fi local.

`visite360 receive` ouvre un petit serveur HTTP (bibliothèque standard, D23), l'annonce sur le
Wi-Fi par Bonjour avec `dns-sd`, programme fourni avec macOS, et affiche un code à 6 chiffres
à saisir dans l'app. Sans ce code, le serveur refuse tout.

Un envoi se fait en trois temps (format dans `docs/transfert.md`) :

1. l'app annonce la liste complète des fichiers de la visite, avec leur taille et leur
   empreinte SHA-256. Le Mac répond par ceux qu'il n'a pas déjà, à l'identique ;
2. l'app envoie ces fichiers un par un. Chacun est écrit dans un dossier provisoire caché
   (`visites/.reception-<envoi>/`) et refusé si son empreinte ne correspond pas ;
3. l'app demande la fin de l'envoi. Le Mac vérifie qu'il ne manque rien et que `visite.json`
   et les `capture.json` sont valides, puis range les fichiers dans `visites/<visite>/`.

Les photos et `capture.json` déjà présents sur le Mac ne sont jamais réécrits (D9) : un point
qui existe avec d'autres photos est refusé. `visite.json` est remplacé, l'ancien est gardé à
côté sous un autre nom.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, TextIO
from urllib.parse import unquote

from visite360 import __version__, capture, visite
from visite360.serve import lan_address

DEFAULT_PORT = 8361
DEFAULT_FOLDER = Path("visites")
SERVICE_TYPE = "_visite360._tcp"
CODE_HEADER = "X-Visite360-Code"
FORMAT_VERSION = 1
STAGING_PREFIX = ".reception-"
MAX_FILES = 5000
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
# Au-delà, le serveur refuse tout jusqu'à son redémarrage : un code à 6 chiffres ne se devine
# pas en 10 essais.
MAX_WRONG_CODES = 10
CHUNK = 1024 * 1024
JSON = "application/json; charset=utf-8"

NAME = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
VISIT_NAME = re.compile(NAME)
# Seuls fichiers acceptés : visite.json, et pour chaque point capture.json et ses photos.
FILE_PATH = re.compile(
    rf"{visite.FILE_NAME}|(?P<point>{NAME})/"
    rf"(?:{capture.FILE_NAME}|photos/[A-Za-z0-9][A-Za-z0-9_.-]{{0,99}}\.(?i:jpe?g|heic|png))"
)
SHA256 = re.compile(r"[0-9a-f]{64}")


class ReceiveError(Exception):
    """Envoi refusé, avec un message en français pour l'app et le code HTTP à renvoyer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: str


@dataclass
class Upload:
    id: str
    visit: str
    destination: Path
    staging: Path
    files: dict[str, ManifestFile]
    missing: set[str]
    received: set[str] = field(default_factory=set)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def same_file(path: Path, expected: ManifestFile) -> bool:
    """Vrai si le fichier existe avec la même taille et la même empreinte."""
    return (
        path.is_file()
        and path.stat().st_size == expected.size
        and file_digest(path) == expected.sha256
    )


def parse_manifest(raw: Any) -> tuple[str, dict[str, ManifestFile]]:
    """Valide la liste des fichiers annoncée par l'app. Renvoie le nom de la visite et les
    fichiers par chemin."""
    if not isinstance(raw, dict):
        raise ReceiveError("Liste des fichiers mal formée : un objet JSON est attendu.")
    if raw.get("format") != FORMAT_VERSION:
        raise ReceiveError(
            f"Format d'envoi {raw.get('format')!r} inconnu, ce Mac lit le format "
            f"{FORMAT_VERSION}. Mettre à jour l'app et visite360 à la même version."
        )
    name = raw.get("visite")
    if not isinstance(name, str) or not VISIT_NAME.fullmatch(name):
        raise ReceiveError(f"Nom de visite invalide : {name!r}.")
    entries = raw.get("fichiers")
    if not isinstance(entries, list) or not entries:
        raise ReceiveError("La liste des fichiers est vide.")
    if len(entries) > MAX_FILES:
        raise ReceiveError(f"Trop de fichiers dans un seul envoi (plus de {MAX_FILES}).")
    files: dict[str, ManifestFile] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReceiveError("Liste des fichiers mal formée.")
        path, size, digest = entry.get("chemin"), entry.get("taille"), entry.get("sha256")
        if not isinstance(path, str) or not FILE_PATH.fullmatch(path):
            raise ReceiveError(f"Fichier refusé : {path!r} n'est pas un fichier de visite.")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
            raise ReceiveError(f"{path} : taille invalide ({size!r}).")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ReceiveError(f"{path} : empreinte SHA-256 invalide.")
        if path in files:
            raise ReceiveError(f"{path} est annoncé deux fois.")
        files[path] = ManifestFile(path, size, digest)
    if visite.FILE_NAME not in files:
        raise ReceiveError(f"L'envoi ne contient pas {visite.FILE_NAME}.")
    return name, files


def point_of(path: str) -> str | None:
    match = FILE_PATH.fullmatch(path)
    return match.group("point") if match else None


def check_conflicts(destination: Path, files: dict[str, ManifestFile]) -> None:
    """Refuse un point déjà présent sur le Mac avec d'autres photos : ce serait une autre prise
    de vue, qu'on ne mélange pas et qu'on n'écrase pas (D9)."""
    points = sorted({p for p in map(point_of, files) if p})
    for point in points:
        folder = destination / point
        conflict = None
        photos = folder / "photos"
        if photos.is_dir():
            announced = {
                path.rsplit("/", 1)[1] for path in files if path.startswith(f"{point}/photos/")
            }
            extra = sorted(
                child.name
                for child in photos.iterdir()
                if child.is_file()
                and not child.name.startswith(".")
                and child.name not in announced
            )
            if extra:
                conflict = f"la photo {extra[0]} n'est pas dans l'envoi"
        for path, expected in files.items():
            if conflict or not path.startswith(f"{point}/"):
                continue
            target = destination / path
            if target.exists() and not same_file(target, expected):
                conflict = f"{path} est différent"
        if conflict:
            raise ReceiveError(
                f"Le point « {point} » existe déjà sur le Mac dans {destination} avec une autre "
                f"prise de vue ({conflict}). Les photos d'origine ne sont jamais écrasées : "
                "renommer le point dans l'app, ou déplacer ce dossier sur le Mac, puis renvoyer.",
                409,
            )


class Receiver:
    """État du serveur de réception : envois en cours et codes faux."""

    def __init__(self, root: Path, code: str, out: TextIO) -> None:
        self.root = root
        self.code = code
        self.out = out
        self.uploads: dict[str, Upload] = {}
        self.wrong_codes = 0
        self.lock = threading.Lock()

    def check_code(self, given: str | None) -> None:
        with self.lock:
            if self.wrong_codes >= MAX_WRONG_CODES:
                raise ReceiveError(
                    "Trop de codes faux : la réception est bloquée. Relancer "
                    "visite360 receive sur le Mac pour obtenir un nouveau code.",
                    403,
                )
            given = re.sub(r"\s", "", given or "")
            if hmac.compare_digest(given.encode(), self.code.encode()):
                return
            self.wrong_codes += 1
            if self.wrong_codes >= MAX_WRONG_CODES:
                print("Trop de codes faux : réception bloquée jusqu'au redémarrage.", file=self.out)
        raise ReceiveError("Code faux. Recopier le code affiché sur le Mac.", 403)

    def start(self, raw: Any) -> dict[str, Any]:
        name, files = parse_manifest(raw)
        destination = self.root / name
        check_conflicts(destination, files)
        missing = {
            path
            for path, expected in files.items()
            if path == visite.FILE_NAME or not same_file(destination / path, expected)
        }
        if (destination / visite.FILE_NAME).is_file() and same_file(
            destination / visite.FILE_NAME, files[visite.FILE_NAME]
        ):
            missing.discard(visite.FILE_NAME)
        upload_id = uuid.uuid4().hex
        staging = self.root / f"{STAGING_PREFIX}{upload_id}"
        with self.lock:
            # Un nouvel envoi de la même visite remplace celui qui n'a pas abouti.
            for old in [u for u in self.uploads.values() if u.visit == name]:
                shutil.rmtree(old.staging, ignore_errors=True)
                del self.uploads[old.id]
            staging.mkdir(parents=True)
            self.uploads[upload_id] = Upload(upload_id, name, destination, staging, files, missing)
        print(
            f"Envoi de « {name} » : {len(missing)} fichier(s) à recevoir, "
            f"{len(files) - len(missing)} déjà sur le Mac.",
            file=self.out,
            flush=True,
        )
        return {"envoi": upload_id, "manquants": sorted(missing)}

    def _upload(self, upload_id: str) -> Upload:
        with self.lock:
            upload = self.uploads.get(upload_id)
        if upload is None:
            raise ReceiveError(
                "Envoi inconnu : le Mac a peut-être redémarré. Recommencer l'envoi.", 404
            )
        return upload

    def store(self, upload_id: str, path: str, body: BinaryIO, length: int) -> None:
        """Écrit un fichier dans le dossier provisoire et vérifie son empreinte."""
        upload = self._upload(upload_id)
        expected = upload.files.get(path)
        if expected is None:
            raise ReceiveError(f"{path} ne fait pas partie de cet envoi.")
        if length != expected.size:
            raise ReceiveError(f"{path} : {length} octets reçus, {expected.size} annoncés.")
        target = upload.staging / path
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        left = length
        with partial.open("wb") as handle:
            while left:
                chunk = body.read(min(CHUNK, left))
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
                left -= len(chunk)
        if left or digest.hexdigest() != expected.sha256:
            partial.unlink(missing_ok=True)
            raise ReceiveError(f"{path} est arrivé incomplet ou abîmé. Renvoyer la visite.")
        os.replace(partial, target)
        with self.lock:
            upload.received.add(path)

    def finish(self, upload_id: str) -> dict[str, Any]:
        """Vérifie l'envoi complet puis range les fichiers dans le dossier de la visite."""
        upload = self._upload(upload_id)
        missing = sorted(upload.missing - upload.received)
        if missing:
            raise ReceiveError(
                f"Envoi incomplet : {len(missing)} fichier(s) manquant(s), dont {missing[0]}. "
                "Renvoyer la visite : seuls les fichiers manquants partiront.",
                409,
            )
        # Le dossier provisoire devient une copie complète de la visite (liens physiques vers
        # les fichiers déjà sur le Mac, sans recopie), qu'on valide comme le ferait serve.
        for path in upload.files:
            staged = upload.staging / path
            if not staged.exists():
                staged.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(upload.destination / path, staged)
                except OSError:
                    shutil.copy2(upload.destination / path, staged)
        try:
            tour = visite.load(upload.staging)
            for point in tour.points:
                found = capture.find(point.folders.point)
                if found:
                    capture.load(found)
        except (visite.VisiteError, capture.CaptureError) as error:
            self._drop(upload)
            raise ReceiveError(f"Visite refusée : {error}", 422) from error
        new_files = self._commit(upload)
        self._drop(upload)
        folder = upload.destination
        message = (
            f"Visite « {tour.name} » reçue dans {folder} : {len(tour.points)} point(s), "
            f"{new_files} nouveau(x) fichier(s)."
        )
        print(message, file=self.out)
        print(f"Pour la voir : visite360 serve {folder}", file=self.out, flush=True)
        return {"message": message, "points": len(tour.points), "nouveaux": new_files}

    def _commit(self, upload: Upload) -> int:
        """Déplace les fichiers reçus à leur place. Les fichiers déjà présents ne bougent pas,
        sauf visite.json : l'ancien est gardé sous un nom daté."""
        destination = upload.destination
        destination.mkdir(parents=True, exist_ok=True)
        new_files = 0
        for path in sorted(upload.received):
            staged, target = upload.staging / path, destination / path
            if path == visite.FILE_NAME:
                if target.is_file():
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    os.replace(target, destination / f"visite-avant-{stamp}.json")
            elif target.exists():
                continue
            else:
                new_files += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
        return new_files

    def _drop(self, upload: Upload) -> None:
        shutil.rmtree(upload.staging, ignore_errors=True)
        with self.lock:
            self.uploads.pop(upload.id, None)


def remove_leftovers(root: Path) -> None:
    """Supprime les dossiers provisoires d'envois interrompus : les originaux sont sur le
    téléphone, et l'app renverra ce qui manque."""
    for child in root.glob(f"{STAGING_PREFIX}*"):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


def make_server(receiver: Receiver, host: str, port: int) -> ThreadingHTTPServer:
    """Prépare le serveur de réception, sans le lancer."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle(self._info)

        def do_POST(self) -> None:
            self._handle(self._post)

        def do_PUT(self) -> None:
            self._handle(self._put)

        def _info(self, path: str) -> dict[str, Any]:
            if path != "/info":
                raise ReceiveError("Introuvable.", 404)
            return {"app": "visite360", "version": __version__, "format": FORMAT_VERSION}

        def _post(self, path: str) -> dict[str, Any]:
            if path == "/envois":
                length = self._length()
                if length > MAX_MANIFEST_BYTES:
                    raise ReceiveError("Liste des fichiers trop longue.", 413)
                try:
                    raw = json.loads(self.rfile.read(length))
                except ValueError as error:
                    raise ReceiveError("Liste des fichiers illisible (JSON invalide).") from error
                return receiver.start(raw)
            match = re.fullmatch(r"/envois/([0-9a-f]{32})/fin", path)
            if match:
                return receiver.finish(match.group(1))
            raise ReceiveError("Introuvable.", 404)

        def _put(self, path: str) -> dict[str, Any]:
            match = re.fullmatch(r"/envois/([0-9a-f]{32})/(.+)", path)
            if not match:
                raise ReceiveError("Introuvable.", 404)
            receiver.store(match.group(1), unquote(match.group(2)), self.rfile, self._length())
            return {"ok": True}

        def _length(self) -> int:
            try:
                return int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise ReceiveError("Taille de la requête absente.", 411) from error

        def _handle(self, action: Callable[[str], dict[str, Any]]) -> None:
            try:
                receiver.check_code(self.headers.get(CODE_HEADER))
                body, status = action(self.path.split("?", 1)[0]), 200
            except ReceiveError as error:
                body, status = {"message": str(error)}, error.status
                # Le corps de la requête n'a peut-être pas été lu : on ferme la connexion.
                self.close_connection = True
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", JSON)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    try:
        return ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        raise ReceiveError(
            f"Impossible d'ouvrir le port {port} ({error.strerror}). Un autre programme "
            "l'utilise peut-être : essayer --port avec un autre numéro."
        ) from error


def announce(port: int, out: TextIO) -> subprocess.Popen[bytes] | None:
    """Annonce le serveur sur le Wi-Fi par Bonjour, pour que l'app le trouve toute seule."""
    program = shutil.which("dns-sd")
    if program is None:
        print(
            "Annonce automatique impossible (programme dns-sd introuvable, fourni avec macOS) : "
            "saisir l'adresse dans l'app.",
            file=out,
        )
        return None
    name = f"Visite360 sur {socket.gethostname().split('.')[0]}"
    try:
        return subprocess.Popen(
            [program, "-R", name, SERVICE_TYPE, "local", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        print(f"Annonce automatique impossible ({error.strerror}) : saisir l'adresse.", file=out)
        return None


def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def run(root: Path, port: int = DEFAULT_PORT, out: TextIO | None = None) -> int:
    """Point d'entrée de `visite360 receive`. Renvoie le code de sortie."""
    out = out or sys.stdout
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Erreur : impossible de créer {root} ({error.strerror}).", file=sys.stderr)
        return 1
    remove_leftovers(root)
    code = new_code()
    receiver = Receiver(root, code, out)
    try:
        server = make_server(receiver, "0.0.0.0", port)
    except ReceiveError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    actual_port = server.server_address[1]
    print(f"Réception des visites dans {root.resolve()}", file=out)
    print(f"Code à saisir dans l'app : {code[:3]} {code[3:]}", file=out)
    address = lan_address()
    if address:
        print(f"Adresse, si l'app ne trouve pas le Mac : {address}:{actual_port}", file=out)
    process = announce(actual_port, out)
    print("Ctrl+C pour arrêter.", file=out, flush=True)
    # Fenêtre du Terminal fermée ou commande arrêtée : on s'arrête comme avec Ctrl+C, pour ne
    # pas laisser l'annonce Bonjour d'un serveur disparu.
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, _interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.", file=out)
    finally:
        server.server_close()
        if process is not None:
            process.terminate()
        remove_leftovers(root)
    return 0
