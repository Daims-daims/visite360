"""Étape 16 : un lien par client, mesure de sa consultation, ses modifications à part (D43).

Pour une même visite, l'agent crée un lien par client. Le lien mène à une page servie par le
serveur du projet (`/l/<jeton>/`), qui montre la visite publiée et laisse le client essayer ses
propres couleurs et remplacements d'objets :

- la page demande au client, à la première ouverture, s'il accepte d'aider son agent. Rien n'est
  envoyé avant sa réponse, ni après un refus. Après un accord, elle envoie toutes les 15
  secondes le temps passé dans chaque pièce, les bascules avant et après et l'ouverture du
  chiffrage (`/l/<jeton>/api/mesure`) ;
- le serveur vérifie chaque mesure : forme, points connus, durées plafonnées au temps réellement
  écoulé, envois en rafale refusés. Les mesures sont rangées dans la base, par lien ;
- les modifications du client sont rangées à part dans le stockage privé
  (`<visite>/liens/<lien>/<point>/modifications/`). Celles de l'agent et des autres clients ne
  bougent pas. Le client n'a ni la mesure de la pièce ni la grille de prix ;
- au plus `MAX_GENERATIONS` remplacements d'objets par lien et par jour, en plus du plafond
  mensuel de la carte graphique (D41).

Mesures et modifications des clients sont effacées 12 mois après la dernière ouverture du lien.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from visite360 import atelier, serve
from visite360.depot import Depot, DepotError
from visite360.registre import Link, Registre, Visit

MAX_GENERATIONS = 5
MAX_LABEL = 80
MAX_LINKS = 50
# Une mesure couvre au plus une minute ; la page en envoie une toutes les 15 secondes.
MAX_SECONDS = 60
MIN_INTERVAL = 5
SLACK = 5
# Au-delà, une page ouverte en boucle ou un robot : la consultation n'est pas comptée.
MAX_OPENINGS_PER_HOUR = 20
MAX_BODY = 4 * 1024
OPENING_ID = re.compile(r"[0-9a-f]{32}")
TOKEN = r"[A-Za-z0-9_-]{16,64}"

# Ce que l'atelier d'un client range (ses modifications) et ce qu'il reprend de la visite en
# lecture seule (la mesure de la pièce par l'agent, pour chiffrer ses couleurs).
CLIENT_SYNCED = re.compile(r"[^/]+/modifications/[^/]+")
SHARED = re.compile(r"[^/]+/piece\.json")
# Routes ouvertes au client. Ni mesure de la pièce, ni grille de prix, ni catégorie d'objet.
CLIENT_POSTS = frozenset(
    {
        "/api/selection/vue",
        "/api/selection/masque",
        "/api/selection/valider",
        "/api/selection/supprimer",
        "/api/couleur/apercu",
        "/api/couleur/appliquer",
        "/api/couleur/annuler",
        "/api/generation/lancer",
        "/api/generation/refaire",
        "/api/generation/supprimer",
    }
)
GENERATING = frozenset({"/api/generation/lancer", "/api/generation/refaire"})
CLIENT_GETS = frozenset({"/api/selection", "/api/generation", "/api/chiffrage"})
FORBIDDEN_GETS = (serve.PIECE_PATH,)
# Fichiers de la visite publiée que la page du client relit par le serveur : les images
# modifiées par l'agent et son chiffrage.
AGENT_FILE = re.compile(r"/agent/(p/\d+/apres(?:-mobile)?\.jpg|chiffrage\.json)")
JPEG = "image/jpeg"


class EngagementError(Exception):
    """Mesure ou lien refusé, avec un message en français et le code HTTP à renvoyer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def store(visit_id: str, link_id: str) -> str:
    """Préfixe du stockage privé où vivent les modifications d'un client."""
    return f"{visit_id}/liens/{link_id}/"


def url_root(link: Link) -> str:
    return f"/l/{link.token}/"


