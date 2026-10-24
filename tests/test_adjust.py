import numpy as np

from visite360.adjust import (
    PairMatches,
    adjust,
    initial_rotations,
    pair_errors_deg,
    rotation_from_vector,
)
from visite360.spherical import camera_rotation

FOCAL = 640.0
SIZE = (671, 894)


def angle_between(A: np.ndarray, B: np.ndarray) -> float:
    cos = (np.trace(A.T @ B) - 1) / 2
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def project(directions: np.ndarray, R: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Points (origine au centre) et masque des directions visibles dans la photo."""
    local = directions @ R
    front = local[:, 2] > 0
    points = local[:, :2] / np.where(front, local[:, 2], 1.0)[:, None] * FOCAL
    inside = (np.abs(points[:, 0]) <= SIZE[0] / 2) & (np.abs(points[:, 1]) <= SIZE[1] / 2)
    return points, front & inside


def make_pairs(rotations: list[np.ndarray], noise_px: float, seed: int = 0) -> list[PairMatches]:
    """Points vus par deux photos, tirés au hasard sur la sphère."""
    rng = np.random.default_rng(seed)
    directions = rng.normal(size=(20000, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    projected = [project(directions, R) for R in rotations]
    pairs = []
    for i in range(len(rotations)):
        for j in range(i + 1, len(rotations)):
            both = projected[i][1] & projected[j][1]
            if both.sum() >= 20:
                points_i = projected[i][0][both] + rng.normal(0, noise_px, (both.sum(), 2))
                points_j = projected[j][0][both] + rng.normal(0, noise_px, (both.sum(), 2))
                pairs.append(PairMatches(i, j, points_i, points_j))
    return pairs


def ring() -> list[np.ndarray]:
    return [camera_rotation(yaw, 0) for yaw in range(0, 360, 30)] + [
        camera_rotation(yaw, 45) for yaw in range(0, 360, 45)
    ]


def test_rotations_and_focal_are_recovered() -> None:
    truth = ring()
    pairs = make_pairs(truth, noise_px=0.5)

    result = adjust(pairs, initial_rotations(pairs, len(truth), FOCAL * 0.9), FOCAL * 0.9)

    assert abs(result.focal - FOCAL) < 2
    assert result.connected == list(range(len(truth)))
    # Les rotations sont définies à une rotation d'ensemble près : on compare à la photo 0.
    offset = truth[0] @ result.rotations[0].T
    for R, expected in zip(result.rotations, truth, strict=True):
        assert angle_between(offset @ R, expected) < 0.1


def test_focal_does_not_run_away() -> None:
    truth = ring()
    pairs = make_pairs(truth, noise_px=2.0)

    result = adjust(pairs, initial_rotations(pairs, len(truth), FOCAL * 1.3), FOCAL * 1.3)

    assert abs(result.focal - FOCAL) / FOCAL < 0.02


def test_inconsistent_pair_is_dropped() -> None:
    truth = ring()
    pairs = make_pairs(truth, noise_px=0.5)
    rng = np.random.default_rng(3)
    wrong = PairMatches(0, 6, rng.uniform(-300, 300, (40, 2)), rng.uniform(-300, 300, (40, 2)))

    result = adjust(pairs + [wrong], initial_rotations(pairs, len(truth), FOCAL), FOCAL)

    assert len(result.pairs) == len(pairs)
    assert max(pair_errors_deg(result.pairs, result.rotations, result.focal)) < 0.2


def test_isolated_photo_is_left_out() -> None:
    truth = ring()
    pairs = [p for p in make_pairs(truth, noise_px=0.5) if 5 not in (p.i, p.j)]

    result = adjust(pairs, initial_rotations(pairs, len(truth), FOCAL), FOCAL)

    assert 5 not in result.connected
    assert len(result.rotations) == len(truth) - 1


def test_rotation_from_vector() -> None:
    R = rotation_from_vector(np.array([0.0, np.pi / 2, 0.0]))

    assert np.allclose(R, camera_rotation(90, 0), atol=1e-9)
