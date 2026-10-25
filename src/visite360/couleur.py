"""Étape 8 : changement de couleur d'une surface sélectionnée, sans IA générative (D11, D30).

Deux temps :

1. **Accrocher le contour aux bords réels.** Le contour trouvé à l'étape 7 suit mal les bords peu
   marqués (porte blanche sur mur blanc) et, reporté dans le panorama, il est agrandi en marches
   d'escalier. Un « filtre guidé » le recale sur les bords visibles de la photo (ligne d'ombre,
   cadre de porte) : autour de chaque point du contour, dans un rayon de 1,4° (32 pixels sur un
   panorama de 8192), il cherche quelle limite de clarté explique le mieux le masque. Au-delà de
   ce rayon, rien ne bouge.
2. **Repeindre en lumière linéaire.** Les valeurs d'un JPEG sont compressées pour l'œil ; on les
   ramène d'abord à la quantité de lumière reçue par le capteur. Chaque pixel du mur y vaut
   « couleur de la peinture × éclairage reçu ». On divise par la couleur de peinture actuelle du
   mur, ce qui laisse l'éclairage seul, avec ses ombres, ses reflets et la teinte des lampes, puis
   on multiplie par la couleur de peinture choisie. Le changement s'adoucit sur deux pixels à
   l'intérieur du contour.

La couleur choisie est celle du pot de peinture, pas celle qu'aura le mur sur la photo : un mur
blanc paraît gris-beige sur une photo, et repeint en vert sauge il paraîtra plus sombre que la
pastille, comme un vrai mur. Il faut donc connaître la couleur actuelle du mur : blanc par
défaut, une autre couleur si on la connaît, ou « comme sur la photo » (la couleur typique du mur
sur la photo, sa médiane canal par canal) quand on ne la connaît pas. Dans ce dernier cas, la
couleur choisie est celle qu'aura le mur sur la photo.

Une recoloration est une opération enregistrée dans `<point>/modifications/` (D9) : une fiche
`couleur-<n>.json` qui désigne une sélection de l'étape 7 et la couleur choisie. Le panorama
modifié, avec toutes les recolorations du point appliquées dans l'ordre, est une image dérivée
rangée dans `cache/`, refaite quand une opération change. Le panorama d'origine n'est jamais
modifié. Le format est décrit dans `docs/couleur.md`.

Étape 9 : le panorama modifié comprend aussi les objets remplacés par génération d'image (voir
`generation.py`), appliqués après les recolorations.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from visite360 import generation, selection
from visite360.opencv import load_cv2

FORMAT_VERSION = 1
# À augmenter quand le calcul change : les panoramas modifiés déjà fabriqués sont alors refaits.
ALGORITHM_VERSION = 3
# Couleur de peinture supposée d'un mur dont on ne dit rien : un blanc mat ordinaire.
DEFAULT_CURRENT = "#f4f4f0"
DEFAULT_CURRENT_RGB = (0xF4, 0xF4, 0xF0)
# Couleur actuelle « comme sur la photo » : la médiane du mur sur la photo.
FROM_PHOTO = "photo"
ID_PATTERN = re.compile(r"^couleur-(\d+)$")
HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
# Rayon de l'accrochage du contour aux bords, en degrés de panorama (32 pixels sur 8192).
SNAP_DEGREES = 1.4
# Plus il est petit, plus un bord peu contrasté (blanc sur blanc) suffit à retenir le contour.
SNAP_EPS = 1e-4
# Largeur, en pixels, de l'adoucissement à l'intérieur du bord du masque.
FEATHER = 2.0
AFTER_NAME = "apres.jpg"
AFTER_MOBILE_NAME = "apres-mobile.jpg"
AFTER_STATE = "apres.json"
JPEG_QUALITY = 92
MAX_SHADE = 40


class ColorError(Exception):
    """Demande de recoloration invalide, ou recoloration introuvable."""


def parse_current(value: Any) -> tuple[int, int, int] | None:
    """Lit la couleur actuelle d'un mur : « #rrggbb », ou « photo » (renvoie `None`).

    Absente, c'est le blanc par défaut.
    """
    if value is None:
        value = DEFAULT_CURRENT
    if value == FROM_PHOTO:
        return None
    try:
        return parse_color(value)
    except ColorError:
        raise ColorError("Couleur actuelle invalide : « #rrggbb » ou « photo » attendu.") from None


def parse_color(value: Any) -> tuple[int, int, int]:
    """Lit une couleur « #rrggbb » et renvoie (rouge, vert, bleu), de 0 à 255."""
    if not isinstance(value, str) or not HEX_PATTERN.match(value):
        raise ColorError("Couleur invalide : format « #rrggbb » attendu, par exemple #c8d3c0.")
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _to_linear(srgb: np.ndarray) -> np.ndarray:
    """Valeurs sRGB de 0 à 1 vers la lumière linéaire (norme sRGB)."""
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def snap_radius(width: int) -> int:
    """Rayon d'accrochage en pixels pour un panorama de largeur `width`."""
    return max(2, round(width * SNAP_DEGREES / 360.0))


