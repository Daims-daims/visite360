"""Étape 4 : lecture et validation de `visite.json`, qui décrit une visite de plusieurs points.

Un dossier de visite contient un dossier par point (`visites/<visite>/<point>/`, avec `photos/`
et plus tard `panorama.jpg`) et un fichier `visite.json` qui déclare à la main les points et les
liens entre eux (D14). Si le fichier n'existe pas, il est créé avec un point par dossier et
aucun lien : il ne reste qu'à y ajouter les liens. Un fichier existant n'est jamais réécrit.

Les angles sont des degrés dans le repère de la visionneuse : 0° est le centre de l'image du
panorama (la direction vers laquelle la vue s'ouvre), positif vers la droite, négatif vers la
gauche, 180° est derrière. La visionneuse affiche l'angle de la direction regardée, pour le
lire en visant une porte au lieu de le calculer.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from visite360 import stitch

FILE_NAME = "visite.json"
FORMAT_VERSION = 1
DEFAULT_LINK_PITCH = -10.0

TOP_KEYS = {"version", "nom", "depart", "points", "liens"}
POINT_KEYS = {"id", "nom", "nord", "position"}
LINK_KEYS = {"de", "vers", "angle", "hauteur", "texte"}


class VisiteError(Exception):
    """`visite.json` ou le dossier de la visite est inutilisable."""


@dataclass(frozen=True)
class Point:
    id: str
    name: str
    folders: stitch.Folders
    # Champs facultatifs, lus mais pas utilisés (D26) : cap de la boussole vers lequel le
    # panorama a été pris, position du point en mètres.
    north: float | None = None
    position: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    angle: float
    pitch: float
    text: str


@dataclass(frozen=True)
class Tour:
    name: str
    start: str
    points: tuple[Point, ...]
    links: tuple[Link, ...]
    ignored: tuple[str, ...] = ()

    def links_from(self, point_id: str) -> list[Link]:
        return [link for link in self.links if link.source == point_id]


def _natural_key(text: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def point_folders(folder: Path) -> list[str]:
    """Noms des sous-dossiers qui ressemblent à un point, dans l'ordre naturel (2 avant 10)."""
    names = [
        child.name
        for child in folder.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and ((child / "photos").is_dir() or (child / "panorama.jpg").is_file())
    ]
    return sorted(names, key=_natural_key)


def looks_like_tour(folder: Path) -> bool:
    """Vrai si le dossier est une visite (fichier `visite.json` ou sous-dossiers de points)."""
    if not folder.is_dir():
        return False
    if (folder / FILE_NAME).is_file():
        return True
    if (folder / "photos").is_dir() or folder.name == "photos":
        return False
    return bool(point_folders(folder))


def single_point(folders: stitch.Folders) -> Tour:
    """Visite d'un seul point, sans fichier : le comportement de l'étape 3."""
    name = folders.point.resolve().name
    point = Point(name, name, folders)
    return Tour(name, name, (point,), ())


def write_skeleton(folder: Path) -> Path:
    """Crée `visite.json` avec un point par dossier et aucun lien. N'écrase jamais un fichier."""
    names = point_folders(folder)
    if not names:
        raise VisiteError(
            f"Aucun point trouvé dans {folder}. Organisation attendue : "
            "visites/<visite>/<point>/photos/."
        )
    content = {
        "version": FORMAT_VERSION,
        "nom": folder.resolve().name,
        "depart": names[0],
        "points": [{"id": name} for name in names],
        "liens": [],
    }
    target = folder / FILE_NAME
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as error:
        raise VisiteError(f"{target} existe déjà et n'est pas réécrit.") from error
    return target


