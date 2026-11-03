"""Étape 15 : atelier en ligne — les outils de modification sur le serveur du projet (D42).

Les outils de l'étape 7 à 11 (sélection, couleur, remplacement d'objet, mesure des pièces,
chiffrage) travaillent sur un dossier de visite. Sur le serveur, la visite vit dans le stockage
privé : un **atelier** en reconstitue le dossier dans un répertoire temporaire, y fait tourner les
mêmes outils que sur le Mac (`serve.Tools`), puis range dans le stockage ce qu'ils ont écrit.

- ce qui vient du stockage : `visite.json`, les `capture.json` et les panoramas d'origine, qui ne
  sont jamais réécrits (D9) ;
- ce qui est écrit par les outils et rangé dans le stockage, à côté du reste de la visite :
  `<point>/modifications/` (sélections, recolorations, remplacements d'objets) et
  `<point>/piece.json` (mesure de la pièce) ;
- la grille de prix est celle de l'agent, rangée dans la base : le même fichier `tarifs.json` est
  écrit dans le dossier de travail avant chaque requête et relu après ;
- ce qui est refabriqué à la demande (panorama modifié, copies pour téléphone, contours) reste
  dans `cache/` du dossier temporaire et n'est jamais rangé.

Un atelier est gardé en mémoire tant qu'il sert, et au plus `MAX_ATELIERS` à la fois : une visite
de plus chasse la moins récente, qui range d'abord ce qui reste à ranger. Les fichiers du
stockage sont la référence : avant chaque requête, l'atelier relit la liste et reprend ce qui a
changé, ce qui permet plusieurs copies du serveur.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from visite360 import capture, chiffrage, selection, serve, visite
from visite360.depot import Depot, DepotError
from visite360.registre import Visit

MAX_ATELIERS = 3
PANORAMA = "panorama.jpg"
# Ce que les outils écrivent et qu'on range : relatif au dossier de la visite.
SYNCED = re.compile(r"[^/]+/(modifications/[^/]+|piece\.json)")
TYPES = {".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg"}
LISTING = ("/info.json", "/status.json")
READY = {"status": "ready", "progress": 1.0, "message": "Visite prête", "error": None}

ToolsFactory = Callable[[visite.Tour], serve.Tools]


class AtelierError(Exception):
    """L'atelier ne peut pas être ouvert (visite abîmée, fichier manquant)."""


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class Atelier:
    """Dossier de travail d'une visite et outils qui y tournent."""

    def __init__(
        self,
        visit: Visit,
        depot: Depot,
        root: Path,
        make_tools: ToolsFactory,
        grid: Callable[[], str | None],
        save_grid: Callable[[str | None], None],
    ) -> None:
        self.visit = visit
        self.depot = depot
        self.prefix = f"{visit.id}/"
        self.folder = root / visit.name
        self.folder.mkdir(parents=True)
        self.make_tools = make_tools
        self._grid, self._save_grid = grid, save_grid
        self.lock = threading.RLock()
        # Fichiers rangés dans le stockage, avec l'empreinte du contenu local correspondant.
        self.known: dict[str, str] = {}
        self._tools: serve.Tools | None = None
        self._assets: dict[str, serve.Asset] = {}
        self._info = b""

    # --- Dossier de travail -------------------------------------------------------------------

    def _fetch(self, rel: str) -> None:
        try:
            data = self.depot.get(self.prefix + rel)
        except DepotError as error:
            raise AtelierError(f"{rel} manque dans le stockage ({error}).") from None
        target = self.folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def open(self) -> None:
        """Récupère `visite.json`, les `capture.json` et les panoramas."""
        manifest = sorted(self.visit.manifest["fichiers"])
        self._fetch(visite.FILE_NAME)
        for rel in manifest:
            if rel.endswith(f"/{capture.FILE_NAME}"):
                self._fetch(rel)
        try:
            tour = visite.load(self.folder)
        except visite.VisiteError as error:
            raise AtelierError(f"visite.json refusé : {error}") from None
        for point in tour.points:
            point.folders.point.mkdir(exist_ok=True)
            self._fetch(f"{point.id}/{PANORAMA}")
        self._tools = self.make_tools(tour)
        self.refresh()

    @property
    def tools(self) -> serve.Tools:
        assert self._tools is not None
        return self._tools

    def _local_files(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for path in self.folder.glob("*/*"):
            candidates = path.glob("*") if path.is_dir() else [path]
            for item in candidates:
                rel = item.relative_to(self.folder).as_posix()
                if SYNCED.fullmatch(rel) and item.is_file() and not item.name.endswith(".partiel"):
                    found[rel] = item
        return found

    def refresh(self) -> None:
        """Reprend du stockage les modifications ajoutées ou changées ailleurs."""
        stored = {
            key[len(self.prefix) :]: md5
            for key, md5 in self.depot.list(self.prefix).items()
            if SYNCED.fullmatch(key[len(self.prefix) :])
        }
        for rel, md5 in stored.items():
            if self.known.get(rel) != md5:
                self._fetch(rel)
                self.known[rel] = md5
        for rel in [rel for rel in self.known if rel not in stored]:
            (self.folder / rel).unlink(missing_ok=True)
            del self.known[rel]
        self._write_grid()

    def push(self) -> None:
        """Range dans le stockage ce que les outils ont écrit ou effacé."""
        local = self._local_files()
        for rel, path in local.items():
            digest = _md5(path)
            if self.known.get(rel) != digest:
                kind = TYPES.get(path.suffix, "application/octet-stream")
                self.depot.put(self.prefix + rel, path.read_bytes(), kind)
                self.known[rel] = digest
        for rel in [rel for rel in self.known if rel not in local]:
            self.depot.delete(self.prefix + rel)
            del self.known[rel]
        self._read_grid()

    # --- Grille de prix de l'agent ----------------------------------------------------------------

    def _write_grid(self) -> None:
        path = chiffrage.grid_path(self.folder)
        content = self._grid()
        if content is None:
            path.unlink(missing_ok=True)
        elif not path.is_file() or path.read_text(encoding="utf-8") != content:
            selection.write_atomic(path, content.encode("utf-8"))

    def _read_grid(self) -> None:
        path = chiffrage.grid_path(self.folder)
        content = path.read_text(encoding="utf-8") if path.is_file() else None
        if content != self._grid():
            self._save_grid(content)

    # --- Requêtes -----------------------------------------------------------------------------

    def _build(self) -> None:
        if not self._info:
            self._assets, self._info = serve.build_assets(
                self.tools.tour, root=f"/atelier/{self.visit.id}/"
            )

    def get(self, rest: str) -> tuple[bytes, str] | None:
        """Contenu de la route `rest` (« /info.json », « /p/0/panorama.jpg », « /api/… »), ou
        None si elle n'existe pas."""
        with self.lock:
            self.refresh()
            try:
                return self._get(rest)
            finally:
                self.push()

    def _get(self, rest: str) -> tuple[bytes, str] | None:
        if rest == "/status.json":
            return json.dumps(READY).encode("utf-8"), serve.JSON
        if rest == "/info.json":
            self._build()
            return self._info, serve.JSON
        if self.tools.is_get(rest):
            return self.tools.get(rest)
        fixed = serve.viewer_assets().get(rest)
        if fixed is not None and rest not in ("/", "/agent"):
            return fixed.path.read_bytes(), fixed.content_type
        self._build()
        asset = self._assets.get(f"/atelier/{self.visit.id}{rest}")
        if asset is not None:
            return asset.path.read_bytes(), asset.content_type
        return None

    def post(self, rest: str, body: dict[str, Any]) -> tuple[bytes, str] | None:
        """Réponse à la route d'outil `rest`, ou None si ce n'est pas une route d'outil."""
        if not self.tools.is_post(rest):
            return None
        with self.lock:
            self.refresh()
            try:
                return self.tools.post(rest, body)
            finally:
                self.push()

    def page(self) -> bytes:
        """Page de la visionneuse, avec le préfixe de ses adresses (`<meta name="base">`)."""
        html = (serve.viewer_folder() / "index.html").read_text(encoding="utf-8")
        meta = f'<meta name="base" content="/atelier/{self.visit.id}">'
        return html.replace("<head>", f"<head>\n  {meta}", 1).encode("utf-8")

    def close(self, save: bool = True) -> None:
        """Range ce qui reste (sauf si la visite n'existe plus), puis efface le dossier."""
        with self.lock:
            try:
                if save and self._tools is not None:
                    self.push()
            except (DepotError, OSError):
                pass
            shutil.rmtree(self.folder.parent, ignore_errors=True)


class Ateliers:
    """Les ateliers ouverts, du plus ancien au plus récent."""

    def __init__(
        self,
        depot: Depot,
        make_tools: ToolsFactory,
        work_root: Path | None = None,
        limit: int = MAX_ATELIERS,
    ) -> None:
        self.depot = depot
        self.make_tools = make_tools
        self.work_root = work_root
        self.limit = limit
        self._open: OrderedDict[str, Atelier] = OrderedDict()
        self._lock = threading.Lock()

    def get(
        self,
        visit: Visit,
        grid: Callable[[], str | None],
        save_grid: Callable[[str | None], None],
    ) -> Atelier:
        with self._lock:
            atelier = self._open.get(visit.id)
            if atelier is not None:
                self._open.move_to_end(visit.id)
                return atelier
            while len(self._open) >= self.limit:
                self._open.popitem(last=False)[1].close()
            root = Path(tempfile.mkdtemp(prefix="visite360-atelier-", dir=self.work_root))
            atelier = Atelier(visit, self.depot, root, self.make_tools, grid, save_grid)
            try:
                atelier.open()
            except Exception:
                shutil.rmtree(root, ignore_errors=True)
                raise
            self._open[visit.id] = atelier
            return atelier

    def drop(self, visit_id: str, save: bool = True) -> None:
        """Ferme l'atelier de cette visite : panoramas refaits, ou visite supprimée (`save`
        faux : rien ne doit plus être rangé sous son nom)."""
        with self._lock:
            atelier = self._open.pop(visit_id, None)
        if atelier is not None:
            atelier.close(save)
