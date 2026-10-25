"""Étape 5 : lecture de `capture.json`, écrit par l'app de capture à côté des photos d'un point.

Pour chaque photo, l'app enregistre l'orientation du téléphone mesurée par ses capteurs au
moment du déclenchement (format dans `docs/capture-json.md`). L'assemblage s'en sert comme
point de départ et pour ne chercher des points communs qu'entre photos voisines (D25).

La rotation est donnée dans le repère de `spherical.py` : elle envoie une direction vue par
la photo (x vers la droite de l'image, y vers le bas, z dans l'axe de l'objectif) dans le
repère du monde (y vers le bas, x et z horizontaux, cap de départ arbitraire).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FILE_NAME = "capture.json"
FORMAT_VERSION = 1
# Écart toléré entre la rotation lue et une vraie rotation (arrondis de l'écriture JSON).
ORTHONORMAL_TOLERANCE = 1e-3


class CaptureError(Exception):
    """`capture.json` est illisible ou mal formé, avec un message en français."""


@dataclass(frozen=True)
class Capture:
    """Orientations mesurées par le téléphone, par nom de fichier de photo."""

    path: Path
    rotations: dict[str, np.ndarray]
    device: str | None = None
    # Cap de la direction visée au début de la prise de vue, en degrés, dans le même repère que
    # les rotations. Le panorama la place en son centre, pour que les flèches visées dans l'app
    # (étape 6) tombent au bon endroit. Absent des fichiers de l'étape 5.
    start_yaw: float | None = None
    # Hauteur de l'objectif au-dessus du sol, en mètres, mesurée par ARKit (étape 10, D34) :
    # elle donne l'échelle des dimensions de la pièce. Absente sans « ×1 + AR » ou sans sol repéré.
    lens_height: float | None = None


def find(point: Path) -> Path | None:
    """Chemin de `capture.json` dans le dossier du point, ou None s'il n'y en a pas."""
    path = point / FILE_NAME
    return path if path.is_file() else None


def _rotation(value: Any, where: str) -> np.ndarray:
    if not (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(row, list) and len(row) == 3 for row in value)
        and all(
            isinstance(x, int | float) and not isinstance(x, bool) for row in value for x in row
        )
    ):
        raise CaptureError(f"{where} : « rotation » doit être un tableau de 3 lignes de 3 nombres.")
    matrix = np.array(value, dtype=np.float64)
    if not np.all(np.isfinite(matrix)) or not np.allclose(
        matrix @ matrix.T, np.eye(3), atol=ORTHONORMAL_TOLERANCE
    ):
        raise CaptureError(f"{where} : « rotation » n'est pas une rotation valide.")
    if np.linalg.det(matrix) < 0:
        raise CaptureError(f"{where} : « rotation » est un miroir, pas une rotation.")
    # Remet à plat les arrondis : rotation la plus proche (décomposition polaire).
    U, _, Vt = np.linalg.svd(matrix)
    return U @ Vt


def parse(data: Any, path: Path) -> Capture:
    """Valide le contenu de `capture.json`. Les champs inconnus sont ignorés."""
    name = path.name
    if not isinstance(data, dict):
        raise CaptureError(f"{name} doit contenir un objet JSON.")
    if data.get("format") != FORMAT_VERSION:
        raise CaptureError(
            f"{name} : format {data.get('format')!r} inconnu, ce programme lit le format "
            f"{FORMAT_VERSION}. Mettre à jour visite360 ou l'app."
        )
    photos = data.get("photos")
    if not isinstance(photos, list):
        raise CaptureError(f"{name} : « photos » doit être une liste.")
    rotations: dict[str, np.ndarray] = {}
    for number, photo in enumerate(photos, start=1):
        where = f"{name}, photo {number}"
        if not isinstance(photo, dict):
            raise CaptureError(f"{where} : chaque photo doit être un objet JSON.")
        file = photo.get("fichier")
        if not isinstance(file, str) or not file or "/" in file or "\\" in file:
            raise CaptureError(f"{where} : « fichier » doit être un nom de fichier.")
        if file in rotations:
            raise CaptureError(f"{where} : la photo {file} est déclarée deux fois.")
        rotations[file] = _rotation(photo.get("rotation"), f"{where} ({file})")
    device = data.get("appareil")
    start_yaw = data.get("cap_depart")
    if start_yaw is not None and (
        isinstance(start_yaw, bool)
        or not isinstance(start_yaw, int | float)
        or not -360 <= start_yaw <= 360
    ):
        raise CaptureError(f"{name} : « cap_depart » doit être un angle en degrés.")
    lens_height = data.get("hauteur_objectif_m")
    if lens_height is not None and (
        isinstance(lens_height, bool)
        or not isinstance(lens_height, int | float)
        or not 0 < lens_height < 5
    ):
        raise CaptureError(f"{name} : « hauteur_objectif_m » doit être un nombre de mètres.")
    return Capture(
        path,
        rotations,
        device if isinstance(device, str) else None,
        None if start_yaw is None else float(start_yaw),
        None if lens_height is None else float(lens_height),
    )


def load(path: Path) -> Capture:
    """Lit et valide `capture.json`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CaptureError(f"Impossible de lire {path} ({error}).") from error
    except ValueError as error:
        raise CaptureError(f"{path.name} n'est pas un JSON valide ({error}).") from error
    return parse(data, path)
