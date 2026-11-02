"""Étape 12 : publie une visite chez Scaleway, en fichiers statiques, et la retire (D35).

`visite360 publier <visite>` dépose dans un stockage de fichiers de Scaleway (Object Storage,
région Paris) la visionneuse en lecture seule, `info.json` et les panoramas, sous un identifiant
tiré au hasard, puis affiche le lien. Aucun serveur ne tourne pour consulter la visite.

- Seule une liste fermée de fichiers part : jamais les photos d'origine, les modifications, les
  mesures de pièce ni les rapports.
- L'identifiant (128 bits) est rangé dans `<visite>/publication.json` : relancer la commande
  garde le même lien et n'envoie que les fichiers dont l'empreinte MD5 diffère de celle du
  stockage. Les fichiers en ligne qui n'existent plus en local sont supprimés.
- Chaque fichier est lisible par tous, mais le stockage reste privé : sa liste n'est pas
  consultable. Un `robots.txt` à la racine et la balise `noindex` de la page demandent aux
  moteurs de recherche de ne rien indexer.

`visite360 depublier <visite>` supprime tout ce qui est en ligne sous l'identifiant, puis oublie
celui-ci : une nouvelle publication aura un autre lien.

Le stockage se pilote par le protocole S3, que parle Scaleway, avec la bibliothèque standard :
chaque requête est signée par la méthode « Signature Version 4 » (`sign`). Les clés d'accès sont
lues dans `~/.config/visite360/scaleway.json`, hors du dépôt, ou dans les variables
d'environnement `SCW_ACCESS_KEY` et `SCW_SECRET_KEY`.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TextIO

from visite360 import serve, stitch, visite
from visite360.photos import PhotoError

CONFIG_PATH = Path.home() / ".config" / "visite360" / "scaleway.json"
STATE_NAME = "publication.json"
CONFIGURE = "visite360 publier --configurer"
DEFAULT_REGION = "fr-par"
# 16 octets tirés au hasard = 128 bits, écrits en 22 caractères (lettres, chiffres, - et _).
ID_BYTES = 16
TIMEOUT = 60
ROBOTS_KEY = "robots.txt"
ROBOTS = b"User-agent: *\nDisallow: /\n"
READY = {"status": "ready", "progress": 1.0, "message": "Visite prête", "error": None}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": serve.JSON,
    ".jpg": "image/jpeg",
    ".txt": "text/plain; charset=utf-8",
}


class PublishError(Exception):
    """La publication est impossible : clé absente ou refusée, réseau, visite incomplète."""


@dataclass(frozen=True)
class Settings:
    """Réglages de Scaleway : clés, nom du stockage (« bucket »), région, adresse des liens."""

    access_key: str
    secret_key: str
    bucket: str
    region: str = DEFAULT_REGION
    # Adresse de base des liens ; par défaut celle que fournit Scaleway. Un nom de domaine du
    # projet la remplacera (question ouverte de l'étape 12).
    address: str | None = None
    # Adresse du service S3 ; changée seulement par les tests (faux serveur local).
    endpoint: str | None = None

    @property
    def public_base(self) -> str:
        return (self.address or f"https://{self.bucket}.s3.{self.region}.scw.cloud").rstrip("/")

    @property
    def api_base(self) -> str:
        return (self.endpoint or f"https://s3.{self.region}.scw.cloud").rstrip("/")


def load_settings(path: Path, environ: Mapping[str, str]) -> Settings:
    """Lit les réglages ; les variables d'environnement passent avant le fichier."""
    raw: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PublishError(
                f"{path} est illisible ({error}). Le refaire : {CONFIGURE}"
            ) from None
        if not isinstance(loaded, dict):
            raise PublishError(f"{path} doit contenir un objet {{...}}. Le refaire : {CONFIGURE}")
        raw = loaded
    values = {
        "access_key": environ.get("SCW_ACCESS_KEY") or raw.get("cle_acces"),
        "secret_key": environ.get("SCW_SECRET_KEY") or raw.get("cle_secrete"),
        "bucket": environ.get("VISITE360_BUCKET") or raw.get("bucket"),
    }
    missing = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if missing:
        labels = {
            "access_key": "clé d'accès",
            "secret_key": "clé secrète",
            "bucket": "nom du stockage (bucket)",
        }
        raise PublishError(
            f"Réglages de Scaleway incomplets : {', '.join(labels[m] for m in missing)} "
            f"manquant(s) dans {path}. Les enregistrer : {CONFIGURE}"
        )
    region = raw.get("region", DEFAULT_REGION)
    address = environ.get("VISITE360_ADRESSE_VISITES") or raw.get("adresse")
    if not isinstance(region, str) or (address is not None and not isinstance(address, str)):
        raise PublishError(f"{path} : « region » et « adresse » doivent être du texte.")
    return Settings(
        str(values["access_key"]),
        str(values["secret_key"]),
        str(values["bucket"]),
        region,
        address,
        environ.get("VISITE360_S3_ENDPOINT"),
    )


