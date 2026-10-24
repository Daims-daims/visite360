"""Modèle de détourage SAM 2.1 small (D10, D29), qui tourne sur le Mac.

SAM 2.1 (Meta, code et poids sous Apache 2.0) trouve le contour de l'objet ou de la surface
désignés par des clics. Il est facultatif : PyTorch, SAM 2 et les poids (176 Mo) s'installent à
part avec `scripts/installer-sam2.sh`, pour que le reste de l'outil reste léger. Les poids sont
rangés hors du dépôt, dans `~/.cache/visite360/modeles/` (ou le dossier de `VISITE360_MODELES`).

PyTorch n'est importé qu'au chargement du modèle : sans lui, tout le reste fonctionne.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import urllib.request
import warnings
from pathlib import Path
from typing import TextIO

import numpy as np

from visite360.selection import file_sha256

MODEL_NAME = "sam2.1_hiera_small"
CONFIG = "configs/sam2.1/sam2.1_hiera_s.yaml"
WEIGHTS_FILE = f"{MODEL_NAME}.pt"
WEIGHTS_URL = f"https://dl.fbaipublicfiles.com/segment_anything_2/092824/{WEIGHTS_FILE}"
# Empreinte du fichier publié par Meta, relevée le 2026-10-25.
WEIGHTS_SHA256 = "6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38"
INSTALL_COMMAND = "bash scripts/installer-sam2.sh"
DOWNLOAD_TIMEOUT_S = 60


class SegmentError(Exception):
    """SAM 2.1 est absent, incomplet ou n'a pas pu être chargé."""


def models_folder() -> Path:
    """Dossier des poids de modèles, hors du dépôt."""
    override = os.environ.get("VISITE360_MODELES")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "visite360" / "modeles"


def weights_path() -> Path:
    return models_folder() / WEIGHTS_FILE


def missing() -> str | None:
    """Ce qui manque pour lancer SAM 2.1, en clair, ou None si tout est là. N'importe rien."""
    absent = [name for name in ("torch", "sam2") if importlib.util.find_spec(name) is None]
    if absent:
        names = " et ".join("PyTorch" if name == "torch" else "SAM 2" for name in absent)
        return f"{names} absent{'s' if len(absent) > 1 else ''}"
    if not weights_path().is_file():
        return f"poids absents ({weights_path()})"
    return None


def download_weights(
    url: str = WEIGHTS_URL,
    expected: str = WEIGHTS_SHA256,
    target: Path | None = None,
    out: TextIO | None = None,
) -> Path:
    """Télécharge les poids si besoin et vérifie leur empreinte.

    Un fichier déjà présent et intact n'est pas retéléchargé.
    """
    out = out or sys.stdout
    target = target or weights_path()
    if target.is_file() and file_sha256(target) == expected:
        print(f"Poids déjà présents et vérifiés : {target}", file=out)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partiel")
    print(f"Téléchargement de {url}", file=out)
    try:
        with (
            urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response,
            partial.open("wb") as handle,
        ):
            for chunk in iter(lambda: response.read(1 << 20), b""):
                handle.write(chunk)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise SegmentError(f"Le téléchargement des poids a échoué ({error}).") from error
    actual = file_sha256(partial)
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise SegmentError(
            "Les poids téléchargés ne correspondent pas à ceux publiés par Meta "
            f"(empreinte {actual[:12]}… au lieu de {expected[:12]}…). Rien n'a été installé."
        )
    os.replace(partial, target)
    print(f"Poids installés : {target}", file=out)
    return target


class Sam2Segmenter:
    """SAM 2.1 small, sur la puce graphique du Mac (MPS) si elle est disponible."""

    def __init__(self) -> None:
        problem = missing()
        if problem:
            raise SegmentError(f"SAM 2.1 n'est pas installé : {problem}. Lancer {INSTALL_COMMAND}")
        # Les rares opérations que la puce graphique ne sait pas faire passent par le processeur.
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        try:
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except ImportError as error:
            raise SegmentError(
                f"SAM 2.1 est installé mais impossible à charger ({error}). "
                f"Relancer {INSTALL_COMMAND}"
            ) from error
        self.torch = torch
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            # PyTorch prévient qu'une fonction utilisée par SAM 2 sera retirée un jour : sans
            # effet ici, l'avertissement ne ferait qu'inquiéter dans le terminal.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                model = build_sam2(CONFIG, str(weights_path()), device=self.device)
        except Exception as error:  # Hydra et PyTorch lèvent des erreurs de types très variés.
            raise SegmentError(f"Le chargement de SAM 2.1 a échoué ({error}).") from error
        self.predictor = SAM2ImagePredictor(model)

    def set_image(self, rgb: np.ndarray) -> None:
        with self.torch.inference_mode():
            self.predictor.set_image(rgb)

    def predict(self, points: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, float]:
        """Meilleur masque pour ces clics. Avec un seul clic, le modèle propose trois masques
        (du plus petit au plus grand morceau possible) et l'on garde celui qu'il juge le meilleur.
        """
        with self.torch.inference_mode():
            masks, scores, _ = self.predictor.predict(
                point_coords=points, point_labels=labels, multimask_output=len(points) == 1
            )
        best = int(np.argmax(scores))
        return masks[best] > 0, float(scores[best])


def load_segmenter() -> Sam2Segmenter:
    return Sam2Segmenter()
