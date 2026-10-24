"""Assemblage d'un panorama équirectangulaire : `visite360 stitch` (étape 2, D19 et D20).

Deux temps :

1. alignement avec les briques d'OpenCV (points SIFT, appariement, ajustement des rotations
   et de la focale, correction de l'horizon) sur des copies réduites des photos. Si l'app de
   capture a laissé `capture.json`, les orientations mesurées par le téléphone servent de
   départ, limitent l'appariement aux photos voisines et donnent l'horizon (D25) ;
2. rendu par notre code : chaque pixel du panorama 2:1 va chercher la photo qui le voit le
   mieux. Les écarts d'exposition sont compensés et les raccords fondus par bandes de
   fréquences. Les trous près du sol et du plafond sont bouchés par un flou, les autres
   restent en gris. Tout est décrit dans `rapport.json`.

Les photos d'origine ne sont jamais modifiées (D9).
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from visite360 import __version__, capture
from visite360.adjust import (
    PairMatches,
    adjust,
    initial_rotations,
    relative_rotation,
    rotation_from_vector,
    vector_from_rotation,
)
from visite360.opencv import OpenCVError, load_cv2
from visite360.photos import Photo, PhotoError, list_photos, prepare_photos
from visite360.spherical import (
    equirect_directions,
    latitude_weights,
    project,
    rotation_y,
)

DEFAULT_WIDTH = 8192
MIN_WIDTH = 256
MAX_WIDTH = 32768
REPORT_FORMAT = 2

# Alignement, réglages de l'exemple stitching_detailed d'OpenCV adaptés à SIFT.
WORK_MEGAPIX = 0.6
MATCH_CONF = 0.3
CONF_THRESH = 1.0
# Angle de vue horizontal plausible de l'objectif principal d'un téléphone, tenu en portrait
# ou en paysage.
MIN_FOV_DEG = 30.0
MAX_FOV_DEG = 125
# Orientations mesurées par le téléphone (D25). Deux photos dont les axes sont plus écartés
# ne peuvent pas se recouvrir : on ne cherche pas de points communs entre elles.
NEIGHBOUR_MAX_ANGLE_DEG = 75.0
# Au-delà de cet écart médian entre capteurs et photos, les capteurs sont ignorés.
SENSOR_MAX_ERROR_DEG = 10.0
SOURCE_IMAGES = "photos"
SOURCE_SENSORS = "capteurs"

# Rendu.
ANALYSIS_WIDTH = 1024
# Largeur du panorama réduit où se cherchent les raccords : assez fine pour voir les petits
# décalages des objets proches et les contourner (essai sur le salon, 2026-10-24). Au plus la
# moitié de la largeur du panorama demandé.
SEAM_WIDTH = 1536
# Bonus de poids d'une photo dans la zone que la recherche de raccords lui attribue.
SEAM_PRIORITY = 10.0
# Priorité à l'horizon : là où l'œil se pose en premier. Une photo dont l'axe est à moins de
# HORIZON_MAX_PITCH_DEG de l'horizon est prioritaire dans toute la zone qu'elle voit à plus de
# HORIZON_INNER_MARGIN (part de sa largeur et de sa hauteur) de ses bords : les photos des
# autres rangées n'y sont pas candidates, et leurs raccords passent plus haut ou plus bas.
HORIZON_MAX_PITCH_DEG = 20.0
HORIZON_INNER_MARGIN = 0.12
FOOTPRINT_WIDTH = 512
RENDER_OVERSAMPLE = 1.5
# Largeur de la fusion des raccords : étroite, pour ne pas montrer deux versions décalées
# d'un même objet en transparence.
BLEND_STRENGTH = 0.012
GAIN_ALPHA = 0.01
GAIN_BETA = 100.0
GAIN_LIMITS = (0.5, 2.0)
JPEG_QUALITY = 92
HOLE_GRAY = 128
# Un trou qui touche le sol ou le plafond est flouté s'il reste à moins de 45° du pôle.
BLUR_FILL_MIN_ABS_LAT = 45.0
MIN_HOLE_PART = 1e-4

REJECTED_UNREADABLE = "illisible"
REJECTED_UNMATCHED = "pas assez de points communs avec les autres photos"
PLACED_BY_SENSORS = "pas assez de points communs, orientation du téléphone"


class StitchError(Exception):
    """Échec de l'assemblage, avec un message en français."""


class SensorMismatch(Exception):
    """Les orientations mesurées par le téléphone ne correspondent pas aux photos."""


@dataclass
class Camera:
    """Une photo alignée : intrinsèques à pleine résolution et rotation dans le panorama."""

    index: int
    K: np.ndarray
    R: np.ndarray
    size: tuple[int, int]


@dataclass(frozen=True)
class Hole:
    """Zone du panorama vue par aucune photo."""

    kind: str
    part: float
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    fill: str


@dataclass(frozen=True)
class Folders:
    """Dossiers d'un point : photos d'origine, sorties et conversions."""

    point: Path
    photos: Path

    @property
    def panorama(self) -> Path:
        return self.point / "panorama.jpg"

    @property
    def report(self) -> Path:
        return self.point / "rapport.json"

    @property
    def cache(self) -> Path:
        return self.point / "cache"


