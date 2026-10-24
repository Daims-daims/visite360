"""Ajustement robuste de l'orientation des photos et de leur focale commune (D21).

Toutes les photos d'un point sont prises du même endroit avec le même objectif : on cherche
une rotation par photo et une seule focale telles que chaque paire de points appariés vise la
même direction. Les correspondances aberrantes (parallaxe, objet qui bouge, motif répété)
voient leur poids réduit, puis les paires de photos qui restent incohérentes sont écartées.

Les points sont donnés en pixels, l'origine au centre de l'image réduite.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Échelles successives de tolérance (degrés) : large au départ pour converger depuis une
# estimation grossière, fine à la fin pour la précision.
ROBUST_SCALES_DEG = (5.0, 2.0, 0.5)
ITERATIONS_PER_SCALE = 15
# Une paire dont l'écart médian reste au-dessus est jugée incohérente.
PAIR_MAX_ERROR_DEG = 1.5
MAX_MATCHES_PER_PAIR = 300
# Nombre maximal de passes d'élimination des paires incohérentes.
MAX_FILTER_ROUNDS = 4


@dataclass(frozen=True)
class PairMatches:
    """Points appariés entre les photos i et j (positions dans la liste des photos)."""

    i: int
    j: int
    points_i: np.ndarray
    points_j: np.ndarray


@dataclass(frozen=True)
class Adjustment:
    """Résultat : rotations, focale commune, paires retenues et photos reliées."""

    rotations: list[np.ndarray]
    focal: float
    pairs: list[PairMatches]
    connected: list[int]


def rays(points: np.ndarray, focal: float) -> np.ndarray:
    """Directions unitaires, dans le repère de la photo, des points (origine au centre)."""
    vectors = np.column_stack([points / focal, np.ones(len(points))])
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def rotation_from_vector(vector: np.ndarray) -> np.ndarray:
    """Rotation d'axe vector et d'angle sa norme (formule de Rodrigues)."""
    angle = float(np.linalg.norm(vector))
    if angle < 1e-12:
        return np.eye(3)
    k = vector / angle
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def vector_from_rotation(rotation: np.ndarray) -> np.ndarray:
    """Vecteur d'axe et d'angle (radians) d'une rotation, inverse de rotation_from_vector."""
    cosine = np.clip((np.trace(rotation) - 1) / 2, -1.0, 1.0)
    angle = float(np.arccos(cosine))
    axis = np.array(
        [
            rotation[2, 1] - rotation[1, 2],
            rotation[0, 2] - rotation[2, 0],
            rotation[1, 0] - rotation[0, 1],
        ]
    )
    if angle < 1e-9:
        return axis / 2
    if np.pi - angle < 1e-6:
        # Demi-tour : l'axe est la colonne dominante de (R + I) / 2.
        column = (rotation + np.eye(3))[:, int(np.argmax(np.diag(rotation)))]
        return angle * column / np.linalg.norm(column)
    return angle * axis / (2 * np.sin(angle))


def _skew(v: np.ndarray) -> np.ndarray:
    """Matrices antisymétriques [v]× pour un tableau (N, 3)."""
    out = np.zeros((len(v), 3, 3))
    out[:, 0, 1], out[:, 0, 2] = -v[:, 2], v[:, 1]
    out[:, 1, 0], out[:, 1, 2] = v[:, 2], -v[:, 0]
    out[:, 2, 0], out[:, 2, 1] = -v[:, 1], v[:, 0]
    return out


def _residuals(
    pairs: list[PairMatches], rotations: list[np.ndarray], focal: float
) -> list[np.ndarray]:
    """Écarts entre directions appariées, multipliés par la focale : environ des pixels.

    Sans ce facteur, agrandir la focale resserrerait toutes les directions autour de l'axe
    de la photo et ferait baisser les écarts sans rien aligner.
    """
    return [
        focal
        * (rays(p.points_i, focal) @ rotations[p.i].T - rays(p.points_j, focal) @ rotations[p.j].T)
        for p in pairs
    ]


