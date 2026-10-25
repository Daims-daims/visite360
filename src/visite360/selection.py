"""Étape 7 : sélection d'une surface au clic (D10, D29).

Le modèle de détourage (SAM 2.1, voir `segment.py`) travaille sur une photo ordinaire, pas sur
le panorama, dont les lignes droites sont courbées. On découpe donc dans le panorama une « vue »
carrée, comme si l'on photographiait la direction regardée dans la visionneuse. Les clics y sont
placés, le modèle y trouve le contour de la surface, puis ce contour (le « masque », image en noir
et blanc où blanc veut dire « sélectionné ») est reporté dans le panorama.

Une sélection validée est une opération enregistrée dans `<point>/modifications/` (D9) : un
fichier `selection-<n>.json` (vue, clics, modèle, empreinte du panorama) et son masque
`selection-<n>.png` à la taille du panorama. Le panorama d'origine n'est jamais modifié.
Le format est décrit dans `docs/selection.md`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from visite360 import visite
from visite360.opencv import load_cv2
from visite360.spherical import (
    camera_rotation,
    directions_to_equirect,
    equirect_directions,
    project,
)

VIEW_SIZE = 1024
MIN_FOV, MAX_FOV = 30.0, 120.0
FOLDER = "modifications"
FORMAT_VERSION = 1
PREVIEW_WIDTH = 4096
# Trous de moins de 0,05 % de la vue (environ 22 × 22 pixels) bouchés : ce sont des oublis du
# modèle. Un interrupteur ou une affiche, plus grands, restent hors de la sélection.
HOLE_FRACTION = 0.0005
MAX_CLICKS = 20
ROW_BLOCK = 256
ID_PATTERN = re.compile(r"^selection-(\d+)$")
TINT_BGR = (200, 0, 255)
CONTOUR_BGR = (0, 255, 255)


class SelectionError(Exception):
    """Demande de sélection invalide, ou sélection introuvable."""


class Segmenter(Protocol):
    """Modèle qui trouve un contour à partir de clics (SAM 2.1, ou un modèle simulé en test)."""

    def set_image(self, rgb: np.ndarray) -> None: ...

    def predict(self, points: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, float]: ...


@dataclass(frozen=True)
class ViewSpec:
    """Vue carrée découpée dans le panorama : direction du centre et champ de vision, en degrés.

    Mêmes conventions que la visionneuse : cap 0° au centre du panorama, positif vers la droite ;
    hauteur positive vers le haut. Un pixel (x, y) de la vue a son centre en (x + 0,5, y + 0,5).
    """

    yaw: float
    pitch: float
    fov: float
    size: int = VIEW_SIZE

    def __post_init__(self) -> None:
        values = (self.yaw, self.pitch, self.fov)
        if not all(isinstance(v, int | float) and math.isfinite(v) for v in values):
            raise SelectionError("Vue invalide : cap, hauteur et champ doivent être des nombres.")
        if not -90.0 <= self.pitch <= 90.0:
            raise SelectionError(f"Hauteur de vue hors limites : {self.pitch}°.")
        if not MIN_FOV <= self.fov <= MAX_FOV:
            raise SelectionError(
                f"Champ de vision hors limites : {self.fov}° (de {MIN_FOV:g} à {MAX_FOV:g}°)."
            )

    def intrinsics(self) -> np.ndarray:
        focal = self.size / 2.0 / math.tan(math.radians(self.fov) / 2.0)
        return np.array([[focal, 0.0, self.size / 2.0], [0.0, focal, self.size / 2.0], [0, 0, 1]])

    def rotation(self) -> np.ndarray:
        return camera_rotation(self.yaw, self.pitch)

    def directions(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Directions du monde visées par des positions (x, y) de la vue, en pixels continus."""
        pixels = np.stack([xs, ys, np.ones_like(xs)], axis=-1).astype(np.float64)
        return pixels @ (self.rotation() @ np.linalg.inv(self.intrinsics())).T

    def angles(self, x: float, y: float) -> tuple[float, float]:
        """Cap et hauteur, en degrés, du pixel (x, y) de la vue."""
        d = self.directions(np.array([x + 0.5]), np.array([y + 0.5]))[0]
        d = d / np.linalg.norm(d)
        return math.degrees(math.atan2(d[0], d[2])), math.degrees(math.asin(-d[1]))

    def to_json(self) -> dict[str, Any]:
        return {"cap": self.yaw, "hauteur": self.pitch, "champ": self.fov, "taille": self.size}


