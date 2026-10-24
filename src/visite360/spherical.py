"""Géométrie du panorama équirectangulaire (D6).

Repère du monde, celui des caméras d'OpenCV : x vers la droite, y vers le bas, z vers l'avant.
Dans le panorama, la colonne donne la longitude (de -180° à 180°, 0° au centre) et la ligne
donne l'angle depuis le zénith (de 0° en haut à 180° en bas). Une caméra est décrite par sa
matrice intrinsèque K et sa rotation R : un pixel p voit la direction R @ inv(K) @ p.
"""

from __future__ import annotations

import numpy as np


def equirect_directions(width: int, height: int, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Directions unitaires visées par les pixels (rows × cols) d'un panorama width × height.

    Renvoie un tableau (len(rows), len(cols), 3) en float32. Les colonnes peuvent dépasser
    la largeur : elles sont lues modulo width.
    """
    lon = ((np.asarray(cols, dtype=np.float64) + 0.5) / width) * 2.0 * np.pi - np.pi
    theta = ((np.asarray(rows, dtype=np.float64) + 0.5) / height) * np.pi
    sin_t = np.sin(theta)[:, None]
    directions = np.empty((len(theta), len(lon), 3), dtype=np.float32)
    directions[..., 0] = sin_t * np.sin(lon)[None, :]
    directions[..., 1] = -np.cos(theta)[:, None]
    directions[..., 2] = sin_t * np.cos(lon)[None, :]
    return directions


def directions_to_equirect(directions: np.ndarray, width: int, height: int) -> np.ndarray:
    """Coordonnées (colonne, ligne) en pixels, non arrondies, de directions dans le panorama."""
    x, y, z = directions[..., 0], directions[..., 1], directions[..., 2]
    norm = np.sqrt(x * x + y * y + z * z)
    lon = np.arctan2(x, z)
    theta = np.arccos(np.clip(-y / norm, -1.0, 1.0))
    col = (lon + np.pi) / (2.0 * np.pi) * width - 0.5
    row = theta / np.pi * height - 0.5
    return np.stack([col, row], axis=-1)


def rotation_y(angle: float) -> np.ndarray:
    """Rotation d'un angle (radians) autour de l'axe vertical : vers la droite si positif."""
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rotation_x(angle: float) -> np.ndarray:
    """Rotation d'un angle (radians) autour de l'axe horizontal : vers le haut si positif."""
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def camera_rotation(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """Rotation d'une caméra tournée de yaw_deg vers la droite et pitch_deg vers le haut."""
    return rotation_y(np.radians(yaw_deg)) @ rotation_x(np.radians(pitch_deg))


def project(directions: np.ndarray, K: np.ndarray, R: np.ndarray) -> tuple[np.ndarray, ...]:
    """Projette des directions du monde dans l'image d'une caméra.

    Renvoie (x, y, devant) : coordonnées en pixels (float32) et masque des directions situées
    devant la caméra. Les coordonnées des directions derrière la caméra valent -1.
    """
    M = (K @ R.T).astype(np.float32)
    p = directions @ M.T
    in_front = p[..., 2] > 1e-6
    safe_z = np.where(in_front, p[..., 2], 1.0)
    x = np.where(in_front, p[..., 0] / safe_z, -1.0).astype(np.float32)
    y = np.where(in_front, p[..., 1] / safe_z, -1.0).astype(np.float32)
    return x, y, in_front


def latitude_weights(height: int) -> np.ndarray:
    """Aire relative de chaque ligne du panorama sur la sphère (somme égale à 1)."""
    theta = (np.arange(height) + 0.5) / height * np.pi
    weights = np.sin(theta)
    return weights / weights.sum()
