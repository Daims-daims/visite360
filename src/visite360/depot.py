"""Étape 13 : stockage privé des photos envoyées par l'app, et adresses de dépôt signées.

Les photos d'origine ne passent pas par le serveur : il donne à l'app, pour chaque photo, une
adresse de dépôt temporaire, signée avec la clé du stockage, que l'app utilise pour déposer
le fichier directement dans le stockage privé. C'est un « morceau » de l'envoi. Une coupure
de réseau ne perd que la photo en cours : l'app redemande ensuite ce qui manque.

L'adresse fixe l'empreinte MD5 du fichier (en-tête `Content-MD5`, signé) : le stockage refuse
un fichier arrivé abîmé, et donne ensuite cette même empreinte dans sa liste, ce qui permet au
serveur de vérifier qu'un envoi est complet sans relire les photos.

Le stockage privé n'est jamais lisible par un lien : seul le serveur et l'assemblage y lisent,
avec la clé. On y range, par visite (`<visite>/…`), les photos et fiches envoyées par l'app,
puis les panoramas et rapports d'assemblage.

Deux réalisations :

- `S3Depot`, Object Storage de Scaleway, par le client S3 de l'étape 12 ;
- `FolderDepot`, un dossier du Mac, pour le serveur lancé en local et pour les tests : les
  adresses de dépôt pointent alors vers le serveur lui-même (`/depot/…`), signées par HMAC.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import time
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar

from visite360 import publier

UPLOAD_LIFETIME = 6 * 3600
# En-têtes que l'app doit envoyer tels quels avec chaque dépôt.
MD5_HEADER = "Content-MD5"

T = TypeVar("T")


class DepotError(Exception):
    """Opération refusée sur le stockage privé. Message en français."""


def md5_base64(hex_digest: str) -> str:
    """Empreinte MD5 hexadécimale (celle du manifeste) au format de l'en-tête `Content-MD5`."""
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


class Depot(Protocol):
    """Ce que le serveur et l'assemblage demandent au stockage privé."""

    def list(self, prefix: str) -> dict[str, str]:
        """Fichiers dont le nom commence par `prefix`, avec leur empreinte MD5 hexadécimale."""
        ...

    def get(self, key: str) -> bytes: ...

    def put(self, key: str, data: bytes, content_type: str, public: bool = False) -> None: ...

    def delete(self, key: str) -> None: ...

    def upload_url(self, key: str, md5_hex: str, lifetime: int = UPLOAD_LIFETIME) -> str:
        """Adresse de dépôt temporaire d'un fichier, valable seulement avec cette empreinte."""
        ...


def presign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    access_key: str,
    secret_key: str,
    region: str,
    when: datetime,
    lifetime: int,
) -> str:
    """Adresse S3 signée (« Signature Version 4 » dans l'adresse), utilisable sans la clé.

    Les en-têtes donnés font partie de la signature : la requête doit les porter à l'identique.
    """
    parts = urllib.parse.urlsplit(url)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    scope = f"{day}/{region}/s3/aws4_request"
    signed = {key.lower(): str(value).strip() for key, value in headers.items()}
    signed["host"] = parts.netloc
    names = sorted(signed)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True) + [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{scope}"),
        ("X-Amz-Date", stamp),
        ("X-Amz-Expires", str(lifetime)),
        ("X-Amz-SignedHeaders", ";".join(names)),
    ]
    canonical_query = "&".join(f"{publier._quote(k)}={publier._quote(v)}" for k, v in sorted(query))
    canonical = "\n".join(
        [
            method,
            publier._quote(urllib.parse.unquote(parts.path) or "/", safe="-_.~/"),
            canonical_query,
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            "UNSIGNED-PAYLOAD",
        ]
    )
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ]
    )
    key = publier._hmac(("AWS4" + secret_key).encode("utf-8"), day)
    for part in (region, "s3", "aws4_request"):
        key = publier._hmac(key, part)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"{parts.scheme}://{parts.netloc}{parts.path}?{canonical_query}&X-Amz-Signature={signature}"
    )


