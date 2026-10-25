"""Étape 9 : remplacement d'un objet par génération d'image, en local (D31).

L'utilisateur trace un cadre autour d'un meuble dans la vue regardée et dit par quoi le
remplacer. Le modèle FLUX.2 [klein] 4B (Black Forest Labs, code et poids sous Apache 2.0) ne
travaille pas sur le panorama, dont les lignes droites sont courbées : on découpe une « vue »
carrée centrée sur le cadre, avec une marge, comme une photo ordinaire. Le modèle refait toute la
vue d'après la consigne ; on n'en garde que l'intérieur du cadre, aux couleurs recalées sur la
photo et au bord adouci, et on le reporte dans le panorama. Hors du cadre, aucun pixel ne change.

Le modèle tourne sur la puce graphique du Mac par mflux (MIT), installé avec ses dépendances dans
un environnement Python à part par `scripts/installer-generation.sh`, et appelé comme programme
externe. Les poids (15 Go) sont rangés hors du dépôt, dans `~/.cache/visite360/modeles/`.

Une génération est une opération enregistrée dans `<point>/modifications/` (D9) : une fiche
`generation-<n>.json` (cadre, vue, consigne, graine, modèle) et l'image générée
`generation-<n>.png`. Le report est refait à chaque fabrication du panorama modifié, sans relancer
le modèle. Le format est décrit dans `docs/generation.md`.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

import numpy as np

from visite360 import selection, visite
from visite360.opencv import load_cv2
from visite360.segment import models_folder
from visite360.selection import (
    FOLDER,
    MAX_FOV,
    MIN_FOV,
    ROW_BLOCK,
    ViewSpec,
    extract_view,
    file_sha256,
    footprint,
    write_atomic,
)
from visite360.spherical import equirect_directions, project

MODEL_NAME = "FLUX.2 [klein] 4B"
REPOSITORY = "black-forest-labs/FLUX.2-klein-4B"
# Révision publiée par Black Forest Labs, relevée le 2026-10-25.
REVISION = "e7b7dc27f91deacad38e78976d1f2b499d76a294"
DOWNLOAD_PATTERNS = (
    "model_index.json",
    "scheduler/*",
    "text_encoder/*",
    "tokenizer/*",
    "transformer/*",
    "vae/*",
)
# Empreintes SHA-256 des gros fichiers de cette révision, publiées par Hugging Face.
WEIGHTS = {
    "text_encoder/model-00001-of-00002.safetensors": (
        "8c0506e7f4936fa7e26183a4fd8da4e2bdbc5990ba64ae441f965d51228f36ea"
    ),
    "text_encoder/model-00002-of-00002.safetensors": (
        "82f2bd839378541b0557bfabaf37c7d3d637071fdcb73302dedd7cf61162ce07"
    ),
    "tokenizer/tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    "transformer/diffusion_pytorch_model.safetensors": (
        "9f29f9edcfdae452a653ffb51a534ca4decd389952c225724ff3b94042612a6e"
    ),
    "vae/diffusion_pytorch_model.safetensors": (
        "ca70d2202afe6415bdbcb8793ba8cd99fd159cfe6192381504d6c4d3036e0f04"
    ),
}
MFLUX_MODEL = "flux2-klein-4b"
COMMAND = "mflux-generate-flux2-edit"
INSTALL_COMMAND = "bash scripts/installer-generation.sh"

FORMAT_VERSION = 1
ALGORITHM_VERSION = 1
ID_PATTERN = re.compile(r"^generation-(\d+)$")
VIEW_SIZE = 1024
# Le modèle est « distillé » pour 4 passes : moins donne une image ratée.
STEPS = 4
# Le cadre occupe le milieu de la vue : une marge de 20 % de chaque côté montre au modèle la
# pièce autour du meuble (lumière, perspective) et garde tout le meuble dans la vue.
MARGIN = 0.2
# Bord adouci, en pixels de la vue de 1024 : l'image générée se fond dans la photo vers l'intérieur.
FEATHER = 24
# Bande autour du cadre où l'on compare les couleurs de la vue générée et de la photo.
RING = 40
MAX_GAIN = 1.25
MIN_RECT = 16
MAX_TEXT = 200
# Une génération dure 2 à 3 minutes sur le MacBook Air M4 ; au-delà de 20, elle est bloquée.
TIMEOUT_S = 20 * 60
EDGE_SAMPLES = 64

PROMPT_REPLACE = (
    "Remplace {objet}, au centre de l'image, par {nouveau}. Ne change rien d'autre : murs, sol, "
    "plafond, autres meubles, lumière et perspective restent identiques."
)
PROMPT_REMOVE = (
    "Retire {objet}, au centre de l'image, et montre à sa place le mur et le sol qui étaient "
    "derrière. Ne change rien d'autre : murs, sol, plafond, autres meubles, lumière et "
    "perspective restent identiques."
)


class GenerationError(Exception):
    """Génération impossible : modèle absent, demande invalide ou échec du modèle."""


# --- Installation -------------------------------------------------------------------------


def environment_folder() -> Path:
    """Environnement Python de mflux, hors du dépôt."""
    override = os.environ.get("VISITE360_GENERATION")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "visite360" / "generation"


def command_path() -> Path:
    return environment_folder() / "bin" / COMMAND


def cache_folder() -> Path:
    """Cache Hugging Face des poids, dans le dossier des modèles du projet."""
    return models_folder() / "huggingface"


def model_folder() -> Path:
    """Dossier des poids de la révision fixée."""
    name = "models--" + REPOSITORY.replace("/", "--")
    return cache_folder() / name / "snapshots" / REVISION


def missing() -> str | None:
    """Ce qui manque pour générer, en clair, ou None si tout est là. Ne lance rien."""
    if not command_path().is_file():
        return f"mflux absent ({command_path()})"
    absent = [name for name in WEIGHTS if not (model_folder() / name).is_file()]
    if absent:
        return f"poids absents ({model_folder()})"
    return None


def verify_weights(folder: Path | None = None) -> list[str]:
    """Fichiers de poids absents ou dont l'empreinte diffère de celle publiée. Lent : 15 Go lus."""
    folder = folder or model_folder()
    problems = []
    for name, expected in WEIGHTS.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name} absent")
        elif file_sha256(path) != expected:
            problems.append(f"{name} ne correspond pas à la version publiée")
    return problems