def readable_by_others(path: Path) -> bool:
    return path.is_file() and bool(path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def save_settings(path: Path, access_key: str, secret_key: str, bucket: str) -> None:
    """Écrit le fichier de réglages, lisible par son seul propriétaire."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = {"cle_acces": access_key, "cle_secrete": secret_key, "bucket": bucket}
    partial = path.with_name(path.name + ".partiel")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(content, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(partial, 0o600)
    os.replace(partial, path)


# --- Signature des requêtes (AWS Signature Version 4) ------------------------------------------


def _quote(text: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(text, safe=safe)


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    access_key: str,
    secret_key: str,
    region: str,
    when: datetime,
) -> dict[str, str]:
    """En-têtes d'une requête S3 signée : ceux donnés, plus la date, l'empreinte et la signature.

    La signature prouve au stockage que la requête vient du détenteur de la clé secrète, sans
    l'envoyer : c'est un calcul HMAC-SHA256 sur la méthode, l'adresse, les en-têtes et le contenu.
    """
    parts = urllib.parse.urlsplit(url)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    signed = {key.lower(): str(value).strip() for key, value in headers.items()}
    signed["host"] = parts.netloc
    signed["x-amz-content-sha256"] = payload_sha256
    signed["x-amz-date"] = stamp
    names = sorted(signed)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    canonical_query = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query))
    canonical = "\n".join(
        [
            method,
            _quote(urllib.parse.unquote(parts.path) or "/", safe="-_.~/"),
            canonical_query,
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            payload_sha256,
        ]
    )
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ]
    )
    key = _hmac(("AWS4" + secret_key).encode("utf-8"), day)
    for part in (region, "s3", "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    result = {name: value for name, value in signed.items() if name != "host"}
    result["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return result


# --- Stockage -----------------------------------------------------------------------------------


class Storage(Protocol):
    """Ce dont la publication a besoin d'un stockage de fichiers. Les tests en passent un faux."""

    def list(self, prefix: str) -> dict[str, str]:
        """Fichiers dont le nom commence par `prefix`, avec leur empreinte MD5 en hexadécimal."""
        ...

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Dépose un fichier lisible par tous (mais non listable)."""
        ...

    def delete(self, key: str) -> None: ...


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class S3Storage:
    """Object Storage de Scaleway, par le protocole S3, sans bibliothèque externe."""

    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.clock = clock

    def _request(
        self,
        method: str,
        key: str = "",
        query: Mapping[str, str] | None = None,
        data: bytes = b"",
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        settings = self.settings
        url = f"{settings.api_base}/{_quote(settings.bucket)}"
        if key:
            url += "/" + _quote(key, safe="-_.~/")
        if query:
            url += "?" + "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items()))
        payload_hash = hashlib.sha256(data).hexdigest() if data else EMPTY_SHA256
        signed = sign(
            method,
            url,
            headers or {},
            payload_hash,
            settings.access_key,
            settings.secret_key,
            settings.region,
            self.clock(),
        )
        request = urllib.request.Request(
            url, data=data if method == "PUT" else None, headers=signed, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            raise PublishError(self._explain(error)) from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise PublishError(
                f"Scaleway est injoignable ({reason}). Vérifier la connexion à Internet, "
                "puis relancer : les fichiers déjà envoyés ne seront pas renvoyés."
            ) from None

    def _explain(self, error: urllib.error.HTTPError) -> str:
        code = ""
        try:
            root = ElementTree.fromstring(error.read())
            code = next((el.text or "" for el in root.iter() if _local_name(el.tag) == "Code"), "")
        except (ElementTree.ParseError, OSError):
            pass
        bucket = self.settings.bucket
        if code == "NoSuchBucket":
            return (
                f"Le stockage « {bucket} » n'existe pas dans la région {self.settings.region}. "
                "Le créer dans la console de Scaleway (voir docs/publication.md)."
            )
        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch") or error.code in (401, 403):
            return (
                f"Scaleway refuse les clés d'accès (erreur {error.code} {code}). Vérifier la clé "
                f"d'accès, la clé secrète et leurs droits sur le stockage « {bucket} », puis "
                f"les réenregistrer : {CONFIGURE}"
            )
        return f"Scaleway a répondu par une erreur {error.code} {code}".rstrip() + "."

    def list(self, prefix: str) -> dict[str, str]:
        found: dict[str, str] = {}
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            try:
                root = ElementTree.fromstring(self._request("GET", query=query))
            except ElementTree.ParseError:
                raise PublishError(
                    "Réponse illisible de Scaleway à la liste des fichiers."
                ) from None
            token = None
            truncated = False
            for element in root:
                name = _local_name(element.tag)
                if name == "Contents":
                    fields = {_local_name(child.tag): child.text or "" for child in element}
                    found[fields.get("Key", "")] = fields.get("ETag", "").strip('"').lower()
                elif name == "IsTruncated":
                    truncated = (element.text or "").strip() == "true"
                elif name == "NextContinuationToken":
                    token = element.text
            if not truncated or not token:
                return found

    def put(self, key: str, data: bytes, content_type: str, public: bool = True) -> None:
        headers = {
            "Content-Type": content_type,
            "Content-MD5": base64.b64encode(hashlib.md5(data).digest()).decode("ascii"),
            # Relu à chaque ouverture : une visite republiée se voit tout de suite.
            "Cache-Control": "no-cache",
        }
        if public:
            headers["x-amz-acl"] = "public-read"
        self._request("PUT", key, data=data, headers=headers)

    def get(self, key: str) -> bytes:
        """Contenu d'un fichier (stockage privé de l'étape 13)."""
        return self._request("GET", key)

    def delete(self, key: str) -> None:
        self._request("DELETE", key)


# --- Publication --------------------------------------------------------------------------------


@dataclass(frozen=True)
class File:
    """Un fichier à publier : son chemin sous l'identifiant, son contenu et son type."""

    name: str
    data: bytes
    content_type: str

    @property
    def md5(self) -> str:
        return hashlib.md5(self.data).hexdigest()


