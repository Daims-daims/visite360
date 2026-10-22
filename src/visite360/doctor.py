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

MIN_PYTHON = (3, 11)
MIN_OPENCV = (4, 10)
OPENCV_PACKAGE = "opencv-python-headless"
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
    """Vérifie qu'OpenCV s'importe et que sa version est suffisante."""
    install_hint = f'pip install "{OPENCV_PACKAGE}>={_format_version(MIN_OPENCV)}"'
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
            f"Réinstaller : pip install --force-reinstall {OPENCV_PACKAGE}",
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
            f'pip install --upgrade "{OPENCV_PACKAGE}>={_format_version(MIN_OPENCV)}"',
        )
    return CheckResult("OpenCV", True, True, raw_version)


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


def run_checks() -> list[CheckResult]:
    """Lance toutes les vérifications, dans l'ordre d'affichage."""
    return [check_python(), check_opencv(), check_heic(), check_hugin()]


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