def resolve_folders(target: Path) -> Folders:
    """Accepte le dossier du point (qui contient photos/) ou directement son dossier photos/."""
    if (target / "photos").is_dir():
        return Folders(target, target / "photos")
    if target.name == "photos" and target.is_dir():
        return Folders(target.parent, target)
    raise StitchError(
        f"Dossier de photos introuvable : {target}. Organisation attendue : "
        "visites/<visite>/<point>/photos/, en donnant le dossier du point ou son dossier photos."
    )


# --- Alignement ---------------------------------------------------------------------------


def _work_scale(size: tuple[int, int]) -> float:
    return min(1.0, math.sqrt(WORK_MEGAPIX * 1e6 / (size[0] * size[1])))


def _match(cv2: Any, features: list[Any], mask: np.ndarray | None = None) -> list[Any]:
    """Apparie les photos deux à deux, seulement les paires autorisées par mask s'il est donné."""
    for number, feature in enumerate(features):
        feature.img_idx = number
    matcher = cv2.detail_BestOf2NearestMatcher(False, MATCH_CONF)
    if mask is None:
        pairwise = matcher.apply2(features)
    else:
        pairwise = matcher.apply2(features, cv2.UMat(mask))
    matcher.collectGarbage()
    return pairwise


def _pair_matches(
    features: list[Any], pairwise: list[Any], sizes: list[tuple[int, int]]
) -> list[PairMatches]:
    """Points appariés retenus par OpenCV (inliers), origine au centre de chaque image."""
    points = [
        np.array([kp.pt for kp in f.getKeypoints()], dtype=np.float64).reshape(-1, 2)
        for f in features
    ]
    centers = [np.array([w / 2, h / 2]) for w, h in sizes]
    pairs = []
    for info in pairwise:
        i, j = info.src_img_idx, info.dst_img_idx
        if i < 0 or j <= i or info.confidence <= CONF_THRESH:
            continue
        inliers = np.ravel(info.getInliers()).astype(bool)
        matches = [m for m, keep in zip(info.getMatches(), inliers, strict=True) if keep]
        if not matches:
            continue
        query = np.array([m.queryIdx for m in matches])
        train = np.array([m.trainIdx for m in matches])
        pairs.append(
            PairMatches(i, j, points[i][query] - centers[i], points[j][train] - centers[j])
        )
    return pairs


def neighbour_mask(
    rotations: list[np.ndarray], max_angle_deg: float = NEIGHBOUR_MAX_ANGLE_DEG
) -> np.ndarray:
    """Paires de photos dont les axes sont à moins de max_angle_deg (1) ou non (0)."""
    axes = np.array([R[:, 2] for R in rotations])
    return (axes @ axes.T >= math.cos(math.radians(max_angle_deg))).astype(np.uint8)


def sensor_errors_deg(
    pairs: list[PairMatches], rotations: list[np.ndarray], focal: float
) -> list[float]:
    """Écart (degrés) entre la rotation mesurée par le téléphone et celle vue sur les photos.

    Pour chaque paire, compare la rotation qui superpose les points communs des deux photos à
    celle que donnent les capteurs.
    """
    errors = []
    for pair in pairs:
        seen = relative_rotation(pair, focal)
        measured = rotations[pair.j].T @ rotations[pair.i]
        cosine = (np.trace(seen @ measured.T) - 1) / 2
        errors.append(math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0)))))
    return errors


def align_to_sensors(rotations: list[np.ndarray], sensors: list[np.ndarray]) -> list[np.ndarray]:
    """Tourne l'ensemble des photos ajustées pour coller au mieux aux capteurs.

    Les capteurs connaissent la verticale (par la gravité) : le panorama hérite de leur horizon.
    """
    U, _, Vt = np.linalg.svd(sum(S @ R.T for S, R in zip(sensors, rotations, strict=True)))
    turn = U @ np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))]) @ Vt
    return [turn @ R for R in rotations]


def drift_corrected(number: int, corrections: dict[int, np.ndarray]) -> np.ndarray:
    """Correction à appliquer à l'orientation mesurée par le téléphone pour la photo number.

    Le gyroscope dérive de quelques degrés pendant la prise de vue. Pour chaque photo alignée
    par ses points communs, corrections donne la rotation qui mène de l'orientation mesurée à
    l'orientation trouvée. Une photo placée par les seuls capteurs reçoit la correction de ses
    voisines dans l'ordre de prise de vue (numéro de photo), interpolée entre la précédente et
    la suivante.
    """
    before = [n for n in corrections if n < number]
    after = [n for n in corrections if n > number]
    if not before or not after:
        return corrections[max(before) if before else min(after)]
    previous, following = max(before), min(after)
    t = (number - previous) / (following - previous)
    step = vector_from_rotation(corrections[previous].T @ corrections[following])
    return corrections[previous] @ rotation_from_vector(t * step)