def _guided_filter(guide: np.ndarray, source: np.ndarray, radius: int) -> np.ndarray:
    """Filtre guidé (He, Sun et Tang, 2010) : lisse `source` en suivant les bords de `guide`.

    Dans chaque fenêtre, le résultat est une fonction affine de la clarté du guide : il ne peut
    changer brusquement que là où la photo change brusquement.
    """
    cv2 = load_cv2()
    size = (2 * radius + 1, 2 * radius + 1)

    def box(values: np.ndarray) -> np.ndarray:
        return cv2.boxFilter(values, -1, size, borderType=cv2.BORDER_REFLECT)

    mean_g, mean_s = box(guide), box(source)
    slope = (box(guide * source) - mean_g * mean_s) / (box(guide * guide) - mean_g**2 + SNAP_EPS)
    offset = mean_s - slope * mean_g
    return box(slope) * guide + box(offset)


def snap_mask(image: np.ndarray, mask: np.ndarray, radius: int) -> np.ndarray:
    """Recale le contour de `mask` (uint8) sur les bords de `image` (BGR), à `radius` près."""
    cv2 = load_cv2()
    selected = mask > 0
    rows, cols = np.flatnonzero(selected.any(axis=1)), np.flatnonzero(selected.any(axis=0))
    if not len(rows):
        return np.zeros_like(mask)
    height, width = mask.shape
    top, bottom = max(0, rows[0] - 2 * radius), min(height, rows[-1] + 1 + 2 * radius)
    left, right = max(0, cols[0] - 2 * radius), min(width, cols[-1] + 1 + 2 * radius)
    crop = image[top:bottom, left:right]
    guide = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    source = selected[top:bottom, left:right].astype(np.float32)
    snapped = _guided_filter(guide, source, radius) >= 0.5
    out = np.zeros_like(mask)
    out[top:bottom, left:right] = np.where(snapped, 255, 0).astype(np.uint8)
    return out


def recolor(
    image: np.ndarray,
    mask: np.ndarray,
    rgb: tuple[int, int, int],
    snap: bool = True,
    current: tuple[int, int, int] | None = DEFAULT_CURRENT_RGB,
) -> np.ndarray:
    """Repeint la surface `mask` (uint8, blanc = sélectionné) de `image` (BGR) en `rgb`.

    `rgb` est la couleur de peinture choisie et `current` la couleur de peinture actuelle de la
    surface (`None` : la couleur typique de la surface sur la photo).

    Renvoie une nouvelle image ; `image` n'est pas modifiée. Avec `snap`, le contour est d'abord
    recalé sur les bords de la photo (voir `snap_mask`) : seuls les pixels à moins de
    `snap_radius` du masque peuvent alors changer en dehors de lui. Sans `snap`, les pixels hors
    du masque sont identiques à ceux d'origine.
    """
    cv2 = load_cv2()
    if mask.shape != image.shape[:2]:
        raise ColorError("Le masque n'a pas la taille du panorama.")
    if snap:
        mask = snap_mask(image, mask, snap_radius(image.shape[1]))
    out = image.copy()
    selected = mask > 0
    rows, cols = np.flatnonzero(selected.any(axis=1)), np.flatnonzero(selected.any(axis=0))
    if not len(rows):
        return out
    top, bottom, left, right = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    crop = image[top:bottom, left:right]
    inside = selected[top:bottom, left:right]

    linear = _to_linear(crop.astype(np.float32) / 255.0)
    if current is None:
        reference = np.maximum(np.median(linear[inside], axis=0), 1e-4)
    else:
        reference = np.maximum(_to_linear(np.array(current[::-1], np.float32) / 255.0), 1e-4)
    target = _to_linear(np.array(rgb[::-1], dtype=np.float32) / 255.0)
    painted = _to_srgb(linear / reference * target) * 255.0

    # Distance au bord, à l'intérieur du masque : 1 sur le premier pixel, 0 dehors.
    padded = np.pad(inside.astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 3)[1:-1, 1:-1]
    alpha = np.clip(distance / FEATHER, 0.0, 1.0)[..., None]
    blended = alpha * painted + (1.0 - alpha) * crop.astype(np.float32)
    result = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    out[top:bottom, left:right][inside] = result[inside]
    return out


@dataclass(frozen=True)
class Operation:
    """Recoloration enregistrée : fiche et masque de la sélection visée."""

    record: dict[str, Any]
    mask_path: Path