def _content_type(name: str) -> str:
    return TYPES[Path(name).suffix.lower()]


def published_files(tour: visite.Tour) -> list[File]:
    """Liste fermée des fichiers d'une visite publiée, panoramas d'abord, page en dernier.

    La page arrive en dernier pour qu'un visiteur ne la reçoive pas avant ses panoramas.
    """
    try:
        assets, info = serve.build_assets(tour, root="", published=True)
        viewer = serve.viewer_folder()
    except serve.ServeError as error:
        raise PublishError(
            f"{error} Assembler d'abord la visite (visite360 serve), puis relancer."
        ) from None
    files = [
        File(name, asset.path.read_bytes(), asset.content_type) for name, asset in assets.items()
    ]
    for name in ("pannellum/pannellum.js", "pannellum/pannellum.css"):
        files.append(File(name, (viewer / name).read_bytes(), _content_type(name)))
    files.append(File("status.json", json.dumps(READY).encode("utf-8"), serve.JSON))
    files.append(File("info.json", info, serve.JSON))
    page = (viewer / "index.html").read_bytes()
    files.append(File("index.html", page, _content_type("index.html")))
    return files


def new_identifier() -> str:
    return secrets.token_urlsafe(ID_BYTES)


def read_state(folder: Path) -> dict[str, str] | None:
    path = folder / STATE_NAME
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PublishError(f"{path} est illisible ({error}).") from None
    ok = isinstance(state, dict) and all(
        isinstance(state.get(key), str) and state[key] for key in ("identifiant", "bucket")
    )
    if not ok or len(state["identifiant"]) < 22:
        raise PublishError(f"{path} est abîmé : identifiant ou bucket manquant.")
    return state


