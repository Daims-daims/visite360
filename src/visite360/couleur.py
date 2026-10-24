"""Étape 8 : changement de couleur d'une surface sélectionnée, sans IA générative (D11, D30).

Le calcul se fait dans l'espace de couleur Lab, qui sépare la clarté d'un pixel (L, de 0 pour le
noir à 100 pour le blanc) de sa teinte (a : du vert au rouge, b : du bleu au jaune). Sur la
surface sélectionnée :

- la clarté de chaque pixel est multipliée par un même facteur, choisi pour que la clarté typique
  de la surface (sa médiane) devienne celle de la couleur choisie. Un pixel deux fois plus sombre
  que le reste du mur, dans une ombre, le reste : ombres, lumière et texture sont conservées ;
- la teinte devient celle de la couleur choisie, plus une petite part des écarts de teinte
  d'origine (le reflet chaud d'une lampe reste visible) ;
- au bord du masque, le changement s'adoucit sur deux pixels, vers l'intérieur seulement : aucun
  pixel hors de la sélection ne change.

Une recoloration est une opération enregistrée dans `<point>/modifications/` (D9) : une fiche
`couleur-<n>.json` qui désigne une sélection de l'étape 7 et la couleur choisie. Le panorama
modifié, avec toutes les recolorations du point appliquées dans l'ordre, est une image dérivée
rangée dans `cache/`, refaite quand une opération change. Le panorama d'origine n'est jamais
modifié. Le format est décrit dans `docs/couleur.md`.
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

from visite360 import selection
from visite360.opencv import load_cv2

FORMAT_VERSION = 1
ID_PATTERN = re.compile(r"^couleur-(\d+)$")
HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
# Part des écarts de teinte d'origine gardée autour de la teinte choisie.
TINT_KEEP = 0.3
# Largeur, en pixels, de l'adoucissement à l'intérieur du bord du masque.
FEATHER = 2.0
AFTER_NAME = "apres.jpg"
AFTER_MOBILE_NAME = "apres-mobile.jpg"
AFTER_STATE = "apres.json"
JPEG_QUALITY = 92


class ColorError(Exception):
    """Demande de recoloration invalide, ou recoloration introuvable."""


def parse_color(value: Any) -> tuple[int, int, int]:
    """Lit une couleur « #rrggbb » et renvoie (rouge, vert, bleu), de 0 à 255."""
    if not isinstance(value, str) or not HEX_PATTERN.match(value):
        raise ColorError("Couleur invalide : format « #rrggbb » attendu, par exemple #c8d3c0.")
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _to_lab(bgr: np.ndarray) -> np.ndarray:
    cv2 = load_cv2()
    return cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)


def _from_lab(lab: np.ndarray) -> np.ndarray:
    cv2 = load_cv2()
    return cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_Lab2BGR) * 255.0


def recolor(image: np.ndarray, mask: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    """Repeint la surface `mask` (uint8, blanc = sélectionné) de `image` (BGR) en `rgb`.

    Renvoie une nouvelle image ; `image` n'est pas modifiée. Hors du masque, les pixels sont
    identiques à ceux d'origine.
    """
    cv2 = load_cv2()
    if mask.shape != image.shape[:2]:
        raise ColorError("Le masque n'a pas la taille du panorama.")
    out = image.copy()
    selected = mask > 0
    rows, cols = np.flatnonzero(selected.any(axis=1)), np.flatnonzero(selected.any(axis=0))
    if not len(rows):
        return out
    top, bottom, left, right = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    crop = image[top:bottom, left:right]
    inside = selected[top:bottom, left:right]

    lab = _to_lab(crop)
    target = _to_lab(np.array([[rgb[::-1]]], dtype=np.uint8))[0, 0]
    reference = np.median(lab[inside], axis=0)
    new = np.empty_like(lab)
    new[..., 0] = lab[..., 0] * (target[0] / max(float(reference[0]), 1.0))
    new[..., 1:] = target[1:] + TINT_KEEP * (lab[..., 1:] - reference[1:])
    new[..., 0] = np.clip(new[..., 0], 0.0, 100.0)
    painted = _from_lab(new)

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


def save(point: Path, selection_id: Any, color: Any) -> dict[str, Any]:
    """Repeint une sélection et renvoie la fiche de l'opération.

    Une sélection n'a qu'une couleur : la repeindre remplace sa recoloration précédente, qui
    garde son numéro et donc sa place dans l'ordre d'application.
    """
    selection_id = _check_selection(point, selection_id)
    parse_color(color)
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


def apply(image: np.ndarray, ops: Sequence[tuple[np.ndarray, tuple[int, int, int]]]) -> np.ndarray:
    """Applique des recolorations (masque, couleur) dans l'ordre. Un masque est mis à l'échelle
    de l'image s'il le faut."""
    cv2 = load_cv2()
    height, width = image.shape[:2]
    out = image
    for mask, rgb in ops:
        if mask.shape != (height, width):
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_AREA)
            mask = np.where(mask >= 128, 255, 0).astype(np.uint8)
        out = recolor(out, mask, rgb)
    return out