def _numbers(folder: Path) -> list[int]:
    if not folder.is_dir():
        return []
    found = (ID_PATTERN.match(path.stem) for path in folder.glob("couleur-*.json"))
    return [int(match.group(1)) for match in found if match]


def _read(path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def operations(point: Path) -> list[Operation]:
    """Recolorations d'un point, dans l'ordre où elles s'appliquent (par numéro).

    Une recoloration dont la sélection a disparu est ignorée.
    """
    folder = point / selection.FOLDER
    found = []
    for number in sorted(_numbers(folder)):
        record = _read(folder / f"couleur-{number}.json")
        if record is None or not isinstance(record.get("selection"), str):
            continue
        if not selection.ID_PATTERN.match(record["selection"]):
            continue
        mask = folder / f"{record['selection']}.png"
        if mask.is_file() and (folder / f"{record['selection']}.json").is_file():
            found.append(Operation(record, mask))
    return found


def _check_selection(point: Path, selection_id: Any) -> str:
    if not isinstance(selection_id, str) or not selection.ID_PATTERN.match(selection_id):
        raise ColorError("Identifiant de sélection invalide.")
    folder = point / selection.FOLDER
    if (
        not (folder / f"{selection_id}.json").is_file()
        or not (folder / f"{selection_id}.png").is_file()
    ):
        raise ColorError(f"Sélection introuvable : {selection_id}.")
    return selection_id


def save(
    point: Path, selection_id: Any, color: Any, shade: Any = None, current: Any = None
) -> dict[str, Any]:
    """Repeint une sélection et renvoie la fiche de l'opération.

    `current` est la couleur actuelle de la surface (« #rrggbb » ou « photo », blanc si absente).
    `shade` est le nom de la teinte du nuancier (« Vert sauge »), absent pour une couleur
    personnalisée. Une sélection n'a qu'une couleur : la repeindre remplace sa recoloration
    précédente, qui garde son numéro et donc sa place dans l'ordre d'application.
    """
    selection_id = _check_selection(point, selection_id)
    parse_color(color)
    parse_current(current)
    if shade is not None and (not isinstance(shade, str) or len(shade.strip()) > MAX_SHADE):
        raise ColorError("Nom de teinte invalide.")
    folder = point / selection.FOLDER
    previous = [op.record for op in operations(point) if op.record["selection"] == selection_id]
    if previous and ID_PATTERN.match(str(previous[0].get("id"))):
        color_id = str(previous[0]["id"])
    else:
        color_id = f"couleur-{max(_numbers(folder), default=0) + 1}"
    record = {
        "version": FORMAT_VERSION,
        "type": "couleur",
        "id": color_id,
        "selection": selection_id,
        "couleur": color.lower(),
        **({"teinte": shade.strip()} if shade and shade.strip() else {}),
        "couleur_actuelle": (current or DEFAULT_CURRENT).lower(),
        "creee_le": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    selection.write_atomic(
        folder / f"{color_id}.json",
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return record


def delete(point: Path, color_id: Any) -> None:
    """Annule une recoloration : retire sa fiche. Le panorama modifié sera refait sans elle."""
    if not isinstance(color_id, str) or not ID_PATTERN.match(color_id):
        raise ColorError("Identifiant de recoloration invalide.")
    path = point / selection.FOLDER / f"{color_id}.json"
    if not path.is_file():
        raise ColorError(f"Recoloration introuvable : {color_id}.")
    path.unlink()


def delete_for_selection(point: Path, selection_id: str) -> None:
    """Retire les recolorations d'une sélection, avant de supprimer celle-ci."""
    for op in operations(point):
        if op.record["selection"] == selection_id:
            (point / selection.FOLDER / f"{op.record['id']}.json").unlink(missing_ok=True)


Color = tuple[int, int, int]
Paint = tuple[np.ndarray, Color, Color | None]


def apply(image: np.ndarray, ops: Sequence[Paint]) -> np.ndarray:
    """Applique des recolorations (masque, couleur choisie, couleur actuelle) dans l'ordre. Un
    masque est mis à l'échelle de l'image s'il le faut."""
    cv2 = load_cv2()
    height, width = image.shape[:2]
    out = image
    for mask, rgb, current in ops:
        if mask.shape != (height, width):
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_AREA)
            mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        out = recolor(out, mask, rgb, current=current)
    return out


def _load_masks(ops: Sequence[Operation]) -> list[Paint]:
    cv2 = load_cv2()
    loaded = []
    for op in ops:
        mask = cv2.imread(str(op.mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ColorError(f"Masque illisible : {op.mask_path}")
        record = op.record
        loaded.append(
            (
                mask,
                parse_color(record.get("couleur")),
                parse_current(record.get("couleur_actuelle")),
            )
        )
    return loaded


def _read_panorama(panorama: Path, width: int | None = None) -> np.ndarray:
    cv2 = load_cv2()
    image = cv2.imread(str(panorama))
    if image is None:
        raise ColorError(f"Panorama illisible : {panorama}")
    if width is not None and image.shape[1] > width:
        image = cv2.resize(image, (width, width // 2), interpolation=cv2.INTER_AREA)
    return image


def _encode(image: np.ndarray) -> bytes:
    cv2 = load_cv2()
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ColorError("L'écriture du panorama modifié a échoué.")
    return encoded.tobytes()


def signature(
    panorama: Path, ops: Sequence[Operation], generated: Sequence[generation.Operation] = ()
) -> str | None:
    """Empreinte de ce qui fait le panorama modifié. `None` s'il n'y a aucune modification.

    Elle change si une opération, un masque, une image générée ou le panorama change : l'image
    dérivée est refaite.
    """
    if not ops and not generated:
        return None
    versions = f"calcul {ALGORITHM_VERSION}, génération {generation.ALGORITHM_VERSION};"
    digest = hashlib.sha256(versions.encode())
    paths = (panorama, *(op.mask_path for op in ops), *(op.image_path for op in generated))
    for path in paths:
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns};".encode())
    for record in (*(op.record for op in ops), *(op.record for op in generated)):
        digest.update(json.dumps(record, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def preview(
    panorama: Path, point: Path, selection_id: Any, color: Any, width: int, current: Any = None
) -> bytes:
    """Panorama réduit à `width` avec les modifications du point et l'essai demandé (JPEG).

    L'essai remplace la couleur actuelle de la sélection, s'il y en a une. Les objets remplacés
    (étape 9) restent par-dessus. Rien n'est enregistré.
    """
    selection_id = _check_selection(point, selection_id)
    rgb = parse_color(color)
    known = parse_current(current)
    ops = [op for op in operations(point) if op.record["selection"] != selection_id]
    trial_mask = point / selection.FOLDER / f"{selection_id}.png"
    loaded = _load_masks(ops)
    cv2 = load_cv2()
    mask = cv2.imread(str(trial_mask), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ColorError(f"Masque illisible : {trial_mask}")
    image = apply(_read_panorama(panorama, width), [*loaded, (mask, rgb, known)])
    return _encode(generation.apply(image, generation.operations(point)))


class Painter:
    """Panoramas modifiés des points d'une visite, pour `visite360 serve` : recolorations, puis
    objets remplacés par génération d'image (étape 9).

    Un verrou évite que deux requêtes fabriquent la même image en même temps.
    """

    def __init__(self, mobile_width: int) -> None:
        self.mobile_width = mobile_width
        self._lock = threading.Lock()

    def state(self, point: Path, panorama: Path) -> dict[str, Any]:
        """Modifications du point et version du panorama modifié (`None` sans modification)."""
        ops, generated = operations(point), generation.operations(point)
        return {
            "couleurs": [op.record for op in ops],
            "generations": [op.record for op in generated],
            "version": signature(panorama, ops, generated),
        }

    def base(self, point: Path, panorama: Path, without: str | None = None) -> np.ndarray:
        """Panorama sur lequel générer : le panorama modifié s'il y en a un, sinon l'original.

        `without` est une génération à laisser de côté : celle qu'on refait.
        """
        if without is not None:
            generated = [op for op in generation.operations(point) if op.record["id"] != without]
            image = apply(_read_panorama(panorama), _load_masks(operations(point)))
            return generation.apply(image, generated)
        if signature(panorama, operations(point), generation.operations(point)) is None:
            return _read_panorama(panorama)
        return _read_panorama(self.after(point, panorama, mobile=False))

    def after(self, point: Path, panorama: Path, mobile: bool) -> Path:
        """Panorama modifié (ou sa copie pour téléphone), refait s'il est périmé."""
        with self._lock:
            ops, generated = operations(point), generation.operations(point)
            current = signature(panorama, ops, generated)
            if current is None:
                raise ColorError("Ce point n'a aucune modification.")
            cache = point / "cache"
            full, small, state = cache / AFTER_NAME, cache / AFTER_MOBILE_NAME, cache / AFTER_STATE
            saved = _read(state) if state.is_file() else None
            if saved is None or saved.get("signature") != current or not small.is_file():
                image = apply(_read_panorama(panorama), _load_masks(ops))
                image = generation.apply(image, generated)
                cache.mkdir(exist_ok=True)
                selection.write_atomic(full, _encode(image))
                if image.shape[1] > self.mobile_width:
                    cv2 = load_cv2()
                    size = (self.mobile_width, self.mobile_width // 2)
                    image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
                selection.write_atomic(small, _encode(image))
                # L'état en dernier : présent et à jour veut dire images complètes.
                selection.write_atomic(state, json.dumps({"signature": current}).encode())
            return small if mobile else full