DOWNLOAD_SCRIPT = """
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1], revision=sys.argv[2], cache_dir=sys.argv[3],
                  allow_patterns=sys.argv[4:])
"""


def download_weights(out: TextIO | None = None) -> Path:
    """Télécharge les poids de la révision fixée (15 Go, une fois) et vérifie leurs empreintes.

    Le téléchargement passe par huggingface_hub, dans l'environnement de mflux : un fichier déjà
    présent n'est pas retéléchargé.
    """
    out = out or sys.stdout
    python = environment_folder() / "bin" / "python"
    if not python.is_file():
        raise GenerationError(f"Environnement de génération absent. Lancer {INSTALL_COMMAND}")
    print(f"Poids de {MODEL_NAME} : {REPOSITORY}, révision {REVISION[:12]}…", file=out, flush=True)
    arguments = [str(python), "-I", "-c", DOWNLOAD_SCRIPT, REPOSITORY, REVISION]
    arguments += [str(cache_folder()), *DOWNLOAD_PATTERNS]
    result = subprocess.run(arguments, check=False)
    if result.returncode != 0:
        raise GenerationError(
            "Le téléchargement des poids a échoué (connexion ?). Relancer le script : "
            "les fichiers déjà reçus sont gardés."
        )
    print("Vérification des empreintes (une minute environ)...", file=out)
    problems = verify_weights()
    if problems:
        raise GenerationError(
            "Les poids ne correspondent pas à ceux publiés par Black Forest Labs : "
            + " ; ".join(problems)
        )
    print(f"Poids installés et vérifiés : {model_folder()}", file=out)
    return model_folder()


# --- Géométrie : vue autour du cadre, zone remplacée ---------------------------------------


Rect = tuple[float, float, float, float]