def _align(
    cv2: Any,
    images: dict[int, np.ndarray],
    scales: dict[int, float],
    features: dict[int, Any],
    sensors: dict[int, np.ndarray] | None,
) -> tuple[list[Camera], list[int], list[int]]:
    """Renvoie les caméras, les photos écartées et celles placées par les seuls capteurs."""
    numbers = sorted(images)
    found = [features[n] for n in numbers]
    mask = neighbour_mask([sensors[n] for n in numbers]) if sensors else None
    pairwise = _match(cv2, found, mask)
    kept_positions = [
        int(i) for i in np.ravel(cv2.detail.leaveBiggestComponent(found, pairwise, CONF_THRESH))
    ]
    if len(kept_positions) < 2:
        raise StitchError(
            "Les photos n'ont pas assez de points communs pour être assemblées. "
            "Vérifier le recouvrement entre photos voisines (docs/prise-de-vue.md)."
        )
    rejected = [n for position, n in enumerate(numbers) if position not in kept_positions]
    kept = [numbers[position] for position in kept_positions]
    if rejected:
        found = [found[position] for position in kept_positions]
        if mask is not None:
            mask = mask[np.ix_(kept_positions, kept_positions)]
        pairwise = _match(cv2, found, mask)

    estimator = cv2.detail_HomographyBasedEstimator()
    ok, cameras = estimator.apply(found, pairwise, None)
    if not ok:
        raise StitchError("L'estimation de l'orientation des photos a échoué.")
    sizes = [(images[n].shape[1], images[n].shape[0]) for n in kept]
    pairs = _pair_matches(found, pairwise, sizes)
    focal = float(np.median([c.focal for c in cameras]))
    if sensors:
        start = [sensors[n] for n in kept]
        error = float(np.median(sensor_errors_deg(pairs, start, focal)))
        if error > SENSOR_MAX_ERROR_DEG:
            raise SensorMismatch(f"elles s'écartent de {error:.0f}° de ce que montrent les photos")
    else:
        start = initial_rotations(pairs, len(kept), focal)
    adjustment = adjust(pairs, start, focal)
    if not (np.isfinite(adjustment.focal) and adjustment.focal > 0):
        raise StitchError("L'ajustement de l'orientation des photos a échoué.")
    fov = 2 * math.degrees(math.atan(max(sizes[0]) / 2 / adjustment.focal))
    if not MIN_FOV_DEG <= fov <= MAX_FOV_DEG:
        raise StitchError(
            f"L'ajustement donne un angle de vue de {fov:.0f}°, invraisemblable pour l'objectif "
            "principal d'un téléphone. Les photos se recouvrent probablement trop peu."
        )
    rejected += [
        kept[position] for position in range(len(kept)) if position not in adjustment.connected
    ]
    kept = [kept[position] for position in adjustment.connected]
    if len(kept) < 2:
        raise StitchError(
            "Les photos n'ont pas assez de points communs cohérents pour être assemblées."
        )

    placed: list[int] = []
    if sensors:
        rotations = align_to_sensors(adjustment.rotations, [sensors[n] for n in kept])
        # Une photo sans points communs (mur ou plafond unis) prend l'orientation mesurée par
        # le téléphone, corrigée de la dérive du gyroscope constatée sur ses voisines.
        placed, rejected = sorted(rejected), []
        corrections = {n: R @ sensors[n].T for n, R in zip(kept, rotations, strict=True)}
        rotations += [drift_corrected(n, corrections) @ sensors[n] for n in placed]
        kept += placed
    else:
        corrected = cv2.detail.waveCorrect(
            [r.astype(np.float32) for r in adjustment.rotations], cv2.detail.WAVE_CORRECT_HORIZ
        )
        rotations = [np.asarray(r, dtype=np.float64) for r in corrected]
    rotations = level_and_anchor(rotations)

    result = []
    for number, rotation in zip(kept, rotations, strict=True):
        height, width = images[number].shape[:2]
        K_work = np.array(
            [[adjustment.focal, 0, width / 2], [0, adjustment.focal, height / 2], [0, 0, 1.0]]
        )
        K_full = np.diag([1 / scales[number], 1 / scales[number], 1.0]) @ K_work
        size = (round(width / scales[number]), round(height / scales[number]))
        result.append(Camera(number, K_full, rotation, size))
    return result, sorted(rejected), placed


def align(
    cv2: Any,
    images: dict[int, np.ndarray],
    scales: dict[int, float],
    sensors: dict[int, np.ndarray] | None = None,
) -> tuple[list[Camera], list[int], list[int], str | None]:
    """Aligne des photos réduites. Renvoie les caméras retenues, les photos écartées, celles
    placées par les seuls capteurs faute de points communs et, si les orientations du téléphone
    ont été écartées, la raison.

    images associe à chaque numéro de photo sa copie réduite, scales le facteur de réduction,
    sensors l'orientation mesurée par le téléphone (une pour chaque photo, ou None). Si les
    capteurs ne collent pas aux photos, l'alignement est refait à partir des seules photos.
    """
    finder = cv2.SIFT_create()
    features = {n: cv2.detail.computeImageFeatures2(finder, images[n]) for n in sorted(images)}
    if sensors is None:
        return *_align(cv2, images, scales, features, None), None
    try:
        return *_align(cv2, images, scales, features, sensors), None
    except (StitchError, SensorMismatch) as error:
        reason = str(error)
    return *_align(cv2, images, scales, features, None), reason


def level_and_anchor(rotations: list[np.ndarray]) -> list[np.ndarray]:
    """Remet le panorama à l'endroit et oriente la première photo vers la longitude 0.

    La correction d'horizon d'OpenCV laisse le haut et le bas indéterminés : on retourne
    l'ensemble si le haut des photos pointe en moyenne vers le bas du monde.
    """
    image_up = np.array([0.0, -1.0, 0.0])
    world_up = np.array([0.0, -1.0, 0.0])
    if np.mean([(R @ image_up) @ world_up for R in rotations]) < 0:
        flip = np.diag([-1.0, -1.0, 1.0])
        rotations = [flip @ R for R in rotations]
    axis = rotations[0] @ np.array([0.0, 0.0, 1.0])
    yaw = math.atan2(axis[0], axis[2])
    turn = rotation_y(-yaw)
    return [turn @ R for R in rotations]


