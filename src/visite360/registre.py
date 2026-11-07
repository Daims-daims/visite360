"""Étape 13 : registre du serveur, dans une base de données (D39).

Le registre garde la liste des agents autorisés, les codes de connexion envoyés par e-mail, les
sessions ouvertes, les visites envoyées par l'app et leurs traitements (assemblage, puis à
l'étape 14 génération d'image).

Deux bases parlent les mêmes requêtes :

- en ligne, la base PostgreSQL de Scaleway (Serverless SQL), par la bibliothèque pg8000,
  installée seulement sur le serveur ;
- sur le Mac et dans les tests, un fichier SQLite, fourni avec Python.

Pour rester commun aux deux, le SQL n'utilise que des types simples (texte et entiers), des
paramètres nommés (`:nom`) et des dates en secondes depuis 1970, en temps universel. Chaque
requête est validée tout de suite (pas de transaction longue) : les opérations qui doivent être
atomiques tiennent en une seule requête, par exemple la prise d'un traitement en attente.

Les codes de connexion et les sessions ne sont jamais rangés en clair : seulement leur empreinte
SHA-256. Une copie volée de la base ne permet donc pas de se connecter.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# Durées, en secondes.
CODE_LIFETIME = 10 * 60
CODE_INTERVAL = 60
CODE_ATTEMPTS = 5
# Au plus cinq codes par heure et par adresse : avec cinq essais chacun, deviner un code à six
# chiffres prendrait des années.
CODES_PER_HOUR = 5
HOUR = 3600
SESSION_LIFETIME = 90 * 24 * 3600
# Un traitement « en cours » depuis plus longtemps a perdu sa tâche (limite des Serverless Jobs :
# 24 h) : il est repris.
STALE_AFTER = 24 * 3600 + 600
MAX_ATTEMPTS = 3
PHOTOS_KEPT = 30 * 24 * 3600
# Étape 16 (D43) : mesures de consultation et modifications des clients gardées 12 mois après la
# dernière ouverture.
MEASURES_KEPT = 365 * 24 * 3600

# États d'un traitement.
WAITING = "en_attente"
RUNNING = "en_cours"
DONE = "fini"
FAILED = "echec"
ASSEMBLY = "assemblage"

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        cree_le BIGINT NOT NULL,
        retire_le BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS codes (
        email TEXT PRIMARY KEY,
        empreinte TEXT NOT NULL,
        cree_le BIGINT NOT NULL,
        expire_le BIGINT NOT NULL,
        essais BIGINT NOT NULL,
        envois BIGINT NOT NULL,
        fenetre_le BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        empreinte TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        cree_le BIGINT NOT NULL,
        expire_le BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS visites (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        nom TEXT NOT NULL,
        manifeste TEXT NOT NULL,
        cree_le BIGINT NOT NULL,
        envoi_fini_le BIGINT,
        prete_le BIGINT,
        photos_effacees_le BIGINT,
        publication TEXT,
        lien TEXT,
        UNIQUE (agent_id, nom)
    )""",
    """CREATE TABLE IF NOT EXISTS traitements (
        id TEXT PRIMARY KEY,
        visite_id TEXT NOT NULL,
        type TEXT NOT NULL,
        etat TEXT NOT NULL,
        message TEXT NOT NULL,
        essais BIGINT NOT NULL,
        cree_le BIGINT NOT NULL,
        debut_le BIGINT,
        fin_le BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS carte_usage (
        mois TEXT PRIMARY KEY,
        secondes BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS grilles (
        agent_id TEXT PRIMARY KEY,
        contenu TEXT NOT NULL
    )""",
    # Étape 16 (D43) : un lien par client, ses consultations et le temps passé dans chaque pièce.
    # Le jeton est en clair, comme l'identifiant d'une visite publiée : l'agent doit pouvoir
    # recopier le lien. `ouvert_le` ne sert qu'à l'effacement après 12 mois, il n'est pas montré.
    """CREATE TABLE IF NOT EXISTS liens (
        id TEXT PRIMARY KEY,
        visite_id TEXT NOT NULL,
        jeton TEXT NOT NULL UNIQUE,
        libelle TEXT NOT NULL,
        cree_le BIGINT NOT NULL,
        ouvert_le BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS consultations (
        id TEXT PRIMARY KEY,
        lien_id TEXT NOT NULL,
        debut_le BIGINT NOT NULL,
        vue_le BIGINT NOT NULL,
        secondes BIGINT NOT NULL,
        chiffrage BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS consultation_pieces (
        consultation_id TEXT NOT NULL,
        point TEXT NOT NULL,
        secondes BIGINT NOT NULL,
        bascules BIGINT NOT NULL,
        PRIMARY KEY (consultation_id, point)
    )""",
    """CREATE TABLE IF NOT EXISTS lien_generations (
        lien_id TEXT NOT NULL,
        jour TEXT NOT NULL,
        nombre BIGINT NOT NULL,
        PRIMARY KEY (lien_id, jour)
    )""",
    "CREATE INDEX IF NOT EXISTS liens_visite ON liens (visite_id, cree_le)",
    "CREATE INDEX IF NOT EXISTS consultations_lien ON consultations (lien_id, debut_le)",
    "CREATE INDEX IF NOT EXISTS traitements_visite ON traitements (visite_id, cree_le)",
    "CREATE INDEX IF NOT EXISTS traitements_etat ON traitements (etat, cree_le)",
)


