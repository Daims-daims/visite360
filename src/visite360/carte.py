"""Étape 14 : génération d'image sur une carte graphique louée chez Scaleway (D32, D41).

Le remplacement d'objet de l'étape 9 peut tourner sur une carte NVIDIA louée au lieu du Mac. Trois
pièces :

- **la carte** : une instance GPU de Scaleway (`L4-1-24G`), créée à la première demande et
  supprimée après un temps sans demande. Le programme qui tourne dessus est `carte_worker.py` ;
- **le serveur du projet**, qui allume la carte, lui transmet la vue et rend le résultat
  (`Carte`). Les vues ne passent que par lui, jamais par un service de génération ;
- **le Mac**, dont la visionneuse parle au serveur par `RemoteGenerator`, avec repli sur mflux
  (`FallbackGenerator`) quand la carte ne répond pas.

L'extinction est faite par la carte elle-même (elle se supprime après `idle_s` secondes sans
demande) : le serveur du projet, qui s'éteint au bout de 15 minutes, ne peut pas s'en charger. Le
plafond mensuel est appliqué par le serveur avant tout allumage (voir `Meter`).

Les routes de l'API d'instances de Scaleway utilisées ici n'ont pas pu être essayées avec un vrai
compte au moment de l'écriture (quota GPU en attente) : voir `docs/generation.md`.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from visite360 import generation
from visite360.generation import GenerationError, Progress
from visite360.opencv import load_cv2

INSTANCES_API = "https://api.scaleway.com/instance/v1/zones/{zone}"
MACHINE_NAME = "visite360-carte"
DEFAULT_TYPE = "L4-1-24G"
DEFAULT_PRICE_PER_HOUR = 0.7875
DEFAULT_CAP_EUR = 30.0
DEFAULT_IDLE_S = 10 * 60
DEFAULT_PORT = 8090
# Une carte qui n'est pas prête après ce temps est supprimée : elle coûte à la minute.
BOOT_TIMEOUT_S = 15 * 60
POLL_S = 10
API_TIMEOUT = 30
# Le calcul d'une vue prend quelques secondes sur la carte, mais le délai couvre un chargement du
# modèle à froid.
GENERATE_TIMEOUT_S = 10 * 60
MAX_BODY = 32 * 1024 * 1024


class CarteError(Exception):
    """La carte n'est pas disponible. Message en français."""


@dataclass(frozen=True)
class Settings:
    """Réglages de la carte, lus dans l'environnement du serveur (D38)."""

    zone: str
    image: str
    project: str
    secret_key: str
    worker_secret: str
    network: str
    commercial_type: str = DEFAULT_TYPE
    price_per_hour: float = DEFAULT_PRICE_PER_HOUR
    cap_eur: float = DEFAULT_CAP_EUR
    idle_s: int = DEFAULT_IDLE_S
    port: int = DEFAULT_PORT


