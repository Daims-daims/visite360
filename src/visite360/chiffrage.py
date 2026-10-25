"""Étape 11 : ordre de grandeur du prix des modifications d'une visite (D36).

Le but n'est pas un devis mais un ordre d'idée : chaque prix est une fourchette, basse et haute,
tirée d'une grille modifiable (`tarifs.json` dans le dossier de la visite, sinon la grille par
défaut de ce module, aux prix indicatifs TTC publiés par des guides de travaux).

**Surface repeinte.** Une recoloration (étape 8) désigne une sélection (étape 7), dont le masque
dit quels pixels du panorama changent. Chaque pixel est une petite direction de vue depuis
l'objectif. La pièce mesurée à l'étape 10 dit où cette direction rencontre la pièce : un mur, le
sol ou le plafond, et à quelle distance. L'aire réelle couverte par le pixel grandit avec le carré
de cette distance, et encore quand la surface est vue de biais :

    aire = distance² × angle solide du pixel / cos(angle entre la vue et la perpendiculaire)

La somme sur le masque donne les m² repeints, mur par mur, au sol et au plafond. Les portes et
fenêtres laissées hors de la sélection ne sont donc pas comptées. Une surface sans pièce mesurée
n'a pas de prix : la ligne le dit, et le total est marqué incomplet.

**Objet remplacé.** Une génération (étape 9) est chiffrée au forfait, selon le type d'objet
reconnu dans sa consigne par une simple recherche de mots (« canapé », « table basse »…), dans la
partie qui suit « par » quand elle existe (« Remplace le canapé par un fauteuil » : un fauteuil).
L'agent peut corriger le type ; sa correction est rangée dans `modifications/chiffrage.json` du
point. Sans mot reconnu, c'est la ligne « autre » de la grille.

Le calcul des surfaces est mis de côté dans `cache/chiffrage.json` du point, refait quand le
masque ou la pièce change. Rien n'est modifié dans les photos ni les panoramas (D9).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from visite360 import couleur, generation, piece, selection
from visite360.opencv import load_cv2

GRID_NAME = "tarifs.json"
OVERRIDES_NAME = "chiffrage.json"
CACHE_NAME = "chiffrage.json"
FORMAT_VERSION = 1
# À augmenter quand le calcul des surfaces change : les surfaces mises de côté sont refaites.
ALGORITHM_VERSION = 1
# Largeur de travail du masque : 2048 pixels suffisent à 1 % près, et le calcul reste instantané.
WORK_WIDTH = 2048
# Une partie de sélection plus petite que ça (un débord sur le sol, au pied du mur) est ignorée.
MIN_PART_M2 = 0.1
# Évite une aire infinie pour un rayon qui longe presque un mur.
MIN_COSINE = 0.05
SURFACES = ("mur", "plafond", "sol")
OTHER = "autre"
MAX_PRICE = 1_000_000
MAX_NAME = 80
MAX_WORDS = 20

SOURCES = [
    {
        "titre": "Prix de la peinture au m² en 2026, Travaux.com",
        "adresse": "https://www.travaux.com/peinture/guide-des-prix/peinture-tva",
    },
    {
        "titre": "Prix peinture au m² : quel budget prévoir en 2026 ?, La Maison Saint-Gobain",
        "adresse": "https://www.lamaisonsaintgobain.fr/guides-travaux/amenagement-interieur/prix-peinture-au-m2",
    },
    {
        "titre": "Prix de pose d'un lino au m², La Maison Saint-Gobain",
        "adresse": "https://www.lamaisonsaintgobain.fr/guides-travaux/amenagement-interieur/prix-pose-lino",
    },
    {
        "titre": "Combien coûte la pose d'un parquet au m² en 2026 ?, Obat",
        "adresse": "https://travaux.obat.fr/guides/prix-pose-parquet/",
    },
    {
        "titre": "Grille tarifaire de l'équipement de première nécessité, CAF (juillet 2025)",
        "adresse": "https://www.caf.fr/sites/default/files/medias/351/Offre-de-service/logement/aide-equipement-premiere-necessite/RI-AFI_grille-tarifaire-equipement-premiere-necessite.pdf",
    },
]


def _furniture(key: str, name: str, words: list[str], low: int, high: int) -> dict[str, Any]:
    return {"id": key, "nom": name, "mots": words, "bas": low, "haut": high}


# Prix indicatifs TTC, relevés le 2026-10-26 (sources ci-dessus). Peinture : fournie et posée, sur
# un support en bon état. Sol : nouveau revêtement, du stratifié au vinyle, fourni et posé.
# Meubles : achat seul, sans livraison ; le bas suit les plafonds de la CAF pour un équipement
# d'entrée de gamme, le haut est une estimation du projet pour du milieu de gamme.
DEFAULT_GRID: dict[str, Any] = {
    "version": FORMAT_VERSION,
    "type": "tarifs",
    "note": "Prix indicatifs TTC relevés le 2026-10-26, à remplacer par les vôtres.",
    "surfaces": {
        "mur": {"nom": "Peinture des murs, fournie et posée", "bas": 20, "haut": 50},
        "plafond": {"nom": "Peinture du plafond, fournie et posée", "bas": 30, "haut": 50},
        "sol": {"nom": "Nouveau revêtement de sol, fourni et posé", "bas": 35, "haut": 110},
    },
    "meubles": [
        _furniture("canape", "Canapé", ["canapé", "sofa", "banquette", "méridienne"], 500, 2000),
        _furniture("fauteuil", "Fauteuil", ["fauteuil", "bergère", "pouf"], 150, 800),
        _furniture("table_basse", "Table basse", ["table basse", "table de salon"], 100, 500),
        _furniture("table", "Table", ["table", "console"], 300, 1200),
        _furniture("chaise", "Chaise", ["chaise", "tabouret"], 50, 200),
        _furniture("lit", "Lit", ["lit", "matelas"], 350, 1500),
        _furniture("armoire", "Armoire", ["armoire", "penderie", "dressing"], 300, 1500),
        _furniture(
            "rangement",
            "Buffet, commode, bibliothèque",
            ["buffet", "commode", "bibliothèque", "étagère", "meuble tv", "vaisselier", "bahut"],
            200,
            1200,
        ),
        _furniture("bureau", "Bureau", ["bureau"], 150, 700),
        _furniture(
            "luminaire",
            "Luminaire",
            ["lampe", "lampadaire", "suspension", "lustre", "applique"],
            50,
            400,
        ),
        _furniture("tapis", "Tapis", ["tapis"], 100, 600),
        _furniture("rideaux", "Rideaux", ["rideau", "voilage", "store"], 50, 300),
        _furniture("plante", "Plante", ["plante", "arbre", "palmier"], 30, 200),
        _furniture(
            "decoration", "Tableau, miroir, décoration", ["tableau", "miroir", "cadre"], 30, 300
        ),
        _furniture(OTHER, "Autre objet", [], 200, 1000),
    ],
    "sources": SOURCES,
}


class ChiffrageError(Exception):
    """Grille de prix mal formée, ou demande de chiffrage invalide, avec un message en français."""


# --- Grille de prix ----------------------------------------------------------------------


def _price(raw: Any, where: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ChiffrageError(f"{where} : un nombre d'euros est attendu.")
    if not 0 <= raw <= MAX_PRICE:
        raise ChiffrageError(f"{where} : prix hors limites ({raw}).")
    return float(raw)


def _name(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ChiffrageError(f"{where} : un nom est attendu.")
    return " ".join(raw.split())[:MAX_NAME]


def _range(entry: Any, where: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ChiffrageError(f"{where} : fiche illisible.")
    low, high = (
        _price(entry.get("bas"), f"{where}, prix bas"),
        _price(entry.get("haut"), f"{where}, prix haut"),
    )
    if low > high:
        raise ChiffrageError(f"{where} : le prix bas dépasse le prix haut.")
    return {"nom": _name(entry.get("nom"), where), "bas": low, "haut": high}


def parse_grid(raw: Any) -> dict[str, Any]:
    """Vérifie une grille de prix et la renvoie nettoyée. Refuse toute grille mal formée."""
    if not isinstance(raw, dict) or raw.get("version") != FORMAT_VERSION:
        raise ChiffrageError("Grille de prix : format inconnu.")
    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, dict) or set(surfaces) != set(SURFACES):
        raise ChiffrageError(
            "Grille de prix : il faut un prix pour « mur », « plafond » et « sol »."
        )
    clean_surfaces = {key: _range(surfaces[key], f"Surface « {key} »") for key in SURFACES}
    furniture = raw.get("meubles")
    if not isinstance(furniture, list) or not furniture:
        raise ChiffrageError("Grille de prix : la liste des meubles manque.")
    seen: set[str] = set()
    clean_furniture = []
    for number, entry in enumerate(furniture, start=1):
        where = f"Meuble {number}"
        key = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,40}", key):
            raise ChiffrageError(f"{where} : identifiant invalide.")
        if key in seen:
            raise ChiffrageError(f"{where} : identifiant « {key} » en double.")
        seen.add(key)
        words = entry.get("mots", [])
        if (
            not isinstance(words, list)
            or len(words) > MAX_WORDS
            or not all(isinstance(w, str) and w.strip() for w in words)
        ):
            raise ChiffrageError(f"{where} : « mots » doit être une liste de mots.")
        item = _range(entry, f"Meuble « {key} »")
        clean_furniture.append({"id": key, **item, "mots": [" ".join(w.split()) for w in words]})
    if OTHER not in seen:
        raise ChiffrageError(f"Grille de prix : la ligne « {OTHER} » des meubles manque.")
    clean: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "type": "tarifs",
        "surfaces": clean_surfaces,
        "meubles": clean_furniture,
    }
    for key in ("note", "sources"):
        if key in raw:
            clean[key] = raw[key]
    return clean


def grid_path(folder: Path) -> Path:
    return folder / GRID_NAME


def load_grid(folder: Path) -> tuple[dict[str, Any], bool]:
    """Grille de la visite, ou la grille par défaut. Renvoie (grille, est la grille par défaut)."""
    path = grid_path(folder)
    if not path.is_file():
        return parse_grid(DEFAULT_GRID), True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ChiffrageError(f"{GRID_NAME} illisible ({error}).") from error
    try:
        return parse_grid(raw), False
    except ChiffrageError as error:
        raise ChiffrageError(f"{GRID_NAME} : {error}") from error


def save_grid(folder: Path, raw: Any) -> dict[str, Any]:
    """Vérifie et enregistre la grille de la visite."""
    grid = parse_grid(raw)
    data = json.dumps(grid, ensure_ascii=False, indent=2) + "\n"
    selection.write_atomic(grid_path(folder), data.encode("utf-8"))
    return grid


def reset_grid(folder: Path) -> None:
    """Revient à la grille par défaut."""
    grid_path(folder).unlink(missing_ok=True)


# --- Surface touchée ---------------------------------------------------------------------


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def wall_hits(
    plan: np.ndarray, longitudes: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pour chaque direction horizontale (cap en radians), le premier mur rencontré.

    Renvoie (distance horizontale en mètres, numéro du mur à partir de 0, cosinus entre la
    direction et la perpendiculaire au mur). La distance vaut `inf` si aucun mur n'est rencontré :
    l'objectif est alors hors du contour de la pièce dans cette direction.
    """
    u = np.stack([np.sin(longitudes), np.cos(longitudes)], axis=-1)[:, None, :]
    a = plan[None, :, :]
    edge = np.roll(plan, -1, axis=0)[None, :, :] - a
    denom = _cross(u, edge)
    safe = np.where(np.abs(denom) < 1e-12, np.nan, denom)
    distance = _cross(a, edge) / safe
    along = _cross(a, u) / safe
    valid = (distance > 1e-9) & (along >= -1e-9) & (along <= 1 + 1e-9)
    distance = np.where(valid, distance, np.inf)
    wall = np.argmin(distance, axis=1)
    best = distance[np.arange(len(longitudes)), wall]
    lengths = np.hypot(edge[0, :, 0], edge[0, :, 1])
    normal = np.stack([-edge[0, :, 1], edge[0, :, 0]], axis=-1) / lengths[:, None]
    cosine = np.abs(np.sum(u[:, 0, :] * normal[wall], axis=-1))
    return best, wall, cosine