@dataclass(frozen=True)
class Click:
    """Clic dans la vue, en pixels : « en plus » (positive) ou « en moins »."""

    x: float
    y: float
    positive: bool

    def to_json(self) -> dict[str, Any]:
        return {"x": round(self.x, 1), "y": round(self.y, 1), "ajout": self.positive}


def parse_clicks(raw: Any, size: int = VIEW_SIZE) -> list[Click]:
    """Lit les clics envoyés par la visionneuse : [{"x", "y", "ajout"}, ...]."""
    if not isinstance(raw, list) or not raw:
        raise SelectionError("Aucun clic reçu.")
    if len(raw) > MAX_CLICKS:
        raise SelectionError(f"Trop de clics ({len(raw)}, au plus {MAX_CLICKS}).")
    clicks = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise SelectionError("Clic illisible.")
        x, y, positive = entry.get("x"), entry.get("y"), entry.get("ajout")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (x, y)):
            raise SelectionError("Clic illisible : x et y doivent être des nombres.")
        if not isinstance(positive, bool):
            raise SelectionError("Clic illisible : « ajout » doit valoir true ou false.")
        if not (0 <= x < size and 0 <= y < size):
            raise SelectionError("Clic en dehors de la vue.")
        clicks.append(Click(float(x), float(y), positive))
    if not any(click.positive for click in clicks):
        raise SelectionError("Il faut au moins un clic « en plus » sur la surface à sélectionner.")
    return clicks