def day(now: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def parse_label(raw: Any) -> str:
    label = raw.get("libelle") if isinstance(raw, dict) else None
    if not isinstance(label, str) or not label.strip():
        raise EngagementError("Donner un libellé au lien, par exemple le nom du client.")
    label = " ".join(label.split())
    if len(label) > MAX_LABEL:
        raise EngagementError(f"Libellé trop long : {MAX_LABEL} caractères au plus.")
    return label


# --- Mesures ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Measure:
    """Une mesure envoyée par la page : ce qui s'est passé depuis la précédente."""

    opening: str
    seconds: dict[str, int]
    toggles: dict[str, int]
    pricing: bool

    @property
    def total(self) -> int:
        return sum(self.seconds.values())


def _counts(raw: Any, points: set[str], limit: int, what: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > len(points):
        raise EngagementError(f"Mesure illisible ({what}).")
    found: dict[str, int] = {}
    for point, value in raw.items():
        if point not in points:
            raise EngagementError(f"Mesure refusée : point inconnu ({what}).")
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= limit:
            raise EngagementError(f"Mesure refusée : valeur invalide ({what}).")
        if value:
            found[point] = value
    return found


def parse_measure(raw: Any, points: set[str]) -> Measure:
    """Vérifie la forme d'une mesure. `points` : identifiants des points de la visite."""
    if not isinstance(raw, dict):
        raise EngagementError("Mesure illisible : objet JSON attendu.")
    opening = raw.get("consultation")
    if not isinstance(opening, str) or not OPENING_ID.fullmatch(opening):
        raise EngagementError("Mesure illisible : identifiant de consultation invalide.")
    seconds = _counts(raw.get("pieces"), points, MAX_SECONDS, "pièces")
    toggles = _counts(raw.get("bascules"), points, 100, "bascules")
    pricing = raw.get("chiffrage", False)
    if not isinstance(pricing, bool):
        raise EngagementError("Mesure illisible (chiffrage).")
    measure = Measure(opening, seconds, toggles, pricing)
    if measure.total > MAX_SECONDS:
        raise EngagementError("Mesure refusée : plus d'une minute en une fois.")
    return measure


def record(registre: Registre, link: Link, measure: Measure) -> None:
    """Range une mesure après les contrôles de rythme. Lève `EngagementError` sinon."""
    now = registre.now()
    found = registre.opening(measure.opening)
    if found is None:
        if registre.recent_openings(link.id, now - 3600) >= MAX_OPENINGS_PER_HOUR:
            raise EngagementError("Trop d'ouvertures en une heure : mesure ignorée.", 429)
    else:
        link_id, opening = found
        if link_id != link.id:
            raise EngagementError("Consultation inconnue.", 404)
        elapsed = now - opening.seen
        if elapsed < MIN_INTERVAL:
            raise EngagementError("Mesures trop rapprochées : mesure ignorée.", 429)
        if measure.total > elapsed + SLACK:
            raise EngagementError("Mesure refusée : plus de temps que le temps écoulé.")
    registre.record(link.id, measure.opening, measure.seconds, measure.toggles, measure.pricing)


# --- Ce que l'agent voit ------------------------------------------------------------------------


def changes(depot: Depot, visit_id: str, link_id: str) -> dict[str, int]:
    """Nombre de modifications du client, par sorte (sélections, couleurs, remplacements)."""
    prefix = store(visit_id, link_id)
    counts = {"selections": 0, "couleurs": 0, "remplacements": 0}
    kinds = {"selection-": "selections", "couleur-": "couleurs", "generation-": "remplacements"}
    for key in depot.list(prefix):
        name = key.rsplit("/", 1)[-1]
        if not name.endswith(".json"):
            continue
        for start, kind in kinds.items():
            if name.startswith(start):
                counts[kind] += 1
    return counts


def summary(registre: Registre, link: Link, names: Mapping[str, str]) -> dict[str, Any]:
    """Totaux d'un lien. `names` : nom de chaque point, par identifiant."""
    openings = registre.openings(link.id)
    rooms = registre.rooms(link.id)
    return {
        "id": link.id,
        "libelle": link.label,
        "adresse": url_root(link),
        "cree_le": link.created,
        "ouvertures": len(openings),
        "derniere_ouverture": openings[0].started if openings else None,
        "secondes": sum(opening.seconds for opening in openings),
        "chiffrage_ouvert": sum(1 for opening in openings if opening.pricing),
        "pieces": [
            {
                "point": point,
                "nom": names.get(point, point),
                "secondes": rooms[point][0],
                "bascules": rooms[point][1],
            }
            for point in sorted(rooms, key=lambda point: -rooms[point][0])
        ],
    }


def detail(
    registre: Registre, depot: Depot, link: Link, names: Mapping[str, str]
) -> dict[str, Any]:
    """Totaux, liste des ouvertures et modifications du client."""
    result = summary(registre, link, names)
    result["liste"] = [
        {
            "debut": opening.started,
            "secondes": opening.seconds,
            "chiffrage": opening.pricing,
        }
        for opening in registre.openings(link.id)
    ]
    result["modifications"] = changes(depot, link.visit_id, link.id)
    return result


def clear_changes(depot: Depot, visit_id: str, link_id: str) -> int:
    """Efface les modifications d'un client. Renvoie le nombre de fichiers effacés."""
    keys = sorted(depot.list(store(visit_id, link_id)))
    for key in keys:
        depot.delete(key)
    return len(keys)


def purge(registre: Registre, depot: Depot) -> int:
    """Effacement après 12 mois (tâche quotidienne) : mesures anciennes, et modifications des
    clients dont le lien n'a pas été ouvert depuis. Renvoie le nombre de liens nettoyés."""
    cleaned = 0
    for link in registre.forget_old_measures():
        if clear_changes(depot, link.visit_id, link.id):
            cleaned += 1
    return cleaned


# --- Atelier d'un client ------------------------------------------------------------------------


class ClientAtelier(atelier.Atelier):
    """Atelier d'un lien : les outils de l'agent réduits aux couleurs et aux remplacements,
    sur les modifications du seul client. Les images de l'agent viennent de la visite
    publiée, relues par le serveur pour que tout reste à la même adresse que la page."""

    def __init__(
        self,
        visit: Visit,
        link: Link,
        depot: Depot,
        published: Callable[[str], bytes],
        root: Path,
        make_tools: atelier.ToolsFactory,
        grid: Callable[[], str | None],
    ) -> None:
        super().__init__(
            visit,
            depot,
            root,
            make_tools,
            grid,
            lambda content: None,
            store=store(visit.id, link.id),
            synced=CLIENT_SYNCED,
            shared=SHARED,
            url_root=url_root(link),
        )
        self.link = link
        self.published = published
        self.cache = root / "publie"

    def _read_grid(self) -> None:
        # Le client ne modifie jamais la grille de l'agent.
        return None

    def describe(self, info: bytes) -> bytes:
        described = json.loads(info)
        described["client"] = True
        described["mesure"] = f"{self.url_root}api/mesure"
        try:
            agent = json.loads(self.published("info.json"))
        except (DepotError, OSError, ValueError):
            agent = {}
        by_id = {point.get("id"): point for point in agent.get("points", [])}
        for point in described["points"]:
            after = by_id.get(point["id"], {}).get("apres")
            if isinstance(after, dict) and after.get("version"):
                point["agent"] = {
                    "version": after["version"],
                    "full": f"{self.url_root}agent/{after['full']}",
                    "mobile": f"{self.url_root}agent/{after['mobile']}",
                }
        if agent.get("chiffrage"):
            described["chiffrage_agent"] = f"{self.url_root}agent/chiffrage.json"
        return json.dumps(described, ensure_ascii=False).encode("utf-8")

    def get(self, rest: str) -> tuple[bytes, str] | None:
        if rest in ("/api/tarifs", "/agent") or any(route.match(rest) for route in FORBIDDEN_GETS):
            return None
        if rest.startswith("/api/") and rest not in CLIENT_GETS:
            return None
        match = AGENT_FILE.fullmatch(rest)
        if match:
            return self._agent_file(match.group(1))
        if rest == "/info.json":
            # Relu à chaque ouverture : l'agent a pu mettre à jour son lien entre-temps.
            with self.lock:
                self._info = b""
                shutil.rmtree(self.cache, ignore_errors=True)
        return super().get(rest)

    def _agent_file(self, rel: str) -> tuple[bytes, str]:
        target = self.cache / rel
        if not target.is_file():
            try:
                data = self.published(rel)
            except (DepotError, OSError) as error:
                message = f"{rel} manque dans la visite publiée ({error})."
                raise atelier.AtelierError(message) from None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return target.read_bytes(), JPEG if rel.endswith(".jpg") else serve.JSON

    def post(self, rest: str, body: dict[str, Any]) -> tuple[bytes, str] | None:
        if rest not in CLIENT_POSTS:
            return None
        return super().post(rest, body)