def surface_areas(coverage: np.ndarray, room: piece.Room) -> dict[str, float]:
    """m² de la pièce couverts par un masque de panorama (valeurs de 0 à 1, taille quelconque).

    Clés : « mur-1 », « mur-2 »… (numéros de l'étape 10), « sol », « plafond ». Seules les
    surfaces touchées apparaissent.
    """
    height, width = coverage.shape
    rows, cols = np.nonzero(coverage > 0)
    if rows.size == 0:
        return {}
    weight = coverage[rows, cols].astype(np.float64)
    used = np.unique(cols)
    lon = (used + 0.5) / width * 2.0 * np.pi - np.pi
    distance, wall, cosine = wall_hits(room.plan, lon)
    if np.isinf(distance).any():
        raise ChiffrageError(
            "L'objectif est hors du contour de la pièce mesurée : refaire la mesure en cliquant "
            "les coins tout autour de la pièce."
        )
    lookup = np.searchsorted(used, cols)
    horizontal, wall, cosine = (
        distance[lookup],
        wall[lookup],
        np.maximum(cosine[lookup], MIN_COSINE),
    )

    theta = (rows + 0.5) / height * np.pi
    sin_t, down = np.sin(theta), -np.cos(theta)  # down : composante verticale, y vers le bas
    solid_angle = (2.0 * np.pi / width) * (np.pi / height) * sin_t
    # Distance le long de la vue jusqu'au mur, puis hauteur atteinte (y vers le bas, objectif à 0).
    to_wall = horizontal / np.maximum(sin_t, 1e-12)
    y = to_wall * down
    floor_y, ceiling_y = room.lens_height, room.lens_height - room.ceiling_height
    on_floor, on_ceiling = y > floor_y, y < ceiling_y
    on_wall = ~(on_floor | on_ceiling)
    safe_down = np.where(np.abs(down) < 1e-12, 1e-12, down)

    areas: dict[str, float] = {}
    if on_wall.any():
        r = to_wall[on_wall]
        dA = r * r * solid_angle[on_wall] / (sin_t[on_wall] * cosine[on_wall]) * weight[on_wall]
        sums = np.bincount(wall[on_wall], weights=dA, minlength=len(room.plan))
        for index, total in enumerate(sums):
            if total > 0:
                areas[f"mur-{index + 1}"] = float(total)
    for key, mask, level in (("sol", on_floor, floor_y), ("plafond", on_ceiling, ceiling_y)):
        if mask.any():
            r = level / safe_down[mask]
            dA = r * r * solid_angle[mask] / np.abs(down[mask]) * weight[mask]
            areas[key] = float(dA.sum())
    return areas


