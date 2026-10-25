"""Contrôle de l'installation : `visite360 doctor`.

Vérifie que les dépendances nécessaires au traitement sont présentes et dit quoi installer
s'il en manque. Rien n'est installé automatiquement.
"""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO

from visite360 import generation, segment
from visite360.opencv import INSTALL_COMMAND, uses_ffmpeg

MIN_PYTHON = (3, 11)
MIN_OPENCV = (4, 10)
EXTERNAL_TIMEOUT_S = 10


@dataclass(frozen=True)
class CheckResult:
    """Résultat d'une vérification."""

    name: str
    ok: bool
    required: bool
    detail: str
    hint: str | None = None


def parse_version(text: str) -> tuple[int, ...] | None:
    """Extrait (majeur, mineur, correctif) du début d'un numéro de version, ou None."""
    match = re.match(r"\s*(\d+)\.(\d+)(?:\.(\d+))?", text)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def _format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def check_python(version_info: tuple[int, ...] = tuple(sys.version_info[:3])) -> CheckResult:
    """Vérifie la version de Python."""
    version = _format_version(version_info)
    if version_info[:2] >= MIN_PYTHON:
        return CheckResult("Python", True, True, version)
    return CheckResult(
        "Python",
        False,
        True,
        f"version {version} trop ancienne, {_format_version(MIN_PYTHON)} ou plus requise",
        "Installer Python 3.11 ou plus (par exemple `brew install python@3.13`), "
        "puis recréer l'environnement virtuel avec.",
    )


def check_opencv() -> CheckResult:
    """Vérifie qu'OpenCV s'importe, que sa version suffit et qu'il est compilé sans FFmpeg."""
    install_hint = f"Installer la version compilée sans FFmpeg : {INSTALL_COMMAND}"
    try:
        cv2 = importlib.import_module("cv2")
    except ModuleNotFoundError:
        return CheckResult("OpenCV", False, True, "absent", install_hint)
    except ImportError as error:
        return CheckResult(
            "OpenCV",
            False,
            True,
            f"présent mais impossible à charger ({error})",
            f"Réinstaller : {INSTALL_COMMAND} --force",
        )

    raw_version = str(getattr(cv2, "__version__", ""))
    version = parse_version(raw_version)
    if version is None:
        return CheckResult(
            "OpenCV", False, True, f"version illisible ({raw_version!r})", install_hint
        )
    if version[:2] < MIN_OPENCV:
        return CheckResult(
            "OpenCV",
            False,
            True,
            f"version {raw_version} trop ancienne, {_format_version(MIN_OPENCV)} ou plus requise",
            install_hint,
        )
    if uses_ffmpeg(cv2.getBuildInformation()):
        return CheckResult(
            "OpenCV",
            False,
            True,
            f"version {raw_version} de PyPI, avec FFmpeg et des encodeurs sous GPL (D19)",
            f"La remplacer : {INSTALL_COMMAND}",
        )
    return CheckResult("OpenCV", True, True, f"{raw_version}, compilé sans FFmpeg")


def check_heic(platform: str = sys.platform) -> CheckResult:
    """Vérifie que les photos HEIC de l'iPhone pourront être converties, avec `sips` (macOS)."""
    name = "Conversion HEIC"
    if platform != "darwin":
        return CheckResult(
            name,
            False,
            False,
            "disponible seulement sur macOS (sips)",
            "Régler l'iPhone sur « Le plus compatible » pour prendre les photos en JPEG.",
        )

    sips = shutil.which("sips")
    if sips is None:
        return CheckResult(
            name,
            False,
            True,
            "programme sips introuvable",
            "sips est fourni avec macOS : vérifier que /usr/bin est dans le PATH.",
        )
    try:
        result = subprocess.run(
            [sips, "--formats"],
            capture_output=True,
            text=True,
            timeout=EXTERNAL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult(name, False, True, f"sips ne répond pas ({error})")
    if result.returncode != 0:
        return CheckResult(name, False, True, f"sips a échoué (code de sortie {result.returncode})")
    if "public.heic" not in result.stdout:
        return CheckResult(
            name,
            False,
            True,
            "sips ne sait pas lire le HEIC sur ce système",
            "Mettre macOS à jour, ou régler l'iPhone sur « Le plus compatible » (JPEG).",
        )
    return CheckResult(name, True, True, "sips")


def check_hugin() -> CheckResult:
    """Signale la présence de Hugin, repli facultatif pour l'assemblage (D7)."""
    path = shutil.which("hugin_executor")
    if path is None:
        return CheckResult(
            "Hugin",
            False,
            False,
            "absent",
            "Repli pour l'assemblage (D7), à installer seulement si l'étape 2 le demande.",
        )
    return CheckResult("Hugin", True, False, path)


def check_sam2() -> CheckResult:
    """Signale si SAM 2.1, facultatif, est prêt pour la sélection d'une surface (étape 7)."""
    name = "SAM 2.1 (sélection au clic)"
    hint = (
        "Nécessaire seulement pour sélectionner une surface. "
        f"L'installer : {segment.INSTALL_COMMAND}"
    )
    problem = segment.missing()
    if problem:
        return CheckResult(name, False, False, problem, hint)
    if segment.file_sha256(segment.weights_path()) != segment.WEIGHTS_SHA256:
        return CheckResult(name, False, False, "poids abîmés ou différents de ceux de Meta", hint)
    return CheckResult(name, True, False, f"{segment.MODEL_NAME}, poids vérifiés")


def check_generation() -> CheckResult:
    """Signale si FLUX.2 klein, facultatif, est prêt pour remplacer un objet (étape 9).

    Les empreintes des 15 Go de poids sont vérifiées à l'installation, pas ici : trop long.
    """
    name = f"{generation.MODEL_NAME} (remplacement d'un objet)"
    problem = generation.missing()
    if problem:
        hint = (
            "Nécessaire seulement pour remplacer un objet. "
            f"L'installer : {generation.INSTALL_COMMAND}"
        )
        return CheckResult(name, False, False, problem, hint)
    return CheckResult(name, True, False, f"mflux et poids présents ({generation.model_folder()})")


def run_checks() -> list[CheckResult]:
    """Lance toutes les vérifications, dans l'ordre d'affichage."""
    return [
        check_python(),
        check_opencv(),
        check_heic(),
        check_hugin(),
        check_sam2(),
        check_generation(),
    ]


def report(results: list[CheckResult], out: TextIO) -> int:
    """Affiche les résultats et renvoie le code de sortie : 1 si un élément obligatoire manque."""
    print("Vérification de l'installation de visite360\n", file=out)
    for result in results:
        if result.ok:
            mark = "✓"
        elif result.required:
            mark = "✗"
        else:
            mark = "-"
        label = result.name if result.required else f"{result.name} (facultatif)"
        print(f"  {mark} {label} : {result.detail}", file=out)
        if not result.ok and result.hint:
            print(f"      → {result.hint}", file=out)

    missing = sum(1 for result in results if result.required and not result.ok)
    print(file=out)
    if missing == 0:
        print("Tout est prêt.", file=out)
        return 0
    plural = "s" if missing > 1 else ""
    print(f"{missing} élément{plural} obligatoire{plural} à corriger.", file=out)
    return 1


def run(out: TextIO | None = None) -> int:
    """Point d'entrée de `visite360 doctor`."""
    return report(run_checks(), out or sys.stdout)
