"""Accès à OpenCV, compilé sans FFmpeg (décision D19).

Le paquet publié sur PyPI embarque FFmpeg, et sur macOS des encodeurs sous GPL. Le projet
utilise une version compilée par `scripts/installer-opencv.sh`, et refuse l'autre.
"""

from __future__ import annotations

import importlib
import re
from types import ModuleType

INSTALL_COMMAND = "bash scripts/installer-opencv.sh"


class OpenCVError(Exception):
    """OpenCV est absent, inutilisable ou compilé avec FFmpeg."""


def uses_ffmpeg(build_information: str) -> bool:
    """Indique si la description de compilation d'OpenCV mentionne FFmpeg activé."""
    return re.search(r"FFMPEG:\s+YES", build_information) is not None


def load_cv2() -> ModuleType:
    """Importe OpenCV et vérifie qu'il a été compilé sans FFmpeg."""
    try:
        cv2 = importlib.import_module("cv2")
    except ImportError as error:
        raise OpenCVError(
            f"OpenCV est absent ou impossible à charger ({error}). "
            f"L'installer avec : {INSTALL_COMMAND}"
        ) from error
    if uses_ffmpeg(cv2.getBuildInformation()):
        raise OpenCVError(
            "L'OpenCV installé vient de PyPI et embarque FFmpeg, interdit par les règles "
            f"de licence du projet. Le remplacer avec : {INSTALL_COMMAND}"
        )
    return cv2
