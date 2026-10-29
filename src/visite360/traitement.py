"""Étape 13 : traitement des visites envoyées au serveur — assemblage, publication, effacement.

`visite360 traiter` est lancé chez Scaleway comme une tâche (Serverless Jobs) : par le serveur à
la fin de chaque envoi, et une fois par jour par une programmation, au cas où un lancement se
serait perdu. Il prend un à un les traitements en attente du registre et, pour chaque visite :

1. récupère du stockage privé `visite.json` et les `capture.json` ;
2. pour chaque point, reprend le panorama s'il a déjà été assemblé (rangé dans le stockage
   privé), sinon récupère les photos du point et l'assemble avec le code de l'étape 2 ;
3. publie la visite comme à l'étape 12 et note le lien dans le registre.

Relancé, il ne refait pas ce qui est fait : un panorama assemblé est rangé dans le stockage
privé dès qu'il est prêt, et la publication n'envoie que ce qui a changé. Les fichiers de
travail vivent dans un dossier temporaire, effacé à la fin.

Pour finir, il efface les photos d'origine des visites prêtes depuis plus de 30 jours (D39).
`visite.json`, les `capture.json`, les panoramas et les rapports restent.

Les traitements sont génériques (D39) : l'assemblage est le premier type ; la génération d'image
de l'étape 14 viendra s'y ajouter.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from visite360 import capture, publier, serve, stitch, visite
from visite360.depot import Depot, DepotError
from visite360.opencv import OpenCVError
from visite360.photos import PhotoError
from visite360.registre import ASSEMBLY, Job, Registre, RegistreError, Visit

JOBS_API = "https://api.scaleway.com/serverless-jobs/v1alpha2/regions/{region}/job-definitions"
JOB_TIMEOUT = 30
PANORAMA = "panorama.jpg"
REPORT = "rapport.json"


class ProcessError(Exception):
    """Traitement impossible pour cette visite. Message en français, montré à l'agent."""


# --- Lancement de la tâche ----------------------------------------------------------------------


class Launcher(Protocol):
    """Réveille le traitement des visites en attente."""

    def wake(self) -> None: ...


class LaunchError(Exception):
    """Le lancement a échoué. Le traitement reste en attente et partira au prochain réveil."""