# --- Rendu --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """Rectangle du panorama couvert par une photo : lignes [row0, row1), colonnes à partir
    de col0 sur ncols colonnes, lues modulo la largeur."""

    row0: int
    row1: int
    col0: int
    ncols: int

    def cols(self, width: int) -> np.ndarray:
        return (self.col0 + np.arange(self.ncols)) % width


def _visible(x: np.ndarray, y: np.ndarray, front: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return front & (x >= 0) & (x <= size[0] - 1) & (y >= 0) & (y <= size[1] - 1)


def footprint(camera: Camera, width: int) -> Window | None:
    """Fenêtre du panorama width × width/2 où la photo est visible, avec une marge."""
    coarse_w = min(width, FOOTPRINT_WIDTH)
    coarse_h = coarse_w // 2
    directions = equirect_directions(coarse_w, coarse_h, np.arange(coarse_h), np.arange(coarse_w))
    x, y, front = project(directions, camera.K, camera.R)
    visible = _visible(x, y, front, camera.size)
    rows = np.flatnonzero(visible.any(axis=1))
    if rows.size == 0:
        return None
    row0, row1 = max(rows[0] - 1, 0), min(rows[-1] + 2, coarse_h)
    cols = visible.any(axis=0)
    if cols.all():
        col0, ncols = 0, coarse_w
    else:
        # Fenêtre = complément du plus long intervalle de colonnes vides, sur le cercle.
        doubled = np.concatenate([~cols, ~cols])
        best_len, best_end, run = 0, 0, 0
        for position, empty in enumerate(doubled):
            run = run + 1 if empty else 0
            if run > best_len:
                best_len, best_end = run, position
        best_len = min(best_len, coarse_w)
        col0 = (best_end + 1) % coarse_w
        ncols = coarse_w - best_len
        col0, ncols = (col0 - 1) % coarse_w, min(ncols + 2, coarse_w)
    factor = width // coarse_w
    return Window(row0 * factor, row1 * factor, col0 * factor, ncols * factor)


def camera_maps(
    camera: Camera, K: np.ndarray, window: Window, width: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Coordonnées dans la photo (intrinsèques K) des pixels de la fenêtre, visibilité et poids.

    Le poids décroît du centre vers le bord de la photo : il sert à choisir la photo qui voit
    le mieux chaque pixel.
    """
    height = width // 2
    rows = np.arange(window.row0, window.row1)
    directions = equirect_directions(width, height, rows, window.cols(width))
    x, y, front = project(directions, K, camera.R)
    scale = K[0, 0] / camera.K[0, 0]
    size = (camera.size[0] * scale, camera.size[1] * scale)
    visible = _visible(x, y, front, (size[0], size[1]))
    weight = np.minimum(x, size[0] - 1 - x) / (size[0] / 2)
    weight *= np.minimum(y, size[1] - 1 - y) / (size[1] / 2)
    weight = np.where(visible, np.maximum(weight, 1e-6), 0.0).astype(np.float32)
    return x, y, visible, weight