class RegistreError(Exception):
    """La base est injoignable, mal réglée, ou refuse une opération. Message en français."""


def digest(secret: str) -> str:
    """Empreinte rangée à la place d'un code ou d'une session."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_id() -> str:
    return secrets.token_hex(16)


class Database(Protocol):
    """Ce que le registre demande à une base : exécuter une requête, rendre les lignes et le
    nombre de lignes modifiées."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> tuple[list[tuple[Any, ...]], int]: ...


class SQLiteDatabase:
    """Base SQLite, sur le Mac et dans les tests. Partagée entre les fils du serveur."""

    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None : chaque requête est validée tout de suite, comme avec pg8000.
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()

    def execute(self, sql: str, params: Mapping[str, Any]) -> tuple[list[tuple[Any, ...]], int]:
        with self.lock:
            try:
                cursor = self.connection.execute(sql, dict(params))
                return cursor.fetchall(), cursor.rowcount
            except sqlite3.Error as error:
                raise RegistreError(f"Erreur de la base SQLite : {error}") from error


class PostgresDatabase:
    """Base PostgreSQL de Scaleway, par pg8000 (paramètres `:nom` de son interface « native »).

    La base Serverless SQL se met en veille et coupe les connexions inactives : une requête qui
    trouve la connexion fermée la rouvre et recommence une fois.
    """

    def __init__(self, url: str) -> None:
        try:
            import pg8000.native  # noqa: F401 (vérifie seulement la présence)
        except ImportError:
            raise RegistreError(
                "La bibliothèque pg8000 manque pour parler à la base PostgreSQL. L'installer : "
                'pip install -e ".[serveur]"'
            ) from None
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("postgres", "postgresql") or not parts.hostname:
            raise RegistreError("Adresse de la base PostgreSQL invalide (postgresql://…).")
        self.options = {
            "user": urllib.parse.unquote(parts.username or ""),
            "password": urllib.parse.unquote(parts.password or ""),
            "host": parts.hostname,
            "port": parts.port or 5432,
            "database": urllib.parse.unquote(parts.path.lstrip("/")) or None,
        }
        self.connection: Any = None
        self.lock = threading.Lock()

    def _connect(self) -> Any:
        import ssl

        import pg8000.native

        try:
            return pg8000.native.Connection(
                ssl_context=ssl.create_default_context(), timeout=60, **self.options
            )
        except (pg8000.native.InterfaceError, pg8000.native.DatabaseError, OSError) as error:
            raise RegistreError(
                f"La base de données est injoignable ({error}). Vérifier son adresse et sa clé "
                "dans les réglages du serveur (docs/serveur.md)."
            ) from None

    def execute(self, sql: str, params: Mapping[str, Any]) -> tuple[list[tuple[Any, ...]], int]:
        import pg8000.native

        with self.lock:
            for attempt in (1, 2):
                if self.connection is None:
                    self.connection = self._connect()
                try:
                    rows = self.connection.run(sql, **params) or []
                    return [tuple(row) for row in rows], self.connection.row_count
                except pg8000.native.InterfaceError as error:
                    self.connection = None
                    if attempt == 2:
                        raise RegistreError(f"Connexion à la base perdue ({error}).") from None
                except pg8000.native.DatabaseError as error:
                    raise RegistreError(f"Erreur de la base PostgreSQL : {error}") from None
        raise AssertionError("inatteignable")