def _load_masks(ops: Sequence[Operation]) -> list[tuple[np.ndarray, tuple[int, int, int]]]:
    cv2 = load_cv2()
    loaded = []
    for op in ops:
        mask = cv2.imread(str(op.mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ColorError(f"Masque illisible : {op.mask_path}")
        loaded.append((mask, parse_color(op.record.get("couleur"))))
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


def signature(panorama: Path, ops: Sequence[Operation]) -> str | None:
    """Empreinte de ce qui fait le panorama modifié. `None` s'il n'y a aucune recoloration.

    Elle change si une opération, un masque ou le panorama change : l'image dérivée est refaite.
    """
    if not ops:
        return None
    digest = hashlib.sha256()
    for path in (panorama, *(op.mask_path for op in ops)):
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns};".encode())
    for op in ops:
        digest.update(json.dumps(op.record, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()[:16]


def preview(panorama: Path, point: Path, selection_id: Any, color: Any, width: int) -> bytes:
    """Panorama réduit à `width` avec les recolorations du point et l'essai demandé (JPEG).

    L'essai remplace la couleur actuelle de la sélection, s'il y en a une. Rien n'est enregistré.
    """
    selection_id = _check_selection(point, selection_id)
    rgb = parse_color(color)
    ops = [op for op in operations(point) if op.record["selection"] != selection_id]
    trial_mask = point / selection.FOLDER / f"{selection_id}.png"
    loaded = _load_masks(ops)
    cv2 = load_cv2()
    mask = cv2.imread(str(trial_mask), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ColorError(f"Masque illisible : {trial_mask}")
    return _encode(apply(_read_panorama(panorama, width), [*loaded, (mask, rgb)]))


class Painter:
    """Panoramas modifiés des points d'une visite, pour `visite360 serve`.

    Un verrou évite que deux requêtes fabriquent la même image en même temps.
    """

    def __init__(self, mobile_width: int) -> None:
        self.mobile_width = mobile_width
        self._lock = threading.Lock()

    def state(self, point: Path, panorama: Path) -> dict[str, Any]:
        """Recolorations du point et version du panorama modifié (`None` sans recoloration)."""
        ops = operations(point)
        return {"couleurs": [op.record for op in ops], "version": signature(panorama, ops)}

    def after(self, point: Path, panorama: Path, mobile: bool) -> Path:
        """Panorama modifié (ou sa copie pour téléphone), refait s'il est périmé."""
        with self._lock:
            ops = operations(point)
            current = signature(panorama, ops)
            if current is None:
                raise ColorError("Ce point n'a aucune recoloration.")
            cache = point / "cache"
            full, small, state = cache / AFTER_NAME, cache / AFTER_MOBILE_NAME, cache / AFTER_STATE
            saved = _read(state) if state.is_file() else None
            if saved is None or saved.get("signature") != current or not small.is_file():
                image = apply(_read_panorama(panorama), _load_masks(ops))
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
