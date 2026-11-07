"""Étape 13 : serveur du projet — connexion des agents, envoi des visites, espace web (D39).

En ligne, `visite360 serveur` tourne chez Scaleway dans un conteneur (Serverless Containers),
derrière l'adresse HTTPS du projet. Il ne fait aucun calcul lourd : l'assemblage tourne dans une
tâche à part (`traitement.py`).

Un envoi depuis l'app se fait en trois temps, comme vers le Mac à l'étape 6 :

1. l'app annonce la liste complète des fichiers de la visite, avec leur taille et leurs
   empreintes (`POST /api/envois`). Le serveur répond, pour chaque fichier qui manque, par une
   adresse de dépôt temporaire dans le stockage privé (`depot.py`) ;
2. l'app dépose les fichiers directement dans le stockage, en arrière-plan, un par un. Après une
   coupure, elle refait le premier temps : seuls les fichiers absents sont redemandés ;
3. l'app demande la fin de l'envoi (`POST /api/envois/<visite>/fin`). Le serveur vérifie qu'il
   ne manque rien, que `visite.json` et les `capture.json` sont valides, met l'assemblage en
   attente et réveille la tâche.

Un point déjà reçu avec une autre prise de vue (photos ou `capture.json` différents) est refusé :
les photos d'origine ne sont jamais écrasées (D9).

Chaque requête de l'API, sauf la connexion, demande une session : jeton dans l'en-tête
`Authorization: Bearer …` pour l'app, cookie pour l'espace web. Un agent ne voit et ne touche que
ses visites : celle d'un autre répond « introuvable », comme une visite qui n'existe pas. Les
requêtes qui modifient quelque chose portent l'en-tête `X-Visite360: 1`, qu'un autre site ne peut
pas ajouter : une page piégée ne peut donc rien faire au nom d'un agent connecté.

`visite360 serveur --local` fait tourner le tout sur le Mac, sans Scaleway : base SQLite et
stockages dans `visites/.serveur/`, codes de connexion affichés dans le Terminal, assemblage dans
le serveur, visites publiées servies à l'adresse `/v/…`. C'est le mode de développement et de
secours ; il n'a qu'une seule visite en assemblage à la fois.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import sys
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

from visite360 import (
    __version__,
    atelier,
    capture,
    carte,
    comptes,
    engagement,
    generation,
    publier,
    reglages,
    serve,
    traitement,
    visite,
)
from visite360.depot import Depot, DepotError, FolderDepot, S3Depot, md5_base64
from visite360.receive import (
    FILE_PATH,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    SHA256,
    VISIT_NAME,
)
from visite360.registre import (
    RUNNING,
    SESSION_LIFETIME,
    Agent,
    Link,
    Registre,
    RegistreError,
    Visit,
    normalize_email,
    open_database,
)
from visite360.serve import JSON, lan_address

FORMAT_VERSION = 1
MD5 = re.compile(r"[0-9a-f]{32}")
MAX_BODY = 16 * 1024
COOKIE = "visite360_session"
GUARD_HEADER = "X-Visite360"
NEUTRAL = (
    "Si cette adresse est autorisée, un code de connexion vient de lui être envoyé. "
    "Il est valable 10 minutes."
)
NOT_FOUND = "Visite introuvable."
BUSY = "L'assemblage de cette visite est en cours : réessayer quand il sera fini."
VISIT_PATH = re.compile(r"/api/visites/([0-9a-f]{32})(?:/(depublier|publier|liens))?")
LINK_PATH = re.compile(r"/api/visites/([0-9a-f]{32})/liens/([0-9a-f]{32})(?:/(effacer))?")
# Étape 16 : page d'un lien client, à l'adresse /l/<jeton>/ (D43).
CLIENT_PATH = re.compile(rf"/l/({engagement.TOKEN})(/.*)")
GONE = "Ce lien ne mène plus à aucune visite. Demander un nouveau lien à votre agent."
FINISH_PATH = re.compile(r"/api/envois/([0-9a-f]{32})/fin")
WORKSHOP_PATH = re.compile(r"/atelier/([0-9a-f]{32})(/.*)")
NOT_READY = "Cette visite n'est pas prête : attendre la fin de l'assemblage."
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}
PAGE_POLICY = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
# La visionneuse a son script et son style dans la page, et affiche des images fabriquées.
WORKSHOP_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; worker-src 'self' blob:; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'none'"
)
SPACE_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/espace.js": ("espace.js", "text/javascript; charset=utf-8"),
    "/espace.css": ("espace.css", "text/css; charset=utf-8"),
}
PUBLIC_TYPES = {**publier.TYPES, ".jpg": "image/jpeg"}


HTML = "text/html; charset=utf-8"


def client_message(text: str) -> bytes:
    """Petite page qui remplace la visite quand un lien de client ne mène plus à rien."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow"><title>Visite 360°</title></head>'
        '<body style="font-family: system-ui, sans-serif; background: #111; color: #eee; '
        "display: flex; min-height: 90vh; align-items: center; justify-content: center; "
        f'padding: 24px; text-align: center"><p>{safe}</p></body></html>'
    ).encode()


