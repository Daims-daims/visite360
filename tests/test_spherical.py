import numpy as np

from visite360.spherical import (
    camera_rotation,
    directions_to_equirect,
    equirect_directions,
    latitude_weights,
    project,
)


def test_center_of_panorama_looks_forward() -> None:
    directions = equirect_directions(360, 180, np.array([89.5]), np.array([179.5]))

    assert np.allclose(directions[0, 0], [0.0, 0.0, 1.0], atol=1e-6)


def test_top_row_looks_up() -> None:
    directions = equirect_directions(360, 180, np.array([0]), np.array([0]))

    assert directions[0, 0, 1] < -0.99


def test_equirect_round_trip() -> None:
    rows, cols = np.arange(0, 180, 7), np.arange(0, 360, 11)
    directions = equirect_directions(360, 180, rows, cols)

    coords = directions_to_equirect(directions, 360, 180)

    assert np.allclose(coords[..., 0], cols[None, :], atol=1e-3)
    assert np.allclose(coords[..., 1], rows[:, None], atol=1e-3)


def test_camera_rotation_yaw_and_pitch() -> None:
    forward = np.array([0.0, 0.0, 1.0])

    assert np.allclose(camera_rotation(90, 0) @ forward, [1.0, 0.0, 0.0], atol=1e-9)
    assert np.allclose(camera_rotation(0, 90) @ forward, [0.0, -1.0, 0.0], atol=1e-9)


def test_project_center_and_behind() -> None:
    K = np.array([[100.0, 0, 50], [0, 100.0, 40], [0, 0, 1]])
    R = camera_rotation(30, 10)
    directions = np.stack([R @ [0.0, 0.0, 1.0], R @ [0.0, 0.0, -1.0]]).astype(np.float32)

    x, y, front = project(directions, K, R)

    assert front.tolist() == [True, False]
    assert np.allclose([x[0], y[0]], [50, 40], atol=1e-3)


def test_latitude_weights_favor_equator() -> None:
    weights = latitude_weights(100)

    assert np.isclose(weights.sum(), 1.0)
    assert weights[50] > weights[0] * 10
