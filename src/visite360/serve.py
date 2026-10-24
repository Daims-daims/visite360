"""Étape 3 : sert en local la visite d'un point, à ouvrir dans un navigateur.

Le serveur ne distribue que quatre choses : la page de la visionneuse (dossier `visionneuse/`),
la bibliothèque Pannellum qui l'accompagne, le panorama du point et une petite fiche
`info.json`. Tout autre chemin reçoit une erreur 404, pour ne jamais exposer le reste du Mac.

Le panorama d'origine n'est jamais modifié (D9). Une copie réduite pour les téléphones est
fabriquée dans `cache/` du point.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

from visite360 import stitch
from visite360.opencv import OpenCVError, load_cv2

DEFAULT_PORT = 8360
# Largeur de la copie pour téléphone : la limite de texture des GPU de téléphone est souvent 4096.
MOBILE_WIDTH = 4096
MOBILE_NAME = "panorama-mobile.jpg"


class ServeError(Exception):
    """Le point ne peut pas être servi (panorama absent, port occupé, visionneuse introuvable)."""


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


def build_assets(folders: stitch.Folders) -> tuple[dict[str, Asset], bytes]:
    """Table des chemins autorisés et contenu de `info.json`."""
    if not folders.panorama.is_file():
        raise ServeError(
            f"Pas de panorama pour ce point ({folders.panorama}). "
            f"Lancer d'abord : visite360 stitch {folders.point}"
        )
    try:
        cv2 = load_cv2()
    except OpenCVError as error:
        raise ServeError(str(error)) from error
    mobile, full_width, mobile_width = mobile_copy(cv2, folders.panorama, folders.cache)
    viewer = viewer_folder()
    assets = {
        "/": Asset(viewer / "index.html", "text/html; charset=utf-8"),
        "/pannellum/pannellum.js": Asset(
            viewer / "pannellum" / "pannellum.js", "text/javascript; charset=utf-8"
        ),
        "/pannellum/pannellum.css": Asset(
            viewer / "pannellum" / "pannellum.css", "text/css; charset=utf-8"
        ),
        "/panorama.jpg": Asset(folders.panorama, "image/jpeg"),
        "/panorama-mobile.jpg": Asset(mobile, "image/jpeg"),
    }
    info = {
        "name": folders.point.resolve().name,
        "full": {"url": "/panorama.jpg", "width": full_width},
        "mobile": {"url": "/panorama-mobile.jpg", "width": mobile_width},
    }
    return assets, json.dumps(info, ensure_ascii=False).encode("utf-8")


def make_server(folders: stitch.Folders, host: str, port: int) -> ThreadingHTTPServer:
    """Prépare le serveur d'un point, sans le lancer."""
    assets, info = build_assets(folders)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/info.json":
                self._send(info, "application/json; charset=utf-8")
                return
            asset = assets.get(path)
            if asset is None or not asset.path.is_file():
                self.send_error(404, "Introuvable")
                return
            self._send(asset.path.read_bytes(), asset.content_type)

        def _send(self, data: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    try:
        return ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        raise ServeError(
            f"Impossible d'ouvrir le port {port} ({error.strerror}). "
            "Un autre programme l'utilise peut-être : essayer --port avec un autre numéro."
        ) from error


def lan_address() -> str | None:
    """Adresse du Mac sur le Wi-Fi local. Aucun paquet n'est envoyé (socket UDP non connecté)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return str(probe.getsockname()[0])
    except OSError:
        return None


def run(
    target: Path, port: int = DEFAULT_PORT, local_only: bool = False, out: TextIO | None = None
) -> int:
    """Point d'entrée de `visite360 serve`. Renvoie le code de sortie."""
    out = out or sys.stdout
    try:
        folders = stitch.resolve_folders(target)
        server = make_server(folders, "127.0.0.1" if local_only else "0.0.0.0", port)
    except (stitch.StitchError, ServeError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.", file=out)
    finally:
        server.server_close()
    return 0