class ScalewayLauncher:
    """Lance la tâche d'assemblage chez Scaleway (API Serverless Jobs, v1alpha2)."""

    def __init__(self, secret_key: str, region: str, job_definition: str) -> None:
        self.secret_key, self.region, self.job_definition = secret_key, region, job_definition

    def wake(self) -> None:
        url = f"{JOBS_API.format(region=self.region)}/{self.job_definition}/start"
        request = urllib.request.Request(
            url,
            data=b"{}",
            headers={"X-Auth-Token": self.secret_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=JOB_TIMEOUT):
                pass
        except urllib.error.HTTPError as error:
            raise LaunchError(f"Scaleway refuse le lancement (erreur {error.code}).") from None
        except (urllib.error.URLError, OSError) as error:
            raise LaunchError(f"Scaleway est injoignable ({error}).") from None


class ThreadLauncher:
    """Serveur lancé sur le Mac : le traitement tourne dans un fil du serveur, un à la fois."""

    def __init__(self, process: Callable[[], None]) -> None:
        self.process = process
        self.lock = threading.Lock()
        self.again = False
        self.thread: threading.Thread | None = None

    def wake(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                self.again = True
                return
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self) -> None:
        while True:
            self.process()
            with self.lock:
                if not self.again:
                    self.thread = None
                    return
                self.again = False

    def join(self, timeout: float | None = None) -> None:
        thread = self.thread
        if thread is not None:
            thread.join(timeout)


# --- Traitement d'une visite ----------------------------------------------------------------------


@dataclass
class Context:
    """Ce dont le traitement a besoin, fourni par le serveur local ou par `visite360 traiter`."""

    registre: Registre
    depot: Depot
    public: publier.Storage
    public_settings: publier.Settings
    out: TextIO
    work_root: Path | None = None


def manifest_paths(visit: Visit) -> list[str]:
    return sorted(visit.manifest["fichiers"])


def _download(context: Context, visit: Visit, path: str, folder: Path) -> None:
    key = f"{visit.id}/{path}"
    try:
        data = context.depot.get(key)
    except DepotError as error:
        raise ProcessError(f"{path} manque dans le stockage ({error}).") from None
    target = folder / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _point_photos(paths: list[str], point_id: str) -> list[str]:
    return [path for path in paths if path.startswith(f"{point_id}/photos/")]


def assemble(context: Context, job: Job, visit: Visit) -> str:
    """Assemble et publie une visite. Renvoie le message de fin, pour l'agent."""
    registre, depot = context.registre, context.depot
    paths = manifest_paths(visit)
    stored = depot.list(f"{visit.id}/")
    with tempfile.TemporaryDirectory(prefix="visite360-", dir=context.work_root) as temp:
        folder = Path(temp) / visit.name
        folder.mkdir()
        for path in paths:
            if path == visite.FILE_NAME or path.endswith(f"/{capture.FILE_NAME}"):
                _download(context, visit, path, folder)
            point = path.split("/", 1)[0] if "/" in path else None
            if point:
                (folder / point).mkdir(exist_ok=True)
        try:
            tour = visite.load(folder)
        except visite.VisiteError as error:
            raise ProcessError(f"visite.json refusé : {error}") from None
        count = len(tour.points)
        for index, point in enumerate(tour.points):
            label = f"Point {index + 1} sur {count} ({point.name})"
            prefix = f"{visit.id}/{point.id}/"
            if prefix + PANORAMA in stored and prefix + REPORT in stored:
                for name in (PANORAMA, REPORT):
                    _download(context, visit, f"{point.id}/{name}", folder)
                registre.progress(job.id, f"{label} : panorama déjà prêt")
                continue
            photos = _point_photos(paths, point.id)
            if not photos:
                raise ProcessError(f"Le point « {point.name} » n'a aucune photo dans l'envoi.")
            if visit.photos_deleted is not None:
                raise ProcessError(
                    f"Les photos du point « {point.name} » ont été effacées (30 jours après la "
                    "visite prête). Renvoyer la visite depuis l'app."
                )
            registre.progress(job.id, f"{label} : récupération des photos")
            for path in photos:
                _download(context, visit, path, folder)

            def report(progress: float, message: str, label: str = label) -> None:
                registre.progress(job.id, f"{label} : {message}")

            print(f"=== {visit.name} : {label} ===", file=context.out, flush=True)
            try:
                result = stitch.stitch(
                    point.folders,
                    stitch.DEFAULT_WIDTH,
                    False,
                    serve.ProgressWriter(report, context.out),
                )
            except (stitch.StitchError, PhotoError, OpenCVError) as error:
                raise ProcessError(f"Point « {point.name} » : {error}") from None
            if result is not None:
                stitch.print_report(result, point.folders, context.out)
            # Rangé tout de suite : une tâche interrompue ne refera pas ce point.
            for name, kind in ((PANORAMA, "image/jpeg"), (REPORT, serve.JSON)):
                data = (point.folders.point / name).read_bytes()
                depot.put(prefix + name, data, kind)
            shutil.rmtree(point.folders.photos, ignore_errors=True)
            shutil.rmtree(point.folders.cache, ignore_errors=True)
        registre.progress(job.id, "Publication de la visite")
        return publish(context, visit, tour, folder)


def publish(context: Context, visit: Visit, tour: visite.Tour, folder: Path) -> str:
    """Publie la visite assemblée sous son identifiant, ou sous un nouveau. Note le lien."""
    settings = context.public_settings
    if visit.publication:
        publier.write_state(folder, {"identifiant": visit.publication, "bucket": settings.bucket})
    try:
        report = publier.publish(tour, folder, context.public, settings, context.out)
    except publier.PublishError as error:
        raise ProcessError(f"Publication impossible : {error}") from None
    state = publier.read_state(folder)
    assert state is not None
    context.registre.set_published(visit.id, state["identifiant"], report.link)
    return f"Visite prête : {len(tour.points)} point(s)."


def process_one(context: Context, job: Job) -> None:
    """Fait un traitement pris dans le registre, et note sa réussite ou son échec."""
    registre = context.registre
    visit = registre.visit(job.visit_id)
    if visit is None:
        registre.succeed(job.id, "Visite supprimée entre-temps : rien à faire.")
        return
    if job.kind != ASSEMBLY:
        registre.fail(job.id, f"Type de traitement inconnu : {job.kind}.")
        return
    try:
        message = assemble(context, job, visit)
    except (ProcessError, DepotError, publier.PublishError) as error:
        print(f"Échec pour « {visit.name} » : {error}", file=context.out, flush=True)
        registre.fail(job.id, str(error))
        return
    except Exception as error:  # la visite ne doit jamais rester « en cours » sans raison
        print(f"Erreur inattendue pour « {visit.name} » : {error!r}", file=context.out)
        registre.fail(job.id, f"Erreur inattendue pendant le traitement : {error}")
        return
    registre.set_ready(visit.id)
    registre.succeed(job.id, message)
    print(f"« {visit.name} » : {message}", file=context.out, flush=True)


def delete_old_photos(context: Context) -> int:
    """Efface les photos d'origine des visites prêtes depuis plus de 30 jours. Renvoie le
    nombre de visites concernées."""
    count = 0
    for visit in context.registre.photos_to_delete():
        for key in context.depot.list(f"{visit.id}/"):
            if "/photos/" in key:
                context.depot.delete(key)
        context.registre.set_photos_deleted(visit.id)
        count += 1
    return count


def process_all(context: Context) -> int:
    """Fait tous les traitements en attente, puis l'effacement des vieilles photos. Renvoie
    le nombre de traitements faits."""
    done = 0
    while (job := context.registre.claim()) is not None:
        process_one(context, job)
        done += 1
    deleted = delete_old_photos(context)
    if deleted:
        print(f"Photos d'origine effacées pour {deleted} visite(s).", file=context.out)
    context.registre.forget_expired()
    return done


def visit_state(visit: Visit, job: Job | None) -> dict[str, Any]:
    """État d'une visite tel que le montrent l'app et l'espace web."""
    if visit.upload_done is None:
        state, message = "envoi", "Envoi depuis l'app pas encore terminé"
    elif job is None:
        state, message = "en_attente", "En attente"
    else:
        state = {"fini": "prete", "echec": "echec"}.get(job.state, job.state)
        message = job.message
    return {
        "id": visit.id,
        "nom": visit.name,
        "etat": state,
        "message": message,
        "lien": visit.link,
        "cree_le": visit.created,
        "prete_le": visit.ready,
        "photos_effacees": visit.photos_deleted is not None,
    }


# --- Ligne de commande --------------------------------------------------------------------------


def run(environ: Mapping[str, str] | None = None, out: TextIO | None = None) -> int:
    """Point d'entrée de `visite360 traiter`, lancé chez Scaleway. Renvoie le code de sortie."""
    from visite360 import reglages
    from visite360.depot import S3Depot
    from visite360.registre import open_database

    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        settings = reglages.from_env(environ, need_job=False)
        assert settings.depot is not None and settings.public is not None
        registre = Registre(open_database(settings.database))
        registre.create_schema()
        context = Context(
            registre,
            S3Depot(settings.depot),
            publier.S3Storage(settings.public),
            settings.public,
            out,
        )
        done = process_all(context)
    except (reglages.SettingsError, RegistreError, DepotError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    print(f"{done} traitement(s) fait(s).", file=out)
    return 0
