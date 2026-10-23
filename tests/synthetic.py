"""Panorama de synthèse et photos découpées dedans, générés pendant les tests.

Aucune image n'est stockée dans le dépôt : tout est recalculé à partir d'une graine.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from visite360.spherical import camera_rotation, directions_to_equirect

# Prise de vue de la fiche docs/prise-de-vue.md : (inclinaison en degrés, nombre de photos).
FULL_ROWS: tuple[tuple[float, int], ...] = ((0.0, 12), (45.0, 8), (-45.0, 8), (90.0, 1), (-90.0, 1))


@dataclass(frozen=True)
class View:
    """Une photo de synthèse et l'orientation avec laquelle elle a été prise."""

    image: np.ndarray
    yaw: float
    pitch: float


def make_panorama(width: int = 2048, seed: int = 0) -> np.ndarray:
    """Panorama texturé, riche en coins et en contours pour l'appariement des photos."""
    height = width // 2
    rng = np.random.default_rng(seed)
    # Fond : dégradé doux pour éviter les grandes zones uniformes.
    rows = np.linspace(0, 1, height)[:, None, None]
    cols = np.linspace(0, 1, width)[None, :, None]
    base = 60 + 80 * rows * np.array([1.0, 0.6, 0.3]) + 60 * cols * np.array([0.2, 0.5, 1.0])
    image = np.ascontiguousarray(base.astype(np.uint8))

    for _ in range(width * 2):
        cx = int(rng.integers(0, width))
        cy = int(rng.integers(0, height))
        lat = np.pi / 2 - (cy + 0.5) / height * np.pi
        radius = int(rng.integers(width // 300 + 2, width // 60 + 4))
        # Les formes sont élargies vers les pôles pour garder une taille constante sur la sphère.
        stretch = 1.0 / max(np.cos(lat), 0.08)
        axes = (min(int(radius * stretch), width // 4), radius)
        color = tuple(int(c) for c in rng.integers(0, 256, 3))
        kind = rng.integers(0, 3)
        for shift in (-width, 0, width):
            center = (cx + shift, cy)
            if kind == 0:
                cv2.ellipse(image, center, axes, 0, 0, 360, color, -1)
            elif kind == 1:
                top_left = (center[0] - axes[0], cy - radius)
                bottom_right = (center[0] + axes[0], cy + radius)
                cv2.rectangle(image, top_left, bottom_right, color, -1)
            else:
                end = (center[0] + axes[0], cy + int(rng.integers(-radius, radius + 1)))
                cv2.line(image, center, end, color, max(1, radius // 4))
    noise = rng.normal(0, 4, image.shape)
    return np.clip(image + noise, 0, 255).astype(np.uint8)


def intrinsics(width: int, height: int, horizontal_fov_deg: float) -> np.ndarray:
    """Matrice K d'une caméra sans distorsion."""
    focal = (width / 2) / np.tan(np.radians(horizontal_fov_deg) / 2)
    return np.array([[focal, 0.0, width / 2], [0.0, focal, height / 2], [0.0, 0.0, 1.0]])


def render_view(
    panorama: np.ndarray,
    yaw: float,
    pitch: float,
    size: tuple[int, int] = (400, 600),
    horizontal_fov_deg: float = 50.0,
) -> np.ndarray:
    """Photo (largeur, hauteur) = size prise depuis le centre du panorama."""
    width, height = size
    K = intrinsics(width, height, horizontal_fov_deg)
    R = camera_rotation(yaw, pitch)
    u, v = np.meshgrid(np.arange(width) + 0.0, np.arange(height) + 0.0)
    pixels = np.stack([u, v, np.ones_like(u)], axis=-1)
    directions = pixels @ (R @ np.linalg.inv(K)).T
    coords = directions_to_equirect(directions, panorama.shape[1], panorama.shape[0])
    pad = 2
    padded = np.concatenate([panorama[:, -pad:], panorama, panorama[:, :pad]], axis=1)
    map_x = (coords[..., 0] + pad).astype(np.float32)
    map_y = coords[..., 1].astype(np.float32)
    return cv2.remap(padded, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def shoot(
    panorama: np.ndarray,
    rows: tuple[tuple[float, int], ...] = FULL_ROWS,
    size: tuple[int, int] = (400, 600),
) -> list[View]:
    """Photos d'un point selon les rangées données, la première face à la longitude 0."""
    views = []
    for pitch, count in rows:
        for index in range(count):
            yaw = 360.0 * index / count
            views.append(View(render_view(panorama, yaw, pitch, size), yaw, pitch))
    return views