def _read_coverage(mask_path: Path) -> np.ndarray:
    cv2 = load_cv2()
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ChiffrageError(f"Masque illisible : {mask_path.name}.")
    if mask.shape[1] > WORK_WIDTH:
        mask = cv2.resize(mask, (WORK_WIDTH, WORK_WIDTH // 2), interpolation=cv2.INTER_AREA)
    return mask.astype(np.float32) / 255.0


def _signature(mask_path: Path, room_path: Path) -> str:
    stat = mask_path.stat()
    digest = hashlib.sha256(f"{ALGORITHM_VERSION}:{stat.st_mtime_ns}:{stat.st_size}:".encode())
    digest.update(room_path.read_bytes())
    return digest.hexdigest()


def selection_areas(point: Path, room: piece.Room, mask_path: Path) -> dict[str, float]:
    """Surfaces couvertes par le masque d'une sélection du point, mises de côté dans `cache/`."""
    signature = _signature(mask_path, point / piece.FILE_NAME)
    cache_path = point / "cache" / CACHE_NAME
    try:
        saved = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    entry = saved.get(mask_path.stem)
    if isinstance(entry, dict) and entry.get("signature") == signature:
        return dict(entry["surfaces"])
    areas = surface_areas(_read_coverage(mask_path), room)
    saved[mask_path.stem] = {"signature": signature, "surfaces": areas}
    cache_path.parent.mkdir(exist_ok=True)
    selection.write_atomic(cache_path, json.dumps(saved).encode("utf-8"))
    return areas


# --- Objets remplacés --------------------------------------------------------------------


def _plain(text: str) -> str:
    """Minuscules sans accents, pour comparer des mots."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def guess_category(instruction: str, grid: dict[str, Any]) -> str:
    """Type d'objet nommé par la consigne, ou « autre ».

    On regarde d'abord ce qui suit le dernier « par » (le nouvel objet), sinon toute la consigne.
    Le mot trouvé le plus tôt l'emporte ; à égalité, le plus long (« table basse » avant
    « table »).
    """
    text = _plain(instruction)
    parts = re.split(r"\bpar\b", text)
    for chunk in ([parts[-1]] if len(parts) > 1 else []) + [text]:
        best: tuple[int, int, str] | None = None
        for item in grid["meubles"]:
            for word in item["mots"]:
                match = re.search(rf"\b{re.escape(_plain(word))}s?\b", chunk)
                if match:
                    candidate = (match.start(), -len(word), item["id"])
                    if best is None or candidate < best:
                        best = candidate
        if best is not None:
            return best[2]
    return OTHER


def _overrides_path(point: Path) -> Path:
    return point / selection.FOLDER / OVERRIDES_NAME


def load_overrides(point: Path) -> dict[str, str]:
    """Types d'objet choisis par l'agent, par génération."""
    path = _overrides_path(point)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}
    chosen = data.get("meubles") if isinstance(data, dict) else None
    if not isinstance(chosen, dict):
        return {}
    return {k: v for k, v in chosen.items() if isinstance(k, str) and isinstance(v, str)}


def _save_overrides(point: Path, chosen: dict[str, str]) -> None:
    path = _overrides_path(point)
    if not chosen:
        path.unlink(missing_ok=True)
        return
    record = {"version": FORMAT_VERSION, "type": "chiffrage", "meubles": chosen}
    path.parent.mkdir(exist_ok=True)
    selection.write_atomic(path, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))


def set_category(point: Path, grid: dict[str, Any], generation_id: Any, category: Any) -> None:
    """Fixe le type d'objet d'une génération, ou revient au type reconnu (`category` à None)."""
    generation.find(point, generation_id)
    chosen = load_overrides(point)
    if category is None:
        chosen.pop(generation_id, None)
    else:
        if category not in {item["id"] for item in grid["meubles"]}:
            raise ChiffrageError(f"Type d'objet inconnu : {category!r}.")
        chosen[generation_id] = category
    _save_overrides(point, chosen)


def forget(point: Path, generation_id: str) -> None:
    """Oublie le type choisi pour une génération supprimée (son numéro peut resservir)."""
    chosen = load_overrides(point)
    if chosen.pop(generation_id, None) is not None:
        _save_overrides(point, chosen)


# --- Chiffrage ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PointInput:
    """Ce qu'il faut pour chiffrer un point : son nom et ses dossiers."""

    name: str
    point: Path
    panorama: Path


def _money(value: float) -> float:
    return round(value, 2)


def _wall_list(numbers: list[int]) -> str:
    if len(numbers) == 1:
        return f"mur {numbers[0]}"
    return "murs " + ", ".join(map(str, numbers[:-1])) + f" et {numbers[-1]}"


def _selection_name(point: Path, selection_id: str) -> str:
    path = point / selection.FOLDER / f"{selection_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return selection_id
    name = record.get("nom") if isinstance(record, dict) else None
    return name if isinstance(name, str) and name else selection_id


def _color_lines(
    point: Path,
    room: piece.Room | None,
    problem: str | None,
    grid: dict[str, Any],
    op: couleur.Operation,
) -> list[dict[str, Any]]:
    record = op.record
    base = {
        "modification": record.get("id"),
        "nom": _selection_name(point, record["selection"]),
        "type": "couleur",
        "couleur": record.get("couleur"),
    }
    if room is None:
        return [{**base, "probleme": problem, "bas": None, "haut": None}]
    areas = selection_areas(point, room, op.mask_path)
    parts: dict[str, float] = {}
    walls: list[int] = []
    for key, area in areas.items():
        kind = "mur" if key.startswith("mur-") else key
        parts[kind] = parts.get(kind, 0.0) + area
        if kind == "mur" and area >= MIN_PART_M2:
            walls.append(int(key.split("-")[1]))
    kept = {kind: area for kind, area in parts.items() if area >= MIN_PART_M2}
    if not kept and parts:
        kind = max(parts, key=parts.__getitem__)
        kept = {kind: parts[kind]}
    lines = []
    for kind in SURFACES:
        if kind not in kept:
            continue
        price = grid["surfaces"][kind]
        area = kept[kind]
        line = {
            **base,
            "poste": kind,
            "libelle": price["nom"],
            "quantite": round(area, 1),
            "unite": "m²",
            "prix_bas": price["bas"],
            "prix_haut": price["haut"],
            "bas": _money(area * price["bas"]),
            "haut": _money(area * price["haut"]),
        }
        if kind == "mur" and walls:
            line["detail"] = _wall_list(sorted(walls))
        lines.append(line)
    if not lines:
        lines.append(
            {**base, "probleme": "La sélection ne touche aucune surface.", "bas": 0.0, "haut": 0.0}
        )
    return lines


def _generation_line(
    grid: dict[str, Any], overrides: dict[str, str], op: generation.Operation
) -> dict[str, Any]:
    record = op.record
    by_id = {item["id"]: item for item in grid["meubles"]}
    guessed = guess_category(f"{record.get('instruction', '')}", grid)
    chosen = overrides.get(record["id"])
    category = chosen if chosen in by_id else guessed
    item = by_id[category]
    return {
        "modification": record["id"],
        "nom": record.get("nom", record["id"]),
        "type": "generation",
        "poste": "meuble",
        "categorie": category,
        "categorie_reconnue": guessed,
        "categorie_choisie": category if chosen in by_id else None,
        "libelle": item["nom"],
        "quantite": 1,
        "unite": "objet",
        "prix_bas": item["bas"],
        "prix_haut": item["haut"],
        "bas": _money(item["bas"]),
        "haut": _money(item["haut"]),
    }


def estimate_point(source: PointInput, grid: dict[str, Any]) -> dict[str, Any]:
    """Lignes et total d'un point."""
    problem: str | None = None
    try:
        room, stale = piece.load_room(source.point, source.panorama)
    except piece.PieceError as error:
        room, stale, problem = None, False, f"Pièce illisible : {error}"
    if room is None and problem is None:
        problem = "Pièce pas encore mesurée : l'agent la mesure à l'adresse /agent."
    lines: list[dict[str, Any]] = []
    for op in couleur.operations(source.point):
        try:
            lines += _color_lines(source.point, room, problem, grid, op)
        except ChiffrageError as error:
            lines.append(
                {
                    "modification": op.record.get("id"),
                    "nom": op.record.get("id"),
                    "type": "couleur",
                    "probleme": str(error),
                    "bas": None,
                    "haut": None,
                }
            )
    overrides = load_overrides(source.point)
    for gen in generation.operations(source.point):
        lines.append(_generation_line(grid, overrides, gen))
    priced = [line for line in lines if line["bas"] is not None]
    return {
        "nom": source.name,
        "piece_mesuree": room is not None,
        "piece_perimee": stale,
        "lignes": lines,
        "bas": _money(sum(line["bas"] for line in priced)),
        "haut": _money(sum(line["haut"] for line in priced)),
        "complet": len(priced) == len(lines),
    }


def estimate(points: list[PointInput], folder: Path) -> dict[str, Any]:
    """Chiffrage de toute la visite : un bloc par point, total de la visite, grille utilisée."""
    grid, default = load_grid(folder)
    blocks = [estimate_point(source, grid) for source in points]
    return {
        "points": blocks,
        "bas": _money(sum(block["bas"] for block in blocks)),
        "haut": _money(sum(block["haut"] for block in blocks)),
        "complet": all(block["complet"] for block in blocks),
        "tarifs_par_defaut": default,
    }


# --- Ligne de commande -------------------------------------------------------------------


def euros(value: float) -> str:
    """Montant arrondi à la dizaine d'euros : c'est un ordre de grandeur."""
    rounded = int(round(value / 10.0)) * 10 if value >= 100 else int(round(value))
    return f"{rounded:,}".replace(",", " ") + " €"


def _surface(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def describe(result: dict[str, Any]) -> list[str]:
    """Le chiffrage en lignes de texte, pour le terminal."""
    lines = []
    for block in result["points"]:
        lines.append(f"{block['nom']} :")
        if not block["lignes"]:
            lines.append("  aucune modification")
        for line in block["lignes"]:
            if line["bas"] is None:
                lines.append(f"  {line['nom']} : pas de prix. {line['probleme']}")
            elif line["poste"] == "meuble":
                lines.append(
                    f"  {line['nom']} : {line['libelle']}, "
                    f"{euros(line['bas'])} à {euros(line['haut'])}"
                )
            else:
                where = f" ({line['detail']})" if "detail" in line else ""
                lines.append(
                    f"  {line['nom']} : {line['libelle']}, {_surface(line['quantite'])} m²{where}, "
                    f"{euros(line['bas'])} à {euros(line['haut'])}"
                )
        if block["piece_perimee"]:
            lines.append("  Attention : panorama refait depuis la mesure de la pièce.")
    total = f"Total : de {euros(result['bas'])} à {euros(result['haut'])}"
    if not result["complet"]:
        total += ", sans les modifications qui n'ont pas de prix"
    lines.append(total + ".")
    if result["tarifs_par_defaut"]:
        lines.append("Prix indicatifs par défaut : à remplacer par les vôtres (docs/chiffrage.md).")
    return lines


def run(target: Path, out: TextIO | None = None) -> int:
    """Point d'entrée de `visite360 chiffrage`. Renvoie le code de sortie."""
    from visite360 import stitch, visite

    out = out or sys.stdout
    try:
        tour, _ = visite.open_tour(target)
        points = [
            PointInput(point.name, point.folders.point, point.folders.panorama)
            for point in tour.points
        ]
        folder = tour.folder or target
        result = estimate(points, folder)
    except (visite.VisiteError, stitch.StitchError, ChiffrageError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    for line in describe(result):
        print(line, file=out)
    return 0
