"""Étapes 3 et 4 : sert en local la visite d'un ou de plusieurs points, dans un navigateur.

Le serveur ne distribue que des fichiers connus : la page de la visionneuse (dossier
`visionneuse/`), la bibliothèque Pannellum, les panoramas des points (`/p/<numéro>/...`) et deux
petites fiches, `status.json` (avancement) et `info.json` (points, liens, tailles des
panoramas). Tout autre chemin reçoit une erreur 404, pour ne jamais exposer le reste du Mac.

Les panoramas qui n'existent pas (ou tous, avec `--force`) sont assemblés en arrière-plan, un
point après l'autre, par `stitch.stitch`, pendant que la page affiche une barre d'avancement.

Les panoramas d'origine ne sont jamais modifiés (D9). Une copie réduite pour les téléphones est
fabriquée dans `cache/` de chaque point.

Étape 7 : la visionneuse peut aussi sélectionner une surface au clic. Les routes `/api/selection/`
reçoivent la vue regardée et les clics, et répondent avec le contour trouvé par SAM 2.1 (voir
`selection.py`). Une sélection validée est enregistrée dans `<point>/modifications/`.

Étape 8 : une sélection peut être repeinte. Les routes `/api/couleur/` essaient, appliquent et
annulent une recoloration (voir `couleur.py`) ; `/p/<numéro>/apres.jpg` sert le panorama modifié,
fabriqué dans `cache/`, que la visionneuse montre en « après ».
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

from visite360 import couleur, segment, selection, stitch, visite
from visite360.opencv import OpenCVError, load_cv2
from visite360.photos import PhotoError

DEFAULT_PORT = 8360
# Largeur de la copie pour téléphone : la limite de texture des GPU de téléphone est souvent 4096.
MOBILE_WIDTH = 4096
MOBILE_NAME = "panorama-mobile.jpg"
JSON = "application/json; charset=utf-8"
MAX_BODY = 64 * 1024
SELECTIONS_PATH = re.compile(r"^/p/(\d+)/selections\.json$")
PREVIEW_PATH = re.compile(r"^/p/(\d+)/selections/(selection-\d+)\.jpg$")
COLORS_PATH = re.compile(r"^/p/(\d+)/couleurs\.json$")
AFTER_PATH = re.compile(r"^/p/(\d+)/(apres|apres-mobile)\.jpg$")


class ServeError(Exception):
    """La visite ne peut pas être servie (panorama absent, port occupé, visionneuse introuvable)."""


@dataclass(frozen=True)
class Asset:
    path: Path
    content_type: str


def viewer_folder() -> Path:
    """Dossier `visionneuse/` : dans le paquet installé, sinon à la racine du dépôt."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "visionneuse", here.parents[1] / "visionneuse"):
        if (candidate / "index.html").is_file():
            return candidate
    raise ServeError("Dossier visionneuse/ introuvable : l'installation du projet est incomplète.")