def _warp(cv2: Any, image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return cv2.remap(image, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


@dataclass
class LowRes:
    """Photos projetées dans un panorama réduit, pour les calculs d'ensemble."""

    width: int
    warped: list[np.ndarray]
    masks: list[np.ndarray]


def low_res_warps(
    cv2: Any,
    cameras: list[Camera],
    images: dict[int, np.ndarray],
    scales: dict[int, float],
    width: int,
) -> LowRes:
    """Projette chaque photo réduite dans un panorama de largeur width."""
    height = width // 2
    directions = equirect_directions(width, height, np.arange(height), np.arange(width))
    warped, masks = [], []
    for camera in cameras:
        s = scales[camera.index]
        K_small = np.diag([s, s, 1.0]) @ camera.K
        x, y, front = project(directions, K_small, camera.R)
        image = images[camera.index]
        masks.append(_visible(x, y, front, (image.shape[1], image.shape[0])))
        warped.append(_warp(cv2, image, x, y).astype(np.float32))
    return LowRes(width, warped, masks)


def compute_gains(cameras: list[Camera], low: LowRes) -> dict[int, np.ndarray]:
    """Gain par photo et par canal qui égalise l'exposition dans les recouvrements.

    Même modèle que le GainCompensator d'OpenCV, calculé sur un panorama réduit.
    """
    warped, masks = low.warped, low.masks
    n = len(cameras)
    counts = np.zeros((n, n))
    means = np.zeros((n, n, 3))
    for i in range(n):
        for j in range(n):
            overlap = masks[i] & masks[j]
            counts[i, j] = overlap.sum()
            if counts[i, j] > 0:
                means[i, j] = warped[i][overlap].mean(axis=0)

    gains = np.ones((n, 3))
    for channel in range(3):
        A = np.zeros((n, n))
        b = np.zeros(n)
        for i in range(n):
            for j in range(n):
                b[i] += GAIN_BETA * counts[i, j]
                A[i, i] += GAIN_BETA * counts[i, j]
                if j == i:
                    continue
                A[i, i] += 2 * GAIN_ALPHA * means[i, j, channel] ** 2 * counts[i, j]
                A[i, j] -= (
                    2 * GAIN_ALPHA * means[i, j, channel] * means[j, i, channel] * counts[i, j]
                )
        gains[:, channel] = np.linalg.lstsq(A, b, rcond=None)[0]
    gains = np.clip(gains, *GAIN_LIMITS)
    return {camera.index: gains[k] for k, camera in enumerate(cameras)}


def is_horizon(camera: Camera) -> bool:
    """Vrai si l'axe de la photo est proche de l'horizon."""
    axis = camera.R[:, 2]
    return abs(math.degrees(math.asin(float(np.clip(-axis[1], -1.0, 1.0))))) <= (
        HORIZON_MAX_PITCH_DEG
    )


def horizon_priority(
    cameras: list[Camera], masks: list[np.ndarray], width: int
) -> list[np.ndarray]:
    """Retire aux photos hors de l'horizon la zone que les photos de l'horizon voient bien.

    masks sont les zones visibles de chaque photo dans un panorama de largeur width. Rien n'est
    retiré s'il n'y a pas de photo à l'horizon.
    """
    height = width // 2
    directions = equirect_directions(width, height, np.arange(height), np.arange(width))
    inner = np.zeros((height, width), bool)
    for camera in cameras:
        if not is_horizon(camera):
            continue
        x, y, front = project(directions, camera.K, camera.R)
        w, h = camera.size
        mx, my = w * HORIZON_INNER_MARGIN, h * HORIZON_INNER_MARGIN
        inner |= front & (x >= mx) & (x <= w - mx) & (y >= my) & (y <= h - my)
    return [
        mask if is_horizon(camera) else mask & ~inner
        for camera, mask in zip(cameras, masks, strict=True)
    ]


def find_seams(
    cv2: Any, cameras: list[Camera], low: LowRes, gains: dict[int, np.ndarray]
) -> list[np.ndarray]:
    """Zone attribuée à chaque photo, avec des raccords qui passent là où les photos voisines
    se ressemblent le plus (coupe minimale d'OpenCV, sur le panorama réduit).

    Le panorama est prolongé d'une marge de chaque côté pour que les raccords restent
    cohérents à la longitude 180°.
    """
    margin = low.width // 8
    images, masks, corners, boxes = [], [], [], []
    priority = horizon_priority(cameras, low.masks, low.width)
    for camera, warped, mask in zip(cameras, low.warped, priority, strict=True):
        if not mask.any():
            # Photo entièrement couverte par l'horizon : un pixel suffit à la garder en lice.
            mask = np.zeros_like(mask)
            mask[0, 0] = True
        image = warped * gains[camera.index].astype(np.float32)
        image = np.concatenate([image[:, -margin:], image, image[:, :margin]], axis=1)
        wrapped = np.concatenate([mask[:, -margin:], mask, mask[:, :margin]], axis=1)
        # Chaque photo est recadrée sur sa zone visible : OpenCV ne compare alors que les
        # photos dont les zones se touchent.
        rows, cols = np.flatnonzero(wrapped.any(axis=1)), np.flatnonzero(wrapped.any(axis=0))
        box = (rows[0], rows[-1] + 1, cols[0], cols[-1] + 1)
        images.append(np.ascontiguousarray(image[box[0] : box[1], box[2] : box[3]]))
        crop = wrapped[box[0] : box[1], box[2] : box[3]].astype(np.uint8) * 255
        masks.append(cv2.UMat(np.ascontiguousarray(crop)))
        corners.append((int(box[2]), int(box[0])))
        boxes.append(box)
    finder = cv2.detail_GraphCutSeamFinder("COST_COLOR_GRAD")
    found = finder.find(images, corners, masks)
    seams = []
    for mask, box in zip(found, boxes, strict=True):
        full = np.zeros((low.width // 2, low.width + 2 * margin), bool)
        full[box[0] : box[1], box[2] : box[3]] = np.asarray(mask.get()) > 0
        # Les marges reviennent sur les bords opposés du panorama.
        seam = full[:, margin:-margin].copy()
        seam[:, :margin] |= full[:, -margin:]
        seam[:, -margin:] |= full[:, :margin]
        seams.append(seam)
    return seams


def render(
    cv2: Any,
    cameras: list[Camera],
    photos: list[Photo],
    gains: dict[int, np.ndarray],
    seams: list[np.ndarray],
    width: int,
    out: TextIO,
) -> tuple[np.ndarray, np.ndarray]:
    """Panorama width × width/2 en BGR et masque des pixels vus par au moins une photo."""
    height = width // 2
    windows = {camera.index: footprint(camera, width) for camera in cameras}

    # Pour chaque pixel, la photo à qui la recherche de raccords l'a attribué. Là où elle ne le
    # voit pas (bords, à pleine résolution), celle qui le voit le plus près de son centre.
    best_weight = np.zeros((height, width), np.float32)
    owner = np.full((height, width), -1, np.int16)
    seam_h, seam_w = seams[0].shape
    for camera, seam in zip(cameras, seams, strict=True):
        window = windows[camera.index]
        if window is None:
            continue
        _, _, _, weight = camera_maps(camera, camera.K, window, width)
        cols = window.cols(width)
        seam_rows = np.arange(window.row0, window.row1) * seam_h // height
        weight = weight * (1.0 + SEAM_PRIORITY * seam[np.ix_(seam_rows, cols * seam_w // width)])
        current = best_weight[window.row0 : window.row1][:, cols]
        better = weight > current
        best_weight[window.row0 : window.row1, cols] = np.where(better, weight, current)
        owners = owner[window.row0 : window.row1][:, cols]
        owner[window.row0 : window.row1, cols] = np.where(better, camera.index, owners)

    margin = min(512, width // 4)
    blend_width = math.sqrt(width * height) * BLEND_STRENGTH
    bands = max(1, math.ceil(math.log2(max(blend_width, 2))) - 1)
    blender = cv2.detail_MultiBandBlender(0, bands)
    blender.prepare((-margin, 0, width + 2 * margin, height))

    for number, camera in enumerate(cameras, start=1):
        window = windows[camera.index]
        if window is None:
            continue
        print(f"  Rendu de la photo {number} sur {len(cameras)}", file=out, flush=True)
        image = cv2.imread(str(photos[camera.index].readable), cv2.IMREAD_COLOR)
        scale = min(1.0, RENDER_OVERSAMPLE * width / (2 * math.pi * camera.K[0, 0]))
        if scale < 1.0:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        K = np.diag([scale, scale, 1.0]) @ camera.K
        x, y, visible, _ = camera_maps(camera, K, window, width)
        warped = _warp(cv2, image, x, y).astype(np.float32) * gains[camera.index]
        warped = np.clip(warped, 0, 255).astype(np.int16)
        cols = window.cols(width)
        mask = (owner[window.row0 : window.row1][:, cols] == camera.index) & visible
        if not mask.any():
            continue
        mask = mask.astype(np.uint8) * 255
        # Le panorama se referme sur lui-même : on fournit aussi les copies décalées d'un tour
        # qui tombent dans les marges, pour que le fondu soit continu à la longitude 180°.
        for shift in (-width, 0, width):
            left = window.col0 + shift
            start = max(left, -margin)
            stop = min(left + window.ncols, width + margin)
            if start >= stop:
                continue
            part = slice(start - left, stop - left)
            blender.feed(
                np.ascontiguousarray(warped[:, part]),
                np.ascontiguousarray(mask[:, part]),
                (start, window.row0),
            )

    result, result_mask = blender.blend(None, None)
    panorama = np.clip(result[:, margin : margin + width], 0, 255).astype(np.uint8)
    covered = result_mask[:, margin : margin + width] > 0
    return panorama, covered


# --- Trous --------------------------------------------------------------------------------


def _merge_across_seam(labels: np.ndarray, count: int) -> np.ndarray:
    """Fusionne les zones coupées par le bord gauche-droite du panorama."""
    parent = list(range(count))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for left, right in zip(labels[:, 0], labels[:, -1], strict=True):
        if left and right:
            parent[find(int(left))] = find(int(right))
    roots = np.array([find(label) for label in range(count)])
    return roots[labels]


def _lon_range(cols: np.ndarray, width: int) -> tuple[float, float]:
    """Plus petit arc de longitudes (degrés) contenant les colonnes données."""
    present = np.zeros(width, bool)
    present[cols] = True
    if present.all():
        return -180.0, 180.0
    doubled = np.concatenate([~present, ~present])
    best_len, best_end, run = 0, 0, 0
    for position, empty in enumerate(doubled):
        run = run + 1 if empty else 0
        if run > best_len:
            best_len, best_end = run, position
    first = (best_end + 1) % width
    last = (first + width - best_len - 1) % width

    def to_lon(col: int) -> float:
        return (col + 0.5) / width * 360.0 - 180.0

    return round(to_lon(first)), round(to_lon(last))


def find_holes(cv2: Any, covered: np.ndarray) -> tuple[list[Hole], np.ndarray]:
    """Décrit les zones non couvertes et renvoie aussi le masque de celles à flouter.

    L'analyse se fait sur une version réduite du masque.
    """
    height, width = covered.shape
    small_w = min(width, ANALYSIS_WIDTH)
    small_h = small_w // 2
    holes_small = cv2.resize(
        (~covered).astype(np.uint8), (small_w, small_h), interpolation=cv2.INTER_NEAREST
    )
    count, labels = cv2.connectedComponents(holes_small, connectivity=8)
    labels = _merge_across_seam(labels, count)
    row_weights = latitude_weights(small_h)
    blur_small = np.zeros((small_h, small_w), np.uint8)
    holes = []
    for label in np.unique(labels):
        if label == 0:
            continue
        region = labels == label
        part = float((region.mean(axis=1) * row_weights).sum())
        if part < MIN_HOLE_PART:
            continue
        rows = np.flatnonzero(region.any(axis=1))
        lat_max = 90.0 - (rows[0] + 0.5) / small_h * 180.0
        lat_min = 90.0 - (rows[-1] + 0.5) / small_h * 180.0
        lon_min, lon_max = _lon_range(np.flatnonzero(region.any(axis=0)), small_w)
        if rows[-1] == small_h - 1:
            kind, near_pole = "sol", lat_max <= -BLUR_FILL_MIN_ABS_LAT
        elif rows[0] == 0:
            kind, near_pole = "plafond", lat_min >= BLUR_FILL_MIN_ABS_LAT
        else:
            kind, near_pole = "trou", False
        if near_pole:
            blur_small[region] = 1
        fill = "flou" if near_pole else "gris"
        holes.append(
            Hole(kind, round(part, 4), round(lat_min), round(lat_max), lon_min, lon_max, fill)
        )
    holes.sort(key=lambda hole: -hole.part)
    blur = cv2.resize(blur_small, (width, height), interpolation=cv2.INTER_NEAREST) > 0
    return holes, blur & ~covered


def smooth_fill(cv2: Any, image: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Remplit les pixels inconnus par des moyennes de plus en plus larges de leurs voisins.

    On réduit l'image par moitiés successives en ignorant les pixels inconnus, puis on remonte
    en bouchant chaque trou avec le niveau plus grossier. Le résultat est flou au cœur du trou
    et raccordé à ses bords.
    """
    weight = known.astype(np.float32)
    values = image.astype(np.float32) * weight[..., None]
    levels = []
    while min(weight.shape) > 4:
        levels.append((values, weight))
        values, weight = cv2.pyrDown(values), cv2.pyrDown(weight)
    filled = values / np.maximum(weight, 1e-6)[..., None]
    for values, weight in reversed(levels):
        upper = cv2.resize(
            filled, (weight.shape[1], weight.shape[0]), interpolation=cv2.INTER_LINEAR
        )
        presence = np.clip(weight, 0.0, 1.0)[..., None]
        filled = values / np.maximum(weight, 1e-6)[..., None] * presence + upper * (1 - presence)
    return filled


def fill_holes(cv2: Any, panorama: np.ndarray, covered: np.ndarray, blur: np.ndarray) -> np.ndarray:
    """Bouche les trous : flou étiré depuis les bords près des pôles, gris ailleurs."""
    result = panorama.copy()
    if blur.any():
        height, width = covered.shape
        small_size = (max(width // 8, 64), max(height // 8, 32))
        small = cv2.resize(panorama, small_size, interpolation=cv2.INTER_AREA)
        small_known = cv2.resize(covered.astype(np.uint8), small_size, interpolation=cv2.INTER_AREA)
        small_known = cv2.erode(small_known, np.ones((3, 3), np.uint8))
        filled = smooth_fill(cv2, small, small_known > 0)
        filled = cv2.GaussianBlur(filled, (0, 0), sigmaX=small_size[0] / 200)
        filled = cv2.resize(filled, (width, height), interpolation=cv2.INTER_LINEAR)
        result[blur] = np.clip(filled[blur], 0, 255).astype(np.uint8)
    result[~covered & ~blur] = HOLE_GRAY
    return result


# --- Commande -----------------------------------------------------------------------------


def _inputs(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {"name": path.name, "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        for path in paths
    ]


def _settings(width: int) -> dict[str, Any]:
    return {"width": width, "tool_version": __version__, "report_format": REPORT_FORMAT}


def is_up_to_date(folders: Folders, paths: list[Path], width: int) -> bool:
    """Vrai si le panorama existe et a été calculé avec ces photos et ces réglages."""
    if not folders.panorama.is_file() or not folders.report.is_file():
        return False
    try:
        report = json.loads(folders.report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return report.get("settings") == _settings(width) and report.get("inputs") == _inputs(paths)


def _write_atomic(path: Path, data: bytes) -> None:
    partial = path.with_name(path.name + ".partiel")
    partial.write_bytes(data)
    os.replace(partial, path)


def _percent(value: float) -> str:
    if 0 < value < 0.001:
        return "moins de 0,1 %"
    return f"{value * 100:.1f}".replace(".", ",") + " %"


def describe_hole(hole: Hole) -> str:
    """Description en clair d'une zone manquante."""
    if hole.kind == "sol":
        where = f"sol, sous {hole.lat_max:.0f}°"
    elif hole.kind == "plafond":
        where = f"plafond, au-dessus de {hole.lat_min:.0f}°"
    else:
        where = (
            f"trou entre {hole.lon_min:.0f}° et {hole.lon_max:.0f}° de longitude, "
            f"de {hole.lat_min:.0f}° à {hole.lat_max:.0f}° de latitude"
        )
    fill = "remplie par un flou" if hole.fill == "flou" else "laissée en gris"
    return f"{where} ({_percent(hole.part)} de la sphère), {fill}"


CAPTURE_IGNORED = "orientations du téléphone ignorées"


def phone_orientations(
    folders: Folders, paths: list[Path], images: dict[int, np.ndarray]
) -> tuple[dict[int, np.ndarray] | None, dict[str, str | None]]:
    """Orientations de `capture.json` par numéro de photo lisible, et leur description.

    Elles ne servent que si chaque photo lisible en a une : sinon l'alignement se fait à partir
    des seules photos, comme sans app.
    """
    path = capture.find(folders.point)
    if path is None:
        return None, {"source": SOURCE_IMAGES, "detail": None}
    try:
        found = capture.load(path)
    except capture.CaptureError as error:
        raise StitchError(
            f"{error} Supprimer {path} pour assembler sans les orientations du téléphone."
        ) from error
    missing = [paths[n].name for n in sorted(images) if paths[n].name not in found.rotations]
    if missing:
        detail = f"{CAPTURE_IGNORED} : {len(missing)} photo(s) absente(s) de {path.name}"
        return None, {"source": SOURCE_IMAGES, "detail": detail}
    sensors = {n: found.rotations[paths[n].name] for n in images}
    return sensors, {"source": SOURCE_SENSORS, "detail": None}


def describe_orientations(orientations: dict[str, str | None]) -> str:
    """Origine des orientations de départ, en clair."""
    if orientations["source"] == SOURCE_SENSORS:
        return f"mesurées par le téléphone ({capture.FILE_NAME})"
    return orientations["detail"] or "déduites des photos"


def stitch(folders: Folders, width: int, force: bool, out: TextIO) -> dict[str, Any] | None:
    """Assemble le panorama d'un point. Renvoie le rapport, ou None s'il était déjà à jour."""
    if width % 2 or not MIN_WIDTH <= width <= MAX_WIDTH:
        raise StitchError(
            f"Largeur invalide : {width}. Donner un nombre pair entre {MIN_WIDTH} et {MAX_WIDTH}."
        )
    paths = list_photos(folders.photos)
    inputs = paths + [path for path in [capture.find(folders.point)] if path]
    if not force and is_up_to_date(folders, inputs, width):
        return None
    cv2 = load_cv2()

    print(f"Assemblage de {len(paths)} photos ({folders.photos})", file=out, flush=True)
    photos = prepare_photos(paths, folders.cache)
    images: dict[int, np.ndarray] = {}
    scales: dict[int, float] = {}
    reasons: dict[int, str] = {}
    for number, photo in enumerate(photos):
        image = cv2.imread(str(photo.readable), cv2.IMREAD_COLOR)
        if image is None:
            reasons[number] = REJECTED_UNREADABLE
            continue
        scale = _work_scale((image.shape[1], image.shape[0]))
        images[number] = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        scales[number] = scale
    if len(images) < 2:
        raise StitchError("Il faut au moins 2 photos lisibles pour assembler un panorama.")

    sensors, orientations = phone_orientations(folders, paths, images)
    print("  Alignement des photos", file=out, flush=True)
    cameras, unmatched, placed, ignored = align(cv2, images, scales, sensors)
    if ignored:
        orientations = {"source": SOURCE_IMAGES, "detail": f"{CAPTURE_IGNORED} : {ignored}"}
    print(f"  Orientations : {describe_orientations(orientations)}", file=out, flush=True)
    for number in unmatched:
        reasons[number] = REJECTED_UNMATCHED
    print("  Exposition et raccords", file=out, flush=True)
    gains = compute_gains(cameras, low_res_warps(cv2, cameras, images, scales, ANALYSIS_WIDTH))
    seam_width = min(SEAM_WIDTH, width // 2)
    seams = find_seams(cv2, cameras, low_res_warps(cv2, cameras, images, scales, seam_width), gains)
    images.clear()

    panorama, covered = render(cv2, cameras, photos, gains, seams, width, out)
    holes, blur = find_holes(cv2, covered)
    panorama = fill_holes(cv2, panorama, covered, blur)
    coverage = 1.0 - float(((~covered).mean(axis=1) * latitude_weights(width // 2)).sum())

    ok, encoded = cv2.imencode(".jpg", panorama, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise StitchError("L'écriture du panorama en JPEG a échoué.")
    _write_atomic(folders.panorama, encoded.tobytes())

    report = {
        "settings": _settings(width),
        "inputs": _inputs(inputs),
        "panorama": {"file": folders.panorama.name, "width": width, "height": width // 2},
        "photos": [
            {
                "file": path.name,
                "used": number not in reasons,
                "reason": reasons.get(number),
                "placed_by_sensors": number in placed,
            }
            for number, path in enumerate(paths)
        ],
        "orientations": orientations,
        "coverage": round(coverage, 4),
        "missing_areas": [asdict(hole) for hole in holes],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    _write_atomic(folders.report, text.encode("utf-8"))
    return report


def print_report(report: dict[str, Any], folders: Folders, out: TextIO) -> None:
    """Résumé lisible du rapport."""
    panorama = report["panorama"]
    used = [photo for photo in report["photos"] if photo["used"]]
    print(f"\nPanorama : {folders.panorama} ({panorama['width']} × {panorama['height']})", file=out)
    print(f"Photos utilisées : {len(used)} sur {len(report['photos'])}", file=out)
    for photo in report["photos"]:
        if not photo["used"]:
            print(f"  Rejetée : {photo['file']} ({photo['reason']})", file=out)
        elif photo.get("placed_by_sensors"):
            print(f"  Placée par les capteurs : {photo['file']} ({PLACED_BY_SENSORS})", file=out)
    print(f"Orientations : {describe_orientations(report['orientations'])}", file=out)
    print(f"Couverture : {_percent(report['coverage'])} de la sphère", file=out)
    holes = [Hole(**hole) for hole in report["missing_areas"]]
    if holes:
        print("Zones manquantes :", file=out)
        for hole in holes:
            print(f"  - {describe_hole(hole)}", file=out)
    else:
        print("Zones manquantes : aucune", file=out)
    print(f"Rapport : {folders.report}", file=out)


def run(
    target: Path, width: int = DEFAULT_WIDTH, force: bool = False, out: TextIO | None = None
) -> int:
    """Point d'entrée de `visite360 stitch`. Renvoie le code de sortie."""
    out = out or sys.stdout
    try:
        folders = resolve_folders(target)
        report = stitch(folders, width, force, out)
    except (StitchError, PhotoError, OpenCVError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    if report is None:
        print(
            f"Panorama déjà à jour : {folders.panorama}. Ajouter --force pour le recalculer.",
            file=out,
        )
        return 0
    print_report(report, folders, out)
    return 0
