import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic import make_panorama
from visite360 import couleur, generation, selection, stitch, visite
from visite360.generation import GenerationError, Request
from visite360.selection import ViewSpec, extract_view

SCREEN = ViewSpec(20.0, -10.0, 90.0)
RECT = (400.0, 380.0, 640.0, 700.0)


class FakeGenerator:
    """Modèle simulé : la vue un peu plus claire partout (le défaut habituel d'un vrai modèle),
    avec un carré rouge au centre à la place de l'objet."""

    seen: list[np.ndarray] = []

    def generate(self, image, prompt, seed, progress):  # type: ignore[no-untyped-def]
        FakeGenerator.seen.append(image.copy())
        for step in range(1, generation.STEPS + 1):
            progress(step, generation.STEPS)
        out = np.clip(image.astype(np.int16) + 30, 0, 255).astype(np.uint8)
        h, w = out.shape[:2]
        out[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3] = (0, 0, 255)
        return out


def make_point(tmp_path: Path, width: int = 2048) -> stitch.Folders:
    point = tmp_path / "visite" / "salon"
    (point / "photos").mkdir(parents=True)
    cv2.imwrite(str(point / "panorama.jpg"), make_panorama(width))
    return stitch.resolve_folders(point)


def make_request(rect: tuple[float, float, float, float] = RECT) -> Request:
    return Request.parse(SCREEN, list(rect), "Remplace le canapé gris par un canapé vert", "Canapé")


def add_generation(folders: stitch.Folders, request: Request | None = None) -> dict:
    request = request or make_request()
    panorama = cv2.imread(str(folders.panorama))
    view_image = extract_view(panorama, request.view)
    generated = FakeGenerator().generate(view_image, request.prompt(), 1, lambda s, t: None)
    return generation.save(folders.point, folders.panorama, generated, request, 1, 2.0)


# --- Géométrie ----------------------------------------------------------------------------


def test_parse_rect_sorts_and_clamps() -> None:
    assert generation.parse_rect([600, 700, -50, 100], 1024) == (0.0, 100.0, 600.0, 700.0)
    assert generation.parse_rect([10, 10, 2000, 50], 1024) == (10.0, 10.0, 1024.0, 50.0)


@pytest.mark.parametrize(
    "raw", [None, [1, 2, 3], [0, 0, 10, 10], [0, 0, "a", 50], [0, 0, True, 50]]
)
def test_parse_rect_refuses_bad_frames(raw: object) -> None:
    with pytest.raises(GenerationError):
        generation.parse_rect(raw, 1024)


def test_view_is_centered_on_the_frame_with_a_margin() -> None:
    rect = (312.0, 412.0, 712.0, 612.0)  # centré sur l'écran
    view = generation.generation_view(SCREEN, rect)
    assert view.yaw == pytest.approx(SCREEN.yaw, abs=0.2)
    assert view.pitch == pytest.approx(SCREEN.pitch, abs=0.2)
    mask = generation.zone_mask(view, SCREEN, rect)
    ys, xs = np.nonzero(mask)
    # Le côté le plus large du cadre occupe 1 - 2 × MARGIN de la vue.
    widest = max(xs.max() - xs.min(), ys.max() - ys.min()) + 1
    assert widest / view.size == pytest.approx(1 - 2 * generation.MARGIN, abs=0.03)
    assert abs((xs.min() + xs.max()) / 2 - view.size / 2) < 4


def test_small_frame_gets_the_narrowest_view() -> None:
    view = generation.generation_view(SCREEN, (500.0, 500.0, 530.0, 530.0))
    assert view.fov == selection.MIN_FOV


def test_frame_off_center_moves_the_view() -> None:
    view = generation.generation_view(SCREEN, (800.0, 100.0, 1000.0, 300.0))
    assert view.yaw > SCREEN.yaw + 10
    assert view.pitch > SCREEN.pitch + 10


def test_frame_too_large_is_refused() -> None:
    wide = ViewSpec(0.0, 0.0, 120.0)
    with pytest.raises(GenerationError, match="trop grand"):
        generation.generation_view(wide, (0.0, 0.0, 1024.0, 1024.0))


def test_zone_in_the_same_view_is_the_frame() -> None:
    mask = generation.zone_mask(SCREEN, SCREEN, RECT)
    expected = np.zeros_like(mask)
    expected[380:700, 400:640] = 255
    assert (mask != expected).mean() < 0.005