def mobile_copy(cv2: Any, panorama: Path, cache: Path) -> tuple[Path, int, int]:
    """Renvoie (fichier, largeur du panorama d'origine, largeur de la copie pour téléphone).

    La copie n'est refaite que si le panorama est plus récent qu'elle.
    """
    image = cv2.imread(str(panorama))
    if image is None:
        raise ServeError(f"Panorama illisible : {panorama}")
    full_width = int(image.shape[1])
    if full_width <= MOBILE_WIDTH:
        return panorama, full_width, full_width
    target = cache / MOBILE_NAME
    if not target.is_file() or target.stat().st_mtime < panorama.stat().st_mtime:
        cache.mkdir(parents=True, exist_ok=True)
        small = cv2.resize(image, (MOBILE_WIDTH, MOBILE_WIDTH // 2), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ServeError("L'écriture de la copie pour téléphone a échoué.")
        partial = target.with_name(target.name + ".partiel")
        partial.write_bytes(encoded.tobytes())
        os.replace(partial, target)
    return target, full_width, MOBILE_WIDTH


class ProgressWriter:
    """Flux de texte qui reçoit les messages de `stitch.stitch` et en déduit un avancement.

    L'assemblage écrit des lignes comme « Alignement des photos » ou « Rendu de la photo 3 sur
    12 ». Chaque ligne reconnue fait avancer la barre (via `report`, qui reçoit un avancement de
    0 à 1 et un message), et le texte est aussi recopié sur `echo` (le terminal). L'avancement
    est une estimation : l'alignement est une longue étape sans message intermédiaire, la barre
    y reste donc immobile un moment.
    """

    STEPS = (
        ("Assemblage de", 0.05, "Préparation des photos"),
        ("Alignement des photos", 0.15, "Alignement des photos"),
        ("Exposition et raccords", 0.45, "Exposition et raccords"),
    )
    RENDER = re.compile(r"Rendu de la photo (\d+) sur (\d+)")

    def __init__(self, report: Callable[[float, str], None], echo: TextIO) -> None:
        self.report = report
        self.echo = echo

    def write(self, text: str) -> int:
        self.echo.write(text)
        for marker, progress, message in self.STEPS:
            if marker in text:
                self.report(progress, message)
        match = self.RENDER.search(text)
        if match:
            number, total = int(match.group(1)), int(match.group(2))
            self.report(0.6 + 0.35 * number / max(total, 1), "Rendu du panorama")
        return len(text)

    def flush(self) -> None:
        self.echo.flush()


def needs_generation(folders: stitch.Folders, force: bool) -> bool:
    return force or not folders.panorama.is_file()


class Visit:
    """État de la visite : en cours de génération, prête, ou en erreur."""

    def __init__(self, tour: visite.Tour) -> None:
        self.tour = tour
        self._lock = threading.Lock()
        self._status = "generating"
        self._progress = 0.0
        self._message = "Préparation"
        self._error: str | None = None
        self._assets: dict[str, Asset] = {}
        self._info = b""

    def update(self, progress: float, message: str) -> None:
        with self._lock:
            self._progress = max(self._progress, progress)
            self._message = message

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "progress": round(self._progress, 3),
                "message": self._message,
                "error": self._error,
            }

    def lookup(self, path: str) -> tuple[bytes | None, Asset | None]:
        """Contenu de `info.json` ou fichier autorisé pour ce chemin, selon l'état."""
        with self._lock:
            if path == "/info.json":
                return (self._info, None) if self._status == "ready" else (None, None)
            return None, self._assets.get(path)

    def prepare(self) -> None:
        """Construit la table des chemins autorisés, quand tous les panoramas existent."""
        assets, info = build_assets(self.tour)
        with self._lock:
            self._assets, self._info = assets, info
            self._status, self._progress, self._message = "ready", 1.0, "Visite prête"

    def fail(self, message: str) -> None:
        with self._lock:
            self._status, self._error = "error", message

    def generate(self, force: bool, echo: TextIO) -> None:
        """Assemble les panoramas manquants puis passe la visite à « prête »."""
        points = self.tour.points
        count = len(points)
        current = points[0]
        try:
            for index, current in enumerate(points):
                if not needs_generation(current.folders, force):
                    self.update((index + 1) / count, "Panorama déjà prêt")
                    continue
                label = f"Point {index + 1} sur {count} ({current.name}) : " if count > 1 else ""

                def report(
                    progress: float, message: str, index: int = index, label: str = label
                ) -> None:
                    self.update((index + progress) / count, label + message)

                if count > 1:
                    print(f"=== Point {index + 1} sur {count} : {current.name} ===", file=echo)
                result = stitch.stitch(
                    current.folders, stitch.DEFAULT_WIDTH, force, ProgressWriter(report, echo)
                )
                if result is not None:
                    stitch.print_report(result, current.folders, echo)
                self.update((index + 1) / count, label + "Panorama assemblé")
            self.update(0.97, "Finalisation")
            self.prepare()
        except (stitch.StitchError, PhotoError, OpenCVError, ServeError) as error:
            print(f"Erreur : {error}", file=sys.stderr)
            self.fail(f"Point « {current.name} » : {error}" if count > 1 else str(error))
        except (
            Exception
        ) as error:  # le fil ne doit jamais mourir en silence : la page attendrait sans fin
            print(f"Erreur inattendue : {error!r}", file=sys.stderr)
            self.fail(f"Erreur inattendue pendant l'assemblage : {error}")


def build_assets(tour: visite.Tour) -> tuple[dict[str, Asset], bytes]:
    """Table des chemins autorisés et contenu de `info.json`."""
    try:
        cv2 = load_cv2()
    except OpenCVError as error:
        raise ServeError(str(error)) from error
    assets: dict[str, Asset] = {}
    points = []
    for index, point in enumerate(tour.points):
        folders = point.folders
        if not folders.panorama.is_file():
            raise ServeError(
                f"Pas de panorama pour le point « {point.name} » ({folders.panorama})."
            )
        mobile, full_width, mobile_width = mobile_copy(cv2, folders.panorama, folders.cache)
        prefix = f"/p/{index}"
        assets[f"{prefix}/panorama.jpg"] = Asset(folders.panorama, "image/jpeg")
        assets[f"{prefix}/panorama-mobile.jpg"] = Asset(mobile, "image/jpeg")
        points.append(
            {
                "id": point.id,
                "name": point.name,
                "full": {"url": f"{prefix}/panorama.jpg", "width": full_width},
                "mobile": {"url": f"{prefix}/panorama-mobile.jpg", "width": mobile_width},
                "links": [
                    {
                        "to": link.target,
                        "angle": link.angle,
                        "pitch": link.pitch,
                        "text": link.text,
                    }
                    for link in tour.links_from(point.id)
                ],
            }
        )
    info = {"name": tour.name, "start": tour.start, "points": points}
    return assets, json.dumps(info, ensure_ascii=False).encode("utf-8")


def viewer_assets() -> dict[str, Asset]:
    """Fichiers de la visionneuse, servis dans tous les états."""
    viewer = viewer_folder()
    return {
        "/": Asset(viewer / "index.html", "text/html; charset=utf-8"),
        "/pannellum/pannellum.js": Asset(
            viewer / "pannellum" / "pannellum.js", "text/javascript; charset=utf-8"
        ),
        "/pannellum/pannellum.css": Asset(
            viewer / "pannellum" / "pannellum.css", "text/css; charset=utf-8"
        ),
        "/nuancier.json": Asset(viewer / "nuancier.json", JSON),
    }


def tour_needs_generation(tour: visite.Tour, force: bool) -> bool:
    return any(needs_generation(point.folders, force) for point in tour.points)


def default_selector(tour: visite.Tour) -> selection.Selector:
    """Sélection avec SAM 2.1, s'il est installé (sinon la visionneuse dit quoi installer)."""
    problem = segment.missing()
    message = (
        f"La sélection demande SAM 2.1 ({problem}). L'installer : {segment.INSTALL_COMMAND}"
        if problem
        else None
    )
    return selection.Selector(tour, segment.load_segmenter, segment.MODEL_NAME, message)


class RequestError(Exception):
    """Requête refusée, avec son code HTTP et un message en français pour la visionneuse."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def handle_selection(
    selector: selection.Selector, route: str, body: dict[str, Any]
) -> tuple[bytes, str]:
    """Traite une route POST `/api/selection/...`. Renvoie (contenu, type)."""
    if selector.unavailable and route in ("vue", "masque", "valider"):
        raise RequestError(503, selector.unavailable)
    if route == "vue":
        token = selector.open_view(
            body.get("point"), body.get("cap"), body.get("hauteur"), body.get("champ")
        )
        result: Any = {"vue": token, "taille": selection.VIEW_SIZE}
    elif route == "masque":
        mask, _ = selector.mask(body.get("vue"), body.get("clics"))
        return selection.overlay_png(mask), "image/png"
    elif route == "valider":
        result = selector.validate(body.get("vue"), body.get("clics"), body.get("nom"))
    elif route == "supprimer":
        point = selector.point(body.get("point"))
        selection_id = body.get("id")
        if not isinstance(selection_id, str):
            raise selection.SelectionError("Identifiant de sélection manquant.")
        # Ses recolorations d'abord : sans sélection, elles n'auraient plus de masque.
        couleur.delete_for_selection(point.folders.point, selection_id)
        selection.delete(point.folders.point, selection_id)
        result = {"supprimee": selection_id}
    else:
        raise RequestError(404, "Introuvable")
    return json.dumps(result, ensure_ascii=False).encode("utf-8"), JSON


def handle_color(
    selector: selection.Selector, route: str, body: dict[str, Any]
) -> tuple[bytes, str]:
    """Traite une route POST `/api/couleur/...`. Renvoie (contenu, type)."""
    folders = selector.point(body.get("point")).folders
    if route == "apercu":
        image = couleur.preview(
            folders.panorama,
            folders.point,
            body.get("selection"),
            body.get("couleur"),
            MOBILE_WIDTH,
            body.get("actuelle"),
        )
        return image, "image/jpeg"
    if route == "appliquer":
        result: Any = couleur.save(
            folders.point,
            body.get("selection"),
            body.get("couleur"),
            body.get("teinte"),
            body.get("actuelle"),
        )
    elif route == "annuler":
        couleur.delete(folders.point, body.get("id"))
        result = {"annulee": body.get("id")}
    else:
        raise RequestError(404, "Introuvable")
    return json.dumps(result, ensure_ascii=False).encode("utf-8"), JSON


def make_server(
    tour: visite.Tour,
    host: str,
    port: int,
    force: bool = False,
    selector: selection.Selector | None = None,
) -> ThreadingHTTPServer:
    """Prépare le serveur d'une visite, sans le lancer.

    Si un panorama manque (ou avec `force`), la visite reste « en cours de génération » : c'est
    à l'appelant de lancer `server.visit.generate(...)`. Sinon elle est prête tout de suite.
    `selector` remplace la sélection par SAM 2.1 (les tests y passent un modèle simulé).
    """
    visit = Visit(tour)
    fixed = viewer_assets()
    selector = selector or default_selector(tour)
    painter = couleur.Painter(MOBILE_WIDTH)
    if tour_needs_generation(tour, force):
        for point in tour.points:
            if needs_generation(point.folders, force):
                # Échoue tout de suite s'il n'y a rien à assembler.
                stitch.list_photos(point.folders.photos)
    else:
        visit.prepare()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/status.json":
                self._send(json.dumps(visit.status()).encode("utf-8"), JSON)
                return
            if path == "/api/selection":
                message = selector.unavailable
                state = {"disponible": message is None, "message": message}
                self._send(json.dumps(state, ensure_ascii=False).encode("utf-8"), JSON)
                return
            if SELECTIONS_PATH.match(path) or PREVIEW_PATH.match(path):
                self._answer(lambda: self._selection_file(path))
                return
            if COLORS_PATH.match(path) or AFTER_PATH.match(path):
                self._answer(lambda: self._color_file(path))
                return
            info, asset = visit.lookup(path)
            if info is not None:
                self._send(info, JSON)
                return
            asset = asset or fixed.get(path)
            if asset is None or not asset.path.is_file():
                self.send_error(404, "Introuvable")
                return
            self._send(asset.path.read_bytes(), asset.content_type)

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            route = path.rsplit("/", 1)[1]
            if path.startswith("/api/selection/"):
                self._answer(lambda: handle_selection(selector, route, self._body()))
            elif path.startswith("/api/couleur/"):
                self._answer(lambda: handle_color(selector, route, self._body()))
            else:
                self.send_error(404, "Introuvable")

        def _answer(self, produce: Callable[[], tuple[bytes, str]]) -> None:
            """Envoie ce que `produce` renvoie, ou une erreur JSON lisible par la visionneuse."""
            try:
                if visit.status()["status"] != "ready":
                    raise RequestError(409, "La visite n'est pas encore prête.")
                data, kind = produce()
            except RequestError as error:
                self._send_error(error.status, str(error))
            except (selection.SelectionError, couleur.ColorError) as error:
                self._send_error(400, str(error))
            except (segment.SegmentError, OpenCVError) as error:
                print(f"Erreur : {error}", file=sys.stderr)
                self._send_error(503, str(error))
            except Exception as error:  # le serveur doit répondre, même à une erreur imprévue
                print(f"Erreur inattendue : {error!r}", file=sys.stderr)
                self._send_error(500, f"Erreur inattendue : {error}")
            else:
                self._send(data, kind)

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise RequestError(411, "Longueur de la requête manquante.") from None
            if not 0 < length <= MAX_BODY:
                raise RequestError(413, "Requête vide ou trop grosse.")
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise RequestError(400, "Requête illisible : JSON attendu.") from None
            if not isinstance(body, dict):
                raise RequestError(400, "Requête illisible : objet JSON attendu.")
            return body

        def _selection_file(self, path: str) -> tuple[bytes, str]:
            listing = SELECTIONS_PATH.match(path)
            match = listing or PREVIEW_PATH.match(path)
            assert match is not None
            folders = selector.point(int(match.group(1))).folders
            if listing:
                records = selection.list_all(folders.point, folders.panorama)
                return json.dumps(records, ensure_ascii=False).encode("utf-8"), JSON
            image = selection.preview(folders.point, folders.panorama, match.group(2))
            return image.read_bytes(), "image/jpeg"

        def _color_file(self, path: str) -> tuple[bytes, str]:
            listing = COLORS_PATH.match(path)
            match = listing or AFTER_PATH.match(path)
            assert match is not None
            folders = selector.point(int(match.group(1))).folders
            if listing:
                state = painter.state(folders.point, folders.panorama)
                return json.dumps(state, ensure_ascii=False).encode("utf-8"), JSON
            mobile = match.group(2) == "apres-mobile"
            return painter.after(folders.point, folders.panorama, mobile).read_bytes(), "image/jpeg"

        def _send_error(self, status: int, message: str) -> None:
            data = json.dumps({"erreur": message}, ensure_ascii=False).encode("utf-8")
            self._send(data, JSON, status)

        def _send(self, data: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        raise ServeError(
            f"Impossible d'ouvrir le port {port} ({error.strerror}). "
            "Un autre programme l'utilise peut-être : essayer --port avec un autre numéro."
        ) from error
    server.visit = visit  # type: ignore[attr-defined]
    return server


def lan_address() -> str | None:
    """Adresse du Mac sur le Wi-Fi local. Aucun paquet n'est envoyé (socket UDP non connecté)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return str(probe.getsockname()[0])
    except OSError:
        return None


def run(
    target: Path,
    port: int = DEFAULT_PORT,
    local_only: bool = False,
    force: bool = False,
    out: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 serve`. Renvoie le code de sortie."""
    out = out or sys.stdout
    try:
        tour, created = visite.open_tour(target)
        server = make_server(tour, "127.0.0.1" if local_only else "0.0.0.0", port, force)
    except (stitch.StitchError, visite.VisiteError, PhotoError, ServeError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    if created:
        print(
            f"{visite.FILE_NAME} créé avec {len(tour.points)} point(s) et aucun lien. "
            "Ajouter les liens à la main (voir docs/visite-json.md), puis relancer.",
            file=out,
        )
    if tour.ignored:
        print(
            f"Dossiers ignorés (absents de {visite.FILE_NAME}) : {', '.join(tour.ignored)}",
            file=out,
        )
    actual_port = server.server_address[1]
    print(f"Visite servie. Sur ce Mac : http://localhost:{actual_port}", file=out)
    if not local_only:
        address = lan_address()
        if address:
            print(
                f"Sur un téléphone connecté au même Wi-Fi : http://{address}:{actual_port}",
                file=out,
            )
    print("Ctrl+C pour arrêter.", file=out)
    visit: Visit = server.visit  # type: ignore[attr-defined]
    if tour_needs_generation(tour, force):
        print("Génération des panoramas en cours, la page affiche l'avancement.", file=out)
        threading.Thread(target=visit.generate, args=(force, out), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.", file=out)
    finally:
        server.server_close()
    return 0