def _number(value: Any, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise VisiteError(f"{where} : un nombre est attendu (reçu {value!r}).")
    if not low <= value <= high:
        raise VisiteError(f"{where} : {value} est hors de la plage de {low:g} à {high:g} degrés.")
    return float(value)


def _normalize_angle(angle: float) -> float:
    """Ramène un angle dans ]-180, 180]."""
    wrapped = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def _check_keys(entry: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise VisiteError(
            f"{where} : clé inconnue « {unknown[0]} ». "
            f"Clés possibles : {', '.join(sorted(allowed))}."
        )


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VisiteError(f"{where} : « {key} » est obligatoire (du texte non vide).")
    return value.strip()


def _parse_points(raw: Any, folder: Path) -> list[Point]:
    if not isinstance(raw, list) or not raw:
        raise VisiteError("« points » doit être une liste d'au moins un point.")
    points: list[Point] = []
    seen: set[str] = set()
    for number, entry in enumerate(raw, start=1):
        where = f"Point n° {number}"
        if not isinstance(entry, dict):
            raise VisiteError(f"{where} : un objet {{...}} est attendu.")
        _check_keys(entry, POINT_KEYS, where)
        point_id = _text(entry, "id", where)
        if point_id in seen:
            raise VisiteError(f"Le point « {point_id} » est déclaré deux fois.")
        seen.add(point_id)
        if "/" in point_id or "\\" in point_id or point_id.startswith("."):
            raise VisiteError(f"Point « {point_id} » : l'id doit être le nom d'un dossier.")
        point_folder = folder / point_id
        if not point_folder.is_dir():
            raise VisiteError(f"Point « {point_id} » : le dossier {point_folder} n'existe pas.")
        name = _text(entry, "nom", where) if "nom" in entry else point_id
        north = (
            _number(entry["nord"], f"Point « {point_id} », nord", -360, 360)
            if entry.get("nord") is not None
            else None
        )
        position = None
        if entry.get("position") is not None:
            coords = entry["position"]
            if not isinstance(coords, list) or len(coords) not in (2, 3):
                raise VisiteError(f"Point « {point_id} » : « position » est [x, y] ou [x, y, z].")
            position = tuple(
                _number(c, f"Point « {point_id} », position", -1e6, 1e6) for c in coords
            )
        folders = stitch.Folders(point_folder, point_folder / "photos")
        points.append(Point(point_id, name, folders, north, position))
    return points


def _parse_links(raw: Any, ids: set[str], names: dict[str, str]) -> list[Link]:
    if not isinstance(raw, list):
        raise VisiteError("« liens » doit être une liste.")
    links: list[Link] = []
    for number, entry in enumerate(raw, start=1):
        where = f"Lien n° {number}"
        if not isinstance(entry, dict):
            raise VisiteError(f"{where} : un objet {{...}} est attendu.")
        _check_keys(entry, LINK_KEYS, where)
        source, target = _text(entry, "de", where), _text(entry, "vers", where)
        for end, key in ((source, "de"), (target, "vers")):
            if end not in ids:
                raise VisiteError(
                    f"{where} : « {key} » désigne le point « {end} », qui n'existe pas. "
                    f"Points connus : {', '.join(sorted(ids))}."
                )
        if source == target:
            raise VisiteError(f"{where} : un point ne peut pas être relié à lui-même.")
        if "angle" not in entry:
            raise VisiteError(f"{where} : « angle » est obligatoire.")
        angle = _normalize_angle(_number(entry["angle"], f"{where}, angle", -360, 360))
        pitch = (
            _number(entry["hauteur"], f"{where}, hauteur", -90, 90)
            if entry.get("hauteur") is not None
            else DEFAULT_LINK_PITCH
        )
        text = _text(entry, "texte", where) if "texte" in entry else names[target]
        links.append(Link(source, target, angle, pitch, text))
    return links


def load(folder: Path) -> Tour:
    """Lit `visite.json` du dossier et le valide. Les erreurs sont des `VisiteError`."""
    path = folder / FILE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise VisiteError(f"Lecture impossible de {path} : {error.strerror}.") from error
    except json.JSONDecodeError as error:
        raise VisiteError(
            f"{path} n'est pas un JSON valide (ligne {error.lineno}, colonne {error.colno} : "
            f"{error.msg}). Une virgule oubliée ou en trop est la cause la plus fréquente."
        ) from error
    if not isinstance(raw, dict):
        raise VisiteError(f"{path} doit contenir un objet {{...}}.")
    _check_keys(raw, TOP_KEYS, path.name)
    version = raw.get("version", FORMAT_VERSION)
    if version != FORMAT_VERSION:
        raise VisiteError(
            f"{path.name} : version {version!r} non gérée (attendu {FORMAT_VERSION})."
        )
    points = _parse_points(raw.get("points"), folder)
    ids = {point.id for point in points}
    start = raw.get("depart", points[0].id)
    if start not in ids:
        raise VisiteError(f"« depart » désigne le point « {start} », qui n'existe pas.")
    links = _parse_links(raw.get("liens", []), ids, {p.id: p.name for p in points})
    name = raw.get("nom") or folder.resolve().name
    if not isinstance(name, str):
        raise VisiteError("« nom » doit être du texte.")
    ignored = tuple(sorted(set(point_folders(folder)) - ids, key=_natural_key))
    return Tour(name, start, tuple(points), tuple(links), ignored)


def open_tour(target: Path) -> tuple[Tour, bool]:
    """Ouvre ce que `serve` reçoit : un dossier de visite ou un dossier de point.

    Renvoie la visite et un indicateur « `visite.json` vient d'être créé ».
    """
    if looks_like_tour(target):
        created = not (target / FILE_NAME).is_file()
        if created:
            write_skeleton(target)
        return load(target), created
    return single_point(stitch.resolve_folders(target)), False