def _robust_cost(residuals: list[np.ndarray], scale: float) -> float:
    squared = np.concatenate([np.sum(r * r, axis=1) for r in residuals])
    return float(np.sum(np.log1p(squared / scale**2)))


def pair_errors_deg(
    pairs: list[PairMatches], rotations: list[np.ndarray], focal: float
) -> list[float]:
    """Écart angulaire médian (degrés) entre points appariés, pour chaque paire."""
    return [
        float(np.degrees(np.median(np.linalg.norm(r, axis=1)) / focal))
        for r in _residuals(pairs, rotations, focal)
    ]


def _solve(
    pairs: list[PairMatches], rotations: list[np.ndarray], focal: float, scale: float
) -> tuple[list[np.ndarray], float]:
    """Levenberg-Marquardt sur les rotations (la photo 0 sert de référence) et log(focale).

    scale est la tolérance robuste en radians, convertie en pixels avec la focale de départ.
    """
    scale = scale * focal
    count = len(rotations)
    n_params = 3 * (count - 1) + 1
    damping = 1e-3
    residuals = _residuals(pairs, rotations, focal)
    cost = _robust_cost(residuals, scale)
    for _ in range(ITERATIONS_PER_SCALE):
        H = np.zeros((n_params, n_params))
        g = np.zeros(n_params)
        step = 1e-4
        for pair, r in zip(pairs, residuals, strict=True):
            world_i = rays(pair.points_i, focal) @ rotations[pair.i].T
            world_j = rays(pair.points_j, focal) @ rotations[pair.j].T
            # Dérivée par rapport à log(focale), par différence finie.
            plus = _residuals([pair], rotations, focal * np.exp(step))[0]
            d_focal = (plus - r) / step
            weights = 1.0 / (1.0 + np.sum(r * r, axis=1) / scale**2)
            blocks = {n_params - 1: d_focal[:, :, None]}
            # Une rotation infinitésimale w déplace v de w × v = -[v]× w.
            if pair.i > 0:
                blocks[3 * (pair.i - 1)] = -focal * _skew(world_i)
            if pair.j > 0:
                blocks[3 * (pair.j - 1)] = focal * _skew(world_j)
            for col_a, J_a in blocks.items():
                width_a = J_a.shape[2]
                g[col_a : col_a + width_a] += np.einsum("n,nk,nka->a", weights, r, J_a)
                for col_b, J_b in blocks.items():
                    width_b = J_b.shape[2]
                    H[col_a : col_a + width_a, col_b : col_b + width_b] += np.einsum(
                        "n,nka,nkb->ab", weights, J_a, J_b
                    )
        while True:
            delta = np.linalg.solve(H + damping * np.diag(np.diag(H) + 1e-9), -g)
            candidate = [rotations[0]] + [
                rotation_from_vector(delta[3 * (k - 1) : 3 * k]) @ rotations[k]
                for k in range(1, count)
            ]
            candidate_focal = focal * float(np.exp(delta[-1]))
            candidate_residuals = _residuals(pairs, candidate, candidate_focal)
            candidate_cost = _robust_cost(candidate_residuals, scale)
            if candidate_cost <= cost:
                rotations, focal, residuals, cost = (
                    candidate,
                    candidate_focal,
                    candidate_residuals,
                    candidate_cost,
                )
                damping = max(damping / 3, 1e-7)
                break
            damping *= 4
            if damping > 1e6:
                return rotations, focal
        if np.max(np.abs(delta)) < 1e-7:
            break
    return rotations, focal