class S3Depot:
    """Stockage privé chez Scaleway. Les fichiers déposés ne sont lisibles qu'avec la clé."""

    def __init__(
        self,
        settings: publier.Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.storage = publier.S3Storage(settings, clock)
        self.clock = clock

    def list(self, prefix: str) -> dict[str, str]:
        return self._wrap(lambda: self.storage.list(prefix))

    def get(self, key: str) -> bytes:
        return self._wrap(lambda: self.storage.get(key))

    def put(self, key: str, data: bytes, content_type: str, public: bool = False) -> None:
        self._wrap(lambda: self.storage.put(key, data, content_type, public=public))

    def delete(self, key: str) -> None:
        self._wrap(lambda: self.storage.delete(key))

    def upload_url(self, key: str, md5_hex: str, lifetime: int = UPLOAD_LIFETIME) -> str:
        settings = self.settings
        url = (
            f"{settings.api_base}/{publier._quote(settings.bucket)}/"
            f"{publier._quote(key, safe='-_.~/')}"
        )
        return presign(
            "PUT",
            url,
            {MD5_HEADER: md5_base64(md5_hex)},
            settings.access_key,
            settings.secret_key,
            settings.region,
            self.clock(),
            lifetime,
        )

    @staticmethod
    def _wrap(action: Callable[[], T]) -> T:
        try:
            return action()
        except publier.PublishError as error:
            raise DepotError(str(error)) from None


class FolderDepot:
    """Stockage dans un dossier : serveur lancé sur le Mac, et tests.

    Sert aussi de stockage « public » pour les visites publiées en local : `put` ignore alors
    la lecture publique, c'est le serveur local qui sert le dossier.
    """

    def __init__(
        self,
        root: Path,
        base_url: str = "",
        secret: bytes = b"",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.secret = secret or os.urandom(32)
        self.clock = clock

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()) or not key or key.startswith("/"):
            raise DepotError(f"Nom de fichier refusé : {key!r}.")
        return path

    def list(self, prefix: str) -> dict[str, str]:
        found: dict[str, str] = {}
        if not self.root.is_dir():
            return found
        for path in self.root.rglob("*"):
            if path.is_file() and not path.name.endswith(".partiel"):
                key = path.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    found[key] = hashlib.md5(path.read_bytes()).hexdigest()
        return found

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise DepotError(f"Fichier absent du stockage : {key}.")
        return path.read_bytes()

    def put(self, key: str, data: bytes, content_type: str, public: bool = False) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partiel")
        partial.write_bytes(data)
        os.replace(partial, path)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        # Retire les dossiers vides laissés derrière.
        parent = path.parent
        root = self.root.resolve()
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    # --- Adresses de dépôt vers le serveur local ------------------------------------------------

    def _signature(self, key: str, md5_hex: str, expires: int) -> str:
        message = f"{key}\n{md5_hex}\n{expires}".encode()
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def upload_url(self, key: str, md5_hex: str, lifetime: int = UPLOAD_LIFETIME) -> str:
        expires = int(self.clock()) + lifetime
        query = urllib.parse.urlencode(
            {"md5": md5_hex, "exp": expires, "sig": self._signature(key, md5_hex, expires)}
        )
        return f"{self.base_url}/depot/{urllib.parse.quote(key)}?{query}"

    def accept_upload(
        self, key: str, query: Mapping[str, str], md5_header: str, data: bytes
    ) -> None:
        """Dépôt reçu par le serveur local : vérifie l'adresse signée et l'empreinte."""
        md5_hex, expires = query.get("md5", ""), query.get("exp", "")
        try:
            expiry = int(expires)
        except ValueError:
            raise DepotError("Adresse de dépôt invalide.") from None
        expected = self._signature(key, md5_hex, expiry)
        if not hmac.compare_digest(expected, query.get("sig", "")):
            raise DepotError("Adresse de dépôt invalide.")
        if expiry < self.clock():
            raise DepotError("Adresse de dépôt expirée : relancer l'envoi depuis l'app.")
        try:
            given = base64.b64decode(md5_header, validate=True).hex()
        except (binascii.Error, ValueError):
            given = ""
        if given != md5_hex or hashlib.md5(data).hexdigest() != md5_hex:
            raise DepotError("Fichier arrivé abîmé (empreinte MD5 différente).")
        self.put(key, data, "application/octet-stream")