# --- Report -------------------------------------------------------------------------------


def test_blend_corrects_the_color_shift_and_stays_inside_the_frame() -> None:
    rng = np.random.default_rng(0)
    original = rng.integers(40, 200, (256, 256, 3)).astype(np.uint8)
    generated = np.clip(original.astype(np.int16) + 30, 0, 255).astype(np.uint8)
    mask = np.zeros((256, 256), np.uint8)
    mask[64:192, 64:192] = 255
    colors, alpha = generation.blend(original, generated, mask)
    assert np.abs(colors[mask > 0] - original[mask > 0]).mean() < 2
    assert (alpha[mask == 0] == 0).all()
    assert alpha[128, 128] == 1.0
    assert 0 < alpha[64 + generation.FEATHER // 2, 128] < 1


def test_apply_changes_only_pixels_inside_the_frame(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    record = add_generation(folders)
    original = cv2.imread(str(folders.panorama))
    result = generation.apply(original, generation.operations(folders.point))
    request = make_request()
    zone = generation.zone_mask(request.view, SCREEN, RECT)
    footprint = selection.to_panorama(zone, request.view, original.shape[1], original.shape[0])
    allowed = cv2.dilate(footprint, np.ones((5, 5), np.uint8)) > 0
    changed = (result != original).any(axis=2)
    assert changed.any()
    assert not (changed & ~allowed).any()
    # Le centre du cadre est bien remplacé par le rouge du modèle simulé.
    view = extract_view(result, request.view)
    center = view[view.shape[0] // 2, view.shape[1] // 2].astype(int)
    assert center[2] > 200 and center[0] < 60
    assert record["id"] == "generation-1"


def test_apply_works_on_a_reduced_panorama(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    add_generation(folders)
    small = cv2.resize(cv2.imread(str(folders.panorama)), (1024, 512), interpolation=cv2.INTER_AREA)
    result = generation.apply(small, generation.operations(folders.point))
    assert result.shape == small.shape and (result != small).any()


# --- Fiches -------------------------------------------------------------------------------


def test_save_writes_record_and_image(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    record = add_generation(folders)
    folder = folders.point / selection.FOLDER
    saved = json.loads((folder / "generation-1.json").read_text(encoding="utf-8"))
    assert saved == record
    assert (folder / "generation-1.png").is_file()
    assert record["consigne"] == make_request().prompt()
    assert record["instruction"] == "Remplace le canapé gris par un canapé vert"
    assert record["modele"]["revision"] == generation.REVISION
    assert record["zone"]["cadre"] == list(RECT)
    assert Request.from_record(record).rect == RECT


def test_redo_keeps_the_number_and_new_ones_follow(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    add_generation(folders)
    add_generation(folders)
    view = np.zeros((1024, 1024, 3), np.uint8)
    redone = generation.save(
        folders.point, folders.panorama, view, make_request(), 7, 1.0, "generation-1"
    )
    assert redone["id"] == "generation-1" and redone["graine"] == 7
    assert [op.record["id"] for op in generation.operations(folders.point)] == [
        "generation-1",
        "generation-2",
    ]


def test_delete_removes_record_and_image(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    add_generation(folders)
    generation.delete(folders.point, "generation-1")
    assert not list((folders.point / selection.FOLDER).glob("generation-1.*"))
    assert generation.operations(folders.point) == []
    with pytest.raises(GenerationError):
        generation.delete(folders.point, "generation-1")
    with pytest.raises(GenerationError):
        generation.delete(folders.point, "../panorama")


def test_operations_skip_broken_records(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    add_generation(folders)
    add_generation(folders)
    folder = folders.point / selection.FOLDER
    (folder / "generation-2.png").unlink()
    (folder / "generation-3.json").write_text("{pas du json", encoding="utf-8")
    assert [op.record["id"] for op in generation.operations(folders.point)] == ["generation-1"]


def test_prompt_keeps_the_instruction_and_limits_the_change() -> None:
    request = Request.parse(SCREEN, list(RECT), "  Retire le   pouf. ", None)
    assert request.prompt() == "Retire le pouf. " + generation.PROMPT_SUFFIX


@pytest.mark.parametrize("instruction", ["", "   ", "x" * 201, 3, None])
def test_bad_instructions_are_refused(instruction: object) -> None:
    with pytest.raises(GenerationError):
        Request.parse(SCREEN, list(RECT), instruction, None)


def test_older_records_are_read_back() -> None:
    record = {
        "consigne": "Remplace le pouf par un fauteuil.",
        "vue": SCREEN.to_json(),
        "zone": {"ecran": SCREEN.to_json(), "cadre": list(RECT)},
    }
    assert Request.from_record(record).instruction == "Remplace le pouf par un fauteuil."


def test_change_amount_ignores_a_shift_of_the_whole_view() -> None:
    rng = np.random.default_rng(1)
    original = rng.integers(40, 200, (128, 128, 3)).astype(np.uint8)
    mask = np.zeros((128, 128), np.uint8)
    mask[32:96, 32:96] = 255
    shifted = np.clip(original.astype(np.int16) + 12, 0, 255).astype(np.uint8)
    assert generation.change_amount(original, shifted, mask) < 1
    replaced = shifted.copy()
    replaced[40:88, 40:88] = (0, 0, 255)
    assert generation.change_amount(original, replaced, mask) > generation.MIN_CHANGE


# --- Installation et commande -------------------------------------------------------------


def test_missing_says_what_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISITE360_GENERATION", str(tmp_path / "env"))
    monkeypatch.setenv("VISITE360_MODELES", str(tmp_path / "modeles"))
    assert "mflux absent" in (generation.missing() or "")
    command = generation.command_path()
    command.parent.mkdir(parents=True)
    command.write_text("")
    assert "poids absents" in (generation.missing() or "")
    for name in generation.WEIGHTS:
        path = generation.model_folder() / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    assert generation.missing() is None


def test_verify_weights_detects_a_wrong_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = tmp_path / "bon.bin", tmp_path / "mauvais.bin"
    good.write_bytes(b"bon")
    bad.write_bytes(b"mauvais")
    monkeypatch.setattr(
        generation,
        "WEIGHTS",
        {
            "bon.bin": selection.file_sha256(good),
            "mauvais.bin": "0" * 64,
            "absent.bin": "0" * 64,
        },
    )
    problems = generation.verify_weights(tmp_path)
    assert problems == ["mauvais.bin ne correspond pas à la version publiée", "absent.bin absent"]


def fake_command(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_run_command_reports_each_step() -> None:
    script = (
        "import sys\n"
        "sys.stderr.write('Fetching 16 files: 16/16 [00:01<00:00]\\n')\n"
        "for i in range(5):\n"
        "    sys.stderr.write(f'\\r {i * 25}%|##| {i}/4 [00:0{i}<00:10, 2.0s/it]')\n"
        "    sys.stderr.flush()\n"
    )
    steps: list[tuple[int, int]] = []
    generation.run_command(fake_command(script), {}, lambda s, t: steps.append((s, t)), 30)
    assert steps == [(i, 4) for i in range(5)]


def test_run_command_failure_gives_a_clear_message() -> None:
    script = "import sys\nsys.stderr.write('ValueError: modèle cassé\\n')\nsys.exit(3)\n"
    with pytest.raises(GenerationError, match="code 3.*modèle cassé"):
        generation.run_command(fake_command(script), {}, lambda s, t: None, 30)


def test_run_command_stops_a_stuck_model() -> None:
    script = "import time\ntime.sleep(30)\n"
    with pytest.raises(GenerationError, match="n'a pas fini"):
        generation.run_command(fake_command(script), {}, lambda s, t: None, 0.5)


def test_mflux_generator_without_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISITE360_GENERATION", str(tmp_path / "env"))
    with pytest.raises(GenerationError, match="installer-generation.sh"):
        generation.MfluxGenerator()


# --- Panorama modifié et générations en cours ---------------------------------------------


def test_painter_includes_generations_and_undo_restores_original(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    painter = couleur.Painter(1024)
    original = cv2.imread(str(folders.panorama))
    assert (painter.base(folders.point, folders.panorama) == original).all()
    add_generation(folders)
    state = painter.state(folders.point, folders.panorama)
    assert [record["id"] for record in state["generations"]] == ["generation-1"]
    assert state["version"] is not None
    after = cv2.imread(str(painter.after(folders.point, folders.panorama, mobile=False)))
    assert (after != cv2.imread(str(folders.panorama))).any()
    assert (painter.base(folders.point, folders.panorama) != original).any()
    without = painter.base(folders.point, folders.panorama, "generation-1")
    assert (without == couleur.apply(original, [])).all()
    generation.delete(folders.point, "generation-1")
    assert painter.state(folders.point, folders.panorama)["version"] is None
    assert (painter.base(folders.point, folders.panorama) == original).all()


def make_generations(
    folders: stitch.Folders, factory=FakeGenerator, released: list | None = None
) -> tuple[generation.Generations, visite.Point]:
    tour = visite.single_point(folders)
    painter = couleur.Painter(1024)
    jobs = generation.Generations(
        tour,
        factory,
        lambda point, without: painter.base(point.folders.point, point.folders.panorama, without),
        before=(lambda: released.append(True)) if released is not None else (lambda: None),
    )
    return jobs, tour.points[0]


def test_job_runs_and_saves_the_generation(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    released: list[bool] = []
    jobs, point = make_generations(folders, released=released)
    jobs.start(0, point, make_request(), None)
    jobs.wait(30)
    job = jobs.state()["travail"]
    assert job["etat"] == "terminee", job["message"]
    assert job["passe"] == generation.STEPS
    assert job["fiche"]["id"] == "generation-1"
    assert released == [True]


def test_redo_job_replaces_the_same_generation(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    jobs, point = make_generations(folders)
    record = add_generation(folders)
    FakeGenerator.seen.clear()
    jobs.start(0, point, Request.from_record(record), record["id"])
    jobs.wait(30)
    assert jobs.state()["travail"]["fiche"]["id"] == "generation-1"
    assert len(generation.operations(folders.point)) == 1
    # Le modèle a reçu la vue d'origine, pas celle qui contient déjà le carré rouge à refaire.
    view = FakeGenerator.seen[-1]
    center = view[view.shape[0] // 2, view.shape[1] // 2].astype(int)
    assert not (center[2] > 200 and center[0] < 60)


def test_job_without_visible_change_is_not_saved(tmp_path: Path) -> None:
    class LazyGenerator:
        def generate(self, image, prompt, seed, progress):  # type: ignore[no-untyped-def]
            return np.clip(image.astype(np.int16) + 3, 0, 255).astype(np.uint8)

    folders = make_point(tmp_path)
    jobs, point = make_generations(folders, LazyGenerator)
    jobs.start(0, point, make_request(), None)
    jobs.wait(30)
    job = jobs.state()["travail"]
    assert job["etat"] == "erreur" and "presque rien changé" in job["message"]
    assert generation.operations(folders.point) == []


def test_only_one_job_at_a_time(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()

    class SlowGenerator(FakeGenerator):
        def generate(self, image, prompt, seed, progress):  # type: ignore[no-untyped-def]
            gate.wait(10)
            return super().generate(image, prompt, seed, progress)

    folders = make_point(tmp_path)
    jobs, point = make_generations(folders, SlowGenerator)
    jobs.start(0, point, make_request(), None)
    with pytest.raises(GenerationError, match="déjà en cours"):
        jobs.start(0, point, make_request(), None)
    gate.set()
    jobs.wait(30)
    assert jobs.state()["travail"]["etat"] == "terminee"


def test_job_reports_model_errors(tmp_path: Path) -> None:
    class BrokenGenerator:
        def generate(self, image, prompt, seed, progress):  # type: ignore[no-untyped-def]
            raise GenerationError("Le modèle a échoué.")

    folders = make_point(tmp_path)
    jobs, point = make_generations(folders, BrokenGenerator)
    jobs.start(0, point, make_request(), None)
    jobs.wait(30)
    job = jobs.state()["travail"]
    assert job["etat"] == "erreur" and job["message"] == "Le modèle a échoué."
    assert generation.operations(folders.point) == []


def test_unavailable_generations_are_refused(tmp_path: Path) -> None:
    folders = make_point(tmp_path)
    tour = visite.single_point(folders)
    jobs = generation.Generations(tour, FakeGenerator, lambda p, w: np.zeros(1), "Pas installé.")
    assert jobs.state()["disponible"] is False
    with pytest.raises(GenerationError, match="Pas installé"):
        jobs.start(0, tour.points[0], make_request(), None)