def parse_rect(raw: Any, size: int) -> Rect:
    """Lit le cadre tracé dans la vue de l'écran : [x0, y0, x1, y1] en pixels de cette vue."""
    if not isinstance(raw, list) or len(raw) != 4:
        raise GenerationError("Cadre illisible : quatre nombres attendus.")
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        raise GenerationError("Cadre illisible : quatre nombres attendus.")
    if not all(math.isfinite(v) for v in raw):
        raise GenerationError("Cadre illisible : quatre nombres attendus.")
    x0, x1 = sorted((float(raw[0]), float(raw[2])))
    y0, y1 = sorted((float(raw[1]), float(raw[3])))
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(size), x1), min(float(size), y1)
    if x1 - x0 < MIN_RECT or y1 - y0 < MIN_RECT:
        raise GenerationError("Cadre trop petit : l'agrandir autour de l'objet.")
    return x0, y0, x1, y1


def boundary(screen: ViewSpec, rect: Rect) -> np.ndarray:
    """Directions du monde le long du bord du cadre (EDGE_SAMPLES points par côté)."""
    x0, y0, x1, y1 = rect
    t = np.linspace(0.0, 1.0, EDGE_SAMPLES, endpoint=False)
    xs = np.concatenate(
        [x0 + (x1 - x0) * t, np.full_like(t, x1), x1 - (x1 - x0) * t, np.full_like(t, x0)]
    )
    ys = np.concatenate(
        [np.full_like(t, y0), y0 + (y1 - y0) * t, np.full_like(t, y1), y1 - (y1 - y0) * t]
    )
    d = screen.directions(xs, ys)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def generation_view(screen: ViewSpec, rect: Rect) -> ViewSpec:
    """Vue envoyée au modèle : centrée sur le cadre, qui en occupe le milieu avec une marge."""
    x0, y0, x1, y1 = rect
    yaw, pitch = screen.angles((x0 + x1) / 2 - 0.5, (y0 + y1) / 2 - 0.5)
    pitch = max(-90.0, min(90.0, pitch))
    # Caméra de focale 1 dans cette direction : les coordonnées projetées sont des tangentes.
    unit = ViewSpec(yaw, pitch, 90.0, size=2)
    x, y, front = project(
        boundary(screen, rect).astype(np.float32), unit.intrinsics(), unit.rotation()
    )
    if not front.all():
        raise GenerationError("Cadre trop grand : le tracer autour d'un seul objet.")
    half = float(max(np.abs(x - 1.0).max(), np.abs(y - 1.0).max()))
    widest = math.tan(math.radians(MAX_FOV) / 2)
    if half >= widest * 0.95:
        raise GenerationError("Cadre trop grand : reculer la vue ou tracer un cadre plus serré.")
    fov = math.degrees(2 * math.atan(min(half / (1 - 2 * MARGIN), widest)))
    return ViewSpec(yaw, pitch, max(MIN_FOV, fov), VIEW_SIZE)


def zone_mask(view: ViewSpec, screen: ViewSpec, rect: Rect) -> np.ndarray:
    """Le cadre de l'écran, vu dans la vue du modèle (uint8, 0 ou 255)."""
    cv2 = load_cv2()
    x, y, _ = project(boundary(screen, rect).astype(np.float32), view.intrinsics(), view.rotation())
    polygon = np.stack([x - 0.5, y - 0.5], axis=-1)
    mask = np.zeros((view.size, view.size), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(polygon * 16).astype(np.int32)], 255, cv2.LINE_8, shift=4)
    return mask


# --- Report dans le panorama --------------------------------------------------------------


