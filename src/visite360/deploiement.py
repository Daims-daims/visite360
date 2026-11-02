"""Étape 13 bis : mise en ligne d'une version, serveur et tâche d'assemblage ensemble.

`visite360 deployer <étiquette>` donne la même image (celle de cette étiquette, déjà envoyée dans
l'espace d'images de Scaleway) au conteneur du serveur et à la tâche d'assemblage, redéploie le
conteneur, puis vérifie que le serveur annonce bien le commit attendu (`/api/info`).

Le serveur et la tâche font tourner le même code : s'ils divergeaient, une visite pourrait être
assemblée par une version et affichée par une autre. L'ordre des opérations garantit donc qu'on ne
reste jamais à moitié déployé : si un pas échoue, ce qui avait déjà changé est remis comme avant.

Appelé par GitHub Actions après la fabrication de l'image (`.github/workflows/deploiement.yml`),
et à la main depuis le Mac, qui reste un secours indépendant de GitHub. Pour revenir à une version
précédente, il suffit de redéployer son étiquette.

Les routes de l'API de Scaleway utilisées ici (changement d'image d'un conteneur et d'une tâche)
n'ont pas pu être essayées avec un vrai compte au moment de l'écriture : voir `docs/serveur.md`.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from visite360 import publier
from visite360.traitement import JOBS_API

CONTAINERS_API = "https://api.scaleway.com/containers/v1beta1/regions/{region}/containers"
API_TIMEOUT = 30
TAG = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{0,127}")
IMAGE_NAME = "visite360"
CHECK_TIMEOUT = 600
CHECK_INTERVAL = 10


class DeployError(Exception):
    """Déploiement impossible ou échoué. Message en français."""


class Api(Protocol):
    """Appels à l'API de Scaleway, séparés pour que les tests utilisent une fausse."""

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Appelle l'API et renvoie sa réponse décodée. Lève `DeployError` en cas d'échec."""
        ...


class ScalewayApi:
    def __init__(self, secret_key: str) -> None:
        self.secret_key = secret_key

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body if body is not None else {}).encode() if method != "GET" else None,
            headers={"X-Auth-Token": self.secret_key, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
                content = response.read()
        except urllib.error.HTTPError as error:
            reason = {
                401: "clé refusée",
                403: "droit manquant pour cette clé",
                404: "identifiant inconnu",
            }.get(error.code, "refusé")
            raise DeployError(f"Scaleway : {reason} (erreur {error.code}, {url}).") from None
        except (urllib.error.URLError, OSError) as error:
            raise DeployError(f"Scaleway est injoignable ({error}).") from None
        try:
            decoded = json.loads(content) if content else {}
        except ValueError:
            raise DeployError(f"Réponse illisible de Scaleway ({url}).") from None
        return decoded if isinstance(decoded, dict) else {}


@dataclass(frozen=True)
class Target:
    """Ce qu'on met à jour : tout vient de réglages (D38), rien n'est écrit dans le code."""

    region: str
    container: str
    job: str
    # Espace d'images, hôte compris : rg.fr-par.scw.cloud/<espace>.
    images: str
    # Adresse publique du serveur, pour le contrôle final.
    address: str

    def image(self, tag: str) -> str:
        return f"{self.images.rstrip('/')}/{IMAGE_NAME}:{tag}"

    @property
    def container_url(self) -> str:
        return f"{CONTAINERS_API.format(region=self.region)}/{self.container}"

    @property
    def job_url(self) -> str:
        return f"{JOBS_API.format(region=self.region)}/{self.job}"


def _required(environ: Mapping[str, str], name: str, role: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise DeployError(f"Réglage {name} manquant ({role}). Voir docs/serveur.md.")
    return value


def target_from_env(environ: Mapping[str, str]) -> Target:
    return Target(
        region=environ.get("VISITE360_REGION", publier.DEFAULT_REGION),
        container=_required(environ, "VISITE360_CONTENEUR", "identifiant du conteneur du serveur"),
        job=_required(environ, "VISITE360_JOB", "identifiant de la tâche d'assemblage"),
        images=_required(environ, "VISITE360_IMAGES", "espace d'images, hôte compris"),
        address=_required(environ, "VISITE360_ADRESSE_API", "adresse publique du serveur").rstrip(
            "/"
        ),
    )


def secret_key(environ: Mapping[str, str], config: Path = publier.CONFIG_PATH) -> str:
    """Clé secrète : variable d'environnement (GitHub), sinon fichier du Mac (D37)."""
    value = environ.get("SCW_SECRET_KEY", "").strip()
    if not value and config.is_file():
        try:
            raw = json.loads(config.read_text(encoding="utf-8"))
            value = str(raw.get("cle_secrete", "")).strip() if isinstance(raw, dict) else ""
        except (OSError, ValueError):
            value = ""
    if not value:
        raise DeployError(f"Clé secrète de Scaleway introuvable (SCW_SECRET_KEY ou {config}).")
    return value