def open_database(url: str) -> Database:
    """Ouvre la base désignée par son adresse : `sqlite:///chemin` ou `postgresql://…`."""
    if url.startswith("sqlite:///"):
        return SQLiteDatabase(Path(url[len("sqlite:///") :]))
    if url == "sqlite://:memory:":
        return SQLiteDatabase(":memory:")
    return PostgresDatabase(url)


@dataclass(frozen=True)
class Agent:
    id: str
    email: str
    created: int
    retired: int | None


@dataclass(frozen=True)
class Visit:
    id: str
    agent_id: str
    name: str
    manifest: dict[str, Any]
    created: int
    upload_done: int | None
    ready: int | None
    photos_deleted: int | None
    publication: str | None
    link: str | None


@dataclass(frozen=True)
class Job:
    id: str
    visit_id: str
    kind: str
    state: str
    message: str
    attempts: int
    created: int
    started: int | None
    finished: int | None


@dataclass(frozen=True)
class Link:
    """Lien d'une visite pour un client (étape 16)."""

    id: str
    visit_id: str
    token: str
    label: str
    created: int
    opened: int | None


@dataclass(frozen=True)
class Opening:
    """Une consultation acceptée par le client : début, dernière mesure, durée vue."""

    id: str
    started: int
    seen: int
    seconds: int
    pricing: bool


LINK_COLUMNS = "id, visite_id, jeton, libelle, cree_le, ouvert_le"
OPENING_COLUMNS = "id, debut_le, vue_le, secondes, chiffrage"

VISIT_COLUMNS = (
    "id, agent_id, nom, manifeste, cree_le, envoi_fini_le, prete_le, photos_effacees_le, "
    "publication, lien"
)
JOB_COLUMNS = "id, visite_id, type, etat, message, essais, cree_le, debut_le, fin_le"


def _visit(row: tuple[Any, ...]) -> Visit:
    return Visit(row[0], row[1], row[2], json.loads(row[3]), *row[4:])


def _job(row: tuple[Any, ...]) -> Job:
    return Job(*row)


def normalize_email(email: str) -> str:
    return email.strip().lower()