def _largest_component(count: int, pairs: list[PairMatches]) -> list[int]:
    neighbours: dict[int, set[int]] = {k: set() for k in range(count)}
    for pair in pairs:
        neighbours[pair.i].add(pair.j)
        neighbours[pair.j].add(pair.i)
    best: list[int] = []
    seen: set[int] = set()
    for start in range(count):
        if start in seen:
            continue
        component, stack = [], [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for other in neighbours[node] - seen:
                seen.add(other)
                stack.append(other)
        if len(component) > len(best):
            best = component
    return sorted(best)


def relative_rotation(pair: PairMatches, focal: float) -> np.ndarray:
    """Rotation Q qui envoie les directions de la photo i sur celles de la photo j (Kabsch)."""
    a, b = rays(pair.points_i, focal), rays(pair.points_j, focal)
    U, _, Vt = np.linalg.svd(b.T @ a)
    sign = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, sign]) @ Vt


def initial_rotations(pairs: list[PairMatches], count: int, focal: float) -> list[np.ndarray]:
    """Rotations de départ, enchaînées le long des paires les plus riches en points communs.

    La photo 0 sert de référence. Une photo reliée à aucune autre garde l'identité.
    """
    edges = sorted(pairs, key=lambda p: -len(p.points_i))
    relative = {(p.i, p.j): relative_rotation(p, focal) for p in edges}
    rotations: list[np.ndarray | None] = [None] * count
    rotations[0] = np.eye(3)
    added = True
    while added:
        added = False
        for pair in edges:
            Q = relative[(pair.i, pair.j)]
            # R_j^T R_i = Q, donc R_j = R_i Q^T et R_i = R_j Q.
            if rotations[pair.i] is not None and rotations[pair.j] is None:
                rotations[pair.j] = rotations[pair.i] @ Q.T
                added = True
                break
            if rotations[pair.j] is not None and rotations[pair.i] is None:
                rotations[pair.i] = rotations[pair.j] @ Q
                added = True
                break
    return [np.eye(3) if R is None else R for R in rotations]


def subsample(pairs: list[PairMatches], limit: int = MAX_MATCHES_PER_PAIR) -> list[PairMatches]:
    """Limite le nombre de points par paire, de façon reproductible."""
    result = []
    for pair in pairs:
        if len(pair.points_i) > limit:
            keep = np.linspace(0, len(pair.points_i) - 1, limit).astype(int)
            pair = PairMatches(pair.i, pair.j, pair.points_i[keep], pair.points_j[keep])
        result.append(pair)
    return result


def adjust(pairs: list[PairMatches], rotations: list[np.ndarray], focal: float) -> Adjustment:
    """Affine rotations et focale, écarte les paires incohérentes, puis affine à nouveau.

    L'écart d'une paire se recalcule après chaque nouvel ajustement, qui peut révéler une
    paire jusque-là masquée par les autres : on recommence tant qu'il en reste.
    Les photos qui ne sont plus reliées au groupe principal sont laissées de côté :
    `connected` donne les positions retenues, dans l'ordre de `rotations`.
    """
    pairs = subsample(pairs)
    for scale_deg in ROBUST_SCALES_DEG:
        rotations, focal = _solve(pairs, rotations, focal, np.radians(scale_deg))
    connected = list(range(len(rotations)))
    for _ in range(MAX_FILTER_ROUNDS):
        errors = pair_errors_deg(pairs, rotations, focal)
        consistent = [p for p, e in zip(pairs, errors, strict=True) if e <= PAIR_MAX_ERROR_DEG]
        kept = _largest_component(len(rotations), consistent)
        if len(consistent) == len(pairs) and len(kept) == len(rotations):
            break
        position = {old: new for new, old in enumerate(kept)}
        pairs = [
            PairMatches(position[p.i], position[p.j], p.points_i, p.points_j)
            for p in consistent
            if p.i in position and p.j in position
        ]
        rotations = [rotations[old] for old in kept]
        connected = [connected[old] for old in kept]
        for scale_deg in ROBUST_SCALES_DEG[1:]:
            rotations, focal = _solve(pairs, rotations, focal, np.radians(scale_deg))
    return Adjustment(rotations, focal, pairs, connected)