def blend(
    original: np.ndarray, generated: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vue générée aux couleurs recalées sur la photo, et son opacité (0 hors du cadre).

    Le modèle décale souvent un peu la teinte ou le contraste de toute l'image. On mesure ce
    décalage dans une bande autour du cadre, où les deux images montrent la même chose, et on le
    corrige canal par canal. L'opacité monte de 0 au bord du cadre à 1 à FEATHER pixels dedans.
    """
    cv2 = load_cv2()
    size = original.shape[1], original.shape[0]
    if generated.shape[:2] != original.shape[:2]:
        generated = cv2.resize(generated, size, interpolation=cv2.INTER_AREA)
    out = generated.astype(np.float32)
    source = original.astype(np.float32)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * RING + 1, 2 * RING + 1))
    ring = (cv2.dilate(mask, kernel) > 0) & (mask == 0)
    if ring.sum() >= 100:
        for c in range(3):
            g, o = out[..., c][ring], source[..., c][ring]
            gain = float(np.clip(o.std() / max(float(g.std()), 1.0), 1 / MAX_GAIN, MAX_GAIN))
            out[..., c] = out[..., c] * gain + (float(o.mean()) - gain * float(g.mean()))
    inside = np.pad(mask, 1) > 0  # le bord de la vue compte comme un bord du cadre
    distance = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    alpha = np.clip(distance / FEATHER, 0.0, 1.0).astype(np.float32)
    return np.clip(out, 0, 255), alpha


def paste(panorama: np.ndarray, view: ViewSpec, image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Reporte `image` (vue `view`) dans le panorama, pondérée par `alpha`. Renvoie une copie."""
    cv2 = load_cv2()
    height, width = panorama.shape[:2]
    out = panorama.copy()
    source = np.dstack([image.astype(np.float32), alpha.astype(np.float32)])
    rows, cols = footprint(view, width, height)
    K, R = view.intrinsics(), view.rotation()
    for start in range(0, len(rows), ROW_BLOCK):
        block = rows[start : start + ROW_BLOCK]
        x, y, front = project(equirect_directions(width, height, block, cols), K, R)
        map_x = np.where(front, x - 0.5, -10.0).astype(np.float32)
        map_y = np.where(front, y - 0.5, -10.0).astype(np.float32)
        values = cv2.remap(
            source, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0
        )
        weight = values[..., 3:4]
        if not (weight > 0).any():
            continue
        index = np.ix_(block, cols % width)
        mixed = out[index] * (1.0 - weight) + values[..., :3] * weight
        out[index] = np.clip(np.round(mixed), 0, 255).astype(np.uint8)
    return out


@dataclass(frozen=True)
class Operation:
    """Génération enregistrée : fiche et image générée."""

    record: dict[str, Any]
    image_path: Path

    def zone(self) -> tuple[ViewSpec, ViewSpec, Rect]:
        """Vue du modèle, vue de l'écran et cadre, relus dans la fiche."""
        return _zone(self.record)


def _spec(raw: Any) -> ViewSpec:
    if not isinstance(raw, dict):
        raise GenerationError("Fiche de génération illisible : vue absente.")
    return ViewSpec(
        raw.get("cap"), raw.get("hauteur"), raw.get("champ"), int(raw.get("taille", VIEW_SIZE))
    )


def _zone(record: dict[str, Any]) -> tuple[ViewSpec, ViewSpec, Rect]:
    zone = record.get("zone")
    if not isinstance(zone, dict):
        raise GenerationError("Fiche de génération illisible : cadre absent.")
    screen = _spec(zone.get("ecran"))
    return _spec(record.get("vue")), screen, parse_rect(zone.get("cadre"), screen.size)


def apply(image: np.ndarray, ops: Sequence[Operation]) -> np.ndarray:
    """Applique des générations dans l'ordre, à un panorama de n'importe quelle largeur."""
    cv2 = load_cv2()
    out = image
    for op in ops:
        view, screen, rect = op.zone()
        generated = cv2.imread(str(op.image_path))
        if generated is None:
            raise GenerationError(f"Image générée illisible : {op.image_path}")
        # La photo de référence est relue dans le panorama tel qu'il est à ce moment : avec les
        # recolorations et les générations précédentes.
        original = extract_view(out, view)
        colors, alpha = blend(original, generated, zone_mask(view, screen, rect))
        out = paste(out, view, colors, alpha)
    return out


# --- Fiches -------------------------------------------------------------------------------


def _numbers(folder: Path) -> list[int]:
    if not folder.is_dir():
        return []
    found = (ID_PATTERN.match(path.stem) for path in folder.glob("generation-*.json"))
    return [int(match.group(1)) for match in found if match]


def _read(path: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def operations(point: Path) -> list[Operation]:
    """Générations d'un point, dans l'ordre où elles s'appliquent (par numéro).

    Une fiche illisible ou sans son image est ignorée.
    """
    folder = point / FOLDER
    found = []
    for number in sorted(_numbers(folder)):
        record = _read(folder / f"generation-{number}.json")
        image = folder / f"generation-{number}.png"
        if record is None or not image.is_file():
            continue
        try:
            _zone(record)
        except (GenerationError, selection.SelectionError, TypeError, ValueError):
            continue
        found.append(Operation(record, image))
    return found


def _check_id(generation_id: Any) -> str:
    if not isinstance(generation_id, str) or not ID_PATTERN.match(generation_id):
        raise GenerationError("Identifiant de génération invalide.")
    return generation_id


def find(point: Path, generation_id: Any) -> Operation:
    generation_id = _check_id(generation_id)
    for op in operations(point):
        if op.record.get("id") == generation_id:
            return op
    raise GenerationError(f"Génération introuvable : {generation_id}.")


def save(
    point: Path,
    panorama: Path,
    generated: np.ndarray,
    request: Request,
    seed: int,
    seconds: float,
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Enregistre une génération dans `<point>/modifications/` et renvoie sa fiche.

    Avec `generation_id`, la génération remplace celle de ce numéro (« Refaire ») et garde sa
    place dans l'ordre d'application.
    """
    cv2 = load_cv2()
    folder = point / FOLDER
    folder.mkdir(exist_ok=True)
    if generation_id is None:
        generation_id = f"generation-{max(_numbers(folder), default=0) + 1}"
    number = int(ID_PATTERN.match(generation_id).group(1))  # type: ignore[union-attr]
    ok, encoded = cv2.imencode(".png", generated)
    if not ok:
        raise GenerationError("L'écriture de l'image générée a échoué.")
    record = {
        "version": FORMAT_VERSION,
        "type": "generation",
        "id": generation_id,
        "nom": request.name or f"Remplacement {number}",
        "objet": request.target,
        "nouveau": request.replacement,
        "consigne": request.prompt(),
        "graine": seed,
        "pas": STEPS,
        "modele": {"nom": MODEL_NAME, "depot": REPOSITORY, "revision": REVISION},
        "vue": request.view.to_json(),
        "zone": {"ecran": request.screen.to_json(), "cadre": [round(v, 1) for v in request.rect]},
        "image": f"{generation_id}.png",
        "panorama_sha256": file_sha256(panorama),
        "duree_s": round(seconds, 1),
        "creee_le": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    # L'image d'abord : une fiche présente veut dire une génération complète.
    write_atomic(folder / record["image"], encoded.tobytes())
    write_atomic(
        folder / f"{generation_id}.json",
        (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return record


def delete(point: Path, generation_id: Any) -> None:
    """Annule une génération : retire sa fiche et son image. Le panorama ne change pas (D9)."""
    generation_id = _check_id(generation_id)
    folder = point / FOLDER
    if not (folder / f"{generation_id}.json").is_file():
        raise GenerationError(f"Génération introuvable : {generation_id}.")
    # La fiche d'abord : sans elle, la génération n'existe plus, même si la suite échoue.
    for path in (folder / f"{generation_id}.json", folder / f"{generation_id}.png"):
        path.unlink(missing_ok=True)


# --- Demande et modèle --------------------------------------------------------------------


def _text(raw: Any, label: str, required: bool) -> str:
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise GenerationError(f"{label} invalide.")
    text = " ".join(raw.split())
    if len(text) > MAX_TEXT:
        raise GenerationError(f"{label} trop long ({len(text)} caractères, {MAX_TEXT} au plus).")
    if required and not text:
        raise GenerationError(f"{label} manquant.")
    return text


@dataclass(frozen=True)
class Request:
    """Ce que demande l'utilisateur : le cadre dans la vue de l'écran et la consigne."""

    screen: ViewSpec
    rect: Rect
    target: str
    replacement: str
    name: str

    @property
    def view(self) -> ViewSpec:
        return generation_view(self.screen, self.rect)

    def prompt(self) -> str:
        """Consigne donnée au modèle. Sans « nouveau », l'objet est retiré."""
        if self.replacement:
            return PROMPT_REPLACE.format(objet=self.target, nouveau=self.replacement)
        return PROMPT_REMOVE.format(objet=self.target)

    @classmethod
    def parse(
        cls, screen: ViewSpec, raw_rect: Any, target: Any, replacement: Any, name: Any
    ) -> Request:
        request = cls(
            screen,
            parse_rect(raw_rect, screen.size),
            _text(target, "Objet à remplacer", required=True),
            _text(replacement, "Remplacement", required=False),
            _text(name, "Nom", required=False)[:80],
        )
        generation_view(request.screen, request.rect)  # refuse tout de suite un cadre trop grand
        return request

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Request:
        _, screen, rect = _zone(record)
        return cls(
            screen,
            rect,
            str(record.get("objet", "")),
            str(record.get("nouveau", "")),
            str(record.get("nom", "")),
        )


Progress = Callable[[int, int], None]


class Generator(Protocol):
    """Modèle qui refait une vue d'après une consigne (mflux, ou un modèle simulé en test)."""

    def generate(
        self, image: np.ndarray, prompt: str, seed: int, progress: Progress
    ) -> np.ndarray: ...


STEP_PATTERN = re.compile(r"(\d+)/(\d+) \[")


class MfluxGenerator:
    """FLUX.2 [klein] 4B par la commande de mflux, une génération à la fois.

    Le programme recharge le modèle à chaque appel (quelques secondes) et rend toute sa mémoire en
    s'arrêtant. L'avancement est lu dans ce qu'il affiche : « 2/4 [ » à chaque passe.
    """

    def __init__(self, timeout: float = TIMEOUT_S) -> None:
        problem = missing()
        if problem:
            raise GenerationError(
                f"La génération demande {MODEL_NAME} ({problem}). L'installer : {INSTALL_COMMAND}"
            )
        self.timeout = timeout

    def arguments(self, source: Path, target: Path, prompt: str, seed: int) -> list[str]:
        return [
            str(command_path()),
            "--model",
            str(model_folder()),
            "--base-model",
            MFLUX_MODEL,
            "--image-paths",
            str(source),
            "--prompt",
            prompt,
            "--width",
            str(VIEW_SIZE),
            "--height",
            str(VIEW_SIZE),
            "--steps",
            str(STEPS),
            "--seed",
            str(seed),
            "--output",
            str(target),
        ]

    def generate(self, image: np.ndarray, prompt: str, seed: int, progress: Progress) -> np.ndarray:
        cv2 = load_cv2()
        with tempfile.TemporaryDirectory(prefix="visite360-") as work:
            source, target = Path(work) / "vue.png", Path(work) / "generee.png"
            if not cv2.imwrite(str(source), image):
                raise GenerationError("L'écriture de la vue pour le modèle a échoué.")
            # Hors ligne : les poids sont déjà là, aucun accès au réseau pendant une génération.
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            run_command(self.arguments(source, target, prompt, seed), env, progress, self.timeout)
            generated = cv2.imread(str(target))
        if generated is None:
            raise GenerationError("Le modèle n'a pas produit d'image.")
        return generated


def run_command(
    arguments: list[str], env: dict[str, str], progress: Progress, timeout: float
) -> None:
    """Lance la commande de génération et suit son avancement. Erreur claire si elle échoue."""
    try:
        process = subprocess.Popen(
            arguments, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env
        )
    except OSError as error:
        raise GenerationError(f"Impossible de lancer {MODEL_NAME} ({error.strerror}).") from error
    assert process.stderr is not None
    expired = threading.Event()

    def stop() -> None:
        expired.set()
        process.kill()

    timer = threading.Timer(timeout, stop)
    timer.start()
    lines: list[str] = []

    def read(raw: bytes) -> None:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            return
        lines.append(line)
        del lines[:-20]
        match = STEP_PATTERN.search(line)
        if match and int(match.group(2)) == STEPS:
            progress(int(match.group(1)), STEPS)

    buffer = b""
    try:
        # Les barres d'avancement se réécrivent avec « \r » : on découpe aussi sur ce caractère.
        for chunk in iter(lambda: process.stderr.read1(4096), b""):  # type: ignore[union-attr]
            buffer += chunk
            *complete, buffer = re.split(rb"[\r\n]", buffer)
            for raw in complete:
                read(raw)
        read(buffer)
        code = process.wait()
    finally:
        timer.cancel()
    if expired.is_set():
        raise GenerationError(f"{MODEL_NAME} n'a pas fini en {timeout / 60:.0f} minutes : arrêté.")
    if code != 0:
        detail = next(
            (line for line in reversed(lines) if "Error" in line), lines[-1] if lines else ""
        )
        raise GenerationError(f"{MODEL_NAME} a échoué (code {code}) : {detail[:300]}")


# --- Générations en cours dans `visite360 serve` ------------------------------------------


@dataclass
class Job:
    """État d'une génération lancée depuis la visionneuse."""

    point: int
    status: str = "en_cours"  # en_cours, terminee, erreur
    step: int = 0
    message: str = "Préparation de la vue..."
    record: dict[str, Any] | None = None
    started: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "etat": self.status,
            "passe": self.step,
            "passes": STEPS,
            "message": self.message,
            "fiche": self.record,
            "secondes": round(time.monotonic() - self.started),
        }


class Generations:
    """Générations de `visite360 serve` : une seule à la fois, dans un fil à part.

    `factory` fabrique le modèle (les tests en passent un simulé). `base` donne le panorama sur
    lequel générer : le panorama modifié du point s'il en a un, sinon le panorama d'origine.
    `before` est appelé avant chaque génération, pour libérer la mémoire du modèle de sélection.
    """

    def __init__(
        self,
        tour: visite.Tour,
        factory: Callable[[], Generator],
        base: Callable[[visite.Point], Path],
        unavailable: str | None = None,
        before: Callable[[], None] = lambda: None,
    ) -> None:
        self.tour = tour
        self.factory = factory
        self.base = base
        self.unavailable = unavailable
        self.before = before
        self._lock = threading.Lock()
        self._job: Job | None = None
        self._thread: threading.Thread | None = None

    def state(self) -> dict[str, Any]:
        job = self._job
        return {
            "disponible": self.unavailable is None,
            "message": self.unavailable,
            "travail": job.to_json() if job else None,
        }

    def start(self, index: int, point: visite.Point, request: Request, redo: str | None) -> Job:
        """Lance une génération. Refusée si une autre est en cours."""
        if self.unavailable:
            raise GenerationError(self.unavailable)
        with self._lock:
            if self._job and self._job.status == "en_cours":
                raise GenerationError(
                    "Une génération est déjà en cours : attendre qu'elle finisse."
                )
            job = Job(index, started=time.monotonic())
            self._job = job
            self._thread = threading.Thread(
                target=self._run, args=(job, point, request, redo), daemon=True
            )
            self._thread.start()
        return job

    def wait(self, timeout: float | None = None) -> None:
        """Attend la fin de la génération en cours (pour les tests)."""
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _run(self, job: Job, point: visite.Point, request: Request, redo: str | None) -> None:
        cv2 = load_cv2()
        try:
            self.before()
            panorama = cv2.imread(str(self.base(point)))
            if panorama is None:
                raise GenerationError(f"Panorama illisible : {point.folders.panorama}")
            view = request.view
            image = extract_view(panorama, view)
            job.message = "Chargement du modèle..."
            generator = self.factory()

            def progress(done: int, total: int) -> None:
                job.step = done
                job.message = (
                    f"passe {min(done + 1, total)} sur {total}" if done < total else "finition"
                )

            seed = secrets.randbelow(2**31)
            started = time.monotonic()
            generated = generator.generate(image, request.prompt(), seed, progress)
            folders = point.folders
            job.record = save(
                folders.point,
                folders.panorama,
                generated,
                request,
                seed,
                time.monotonic() - started,
                redo,
            )
            job.message = "Terminée"
            job.status = "terminee"
        except Exception as error:  # le fil doit rendre compte de toute erreur à la visionneuse
            if not isinstance(error, GenerationError | selection.SelectionError):
                print(f"Erreur inattendue pendant la génération : {error!r}", file=sys.stderr)
            job.message = str(error)
            job.status = "erreur"