def _number(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        raise CarteError(f"Réglage {name} invalide : « {raw} » n'est pas un nombre.") from None
    if value <= 0:
        raise CarteError(f"Réglage {name} invalide : doit être positif.")
    return value


def from_env(environ: Mapping[str, str]) -> Settings | None:
    """Réglages de la carte, ou None si elle n'est pas configurée (génération sur le Mac)."""
    if not environ.get("VISITE360_CARTE_IMAGE", "").strip():
        return None

    def required(name: str, role: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise CarteError(f"Réglage {name} manquant ({role}). Voir docs/generation.md.")
        return value

    return Settings(
        zone=required("VISITE360_CARTE_ZONE", "zone de la carte, par exemple fr-par-2"),
        image=required("VISITE360_CARTE_IMAGE", "image système préparée pour la carte"),
        project=required("VISITE360_CARTE_PROJET", "identifiant du projet Scaleway"),
        secret_key=required("SCW_SECRET_KEY", "clé secrète de Scaleway"),
        worker_secret=required("VISITE360_CARTE_SECRET", "secret partagé avec la carte"),
        # Sans réseau privé, les vues voyageraient en clair sur Internet : refusé.
        network=required("VISITE360_CARTE_RESEAU", "réseau privé reliant le serveur et la carte"),
        commercial_type=environ.get("VISITE360_CARTE_TYPE", "").strip() or DEFAULT_TYPE,
        price_per_hour=_number(environ, "VISITE360_CARTE_PRIX_HEURE", DEFAULT_PRICE_PER_HOUR),
        cap_eur=_number(environ, "VISITE360_CARTE_PLAFOND", DEFAULT_CAP_EUR),
        idle_s=int(_number(environ, "VISITE360_CARTE_ATTENTE_MIN", DEFAULT_IDLE_S / 60) * 60),
        port=int(_number(environ, "VISITE360_CARTE_PORT", DEFAULT_PORT)),
    )


# --- Instance chez Scaleway ---------------------------------------------------------------------


@dataclass(frozen=True)
class Machine:
    id: str
    address: str | None  # None tant que la carte n'a pas d'adresse sur le réseau privé


class Provider(Protocol):
    """Ce qu'il faut savoir demander à Scaleway (simulé dans les tests)."""

    def find(self) -> Machine | None: ...

    def create(self) -> Machine: ...

    def refresh(self, machine_id: str) -> Machine | None: ...

    def delete(self, machine_id: str) -> None: ...


class ScalewayProvider:
    """Instance GPU par l'API d'instances de Scaleway, en bibliothèque standard."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = INSTANCES_API.format(zone=settings.zone)

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "X-Auth-Token": self.settings.secret_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            if error.code in (401, 403):
                hint = " Vérifier les droits de la clé (Instances) et le quota GPU."
            else:
                hint = ""
            raise CarteError(
                f"Scaleway a refusé la demande de carte ({error.code}) : {detail}.{hint}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CarteError(f"Scaleway ne répond pas : {error}") from error
        return json.loads(raw) if raw else {}

    def _machine(self, server: dict[str, Any]) -> Machine:
        address = None
        if server.get("state") == "running":
            address = server.get("private_ip") or None
        return Machine(server["id"], address)

    def find(self) -> Machine | None:
        listing = self._call("GET", f"/servers?name={MACHINE_NAME}&per_page=10")
        for server in listing.get("servers", []):
            if server.get("name") == MACHINE_NAME and server.get("state") != "stopping":
                return self._machine(server)
        return None

    def create(self) -> Machine:
        settings = self.settings
        created = self._call(
            "POST",
            "/servers",
            {
                "name": MACHINE_NAME,
                "commercial_type": settings.commercial_type,
                "image": settings.image,
                "project": settings.project,
                "dynamic_ip_required": False,
                "tags": ["visite360", "carte"],
            },
        )["server"]
        machine_id = created["id"]
        try:
            self._call(
                "POST",
                f"/servers/{machine_id}/private_nics",
                {"private_network_id": settings.network},
            )
            self._call("POST", f"/servers/{machine_id}/action", {"action": "poweron"})
        except CarteError:
            self.delete(machine_id)  # ne pas laisser une instance payante sans programme
            raise
        return self._machine(created)

    def refresh(self, machine_id: str) -> Machine | None:
        try:
            return self._machine(self._call("GET", f"/servers/{machine_id}")["server"])
        except CarteError as error:
            if "(404)" in str(error):
                return None
            raise

    def delete(self, machine_id: str) -> None:
        try:
            self._call("POST", f"/servers/{machine_id}/action", {"action": "terminate"})
        except CarteError as error:
            if "(404)" not in str(error):  # déjà supprimée
                raise


# --- Plafond de dépense -------------------------------------------------------------------------


class Meter(Protocol):
    """Temps de carte utilisé, par mois (`Registre` en ligne, `MemoryMeter` dans les tests)."""

    def seconds(self, month: str) -> int: ...

    def add(self, month: str, seconds: int) -> None: ...


class MemoryMeter:
    def __init__(self) -> None:
        self.used: dict[str, int] = {}

    def seconds(self, month: str) -> int:
        return self.used.get(month, 0)

    def add(self, month: str, seconds: int) -> None:
        self.used[month] = self.used.get(month, 0) + seconds


def month_of(timestamp: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(timestamp))


# --- Contrôle de la carte, côté serveur ---------------------------------------------------------


def encode_png(image: np.ndarray) -> str:
    ok, data = load_cv2().imencode(".png", image)
    if not ok:
        raise GenerationError("L'encodage de la vue a échoué.")
    return base64.b64encode(data.tobytes()).decode("ascii")


def decode_png(text: str) -> np.ndarray:
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise GenerationError("Image illisible reçue de la carte.") from None
    image = load_cv2().imdecode(np.frombuffer(raw, np.uint8), load_cv2().IMREAD_COLOR)
    if image is None:
        raise GenerationError("Image illisible reçue de la carte.")
    return image


def post_json(url: str, body: dict[str, Any], secret: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "X-Visite360": "1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())  # type: ignore[no-any-return]
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read()).get("message", "")
        except ValueError:
            message = ""
        raise CarteError(message or f"La carte a refusé la demande ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise CarteError(f"La carte ne répond pas ({error}).") from error


class Carte:
    """Allume la carte à la demande et lui fait calculer une vue.

    Le temps compté au plafond est une estimation prudente : le temps de la demande, celui de
    l'allumage quand c'est nous qui l'avons déclenché, et le délai d'attente avant extinction.
    La vraie facture est celle de Scaleway : y régler aussi une alerte de budget.
    """

    def __init__(
        self,
        settings: Settings,
        provider: Provider,
        meter: Meter,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        poll_s: float = POLL_S,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.meter = meter
        self.clock = clock
        self.sleep = sleep
        self.poll_s = poll_s

    def spent_eur(self) -> float:
        seconds = self.meter.seconds(month_of(self.clock()))
        return seconds / 3600 * self.settings.price_per_hour

    def _check_cap(self) -> None:
        spent = self.spent_eur()
        if spent >= self.settings.cap_eur:
            raise CarteError(
                f"Plafond de dépense de la carte atteint ce mois-ci ({spent:.2f} € sur "
                f"{self.settings.cap_eur:.2f} €). La génération se fait sur le Mac."
            )

    def _charge(self, seconds: float) -> None:
        self.meter.add(month_of(self.clock()), max(0, round(seconds)))

    def _url(self, machine: Machine, path: str) -> str:
        return f"http://{machine.address}:{self.settings.port}{path}"

    def _healthy(self, machine: Machine) -> bool:
        try:
            with urllib.request.urlopen(self._url(machine, "/sante"), timeout=5):
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def ensure_ready(self) -> Machine:
        """Une carte prête à calculer : celle qui tourne, ou une nouvelle (jusqu'à 15 minutes)."""
        machine = self.provider.find()
        started = self.clock()
        if machine is None:
            self._check_cap()
            machine = self.provider.create()
            self._charge(self.settings.idle_s)
        while True:
            if machine.address and self._healthy(machine):
                self._charge(self.clock() - started)
                return machine
            if self.clock() - started > BOOT_TIMEOUT_S:
                self.provider.delete(machine.id)
                raise CarteError(
                    "La carte graphique n'a pas démarré en "
                    f"{BOOT_TIMEOUT_S // 60} minutes : supprimée pour ne pas être facturée."
                )
            self.sleep(self.poll_s)
            refreshed = self.provider.refresh(machine.id)
            if refreshed is None:
                raise CarteError("La carte graphique a disparu pendant son démarrage.")
            machine = refreshed

    def forward(self, body: dict[str, Any]) -> dict[str, Any]:
        """Transmet une demande (image, consigne, graine) à la carte. Rien n'est gardé ici."""
        machine = self.ensure_ready()
        started = self.clock()
        answer = post_json(
            self._url(machine, "/generer"), body, self.settings.worker_secret, GENERATE_TIMEOUT_S
        )
        self._charge(self.clock() - started)
        return answer

    def generate(self, image: np.ndarray, prompt: str, seed: int) -> np.ndarray:
        """Envoie la vue à la carte et rend l'image générée."""
        answer = self.forward({"image": encode_png(image), "consigne": prompt, "graine": seed})
        return decode_png(str(answer.get("image", "")))


class CarteGenerator:
    """Générateur du serveur du projet (étape 15) : envoie la vue à la carte, sans passer par le
    réseau public. L'agent connecté à l'espace web génère comme depuis le Mac."""

    def __init__(self, carte: Carte) -> None:
        self.carte = carte

    def generate(self, image: np.ndarray, prompt: str, seed: int, progress: Progress) -> np.ndarray:
        try:
            result = self.carte.generate(image, prompt, seed)
        except CarteError as error:
            raise GenerationError(str(error)) from error
        progress(generation.STEPS, generation.STEPS)
        return result


# --- Côté Mac : générateur distant avec repli ---------------------------------------------------


class RemoteGenerator:
    """Générateur de la visionneuse qui passe par le serveur du projet (ou par la carte)."""

    def __init__(self, url: str, token: str, timeout: float = GENERATE_TIMEOUT_S) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def generate(self, image: np.ndarray, prompt: str, seed: int, progress: Progress) -> np.ndarray:
        try:
            answer = post_json(
                self.url,
                {"image": encode_png(image), "consigne": prompt, "graine": seed},
                self.token,
                self.timeout,
            )
        except CarteError as error:
            raise GenerationError(str(error)) from error
        progress(generation.STEPS, generation.STEPS)
        return decode_png(str(answer.get("image", "")))


class FallbackGenerator:
    """Essaie d'abord la carte, puis le Mac si elle ne répond pas (message dans `notice`)."""

    def __init__(
        self,
        remote: generation.Generator,
        local: Callable[[], generation.Generator] | None,
        notice: Callable[[str], None] = lambda message: None,
    ) -> None:
        self.remote = remote
        self.local = local
        self.notice = notice

    def generate(self, image: np.ndarray, prompt: str, seed: int, progress: Progress) -> np.ndarray:
        try:
            return self.remote.generate(image, prompt, seed, progress)
        except GenerationError as error:
            if self.local is None:
                raise GenerationError(
                    f"{error} Le calcul sur le Mac n'est pas installé "
                    f"({generation.INSTALL_COMMAND})."
                ) from error
            self.notice(f"{error} Calcul sur le Mac à la place.")
            return self.local().generate(image, prompt, seed, progress)