def extract_view(panorama: np.ndarray, spec: ViewSpec) -> np.ndarray:
    """Découpe la vue `spec` dans le panorama (même nombre de canaux que le panorama)."""
    cv2 = load_cv2()
    height, width = panorama.shape[:2]
    centers = np.arange(spec.size) + 0.5
    xs, ys = np.meshgrid(centers, centers)
    coords = directions_to_equirect(spec.directions(xs, ys), width, height).astype(np.float32)
    coords[..., 0] %= width
    # Une colonne recopiée à droite : l'interpolation passe la couture de -180°/180° sans trou.
    wrapped = np.concatenate([panorama, panorama[:, :1]], axis=1)
    return cv2.remap(
        wrapped, coords[..., 0], coords[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )


def _contains(spec: ViewSpec, direction: tuple[float, float, float]) -> bool:
    target = np.array([[direction]], dtype=np.float32)
    x, y, front = project(target, spec.intrinsics(), spec.rotation())
    return bool(front[0, 0]) and 0 <= x[0, 0] <= spec.size and 0 <= y[0, 0] <= spec.size


def footprint(spec: ViewSpec, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Lignes et colonnes du panorama qui peuvent tomber dans la vue.

    Les colonnes peuvent sortir de [0, width) quand la vue chevauche la couture à 180° : elles se
    lisent modulo width. Si la vue contient le zénith ou le nadir, toutes les colonnes y sont.
    """
    margin = 1.0
    samples = np.linspace(0.0, spec.size, 65)
    xs, ys = np.meshgrid(samples, samples)
    d = spec.directions(xs, ys)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    lon = np.degrees(np.arctan2(d[..., 0], d[..., 2]))
    lat = np.degrees(np.arcsin(-d[..., 1]))
    zenith, nadir = _contains(spec, (0.0, -1.0, 0.0)), _contains(spec, (0.0, 1.0, 0.0))
    lat_max = 90.0 if zenith else min(90.0, float(lat.max()) + margin)
    lat_min = -90.0 if nadir else max(-90.0, float(lat.min()) - margin)
    row0 = max(0, math.floor((90.0 - lat_max) / 180.0 * height))
    row1 = min(height, math.ceil((90.0 - lat_min) / 180.0 * height))
    rows = np.arange(row0, row1)
    relative = (lon - spec.yaw + 180.0) % 360.0 - 180.0
    low, high = float(relative.min()) - margin, float(relative.max()) + margin
    if zenith or nadir or high - low >= 360.0:
        return rows, np.arange(width)
    col0 = math.floor((spec.yaw + low + 180.0) / 360.0 * width)
    col1 = math.ceil((spec.yaw + high + 180.0) / 360.0 * width)
    return rows, np.arange(col0, col1)


def to_panorama(view_mask: np.ndarray, spec: ViewSpec, width: int, height: int) -> np.ndarray:
    """Reporte un masque de la vue dans un panorama width × height (uint8, 0 ou 255)."""
    cv2 = load_cv2()
    source = (view_mask > 0).astype(np.float32)
    rows, cols = footprint(spec, width, height)
    out = np.zeros((height, width), dtype=np.uint8)
    K, R = spec.intrinsics(), spec.rotation()
    for start in range(0, len(rows), ROW_BLOCK):
        block = rows[start : start + ROW_BLOCK]
        x, y, front = project(equirect_directions(width, height, block, cols), K, R)
        map_x = np.where(front, x - 0.5, -10.0).astype(np.float32)
        map_y = np.where(front, y - 0.5, -10.0).astype(np.float32)
        values = cv2.remap(
            source, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0
        )
        out[np.ix_(block, cols % width)] = np.where(values >= 0.5, 255, 0).astype(np.uint8)
    return out


def clean_mask(mask: np.ndarray, clicks: Sequence[Click]) -> np.ndarray:
    """Nettoie le masque brut du modèle (uint8, 0 ou 255).

    Garde seulement les morceaux qui contiennent un clic « en plus » (le plus grand si aucun clic
    ne tombe dedans) : cela efface la frange de points isolés que SAM 2 laisse parfois au bord.
    Bouche ensuite les petits trous, sauf ceux où l'on a cliqué « en moins ».
    """
    cv2 = load_cv2()
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count <= 1:
        return np.zeros_like(binary)
    h, w = binary.shape
    inside = [c for c in clicks if 0 <= int(c.y) < h and 0 <= int(c.x) < w]
    keep = {int(labels[int(c.y), int(c.x)]) for c in inside if c.positive} - {0}
    if not keep:
        keep = {int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1}
    kept = np.isin(labels, sorted(keep))

    count, holes, stats, _ = cv2.connectedComponentsWithStats(
        (~kept).astype(np.uint8), connectivity=4
    )
    x, y = stats[:, cv2.CC_STAT_LEFT], stats[:, cv2.CC_STAT_TOP]
    bw, bh = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    border = (x == 0) | (y == 0) | (x + bw == w) | (y + bh == h)
    small = stats[:, cv2.CC_STAT_AREA] < HOLE_FRACTION * h * w
    fill = set(np.flatnonzero(small & ~border).tolist()) - {0}
    fill -= {int(holes[int(c.y), int(c.x)]) for c in inside if not c.positive}
    if fill:
        kept |= np.isin(holes, sorted(fill))
    return kept.astype(np.uint8) * 255


def compute(
    segmenter: Segmenter, view_image: np.ndarray, clicks: Sequence[Click]
) -> tuple[np.ndarray, float]:
    """Masque nettoyé de la vue (uint8) et score de confiance du modèle, de 0 à 1.

    `segmenter.set_image` doit avoir déjà reçu `view_image` : le gros du calcul est là, une fois
    par vue. Chaque série de clics ne coûte ensuite que quelques centièmes de seconde.
    """
    points = np.array([[c.x, c.y] for c in clicks], dtype=np.float32)
    labels = np.array([1 if c.positive else 0 for c in clicks], dtype=np.int32)
    raw, score = segmenter.predict(points, labels)
    if raw.shape != view_image.shape[:2]:
        raise SelectionError("Le modèle a renvoyé un masque de mauvaise taille.")
    return clean_mask(raw.astype(np.uint8) * 255, clicks), float(score)


def overlay_png(view_mask: np.ndarray) -> bytes:
    """Image PNG transparente de la vue : surface teintée et contour, à poser sur la visionneuse."""
    cv2 = load_cv2()
    h, w = view_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    selected = view_mask > 0
    rgba[selected] = (*TINT_BGR, 110)
    contours, _ = cv2.findContours(
        selected.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(rgba, contours, -1, (*CONTOUR_BGR, 255), 3)
    ok, encoded = cv2.imencode(".png", rgba)
    if not ok:
        raise SelectionError("L'écriture de l'aperçu de la sélection a échoué.")
    return encoded.tobytes()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(target: Path, data: bytes) -> None:
    partial = target.with_name(target.name + ".partiel")
    partial.write_bytes(data)
    os.replace(partial, target)


def _check_id(selection_id: str) -> int:
    match = ID_PATTERN.match(selection_id)
    if match is None:
        raise SelectionError(f"Identifiant de sélection invalide : {selection_id!r}.")
    return int(match.group(1))


def _numbers(folder: Path) -> list[int]:
    if not folder.is_dir():
        return []
    found = (ID_PATTERN.match(path.stem) for path in folder.glob("selection-*.json"))
    return [int(match.group(1)) for match in found if match]


def save(
    point: Path,
    panorama: Path,
    mask: np.ndarray,
    spec: ViewSpec,
    clicks: Sequence[Click],
    model: str,
    score: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Enregistre une sélection dans `<point>/modifications/` et renvoie sa fiche."""
    cv2 = load_cv2()
    folder = point / FOLDER
    folder.mkdir(exist_ok=True)
    number = max(_numbers(folder), default=0) + 1
    selection_id = f"selection-{number}"
    ok, encoded = cv2.imencode(".png", mask, [cv2.IMWRITE_PNG_BILEVEL, 1])
    if not ok:
        raise SelectionError("L'écriture du masque a échoué.")
    record = {
        "version": FORMAT_VERSION,
        "type": "selection",
        "id": selection_id,
        "nom": (name or "").strip()[:80] or f"Sélection {number}",
        "creee_le": datetime.now().astimezone().isoformat(timespec="seconds"),
        "panorama_sha256": file_sha256(panorama),
        "masque": f"{selection_id}.png",
        "vue": spec.to_json(),
        "clics": [click.to_json() for click in clicks],
        "modele": model,
        "score": round(score, 3),
    }
    # Le masque d'abord : une fiche présente veut dire une sélection complète.
    write_atomic(folder / record["masque"], encoded.tobytes())
    write_atomic(
        folder / f"{selection_id}.json",
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return record


def list_all(point: Path, panorama: Path) -> list[dict[str, Any]]:
    """Fiches des sélections d'un point, par numéro. « perimee » : le panorama a changé depuis."""
    folder = point / FOLDER
    current = file_sha256(panorama) if panorama.is_file() else None
    records = []
    for number in sorted(_numbers(folder)):
        try:
            record = json.loads((folder / f"selection-{number}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or not (folder / f"selection-{number}.png").is_file():
            continue
        record["perimee"] = record.get("panorama_sha256") != current
        records.append(record)
    return records


def delete(point: Path, selection_id: str) -> None:
    """Annule une sélection : retire sa fiche, son masque et son aperçu.

    Le panorama ne change pas (D9).
    """
    _check_id(selection_id)
    folder = point / FOLDER
    if not (folder / f"{selection_id}.json").is_file():
        raise SelectionError(f"Sélection introuvable : {selection_id}.")
    # La fiche d'abord : sans elle, la sélection n'existe plus, même si la suite échoue.
    for path in (
        folder / f"{selection_id}.json",
        folder / f"{selection_id}.png",
        point / "cache" / f"{selection_id}.jpg",
    ):
        path.unlink(missing_ok=True)


def preview(point: Path, panorama: Path, selection_id: str) -> Path:
    """Panorama réduit avec la sélection teintée, rangé dans `cache/` (refait s'il est périmé)."""
    cv2 = load_cv2()
    _check_id(selection_id)
    mask_path = point / FOLDER / f"{selection_id}.png"
    if not (point / FOLDER / f"{selection_id}.json").is_file() or not mask_path.is_file():
        raise SelectionError(f"Sélection introuvable : {selection_id}.")
    target = point / "cache" / f"{selection_id}.jpg"
    newest = max(mask_path.stat().st_mtime, panorama.stat().st_mtime)
    if target.is_file() and target.stat().st_mtime >= newest:
        return target
    image = cv2.imread(str(panorama))
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        raise SelectionError("Panorama ou masque illisible.")
    width = min(PREVIEW_WIDTH, image.shape[1])
    size = (width, width // 2)
    image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    selected = cv2.resize(mask, size, interpolation=cv2.INTER_AREA) >= 128
    tint = np.array(TINT_BGR, dtype=np.float32)
    image[selected] = (0.5 * image[selected] + 0.5 * tint).astype(np.uint8)
    contours, _ = cv2.findContours(
        selected.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(image, contours, -1, CONTOUR_BGR, 2)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise SelectionError("L'écriture de l'aperçu a échoué.")
    target.parent.mkdir(exist_ok=True)
    write_atomic(target, encoded.tobytes())
    return target


@dataclass
class _OpenView:
    token: str
    point: visite.Point
    spec: ViewSpec
    image: np.ndarray
    shape: tuple[int, int]


class Selector:
    """Sélections en cours dans `visite360 serve` : une vue ouverte à la fois, un seul modèle.

    Le modèle est chargé à la première demande (quelques secondes), puis gardé en mémoire.
    `factory` fabrique le modèle ; les tests en passent un simulé.
    """

    def __init__(
        self,
        tour: visite.Tour,
        factory: Callable[[], Segmenter],
        model_name: str,
        unavailable: str | None = None,
    ) -> None:
        self.tour = tour
        self.factory = factory
        self.model_name = model_name
        self.unavailable = unavailable
        self._lock = threading.Lock()
        self._segmenter: Segmenter | None = None
        self._view: _OpenView | None = None

    def point(self, index: Any) -> visite.Point:
        if not isinstance(index, int) or isinstance(index, bool):
            raise SelectionError("Numéro de point invalide.")
        if not 0 <= index < len(self.tour.points):
            raise SelectionError(f"Point inexistant : {index}.")
        return self.tour.points[index]

    def open_view(self, index: Any, yaw: Any, pitch: Any, fov: Any) -> str:
        """Découpe la vue et la prépare dans le modèle. Renvoie le jeton de la vue."""
        point = self.point(index)
        spec = ViewSpec(yaw, pitch, fov)
        cv2 = load_cv2()
        panorama = cv2.imread(str(point.folders.panorama))
        if panorama is None:
            raise SelectionError(f"Panorama illisible : {point.folders.panorama}")
        image = extract_view(panorama, spec)
        with self._lock:
            if self._segmenter is None:
                self._segmenter = self.factory()
            self._segmenter.set_image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            token = secrets.token_hex(8)
            self._view = _OpenView(token, point, spec, image, panorama.shape[:2])
        return token

    def _current(self, token: Any) -> _OpenView:
        view = self._view
        if view is None or token != view.token:
            raise SelectionError("Cette vue n'est plus ouverte : relancer la sélection.")
        return view

    def mask(self, token: Any, raw_clicks: Any) -> tuple[np.ndarray, float]:
        with self._lock:
            view = self._current(token)
            clicks = parse_clicks(raw_clicks, view.spec.size)
            assert self._segmenter is not None
            return compute(self._segmenter, view.image, clicks)

    def validate(self, token: Any, raw_clicks: Any, name: Any = None) -> dict[str, Any]:
        """Recalcule le masque des clics, le reporte dans le panorama et l'enregistre."""
        if name is not None and not isinstance(name, str):
            raise SelectionError("Nom de sélection invalide.")
        with self._lock:
            view = self._current(token)
            clicks = parse_clicks(raw_clicks, view.spec.size)
            assert self._segmenter is not None
            view_mask, score = compute(self._segmenter, view.image, clicks)
            if not view_mask.any():
                raise SelectionError("La sélection est vide : cliquer sur la surface à garder.")
            height, width = view.shape
            mask = to_panorama(view_mask, view.spec, width, height)
            folders = view.point.folders
            return save(
                folders.point,
                folders.panorama,
                mask,
                view.spec,
                clicks,
                self.model_name,
                score,
                name,
            )
