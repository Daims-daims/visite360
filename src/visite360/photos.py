"""Photos d'un point : liste, conversion HEIC et lecture.

Les photos d'origine ne sont jamais modifiées (D9). Les HEIC sont convertis en JPEG par
`sips` (D17) dans le dossier `cache/` du point.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
HEIC_SUFFIXES = {".heic", ".heif"}
SIPS_TIMEOUT_S = 120


class PhotoError(Exception):
    """Erreur sur les photos d'un point, avec un message en français."""


@dataclass(frozen=True)
class Photo:
    """Une photo d'origine et le fichier réellement lu (une copie JPEG pour un HEIC)."""

    source: Path
    readable: Path


def list_photos(folder: Path) -> list[Path]:
    """Photos du dossier, triées par nom. Les fichiers cachés et autres formats sont ignorés."""
    if not folder.is_dir():
        raise PhotoError(f"Dossier de photos introuvable : {folder}")
    photos = sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in PHOTO_SUFFIXES
    )
    if not photos:
        raise PhotoError(f"Aucune photo dans {folder}. Formats acceptés : JPEG, PNG, HEIC.")
    return photos


def convert_heic(source: Path, target: Path, platform: str = sys.platform) -> None:
    """Convertit un HEIC en JPEG avec `sips` (macOS)."""
    sips = shutil.which("sips") if platform == "darwin" else None
    if sips is None:
        raise PhotoError(
            f"Impossible de lire {source.name} : la conversion HEIC demande `sips`, "
            "disponible seulement sur macOS. Régler l'iPhone sur « Le plus compatible » "
            "pour prendre les photos en JPEG."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partiel.jpg")
    args = [sips, "-s", "format", "jpeg", "-s", "formatOptions", "95"]
    args += [str(source), "--out", str(partial)]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=SIPS_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PhotoError(f"La conversion de {source.name} par sips a échoué ({error}).") from error
    if result.returncode != 0 or not partial.is_file():
        raise PhotoError(
            f"La conversion de {source.name} par sips a échoué "
            f"(code de sortie {result.returncode}) : {result.stderr.strip()}"
        )
    partial.replace(target)


def prepare_photos(paths: list[Path], cache: Path) -> list[Photo]:
    """Associe à chaque photo un fichier lisible, en convertissant les HEIC si besoin.

    Une conversion déjà faite et plus récente que la photo d'origine est réutilisée.
    """
    photos = []
    for path in paths:
        if path.suffix.lower() not in HEIC_SUFFIXES:
            photos.append(Photo(path, path))
            continue
        target = cache / f"{path.stem}.jpg"
        if not target.is_file() or target.stat().st_mtime < path.stat().st_mtime:
            convert_heic(path, target)
        photos.append(Photo(path, target))
    return photos