def wait_for_commit(
    address: str,
    tag: str,
    timeout: float = CHECK_TIMEOUT,
    interval: float = CHECK_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Attend que le serveur annonce le commit `tag` (un redéploiement prend du temps)."""
    deadline = clock() + timeout
    seen = "aucune réponse"
    while True:
        try:
            with urllib.request.urlopen(f"{address}/api/info", timeout=API_TIMEOUT) as response:
                info = json.loads(response.read())
            if isinstance(info, dict) and info.get("commit") == tag:
                return
            seen = (
                f"commit annoncé : {info.get('commit', 'aucun') if isinstance(info, dict) else '?'}"
            )
        except (urllib.error.URLError, OSError, ValueError) as error:
            seen = f"serveur injoignable ({error})"
        if clock() >= deadline:
            raise DeployError(
                f"Le serveur n'annonce pas le commit {tag} après {timeout:.0f} s ({seen})."
            )
        sleep(interval)


def _set_images(api: Api, target: Target, container_image: str, job_image: str) -> list[str]:
    """Remet ces images sur la tâche et le conteneur (qu'on redéploie). Renvoie les échecs."""
    failures: list[str] = []
    for label, action in (
        ("la tâche", lambda: api.request("PATCH", target.job_url, {"image_uri": job_image})),
        (
            "le conteneur",
            lambda: api.request("PATCH", target.container_url, {"registry_image": container_image}),
        ),
        (
            "le déploiement du conteneur",
            lambda: api.request("POST", f"{target.container_url}/deploy"),
        ),
    ):
        try:
            action()
        except DeployError as error:
            failures.append(f"{label} : {error}")
    return failures


def deploy(
    api: Api,
    target: Target,
    tag: str,
    check: Callable[[str], None],
    dry_run: bool = False,
    out: TextIO | None = None,
) -> None:
    """Met `tag` en ligne partout, ou ne change rien de durable (sinon `DeployError`)."""
    out = out or sys.stdout
    if not TAG.fullmatch(tag):
        raise DeployError(f"Étiquette d'image invalide : « {tag} ».")
    image = target.image(tag)
    if dry_run:
        print(f"[essai à blanc] aucun appel. Mettrait {image} sur :", file=out)
        print(f"  - la tâche {target.job}", file=out)
        print(f"  - le conteneur {target.container}, puis le redéploierait", file=out)
        print(f"  - puis vérifierait {target.address}/api/info (commit {tag}).", file=out)
        return

    # État actuel, pour pouvoir le remettre. Lu avant toute modification.
    container = api.request("GET", target.container_url)
    job = api.request("GET", target.job_url)
    old_container = container.get("registry_image")
    old_job = job.get("image_uri")
    if not isinstance(old_container, str) or not isinstance(old_job, str):
        raise DeployError("Image actuelle illisible chez Scaleway : rien n'a été modifié.")
    print(f"Image actuelle : conteneur {old_container}, tâche {old_job}", file=out)

    # La tâche d'abord : changer son image ne coûte rien et ne coupe rien. Si ça échoue, on
    # s'arrête sans avoir touché au serveur.
    print(f"Mise à jour de la tâche d'assemblage : {image}", file=out)
    api.request("PATCH", target.job_url, {"image_uri": image})
    try:
        print(f"Mise à jour et redéploiement du conteneur : {image}", file=out)
        api.request("PATCH", target.container_url, {"registry_image": image})
        api.request("POST", f"{target.container_url}/deploy")
        print("Vérification du serveur...", file=out)
        check(tag)
    except DeployError as error:
        print(f"Échec : {error}\nRetour à l'image précédente...", file=out)
        failures = _set_images(api, target, old_container, old_job)
        if failures:
            raise DeployError(
                f"{error} Le retour en arrière a lui aussi échoué ({'; '.join(failures)}) : "
                f"vérifier à la main dans la console de Scaleway (conteneur et tâche "
                f"doivent porter la même image)."
            ) from None
        raise DeployError(f"{error} L'image précédente a été remise.") from None
    print(f"Déployé : {image} (conteneur et tâche).", file=out)


def run(
    tag: str,
    dry_run: bool = False,
    skip_check: bool = False,
    environ: Mapping[str, str] | None = None,
    api: Api | None = None,
    check: Callable[[str], None] | None = None,
    config: Path = publier.CONFIG_PATH,
) -> int:
    """Commande `visite360 deployer` : code de sortie 0 si tout est en ligne, 1 sinon."""
    environ = os.environ if environ is None else environ
    try:
        target = target_from_env(environ)
        if check is None:
            if skip_check:

                def check(_tag: str) -> None:
                    print("Contrôle du serveur sauté (--sans-controle).")
            else:

                def check(wanted: str) -> None:
                    wait_for_commit(target.address, wanted)

        if api is None and not dry_run:
            api = ScalewayApi(secret_key(environ, config))
        deploy(api or ScalewayApi(""), target, tag, check, dry_run)
    except DeployError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    return 0