def write_state(folder: Path, state: dict[str, str]) -> None:
    path = folder / STATE_NAME
    partial = path.with_name(path.name + ".partiel")
    partial.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


def link(settings: Settings, identifier: str) -> str:
    return f"{settings.public_base}/{identifier}/index.html"


@dataclass(frozen=True)
class Report:
    link: str
    sent: tuple[str, ...]
    unchanged: int
    deleted: tuple[str, ...]


def publish(
    tour: visite.Tour, folder: Path, storage: Storage, settings: Settings, out: TextIO
) -> Report:
    """Publie la visite ; ne renvoie que ce qui a changé depuis la dernière fois."""
    files = published_files(tour)
    state = read_state(folder)
    if state is not None and state["bucket"] != settings.bucket:
        raise PublishError(
            f"Cette visite est en ligne dans le stockage « {state['bucket']} », pas dans "
            f"« {settings.bucket} ». La dépublier avec l'ancien réglage avant de changer."
        )
    if state is None:
        state = {
            "identifiant": new_identifier(),
            "bucket": settings.bucket,
            "publiee_le": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        # Rangé avant l'envoi : une publication interrompue garde son lien à la reprise.
        write_state(folder, state)
    prefix = state["identifiant"] + "/"
    remote = storage.list(prefix)
    if storage.list(ROBOTS_KEY).get(ROBOTS_KEY) != hashlib.md5(ROBOTS).hexdigest():
        storage.put(ROBOTS_KEY, ROBOTS, TYPES[".txt"])
    sent: list[str] = []
    unchanged = 0
    total = sum(len(file.data) for file in files if remote.get(prefix + file.name) != file.md5)
    done = 0
    for file in files:
        if remote.get(prefix + file.name) == file.md5:
            unchanged += 1
            continue
        done += len(file.data)
        print(
            f"Envoi de {file.name} ({_size(len(file.data))}, {_size(done)} sur {_size(total)})",
            file=out,
        )
        storage.put(prefix + file.name, file.data, file.content_type)
        sent.append(file.name)
    wanted = {prefix + file.name for file in files}
    deleted = sorted(key for key in remote if key not in wanted)
    for key in deleted:
        storage.delete(key)
    state["mise_a_jour_le"] = datetime.now(UTC).isoformat(timespec="seconds")
    write_state(folder, state)
    return Report(
        link(settings, state["identifiant"]),
        tuple(sent),
        unchanged,
        tuple(key[len(prefix) :] for key in deleted),
    )


def unpublish(folder: Path, storage: Storage, settings: Settings) -> int | None:
    """Supprime tout ce qui est en ligne. Renvoie le nombre de fichiers supprimés, ou None."""
    state = read_state(folder)
    if state is None:
        return None
    if state["bucket"] != settings.bucket:
        raise PublishError(
            f"Cette visite est en ligne dans le stockage « {state['bucket']} », mais les "
            f"réglages désignent « {settings.bucket} ». Remettre l'ancien réglage pour la retirer."
        )
    count = remove_published(storage, state["identifiant"])
    (folder / STATE_NAME).unlink()
    return count


def remove_published(storage: Storage, identifier: str) -> int:
    """Supprime tous les fichiers en ligne sous un identifiant. Renvoie leur nombre."""
    prefix = identifier + "/"
    keys = sorted(storage.list(prefix))
    for key in keys:
        storage.delete(key)
    left = storage.list(prefix)
    if left:
        raise PublishError(
            f"{len(left)} fichier(s) sont encore en ligne après la suppression. Relancer."
        )
    return len(keys)


def _size(count: int) -> str:
    if count >= 1024 * 1024:
        return f"{count / (1024 * 1024):.1f} Mo".replace(".", ",")
    return f"{max(1, round(count / 1024))} ko"


# --- Ligne de commande --------------------------------------------------------------------------


def visit_folder(target: Path) -> Path:
    """Dossier où ranger `publication.json` : celui de la visite, ou du point seul."""
    if visite.looks_like_tour(target):
        return target
    return stitch.resolve_folders(target).point


def _open(config: Path, environ: Mapping[str, str], err: TextIO) -> tuple[Settings, Storage] | None:
    try:
        settings = load_settings(config, environ)
    except PublishError as error:
        print(f"Erreur : {error}", file=err)
        return None
    if readable_by_others(config):
        print(
            f"Attention : {config} est lisible par d'autres comptes du Mac. "
            f"Le protéger : chmod 600 {config}",
            file=err,
        )
    return settings, S3Storage(settings)


StorageFactory = Callable[[Settings], Storage]


def run_publish(
    target: Path,
    config: Path = CONFIG_PATH,
    environ: Mapping[str, str] | None = None,
    storage_factory: StorageFactory | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 publier`. Renvoie le code de sortie."""
    out, err = out or sys.stdout, err or sys.stderr
    opened = _open(config, os.environ if environ is None else environ, err)
    if opened is None:
        return 1
    settings, storage = opened
    if storage_factory is not None:
        storage = storage_factory(settings)
    try:
        tour, created = visite.open_tour(target)
        if created:
            print(
                f"{visite.FILE_NAME} créé avec {len(tour.points)} point(s) et aucun lien.", file=out
            )
        report = publish(tour, visit_folder(target), storage, settings, out)
    except (PublishError, visite.VisiteError, stitch.StitchError, PhotoError) as error:
        print(f"Erreur : {error}", file=err)
        return 1
    if report.sent or report.deleted:
        print(
            f"{len(report.sent)} fichier(s) envoyé(s), {report.unchanged} déjà à jour"
            + (f", {len(report.deleted)} retiré(s)" if report.deleted else "")
            + ".",
            file=out,
        )
    else:
        print("Rien n'a changé depuis la dernière publication.", file=out)
    print(f"Visite en ligne : {report.link}", file=out)
    print(
        "Ce lien est le seul accès à la visite : ne le transmettre qu'aux personnes voulues.",
        file=out,
    )
    return 0


def run_unpublish(
    target: Path,
    config: Path = CONFIG_PATH,
    environ: Mapping[str, str] | None = None,
    storage_factory: StorageFactory | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 depublier`. Renvoie le code de sortie."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        folder = visit_folder(target)
        if read_state(folder) is None:
            print("Cette visite n'est pas publiée : rien à retirer.", file=out)
            return 0
    except (PublishError, stitch.StitchError) as error:
        print(f"Erreur : {error}", file=err)
        return 1
    opened = _open(config, os.environ if environ is None else environ, err)
    if opened is None:
        return 1
    settings, storage = opened
    if storage_factory is not None:
        storage = storage_factory(settings)
    try:
        count = unpublish(folder, storage, settings)
    except PublishError as error:
        print(f"Erreur : {error}", file=err)
        return 1
    print(
        f"Visite retirée : {count} fichier(s) supprimé(s). Le lien n'affiche plus rien.", file=out
    )
    return 0


def run_configure(
    config: Path = CONFIG_PATH,
    ask: Callable[[str], str] = input,
    ask_secret: Callable[[str], str] = getpass.getpass,
    out: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 publier --configurer` : enregistre les réglages."""
    out = out or sys.stdout
    print(
        "Clés d'accès à créer dans la console de Scaleway (voir docs/publication.md). "
        f"Elles seront rangées dans {config}, lisible par vous seul, hors du dépôt.",
        file=out,
    )
    try:
        access_key = ask("Clé d'accès (Access Key, commence par SCW) : ").strip()
        secret_key = ask_secret("Clé secrète (Secret Key, ne s'affiche pas) : ").strip()
        bucket = ask("Nom du stockage (bucket) : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbandon : rien n'a été enregistré.", file=sys.stderr)
        return 1
    if not (access_key and secret_key and bucket):
        print(
            "Erreur : les trois valeurs sont nécessaires, rien n'a été enregistré.", file=sys.stderr
        )
        return 1
    save_settings(config, access_key, secret_key, bucket)
    print(f"Réglages enregistrés dans {config}.", file=out)
    return 0