class Registre:
    """Opérations du serveur sur la base. `clock` donne l'heure, remplacée dans les tests."""

    def __init__(self, database: Database, clock: Callable[[], float] = time.time) -> None:
        self.db = database
        self.clock = clock

    def now(self) -> int:
        return int(self.clock())

    def _run(self, sql: str, **params: Any) -> list[tuple[Any, ...]]:
        return self.db.execute(sql, params)[0]

    def _count(self, sql: str, **params: Any) -> int:
        return self.db.execute(sql, params)[1]

    def create_schema(self) -> None:
        """Crée les tables qui manquent. Sans effet sur une base déjà prête."""
        for statement in SCHEMA:
            self._run(statement)

    # --- Agents ---------------------------------------------------------------------------------

    def add_agent(self, email: str) -> tuple[Agent, bool]:
        """Autorise une adresse. Renvoie l'agent et « créé » ; une adresse retirée est rétablie."""
        email = normalize_email(email)
        found = self.agent_by_email(email)
        if found is not None:
            if found.retired is None:
                return found, False
            self._run("UPDATE agents SET retire_le = NULL WHERE id = :id", id=found.id)
            return Agent(found.id, email, found.created, None), True
        agent = Agent(new_id(), email, self.now(), None)
        self._run(
            "INSERT INTO agents (id, email, cree_le) VALUES (:id, :email, :cree)",
            id=agent.id,
            email=email,
            cree=agent.created,
        )
        return agent, True

    def agent_by_email(self, email: str) -> Agent | None:
        rows = self._run(
            "SELECT id, email, cree_le, retire_le FROM agents WHERE email = :email",
            email=normalize_email(email),
        )
        return Agent(*rows[0]) if rows else None

    def agents(self) -> list[Agent]:
        rows = self._run("SELECT id, email, cree_le, retire_le FROM agents ORDER BY email")
        return [Agent(*row) for row in rows]

    def retire_agent(self, email: str) -> Agent | None:
        """Bloque la connexion d'un agent et ferme ses sessions. Ses visites restent."""
        agent = self.agent_by_email(email)
        if agent is None:
            return None
        self._run("UPDATE agents SET retire_le = :t WHERE id = :id", t=self.now(), id=agent.id)
        self._run("DELETE FROM sessions WHERE agent_id = :id", id=agent.id)
        self._run("DELETE FROM codes WHERE email = :email", email=agent.email)
        return agent

    def visit_count(self, agent_id: str) -> int:
        rows = self._run("SELECT COUNT(*) FROM visites WHERE agent_id = :a", a=agent_id)
        return int(rows[0][0])

    # --- Codes de connexion et sessions -----------------------------------------------------------

    def new_code(self, email: str) -> str | None:
        """Tire un code pour une adresse autorisée et le range (son empreinte seulement).

        Renvoie None si l'adresse n'est pas autorisée, si un code vient d'être envoyé (un
        e-mail par minute au plus) ou si cinq codes sont déjà partis dans l'heure.
        """
        return self.issue_code(email)[0]

    def issue_code(self, email: str) -> tuple[str | None, str]:
        """Comme `new_code`, avec en plus la raison, pour les journaux du serveur : « tire »,
        « inconnue », « retiree », « trop_rapproche », « trop_nombreux » ou « simultane ».

        La raison ne sort jamais vers l'écran de l'agent : on ne révèle pas qui est autorisé.
        """
        agent = self.agent_by_email(email)
        if agent is None:
            return None, "inconnue"
        if agent.retired is not None:
            return None, "retiree"
        now = self.now()
        code = f"{secrets.randbelow(10**6):06d}"
        values = {
            "e": agent.email,
            "h": digest(agent.email + ":" + code),
            "t": now,
            "x": now + CODE_LIFETIME,
        }
        rows = self._run(
            "SELECT cree_le, envois, fenetre_le FROM codes WHERE email = :e", e=agent.email
        )
        if not rows:
            self._run(
                "INSERT INTO codes "
                "(email, empreinte, cree_le, expire_le, essais, envois, fenetre_le) "
                "VALUES (:e, :h, :t, :x, 0, 1, :t)",
                **values,
            )
            return code, "tire"
        created, sent, window = (int(value) for value in rows[0])
        if now - window >= HOUR:
            sent, window = 0, now
        if now - created < CODE_INTERVAL:
            return None, "trop_rapproche"
        if sent >= CODES_PER_HOUR:
            return None, "trop_nombreux"
        # Condition sur l'ancienne date : deux demandes simultanées n'envoient qu'un code.
        changed = self._count(
            "UPDATE codes SET empreinte = :h, cree_le = :t, expire_le = :x, essais = 0, "
            "envois = :n, fenetre_le = :w WHERE email = :e AND cree_le = :avant",
            n=sent + 1,
            w=window,
            avant=created,
            **values,
        )
        return (code, "tire") if changed else (None, "simultane")

    def check_code(self, email: str, code: str) -> Agent | None:
        """Vérifie un code. Un code juste ne sert qu'une fois ; cinq essais faux l'annulent."""
        email = normalize_email(email)
        code = "".join(code.split())
        now = self.now()
        # L'essai est compté avant la comparaison, en une seule requête : deux essais en même
        # temps ne passent pas la limite.
        counted = self._count(
            "UPDATE codes SET essais = essais + 1 "
            "WHERE email = :e AND essais < :n AND expire_le > :t",
            e=email,
            n=CODE_ATTEMPTS,
            t=now,
        )
        if not counted:
            return None
        rows = self._run("SELECT empreinte FROM codes WHERE email = :e", e=email)
        if not rows or not secrets.compare_digest(rows[0][0], digest(email + ":" + code)):
            return None
        # Un code juste est annulé aussitôt ; les compteurs d'envoi restent.
        if not self._count(
            "UPDATE codes SET expire_le = 0 WHERE email = :e AND empreinte = :h AND expire_le > :t",
            e=email,
            h=rows[0][0],
            t=now,
        ):
            return None
        agent = self.agent_by_email(email)
        return agent if agent is not None and agent.retired is None else None

    def open_session(self, agent: Agent) -> str:
        """Ouvre une session et renvoie son jeton, à garder par l'app ou le navigateur."""
        token = secrets.token_urlsafe(32)
        now = self.now()
        self._run(
            "INSERT INTO sessions (empreinte, agent_id, cree_le, expire_le) "
            "VALUES (:h, :a, :t, :x)",
            h=digest(token),
            a=agent.id,
            t=now,
            x=now + SESSION_LIFETIME,
        )
        return token

    def session_agent(self, token: str) -> Agent | None:
        """Agent d'une session encore valable, ou None."""
        rows = self._run(
            "SELECT a.id, a.email, a.cree_le, a.retire_le FROM sessions s "
            "JOIN agents a ON a.id = s.agent_id "
            "WHERE s.empreinte = :h AND s.expire_le > :t AND a.retire_le IS NULL",
            h=digest(token),
            t=self.now(),
        )
        return Agent(*rows[0]) if rows else None

    def close_session(self, token: str) -> None:
        self._run("DELETE FROM sessions WHERE empreinte = :h", h=digest(token))

    def forget_expired(self) -> None:
        now = self.now()
        self._run("DELETE FROM sessions WHERE expire_le <= :t", t=now)
        self._run(
            "DELETE FROM codes WHERE expire_le <= :t AND fenetre_le <= :h", t=now, h=now - HOUR
        )

    # --- Visites --------------------------------------------------------------------------------

    def visit_by_name(self, agent_id: str, name: str) -> Visit | None:
        rows = self._run(
            f"SELECT {VISIT_COLUMNS} FROM visites WHERE agent_id = :a AND nom = :n",
            a=agent_id,
            n=name,
        )
        return _visit(rows[0]) if rows else None

    def visit(self, visit_id: str) -> Visit | None:
        rows = self._run(f"SELECT {VISIT_COLUMNS} FROM visites WHERE id = :id", id=visit_id)
        return _visit(rows[0]) if rows else None

    def visits(self, agent_id: str) -> list[Visit]:
        rows = self._run(
            f"SELECT {VISIT_COLUMNS} FROM visites WHERE agent_id = :a ORDER BY cree_le DESC, nom",
            a=agent_id,
        )
        return [_visit(row) for row in rows]

    def save_upload(self, agent_id: str, name: str, manifest: dict[str, Any]) -> Visit:
        """Enregistre l'annonce d'un envoi. Un nouvel envoi de la même visite la met à jour."""
        text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
        found = self.visit_by_name(agent_id, name)
        if found is None:
            visit_id = new_id()
            self._run(
                "INSERT INTO visites (id, agent_id, nom, manifeste, cree_le) "
                "VALUES (:id, :a, :n, :m, :t)",
                id=visit_id,
                a=agent_id,
                n=name,
                m=text,
                t=self.now(),
            )
        else:
            visit_id = found.id
            self._run(
                "UPDATE visites SET manifeste = :m, envoi_fini_le = NULL WHERE id = :id",
                m=text,
                id=visit_id,
            )
        visit = self.visit(visit_id)
        assert visit is not None
        return visit

    def finish_upload(self, visit_id: str) -> None:
        self._run("UPDATE visites SET envoi_fini_le = :t WHERE id = :id", t=self.now(), id=visit_id)

    def set_published(self, visit_id: str, publication: str | None, link: str | None) -> None:
        self._run(
            "UPDATE visites SET publication = :p, lien = :l WHERE id = :id",
            p=publication,
            l=link,
            id=visit_id,
        )

    def set_ready(self, visit_id: str) -> None:
        self._run("UPDATE visites SET prete_le = :t WHERE id = :id", t=self.now(), id=visit_id)

    def set_photos_deleted(self, visit_id: str) -> None:
        self._run(
            "UPDATE visites SET photos_effacees_le = :t WHERE id = :id", t=self.now(), id=visit_id
        )

    def photos_to_delete(self) -> list[Visit]:
        """Visites prêtes depuis plus de 30 jours dont les photos d'origine sont encore là."""
        rows = self._run(
            f"SELECT {VISIT_COLUMNS} FROM visites WHERE prete_le IS NOT NULL "
            "AND prete_le < :limite AND photos_effacees_le IS NULL",
            limite=self.now() - PHOTOS_KEPT,
        )
        return [_visit(row) for row in rows]

    def delete_visit(self, visit_id: str) -> None:
        for link in self.links(visit_id):
            self.delete_link(link.id)
        self._run("DELETE FROM traitements WHERE visite_id = :id", id=visit_id)
        self._run("DELETE FROM visites WHERE id = :id", id=visit_id)

    # --- Traitements ----------------------------------------------------------------------------

    def queue(self, visit_id: str, kind: str = ASSEMBLY) -> Job:
        """Met un traitement en attente, sauf s'il y en a déjà un en attente pour cette visite."""
        waiting = self._run(
            f"SELECT {JOB_COLUMNS} FROM traitements "
            "WHERE visite_id = :v AND type = :k AND etat = :w",
            v=visit_id,
            k=kind,
            w=WAITING,
        )
        if waiting:
            return _job(waiting[0])
        job = Job(new_id(), visit_id, kind, WAITING, "En attente", 0, self.now(), None, None)
        self._run(
            f"INSERT INTO traitements ({JOB_COLUMNS}) "
            "VALUES (:id, :v, :k, :e, :m, 0, :t, NULL, NULL)",
            id=job.id,
            v=visit_id,
            k=kind,
            e=WAITING,
            m=job.message,
            t=job.created,
        )
        return job

    def last_job(self, visit_id: str) -> Job | None:
        rows = self._run(
            f"SELECT {JOB_COLUMNS} FROM traitements WHERE visite_id = :v "
            "ORDER BY cree_le DESC, debut_le DESC",
            v=visit_id,
        )
        return _job(rows[0]) if rows else None

    def claim(self) -> Job | None:
        """Prend le plus ancien traitement à faire et le passe « en cours ».

        Un traitement resté « en cours » trop longtemps a perdu sa tâche : il est repris, au
        plus trois fois. La prise se fait en une seule requête conditionnelle, pour que deux
        tâches lancées en même temps ne prennent jamais le même traitement.
        """
        now = self.now()
        candidates = self._run(
            f"SELECT {JOB_COLUMNS} FROM traitements "
            "WHERE (etat = :w) OR (etat = :r AND debut_le < :stale AND essais < :n) "
            "ORDER BY cree_le",
            w=WAITING,
            r=RUNNING,
            stale=now - STALE_AFTER,
            n=MAX_ATTEMPTS,
        )
        for row in candidates:
            job = _job(row)
            taken = self._count(
                "UPDATE traitements SET etat = :r, debut_le = :t, essais = essais + 1, "
                "message = :m WHERE id = :id AND etat = :e AND essais = :essais",
                r=RUNNING,
                t=now,
                m="Démarrage",
                id=job.id,
                e=job.state,
                essais=job.attempts,
            )
            if taken:
                return Job(
                    job.id,
                    job.visit_id,
                    job.kind,
                    RUNNING,
                    "Démarrage",
                    job.attempts + 1,
                    job.created,
                    now,
                    None,
                )
        stuck = self._run(
            "SELECT id FROM traitements WHERE etat = :r AND debut_le < :stale AND essais >= :n",
            r=RUNNING,
            stale=now - STALE_AFTER,
            n=MAX_ATTEMPTS,
        )
        for (job_id,) in stuck:
            self.fail(job_id, "Le traitement s'est interrompu trois fois. Renvoyer la visite.")
        return None

    def progress(self, job_id: str, message: str) -> None:
        self._run("UPDATE traitements SET message = :m WHERE id = :id", m=message, id=job_id)

    def succeed(self, job_id: str, message: str) -> None:
        self._run(
            "UPDATE traitements SET etat = :e, message = :m, fin_le = :t WHERE id = :id",
            e=DONE,
            m=message,
            t=self.now(),
            id=job_id,
        )

    def fail(self, job_id: str, message: str) -> None:
        self._run(
            "UPDATE traitements SET etat = :e, message = :m, fin_le = :t WHERE id = :id",
            e=FAILED,
            m=message,
            t=self.now(),
            id=job_id,
        )

    # --- Temps de carte graphique (étape 14) ----------------------------------------------------

    def seconds(self, month: str) -> int:
        """Secondes de carte comptées pour un mois (« 2026-11 »), pour le plafond de dépense."""
        rows = self._run("SELECT secondes FROM carte_usage WHERE mois = :m", m=month)
        return int(rows[0][0]) if rows else 0

    def add(self, month: str, seconds: int) -> None:
        self._run(
            "INSERT INTO carte_usage (mois, secondes) VALUES (:m, :s) "
            "ON CONFLICT (mois) DO UPDATE SET secondes = carte_usage.secondes + :s",
            m=month,
            s=seconds,
        )

    # --- Grille de prix de l'agent (étape 15) ---------------------------------------------------

    def grid(self, agent_id: str) -> str | None:
        """Grille de prix de l'agent (texte JSON), ou None s'il garde la grille par défaut."""
        rows = self._run("SELECT contenu FROM grilles WHERE agent_id = :a", a=agent_id)
        return str(rows[0][0]) if rows else None

    def set_grid(self, agent_id: str, content: str | None) -> None:
        """Enregistre la grille de l'agent ; None revient à la grille par défaut."""
        if content is None:
            self._run("DELETE FROM grilles WHERE agent_id = :a", a=agent_id)
            return
        self._run(
            "INSERT INTO grilles (agent_id, contenu) VALUES (:a, :c) "
            "ON CONFLICT (agent_id) DO UPDATE SET contenu = :c",
            a=agent_id,
            c=content,
        )

    # --- Liens des clients et mesures de consultation (étape 16) --------------------------------

    def create_link(self, visit_id: str, label: str) -> Link:
        link = Link(new_id(), visit_id, secrets.token_urlsafe(16), label, self.now(), None)
        self._run(
            f"INSERT INTO liens ({LINK_COLUMNS}) VALUES (:id, :v, :j, :l, :t, NULL)",
            id=link.id,
            v=visit_id,
            j=link.token,
            l=label,
            t=link.created,
        )
        return link

    def links(self, visit_id: str) -> list[Link]:
        rows = self._run(
            f"SELECT {LINK_COLUMNS} FROM liens WHERE visite_id = :v ORDER BY cree_le, libelle",
            v=visit_id,
        )
        return [Link(*row) for row in rows]

    def link(self, link_id: str) -> Link | None:
        rows = self._run(f"SELECT {LINK_COLUMNS} FROM liens WHERE id = :id", id=link_id)
        return Link(*rows[0]) if rows else None

    def link_by_token(self, token: str) -> Link | None:
        rows = self._run(f"SELECT {LINK_COLUMNS} FROM liens WHERE jeton = :j", j=token)
        return Link(*rows[0]) if rows else None

    def touch_link(self, link_id: str) -> None:
        """Note l'ouverture de la page, pour l'effacement après 12 mois seulement."""
        self._run("UPDATE liens SET ouvert_le = :t WHERE id = :id", t=self.now(), id=link_id)

    def forget_measures(self, link_id: str) -> None:
        self._run(
            "DELETE FROM consultation_pieces WHERE consultation_id IN "
            "(SELECT id FROM consultations WHERE lien_id = :l)",
            l=link_id,
        )
        self._run("DELETE FROM consultations WHERE lien_id = :l", l=link_id)

    def delete_link(self, link_id: str) -> None:
        self.forget_measures(link_id)
        self._run("DELETE FROM lien_generations WHERE lien_id = :l", l=link_id)
        self._run("DELETE FROM liens WHERE id = :l", l=link_id)

    def opening(self, opening_id: str) -> tuple[str, Opening] | None:
        """Lien et état d'une consultation, ou None si elle n'existe pas."""
        rows = self._run(
            f"SELECT lien_id, {OPENING_COLUMNS} FROM consultations WHERE id = :id", id=opening_id
        )
        if not rows:
            return None
        row = rows[0]
        return str(row[0]), Opening(row[1], row[2], row[3], row[4], bool(row[5]))

    def recent_openings(self, link_id: str, since: int) -> int:
        rows = self._run(
            "SELECT COUNT(*) FROM consultations WHERE lien_id = :l AND debut_le >= :t",
            l=link_id,
            t=since,
        )
        return int(rows[0][0])

    def record(
        self,
        link_id: str,
        opening_id: str,
        seconds: Mapping[str, int],
        toggles: Mapping[str, int],
        pricing: bool,
    ) -> None:
        """Ajoute une mesure déjà vérifiée à une consultation, créée à sa première mesure."""
        now = self.now()
        total = sum(seconds.values())
        if self.opening(opening_id) is None:
            self._run(
                f"INSERT INTO consultations ({OPENING_COLUMNS}, lien_id) "
                "VALUES (:id, :t, :t, :s, :c, :l)",
                id=opening_id,
                t=now,
                s=total,
                c=int(pricing),
                l=link_id,
            )
        else:
            self._run(
                "UPDATE consultations SET vue_le = :t, secondes = secondes + :s, "
                "chiffrage = CASE WHEN :c = 1 THEN 1 ELSE chiffrage END WHERE id = :id",
                t=now,
                s=total,
                c=int(pricing),
                id=opening_id,
            )
        for point in sorted(set(seconds) | set(toggles)):
            self._run(
                "INSERT INTO consultation_pieces (consultation_id, point, secondes, bascules) "
                "VALUES (:o, :p, :s, :b) ON CONFLICT (consultation_id, point) DO UPDATE SET "
                "secondes = consultation_pieces.secondes + :s, "
                "bascules = consultation_pieces.bascules + :b",
                o=opening_id,
                p=point,
                s=seconds.get(point, 0),
                b=toggles.get(point, 0),
            )

    def openings(self, link_id: str) -> list[Opening]:
        rows = self._run(
            f"SELECT {OPENING_COLUMNS} FROM consultations WHERE lien_id = :l "
            "ORDER BY debut_le DESC",
            l=link_id,
        )
        return [Opening(row[0], row[1], row[2], row[3], bool(row[4])) for row in rows]

    def rooms(self, link_id: str) -> dict[str, tuple[int, int]]:
        """Pour chaque point : secondes passées et nombre de bascules avant et après."""
        rows = self._run(
            "SELECT p.point, SUM(p.secondes), SUM(p.bascules) FROM consultation_pieces p "
            "JOIN consultations c ON c.id = p.consultation_id WHERE c.lien_id = :l "
            "GROUP BY p.point",
            l=link_id,
        )
        return {str(row[0]): (int(row[1]), int(row[2])) for row in rows}

    def forget_old_measures(self) -> list[Link]:
        """Efface les consultations de plus de 12 mois. Renvoie les liens restés sans ouverture
        depuis 12 mois, dont les modifications du client sont à effacer."""
        limit = self.now() - MEASURES_KEPT
        self._run(
            "DELETE FROM consultation_pieces WHERE consultation_id IN "
            "(SELECT id FROM consultations WHERE vue_le < :t)",
            t=limit,
        )
        self._run("DELETE FROM consultations WHERE vue_le < :t", t=limit)
        rows = self._run(
            f"SELECT {LINK_COLUMNS} FROM liens WHERE COALESCE(ouvert_le, cree_le) < :t", t=limit
        )
        return [Link(*row) for row in rows]

    def generations_today(self, link_id: str, day: str) -> int:
        rows = self._run(
            "SELECT nombre FROM lien_generations WHERE lien_id = :l AND jour = :d",
            l=link_id,
            d=day,
        )
        return int(rows[0][0]) if rows else 0

    def add_generation(self, link_id: str, day: str) -> None:
        self._run(
            "INSERT INTO lien_generations (lien_id, jour, nombre) VALUES (:l, :d, 1) "
            "ON CONFLICT (lien_id, jour) DO UPDATE SET nombre = lien_generations.nombre + 1",
            l=link_id,
            d=day,
        )