class ApiError(Exception):
    """Requête refusée, avec un message en français et le code HTTP à renvoyer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def mask_email(email: str) -> str:
    """Adresse abrégée pour les journaux, qui ne doivent pas garder les adresses en clair."""
    name, _, domain = normalize_email(email).partition("@")
    return f"{name[:1]}***@{domain}"


def space_folder() -> Path:
    """Dossier `espace/` (page web des agents) : dans le paquet installé, sinon dans le dépôt."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "espace", here.parents[1] / "espace"):
        if (candidate / "index.html").is_file():
            return candidate
    raise ApiError("Dossier espace/ introuvable : l'installation est incomplète.", 500)


# --- Liste des fichiers d'un envoi --------------------------------------------------------------


def parse_manifest(raw: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    """Valide la liste des fichiers annoncée par l'app. Renvoie le nom de la visite et, par
    chemin, la taille et les empreintes."""
    if not isinstance(raw, dict):
        raise ApiError("Liste des fichiers mal formée : un objet JSON est attendu.")
    if raw.get("format") != FORMAT_VERSION:
        raise ApiError(
            f"Format d'envoi {raw.get('format')!r} inconnu, le serveur lit le format "
            f"{FORMAT_VERSION}. Mettre l'app à jour."
        )
    name = raw.get("visite")
    if not isinstance(name, str) or not VISIT_NAME.fullmatch(name):
        raise ApiError(f"Nom de visite invalide : {name!r}.")
    entries = raw.get("fichiers")
    if not isinstance(entries, list) or not entries:
        raise ApiError("La liste des fichiers est vide.")
    if len(entries) > MAX_FILES:
        raise ApiError(f"Trop de fichiers dans un seul envoi (plus de {MAX_FILES}).")
    files: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("Liste des fichiers mal formée.")
        path, size = entry.get("chemin"), entry.get("taille")
        sha256, md5 = entry.get("sha256"), entry.get("md5")
        if not isinstance(path, str) or not FILE_PATH.fullmatch(path):
            raise ApiError(f"Fichier refusé : {path!r} n'est pas un fichier de visite.")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
            raise ApiError(f"{path} : taille invalide ({size!r}).")
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise ApiError(f"{path} : empreinte SHA-256 invalide.")
        if not isinstance(md5, str) or not MD5.fullmatch(md5):
            raise ApiError(f"{path} : empreinte MD5 invalide.")
        if path in files:
            raise ApiError(f"{path} est annoncé deux fois.")
        files[path] = {"taille": size, "sha256": sha256, "md5": md5}
    if visite.FILE_NAME not in files:
        raise ApiError(f"L'envoi ne contient pas {visite.FILE_NAME}.")
    return name, files


def _point(path: str) -> str | None:
    match = FILE_PATH.fullmatch(path)
    return match.group("point") if match else None


def needed(
    files: Mapping[str, Mapping[str, Any]], stored: Mapping[str, str], prefix: str
) -> set[str]:
    """Fichiers de l'envoi qui doivent être dans le stockage. Les photos d'un point déjà
    assemblé ne sont plus nécessaires : elles ont peut-être été effacées après 30 jours."""
    assembled = {
        key[len(prefix) :].split("/", 1)[0]
        for key in stored
        if key.endswith(f"/{traitement.PANORAMA}")
    }
    return {path for path in files if not (_point(path) in assembled and "/photos/" in path)}


def check_conflicts(
    files: Mapping[str, Mapping[str, Any]], stored: Mapping[str, str], prefix: str
) -> None:
    """Refuse un point déjà reçu avec une autre prise de vue (D9)."""
    for path, entry in sorted(files.items()):
        if path == visite.FILE_NAME:
            continue
        known = stored.get(prefix + path)
        if known is not None and known != entry["md5"]:
            raise ApiError(
                f"Le point « {_point(path)} » a déjà été reçu avec une autre prise de vue "
                f"({path} est différent). Les photos d'origine ne sont jamais écrasées : "
                "renommer le point dans l'app, puis renvoyer.",
                409,
            )
    points = {_point(path) for path in files} - {None}
    for key in stored:
        path = key[len(prefix) :]
        point = _point(path)
        if point in points and "/photos/" in path and path not in files:
            raise ApiError(
                f"Le point « {point} » a déjà été reçu avec une autre prise de vue (la photo "
                f"{path.rsplit('/', 1)[1]} n'est pas dans l'envoi). Renommer le point dans "
                "l'app, puis renvoyer.",
                409,
            )


# --- Opérations du serveur ----------------------------------------------------------------------


@dataclass
class App:
    """État et opérations du serveur, indépendants du protocole HTTP (testés directement)."""

    registre: Registre
    depot: Depot
    public: publier.Storage
    public_settings: publier.Settings
    mailer: comptes.Mailer
    launcher: traitement.Launcher
    out: TextIO
    secure_cookie: bool = True
    # Serveur local : dossier des visites publiées, servi à l'adresse /v/.
    local_public: FolderDepot | None = None
    # Attente maximale de l'envoi d'un code avant de répondre à l'agent, en secondes.
    mail_wait: float = 4.0
    # Carte graphique louée (étape 14) : None si elle n'est pas configurée.
    gpu: carte.Carte | None = None
    # Outils de modification en ligne (étape 15) : None si le serveur n'en propose pas.
    ateliers: atelier.Ateliers | None = None

    # Atelier : outils de modification d'une visite, pour l'agent connecté

    def workshop(self, agent: Agent, visit_id: str) -> atelier.Atelier:
        visit = self._own(agent, visit_id)
        if self.ateliers is None:
            raise ApiError("Les outils de modification ne sont pas disponibles ici.", 503)
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        if visit.ready is None:
            raise ApiError(NOT_READY, 409)
        return self.ateliers.get(
            visit,
            lambda: self.registre.grid(agent.id),
            lambda content: self.registre.set_grid(agent.id, content),
        )

    def workshop_get(self, agent: Agent, visit_id: str, rest: str) -> tuple[bytes, str, bool]:
        """Contenu d'une route GET de l'atelier. Le dernier élément dit si c'est la page."""
        found = self.workshop(agent, visit_id)
        if rest == "/":
            return found.page(), "text/html; charset=utf-8", True
        content = found.get(rest)
        if content is None:
            raise ApiError("Introuvable.", 404)
        return content[0], content[1], False

    def workshop_post(self, agent: Agent, visit_id: str, rest: str, body: Any) -> tuple[bytes, str]:
        if not isinstance(body, dict):
            raise ApiError("Requête illisible : objet JSON attendu.")
        content = self.workshop(agent, visit_id).post(rest, body)
        if content is None:
            raise ApiError("Introuvable.", 404)
        return content

    # Liens des clients (étape 16, D43)

    def _names(self, visit: Visit) -> dict[str, str]:
        """Nom de chaque point de la visite, par identifiant."""
        try:
            described = json.loads(self.depot.get(f"{visit.id}/{visite.FILE_NAME}"))
            return {
                str(point["id"]): str(point.get("nom", point["id"]))
                for point in described["points"]
            }
        except (DepotError, ValueError, KeyError, TypeError):
            return {}

    def _own_link(self, agent: Agent, visit_id: str, link_id: str) -> tuple[Visit, Link]:
        visit = self._own(agent, visit_id)
        link = self.registre.link(link_id)
        if link is None or link.visit_id != visit.id:
            raise ApiError("Lien introuvable.", 404)
        return visit, link

    def links(self, agent: Agent, visit_id: str) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        names = self._names(visit)
        return {
            "liens": [
                engagement.summary(self.registre, link, names)
                for link in self.registre.links(visit.id)
            ]
        }

    def create_link(self, agent: Agent, visit_id: str, raw: Any) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        label = self._checked(lambda: engagement.parse_label(raw))
        if len(self.registre.links(visit.id)) >= engagement.MAX_LINKS:
            raise ApiError(f"Au plus {engagement.MAX_LINKS} liens par visite.", 409)
        link = self.registre.create_link(visit.id, label)
        print(f"Lien « {label} » créé pour « {visit.name} ».", file=self.out, flush=True)
        return engagement.summary(self.registre, link, self._names(visit))

    def link_detail(self, agent: Agent, visit_id: str, link_id: str) -> dict[str, Any]:
        visit, link = self._own_link(agent, visit_id, link_id)
        return engagement.detail(self.registre, self.depot, link, self._names(visit))

    def delete_link(self, agent: Agent, visit_id: str, link_id: str) -> dict[str, Any]:
        visit, link = self._own_link(agent, visit_id, link_id)
        if self.ateliers is not None:
            self.ateliers.drop_key(f"lien:{link.id}", save=False)
        engagement.clear_changes(self.depot, visit.id, link.id)
        self.registre.delete_link(link.id)
        return {"message": f"Lien « {link.label} » supprimé. Les autres liens ne changent pas."}

    def clear_link(self, agent: Agent, visit_id: str, link_id: str) -> dict[str, Any]:
        visit, link = self._own_link(agent, visit_id, link_id)
        if self.ateliers is not None:
            self.ateliers.drop_key(f"lien:{link.id}", save=False)
        count = engagement.clear_changes(self.depot, visit.id, link.id)
        message = "Modifications du client effacées." if count else "Aucune modification à effacer."
        return {"message": message}

    @staticmethod
    def _checked(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except engagement.EngagementError as error:
            raise ApiError(str(error), error.status) from None

    def _client(self, token: str) -> tuple[Visit, Link]:
        """Visite et lien d'un jeton, si la visite est prête et en ligne."""
        link = self.registre.link_by_token(token)
        visit = self.registre.visit(link.visit_id) if link is not None else None
        if link is None or visit is None or visit.ready is None or not visit.publication:
            raise ApiError(GONE, 404)
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        return visit, link

    def client_workshop(self, token: str) -> engagement.ClientAtelier:
        visit, link = self._client(token)
        if self.ateliers is None:
            raise ApiError("Les outils de modification ne sont pas disponibles ici.", 503)
        publication = visit.publication
        assert publication is not None

        def published(rel: str) -> bytes:
            try:
                return self.public.get(f"{publication}/{rel}")
            except publier.PublishError as error:
                raise DepotError(str(error)) from None

        found = self.ateliers.open_with(
            f"lien:{link.id}",
            lambda root: engagement.ClientAtelier(
                visit,
                link,
                self.depot,
                published,
                root,
                self.ateliers.make_tools,  # type: ignore[union-attr]
                lambda: self.registre.grid(visit.agent_id),
            ),
        )
        assert isinstance(found, engagement.ClientAtelier)
        return found

    def client_get(self, token: str, rest: str) -> tuple[bytes, str, bool]:
        found = self.client_workshop(token)
        if rest == "/":
            self.registre.touch_link(found.link.id)
            return found.page(), "text/html; charset=utf-8", True
        content = found.get(rest)
        if content is None:
            raise ApiError("Introuvable.", 404)
        return content[0], content[1], False

    def client_post(self, token: str, rest: str, body: Any) -> tuple[bytes, str]:
        if not isinstance(body, dict):
            raise ApiError("Requête illisible : objet JSON attendu.")
        if rest == "/api/mesure":
            return self.measure(token, body)
        found = self.client_workshop(token)
        if rest not in engagement.CLIENT_POSTS:
            raise ApiError("Introuvable.", 404)
        today = engagement.day(self.registre.now())
        generating = rest in engagement.GENERATING
        if generating:
            used = self.registre.generations_today(found.link.id, today)
            if used >= engagement.MAX_GENERATIONS:
                raise ApiError(
                    f"Limite atteinte : {engagement.MAX_GENERATIONS} remplacements d'objets par "
                    "jour avec ce lien. Réessayer demain, ou demander à votre agent.",
                    429,
                )
        content = found.post(rest, body)
        if content is None:
            raise ApiError("Introuvable.", 404)
        if generating:
            self.registre.add_generation(found.link.id, today)
        return content

    def measure(self, token: str, body: Any) -> tuple[bytes, str]:
        """Range une mesure de consultation envoyée par la page, après accord du client."""
        visit, link = self._client(token)
        points = set(self._names(visit))
        measure = self._checked(lambda: engagement.parse_measure(body, points))
        self._checked(lambda: engagement.record(self.registre, link, measure))
        return b'{"ok": true}', JSON

    # Génération sur la carte graphique

    def generate_view(self, raw: Any) -> dict[str, Any]:
        """Relais d'une demande de génération vers la carte (étape 14, D41).

        La vue traverse le serveur sans y être rangée ni journalisée.
        """
        if self.gpu is None:
            raise ApiError("La carte graphique n'est pas configurée sur ce serveur.", 503)
        if not isinstance(raw, dict) or not isinstance(raw.get("image"), str):
            raise ApiError("Demande incomplète (image, consigne et graine).")
        consigne, graine = raw.get("consigne"), raw.get("graine")
        if not isinstance(consigne, str) or not consigne.strip() or len(consigne) > 2000:
            raise ApiError("Consigne absente ou trop longue.")
        if not isinstance(graine, int) or isinstance(graine, bool):
            raise ApiError("Graine invalide.")
        try:
            return self.gpu.forward({"image": raw["image"], "consigne": consigne, "graine": graine})
        except carte.CarteError as error:
            raise ApiError(str(error), 503) from error

    # Connexion

    def request_code(self, raw: Any) -> dict[str, Any]:
        email = raw.get("email") if isinstance(raw, dict) else None
        if not isinstance(email, str) or "@" not in email or len(email) > 254:
            raise ApiError("Adresse e-mail invalide.")
        who = mask_email(email)
        code, reason = self.registre.issue_code(email)
        if code is None:
            # Le message reste le même pour l'agent : le dire révélerait qui est autorisé.
            print(f"Code : pas de code tiré pour {who} ({reason}).", file=self.out, flush=True)
            return {"message": NEUTRAL}
        # L'envoi tourne à part et la réponse n'attend qu'un court instant : un serveur
        # d'e-mails lent ne doit pas faire échouer l'app (délai de 60 s) ni laisser deviner, par
        # la durée de la réponse, quelles adresses sont autorisées.
        to = normalize_email(email)
        done = threading.Event()
        threading.Thread(target=self._deliver, args=(to, code, who, done), daemon=True).start()
        done.wait(self.mail_wait)
        return {"message": NEUTRAL}

    def _deliver(self, to: str, code: str, who: str, done: threading.Event) -> None:
        started = time.monotonic()
        try:
            self.mailer.send(to, comptes.SUBJECT, comptes.code_text(code))
        except comptes.MailError as error:
            print(f"Code non envoyé à {who} : {error}", file=self.out, flush=True)
        except Exception as error:  # le fil ne doit jamais mourir sans laisser de trace
            print(
                f"Code non envoyé à {who} : erreur inattendue ({error!r}).",
                file=self.out,
                flush=True,
            )
        else:
            elapsed = time.monotonic() - started
            print(f"Code envoyé à {who} en {elapsed:.1f} s.", file=self.out, flush=True)
        finally:
            done.set()

    def login(self, raw: Any) -> tuple[dict[str, Any], str]:
        email = raw.get("email") if isinstance(raw, dict) else None
        code = raw.get("code") if isinstance(raw, dict) else None
        if not isinstance(email, str) or not isinstance(code, str):
            raise ApiError("Adresse et code attendus.")
        agent = self.registre.check_code(email, code)
        if agent is None:
            raise ApiError(
                "Code faux ou expiré. Recopier le dernier code reçu, ou en demander un autre.",
                403,
            )
        token = self.registre.open_session(agent)
        return {"jeton": token, "email": agent.email}, token

    # Visites

    def _own(self, agent: Agent, visit_id: str) -> Visit:
        visit = self.registre.visit(visit_id)
        if visit is None or visit.agent_id != agent.id:
            raise ApiError(NOT_FOUND, 404)
        return visit

    def _busy(self, visit: Visit) -> bool:
        job = self.registre.last_job(visit.id)
        return job is not None and job.state == RUNNING

    def state(self, visit: Visit) -> dict[str, Any]:
        return traitement.visit_state(visit, self.registre.last_job(visit.id))

    def visits(self, agent: Agent) -> dict[str, Any]:
        return {"visites": [self.state(visit) for visit in self.registre.visits(agent.id)]}

    def start_upload(self, agent: Agent, raw: Any) -> dict[str, Any]:
        name, files = parse_manifest(raw)
        existing = self.registre.visit_by_name(agent.id, name)
        stored: dict[str, str] = {}
        if existing is not None:
            if self._busy(existing):
                raise ApiError(BUSY, 409)
            stored = self.depot.list(f"{existing.id}/")
            check_conflicts(files, stored, f"{existing.id}/")
        visit = self.registre.save_upload(agent.id, name, {"fichiers": files})
        prefix = f"{visit.id}/"
        wanted = needed(files, stored, prefix)
        uploads = [
            {
                "chemin": path,
                "adresse": self.depot.upload_url(prefix + path, files[path]["md5"]),
                "en_tetes": {"Content-MD5": md5_base64(files[path]["md5"])},
            }
            for path in sorted(wanted)
            if stored.get(prefix + path) != files[path]["md5"]
        ]
        print(
            f"Envoi de « {name} » par {agent.email} : {len(uploads)} fichier(s) à recevoir, "
            f"{len(files) - len(uploads)} déjà là.",
            file=self.out,
            flush=True,
        )
        return {"visite": visit.id, "depots": uploads, "deja": len(files) - len(uploads)}

    def finish_upload(self, agent: Agent, visit_id: str) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        files: dict[str, dict[str, Any]] = visit.manifest["fichiers"]
        prefix = f"{visit.id}/"
        stored = self.depot.list(prefix)
        missing = sorted(
            path
            for path in needed(files, stored, prefix)
            if stored.get(prefix + path) != files[path]["md5"]
        )
        if missing:
            raise ApiError(
                f"Envoi incomplet : {len(missing)} fichier(s) manquant(s), dont {missing[0]}. "
                "Reprendre l'envoi : seuls les fichiers manquants partiront.",
                409,
            )
        self._validate(visit, files)
        self.registre.finish_upload(visit.id)
        self.registre.queue(visit.id)
        message = self._wake()
        print(f"Envoi de « {visit.name} » complet, assemblage en attente.", file=self.out)
        result = self.state(self.registre.visit(visit.id) or visit)
        if message:
            result["message"] = message
        return result

    def _validate(self, visit: Visit, files: Mapping[str, Any]) -> None:
        """Relit `visite.json` et les `capture.json` déposés, comme le ferait l'assemblage."""
        with tempfile.TemporaryDirectory(prefix="visite360-") as temp:
            folder = Path(temp) / visit.name
            folder.mkdir()
            for path in files:
                point = _point(path)
                if point:
                    (folder / point).mkdir(exist_ok=True)
                if path == visite.FILE_NAME or path.endswith(f"/{capture.FILE_NAME}"):
                    target = folder / path
                    target.write_bytes(self.depot.get(f"{visit.id}/{path}"))
            try:
                tour = visite.load(folder)
                for point in tour.points:
                    found = capture.find(point.folders.point)
                    if found:
                        capture.load(found)
            except (visite.VisiteError, capture.CaptureError) as error:
                raise ApiError(
                    f"Visite refusée : {str(error).replace(str(folder) + '/', '')}", 422
                ) from None

    def _wake(self) -> str | None:
        try:
            self.launcher.wake()
        except traitement.LaunchError as error:
            print(f"Lancement de l'assemblage impossible : {error}", file=self.out, flush=True)
            return (
                "Envoi complet. L'assemblage n'a pas pu démarrer tout de suite : il partira au "
                "prochain passage, au plus tard dans la journée."
            )
        return None

    def unpublish(self, agent: Agent, visit_id: str) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        if visit.publication:
            publier.remove_published(self.public, visit.publication)
            self.registre.set_published(visit.id, None, None)
        return self.state(self.registre.visit(visit.id) or visit)

    def republish(self, agent: Agent, visit_id: str) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        if visit.upload_done is None:
            raise ApiError("L'envoi de cette visite n'est pas terminé : le reprendre dans l'app.")
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        self.registre.queue(visit.id)
        message = self._wake()
        result = self.state(visit)
        if message:
            result["message"] = message
        return result

    def delete(self, agent: Agent, visit_id: str) -> dict[str, Any]:
        visit = self._own(agent, visit_id)
        if self._busy(visit):
            raise ApiError(BUSY, 409)
        if self.ateliers is not None:
            self.ateliers.drop(visit.id, save=False)
        if visit.publication:
            publier.remove_published(self.public, visit.publication)
        for key in sorted(self.depot.list(f"{visit.id}/")):
            self.depot.delete(key)
        self.registre.delete_visit(visit.id)
        print(f"Visite « {visit.name} » de {agent.email} supprimée.", file=self.out, flush=True)
        return {"message": f"Visite « {visit.name} » supprimée, en ligne comme sur le serveur."}


# --- HTTP ---------------------------------------------------------------------------------------


def make_server(app: App, host: str, port: int) -> ThreadingHTTPServer:
    """Prépare le serveur, sans le lancer."""
    space = space_folder()

    class Handler(BaseHTTPRequestHandler):
        server_version = "visite360"
        sys_version = ""

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            client = CLIENT_PATH.fullmatch(path)
            if client:
                self._workshop(lambda: app.client_get(*client.groups()))
                return
            workshop = WORKSHOP_PATH.fullmatch(path)
            if workshop:
                self._workshop(lambda: self._workshop_get(*workshop.groups()))
                return
            if path in SPACE_FILES:
                name, kind = SPACE_FILES[path]
                self._send(200, (space / name).read_bytes(), kind, page=True)
                return
            if path.startswith("/v/") and app.local_public is not None:
                self._public_file(path[len("/v/") :])
                return
            self._api(lambda: self._get(path))

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            client = CLIENT_PATH.fullmatch(path)
            if client:
                token, rest = client.groups()
                limit = engagement.MAX_BODY if rest == "/api/mesure" else serve.MAX_BODY
                self._workshop(
                    lambda: (*app.client_post(token, rest, self._body(limit)), False),
                    write=True,
                )
                return
            workshop = WORKSHOP_PATH.fullmatch(path)
            if workshop:
                visit_id, rest = workshop.groups()
                self._workshop(
                    lambda: (
                        *app.workshop_post(
                            self._agent(), visit_id, rest, self._body(serve.MAX_BODY)
                        ),
                        False,
                    ),
                    write=True,
                )
                return
            self._api(lambda: self._post(path), write=True)

        def do_DELETE(self) -> None:
            path = self.path.split("?", 1)[0]
            self._api(lambda: self._delete(path), write=True)

        def do_PUT(self) -> None:
            path, _, query = self.path.partition("?")
            if not (path.startswith("/depot/") and isinstance(app.depot, FolderDepot)):
                self._json(404, {"message": "Introuvable."})
                return
            try:
                length = self._length(MAX_FILE_BYTES)
                data = self.rfile.read(length)
                key = urllib.parse.unquote(path[len("/depot/") :])
                params = dict(urllib.parse.parse_qsl(query))
                app.depot.accept_upload(key, params, self.headers.get("Content-MD5", ""), data)
            except (ApiError, DepotError) as error:
                self.close_connection = True
                self._json(getattr(error, "status", 403), {"message": str(error)})
                return
            self._json(200, {"ok": True})

        # Routes de l'API

        def _get(self, path: str) -> dict[str, Any]:
            if path == "/api/info":
                return {
                    "app": "visite360",
                    "version": __version__,
                    "format": FORMAT_VERSION,
                    # Commit du code de l'image (étape 13 bis) : le déploiement vérifie qu'il
                    # est bien celui qu'il vient de publier.
                    "commit": os.environ.get("VISITE360_COMMIT", "inconnu"),
                }
            agent = self._agent()
            if path == "/api/moi":
                return {"email": agent.email}
            if path == "/api/visites":
                return app.visits(agent)
            match = VISIT_PATH.fullmatch(path)
            if match and not match.group(2):
                return app.state(app._own(agent, match.group(1)))
            if match and match.group(2) == "liens":
                return app.links(agent, match.group(1))
            match = LINK_PATH.fullmatch(path)
            if match and not match.group(3):
                return app.link_detail(agent, match.group(1), match.group(2))
            raise ApiError("Introuvable.", 404)

        def _post(self, path: str) -> dict[str, Any]:
            if path == "/api/connexion/code":
                return app.request_code(self._body(MAX_BODY))
            if path == "/api/connexion":
                result, token = app.login(self._body(MAX_BODY))
                self.extra_headers.append(("Set-Cookie", self._cookie(token, SESSION_LIFETIME)))
                return result
            if path == "/api/deconnexion":
                token = self._token()
                if token:
                    app.registre.close_session(token)
                self.extra_headers.append(("Set-Cookie", self._cookie("", 0)))
                return {"message": "Déconnecté."}
            agent = self._agent()
            if path == "/api/carte/generer":
                return app.generate_view(self._body(carte.MAX_BODY))
            if path == "/api/envois":
                return app.start_upload(agent, self._body(MAX_MANIFEST_BYTES))
            match = FINISH_PATH.fullmatch(path)
            if match:
                return app.finish_upload(agent, match.group(1))
            match = VISIT_PATH.fullmatch(path)
            if match and match.group(2) == "depublier":
                return app.unpublish(agent, match.group(1))
            if match and match.group(2) == "publier":
                return app.republish(agent, match.group(1))
            if match and match.group(2) == "liens":
                return app.create_link(agent, match.group(1), self._body(MAX_BODY))
            match = LINK_PATH.fullmatch(path)
            if match and match.group(3) == "effacer":
                return app.clear_link(agent, match.group(1), match.group(2))
            raise ApiError("Introuvable.", 404)

        def _delete(self, path: str) -> dict[str, Any]:
            agent = self._agent()
            match = VISIT_PATH.fullmatch(path)
            if match and not match.group(2):
                return app.delete(agent, match.group(1))
            match = LINK_PATH.fullmatch(path)
            if match and not match.group(3):
                return app.delete_link(agent, match.group(1), match.group(2))
            raise ApiError("Introuvable.", 404)

        # Atelier

        def _workshop_get(self, visit_id: str, rest: str) -> tuple[bytes, str, bool]:
            return app.workshop_get(self._agent(), visit_id, rest)

        def _workshop(
            self, action: Callable[[], tuple[bytes, str, bool]], write: bool = False
        ) -> None:
            """Répond à une route de l'atelier. Les erreurs ont la forme que lit la visionneuse :
            `{"erreur": message}`."""
            self.extra_headers = []
            try:
                if write and self.headers.get(GUARD_HEADER) != "1":
                    raise ApiError(f"En-tête {GUARD_HEADER} manquant.", 403)
                data, kind, is_page = action()
            except ApiError as error:
                if error.status == 401 and self.command == "GET" and self.path.endswith("/"):
                    # Page ouverte sans session : retour à l'espace, qui demande la connexion.
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.close_connection = True
                path = self.path.split("?", 1)[0]
                if self.command == "GET" and CLIENT_PATH.fullmatch(path) and path.endswith("/"):
                    # Lien de client supprimé ou visite retirée : une page lisible, pas du JSON.
                    self._send(error.status, client_message(str(error)), HTML, page=True)
                    return
                self._json(error.status, {"erreur": str(error)})
            except (atelier.AtelierError, DepotError, RegistreError) as error:
                print(f"Erreur : {error}", file=app.out, flush=True)
                self._json(503, {"erreur": f"Erreur du serveur : {error}"})
            except Exception as error:  # la visionneuse attend toujours une réponse lisible
                status, message = serve.tool_error(error)
                self._json(status, {"erreur": message})
            else:
                self._send(200, data, kind, page=is_page, policy=WORKSHOP_POLICY)

        # Outils

        def _token(self) -> str | None:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return header[len("Bearer ") :].strip() or None
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return None
            morsel = cookie.get(COOKIE)
            return morsel.value if morsel is not None and morsel.value else None

        def _agent(self) -> Agent:
            token = self._token()
            agent = app.registre.session_agent(token) if token else None
            if agent is None:
                raise ApiError("Connexion nécessaire : se connecter avec son adresse e-mail.", 401)
            return agent

        def _cookie(self, value: str, max_age: int) -> str:
            secure = "; Secure" if app.secure_cookie else ""
            return f"{COOKIE}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Strict{secure}"

        def _length(self, limit: int) -> int:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise ApiError("Taille de la requête absente.", 411) from None
            if length > limit:
                raise ApiError("Requête trop grosse.", 413)
            return length

        def _body(self, limit: int) -> Any:
            data = self.rfile.read(self._length(limit))
            try:
                return json.loads(data or b"{}")
            except ValueError:
                raise ApiError("Requête illisible (JSON invalide).") from None

        def _api(self, action: Callable[[], dict[str, Any]], write: bool = False) -> None:
            self.extra_headers: list[tuple[str, str]] = []
            try:
                if write and self.headers.get(GUARD_HEADER) != "1":
                    raise ApiError(f"En-tête {GUARD_HEADER} manquant.", 403)
                body, status = action(), 200
            except ApiError as error:
                body, status = {"message": str(error)}, error.status
                self.close_connection = True
            except (RegistreError, DepotError, publier.PublishError) as error:
                print(f"Erreur : {error}", file=app.out, flush=True)
                body, status = {"message": f"Erreur du serveur : {error}"}, 503
            self._json(status, body)

        def _json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._send(status, data, JSON)

        def _send(
            self, status: int, data: bytes, kind: str, page: bool = False, policy: str = PAGE_POLICY
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache" if page else "no-store")
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            if page:
                self.send_header("Content-Security-Policy", policy)
            for name, value in getattr(self, "extra_headers", []):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def _public_file(self, key: str) -> None:
            assert app.local_public is not None
            try:
                data = app.local_public.get(urllib.parse.unquote(key))
            except DepotError:
                self._json(404, {"message": "Introuvable."})
                return
            kind = PUBLIC_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    try:
        return ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        raise ApiError(
            f"Impossible d'ouvrir le port {port} ({error.strerror}). Un autre programme "
            "l'utilise peut-être : essayer --port avec un autre numéro."
        ) from None


# --- Assemblage de l'App selon l'environnement ------------------------------------------------


def describe_mailer(mailer: comptes.Mailer) -> str:
    """Réglage d'envoi des e-mails pour les journaux, sans le mot de passe."""
    if isinstance(mailer, comptes.SMTPMailer):
        return (
            f"E-mails : {mailer.host}:{mailer.port}, utilisateur {mailer.user[:8]}…, "
            f"expéditeur {mailer.sender}."
        )
    return "E-mails : affichés dans les journaux (mode local)."


NO_GPU = "Le remplacement d'objet n'est pas configuré sur ce serveur (carte graphique absente)."


def _no_generator() -> generation.Generator:
    raise generation.GenerationError(NO_GPU)


def online_tools(gpu: carte.Carte | None) -> atelier.ToolsFactory:
    """Outils de l'atelier en ligne : SAM 2.1 sur le processeur du serveur, génération sur la
    carte graphique du projet (D41, D42)."""
    if gpu is None:
        return lambda tour: serve.tools_for(tour, _no_generator, NO_GPU)
    return lambda tour: serve.tools_for(tour, lambda: carte.CarteGenerator(gpu))


def online_app(settings: reglages.Settings, environ: Mapping[str, str], out: TextIO) -> App:
    """Serveur en ligne, chez Scaleway."""
    assert settings.depot is not None and settings.public is not None and settings.job
    registre = Registre(open_database(settings.database))
    registre.create_schema()
    mailer = comptes.mailer_from_env(environ)
    if mailer is None:
        raise reglages.SettingsError(
            "Réglages d'envoi des e-mails manquants (VISITE360_SMTP_HOTE, "
            "VISITE360_SMTP_UTILISATEUR, VISITE360_SMTP_MOT_DE_PASSE). Voir docs/serveur.md."
        )
    print(
        f"Base : {comptes.describe_database(settings.database)}. "
        f"Stockage privé : {settings.depot.bucket}. Visites publiées : {settings.public.bucket}.",
        file=out,
        flush=True,
    )
    print(describe_mailer(mailer), file=out, flush=True)
    gpu = None
    try:
        gpu_settings = carte.from_env(environ)
    except carte.CarteError as error:
        raise reglages.SettingsError(str(error)) from error
    if gpu_settings is None:
        print("Carte graphique : non configurée (génération sur le Mac).", file=out, flush=True)
    else:
        gpu = carte.Carte(gpu_settings, carte.ScalewayProvider(gpu_settings), registre)
        print(
            f"Carte graphique : {gpu_settings.commercial_type} en {gpu_settings.zone}, "
            f"plafond {gpu_settings.cap_eur:.2f} € par mois.",
            file=out,
            flush=True,
        )
    depot = S3Depot(settings.depot)
    return App(
        registre,
        depot,
        publier.S3Storage(settings.public),
        settings.public,
        mailer,
        traitement.ScalewayLauncher(settings.depot.secret_key, settings.depot.region, settings.job),
        out,
        gpu=gpu,
        ateliers=atelier.Ateliers(depot, online_tools(gpu)),
    )


def local_app(settings: reglages.Settings, out: TextIO) -> App:
    """Serveur sur le Mac : tout dans des dossiers, assemblage dans un fil du serveur."""
    root = settings.local_root
    assert root is not None
    registre = Registre(open_database(settings.database))
    registre.create_schema()
    depot = FolderDepot(root / "depot", settings.address, secrets.token_bytes(32))
    public = FolderDepot(root / "publiees")
    public_settings = publier.Settings("local", "local", "local", address=f"{settings.address}/v")
    context = traitement.Context(registre, depot, public, public_settings, out)
    launcher = traitement.ThreadLauncher(lambda: traitement.process_all(context))
    return App(
        registre,
        depot,
        public,
        public_settings,
        comptes.ConsoleMailer(out),
        launcher,
        out,
        secure_cookie=False,
        local_public=public,
        ateliers=atelier.Ateliers(depot, serve.default_tools),
    )


def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def run(
    local: bool = False,
    folder: Path = reglages.LOCAL_FOLDER,
    port: int | None = None,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 serveur`. Renvoie le code de sortie."""
    import os

    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        if local:
            actual = port or reglages.DEFAULT_PORT
            host = lan_address() or "127.0.0.1"
            settings = reglages.local_settings(folder, f"http://{host}:{actual}", actual)
            app = local_app(settings, out)
        else:
            settings = reglages.from_env(environ)
            app = online_app(settings, environ, out)
        server = make_server(app, "0.0.0.0", port or settings.port)
    except (reglages.SettingsError, RegistreError, comptes.MailError, ApiError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    print(f"Serveur visite360 {__version__} : {settings.address}", file=out, flush=True)
    if local:
        print(
            f"Mode local, données dans {folder.resolve()}. Autoriser un agent : "
            f"visite360 compte ajouter <e-mail> --local",
            file=out,
        )
        print("Les codes de connexion s'affichent ici.", file=out)
    print("Ctrl+C pour arrêter.", file=out, flush=True)
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, _interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.", file=out)
    finally:
        server.server_close()
    return 0
