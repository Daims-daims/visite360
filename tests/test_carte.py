import threading
import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from synthetic import make_panorama
from test_generation import FakeGenerator
from test_serveur import Env, env  # noqa: F401  (fixture)
from visite360 import carte, carte_worker, generation, registre, serve
from visite360.carte import (
    Carte,
    CarteError,
    FallbackGenerator,
    Machine,
    MemoryMeter,
    RemoteGenerator,
    Settings,
)
from visite360.generation import GenerationError

SECRET = "secret-de-la-carte"
PROMPT = "Remplace le canapé gris par un canapé vert"


def settings(port: int = 0, **changes: object) -> Settings:
    base = dict(
        zone="fr-par-2",
        image="image-id",
        project="projet-id",
        secret_key="scw-secret",
        worker_secret=SECRET,
        network="reseau-id",
        port=port,
    )
    return Settings(**{**base, **changes})  # type: ignore[arg-type]


def model(image: np.ndarray, prompt: str, seed: int) -> np.ndarray:
    return np.clip(image.astype(np.int16) + 30, 0, 255).astype(np.uint8)


def view() -> np.ndarray:
    return make_panorama(256)[:128, :128].copy()


class Clock:
    """Heure simulée : attendre fait avancer le temps."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeProvider:
    """Scaleway simulé : la carte est la machine locale, prête (ou jamais prête)."""

    def __init__(self, address: str | None = "127.0.0.1", ready_after: int = 0) -> None:
        self.address = address
        self.ready_after = ready_after
        self.machine: Machine | None = None
        self.created = 0
        self.deleted: list[str] = []
        self.refreshes = 0

    def find(self) -> Machine | None:
        return self.machine

    def create(self) -> Machine:
        self.created += 1
        self.machine = Machine(f"machine-{self.created}", None)
        return self.machine

    def refresh(self, machine_id: str) -> Machine | None:
        self.refreshes += 1
        if self.refreshes >= self.ready_after:
            self.machine = Machine(machine_id, self.address)
        return self.machine

    def delete(self, machine_id: str) -> None:
        self.deleted.append(machine_id)
        self.machine = None


@pytest.fixture
def worker() -> Iterator[tuple[carte_worker.Worker, ThreadingHTTPServer]]:
    state = carte_worker.Worker(model, SECRET, 600, lambda: None)
    server = carte_worker.make_server(state, "127.0.0.1", 0)
    state.server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield state, server
    server.shutdown()
    server.server_close()


def make_carte(
    server: ThreadingHTTPServer, provider: FakeProvider, clock: Clock, **changes: object
) -> tuple[Carte, MemoryMeter]:
    meter = MemoryMeter()
    gpu = Carte(
        settings(server.server_address[1], **changes),
        provider,
        meter,
        clock,
        clock.sleep,
        poll_s=1,
    )
    return gpu, meter


# --- La carte, côté serveur -----------------------------------------------------------------


def test_same_result_as_the_model_run_directly(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, _ = make_carte(server, provider, clock)
    image = view()
    assert np.array_equal(gpu.generate(image, PROMPT, 7), model(image, PROMPT, 7))


def test_wakes_on_first_request_then_reuses_the_machine(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, _ = make_carte(server, provider, clock)
    gpu.generate(view(), PROMPT, 1)
    gpu.generate(view(), PROMPT, 2)
    assert provider.created == 1 and provider.deleted == []


def test_waits_for_the_boot_then_answers(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(ready_after=3), Clock()
    gpu, _ = make_carte(server, provider, clock)
    gpu.generate(view(), PROMPT, 1)
    assert provider.refreshes == 3


def test_card_that_never_starts_is_deleted(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(address=None), Clock()
    gpu, _ = make_carte(server, provider, clock)
    with pytest.raises(CarteError, match="n'a pas démarré en 15 minutes"):
        gpu.generate(view(), PROMPT, 1)
    assert provider.deleted == ["machine-1"]


def test_monthly_cap_stops_the_wake_up(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, meter = make_carte(server, provider, clock, cap_eur=1.0, price_per_hour=1.0)
    meter.add(carte.month_of(clock()), 3600)  # 1 € déjà dépensé
    with pytest.raises(CarteError, match="Plafond de dépense"):
        gpu.generate(view(), PROMPT, 1)
    assert provider.created == 0


def test_cap_does_not_stop_a_card_that_is_already_on(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, meter = make_carte(server, provider, clock, cap_eur=1.0, price_per_hour=1.0)
    provider.create()
    provider.refresh("machine-1")
    meter.add(carte.month_of(clock()), 3600)
    gpu.generate(view(), PROMPT, 1)
    assert provider.created == 1


def test_usage_is_counted_by_month(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, meter = make_carte(server, provider, clock, idle_s=600)
    gpu.generate(view(), PROMPT, 1)
    assert meter.seconds(carte.month_of(clock())) >= 600  # au moins le délai d'attente
    assert gpu.spent_eur() > 0


def test_unreachable_card_gives_a_clear_message(worker) -> None:  # type: ignore[no-untyped-def]
    state, server = worker
    provider, clock = FakeProvider(), Clock()
    gpu, _ = make_carte(server, provider, clock)
    gpu.ensure_ready()
    state.secret = "autre"  # la carte refuse le secret du serveur
    with pytest.raises(CarteError, match="Accès refusé"):
        gpu.generate(view(), PROMPT, 1)


# --- Le programme de la carte ---------------------------------------------------------------


def test_worker_refuses_without_the_secret(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    url = f"http://127.0.0.1:{server.server_address[1]}/generer"
    body = {"image": carte.encode_png(view()), "consigne": PROMPT, "graine": 1}
    with pytest.raises(CarteError, match="Accès refusé"):
        carte.post_json(url, body, "mauvais", 5)
    with pytest.raises(CarteError, match="Accès refusé"):
        carte.post_json(url, body, "", 5)


def test_worker_refuses_an_incomplete_request(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    url = f"http://127.0.0.1:{server.server_address[1]}/generer"
    with pytest.raises(CarteError, match="Demande incomplète"):
        carte.post_json(url, {"consigne": PROMPT}, SECRET, 5)


def test_worker_keeps_nothing_on_disk(
    worker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gpu, _ = make_carte(server, FakeProvider(), Clock())
    gpu.generate(view(), PROMPT, 1)
    assert list(tmp_path.iterdir()) == []


def test_worker_idle_rules() -> None:
    now = [100.0]
    state = carte_worker.Worker(model, SECRET, 600, lambda: None, clock=lambda: now[0])
    assert not state.idle()
    now[0] += 599
    assert not state.idle()
    now[0] += 1
    assert state.idle()
    with state.lock:  # un calcul en cours n'est jamais « inactif »
        assert not state.idle()


def test_worker_deletes_itself_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(carte_worker, "WATCH_S", 0.01)
    called = threading.Event()
    state = carte_worker.Worker(model, SECRET, 0.05, called.set)
    server = carte_worker.make_server(state, "127.0.0.1", 0)
    state.server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    watcher = threading.Thread(target=state.watch, daemon=True)
    watcher.start()
    assert called.wait(5)
    watcher.join(5)
    server.server_close()
    assert state.server is None


def test_worker_activity_postpones_the_deletion(worker) -> None:  # type: ignore[no-untyped-def]
    state, server = worker
    state.idle_s = 0.3
    state.last = time.monotonic()
    gpu, _ = make_carte(server, FakeProvider(), Clock())
    time.sleep(0.2)
    gpu.generate(view(), PROMPT, 1)
    assert not state.idle()


# --- Côté Mac -------------------------------------------------------------------------------


def test_remote_generator_gives_the_same_view_as_the_local_model(worker) -> None:  # type: ignore[no-untyped-def]
    _, server = worker
    url = f"http://127.0.0.1:{server.server_address[1]}/generer"
    steps: list[tuple[int, int]] = []
    image = view()
    out = RemoteGenerator(url, SECRET).generate(
        image, PROMPT, 3, lambda done, total: steps.append((done, total))
    )
    assert np.array_equal(out, model(image, PROMPT, 3))
    assert steps[-1] == (generation.STEPS, generation.STEPS)


def test_fallback_uses_the_mac_when_the_card_does_not_answer() -> None:
    notices: list[str] = []
    remote = RemoteGenerator("http://127.0.0.1:1/generer", SECRET, timeout=1)
    fallback = FallbackGenerator(remote, FakeGenerator, notices.append)
    image = view()
    out = fallback.generate(image, PROMPT, 1, lambda done, total: None)
    assert np.array_equal(out, FakeGenerator().generate(image, PROMPT, 1, lambda d, t: None))
    assert len(notices) == 1 and "Calcul sur le Mac à la place" in notices[0]


def test_without_the_mac_installed_the_error_says_what_to_do() -> None:
    remote = RemoteGenerator("http://127.0.0.1:1/generer", SECRET, timeout=1)
    with pytest.raises(GenerationError, match="n'est pas installé"):
        FallbackGenerator(remote, None).generate(view(), PROMPT, 1, lambda done, total: None)


def test_viewer_uses_the_card_when_it_is_set(tmp_path: Path) -> None:
    from test_generation import make_point
    from visite360 import couleur, selection, visite

    tour = visite.single_point(make_point(tmp_path))
    selector = selection.Selector(tour, lambda: None, "simulé")  # type: ignore[arg-type]
    jobs = serve.default_generations(
        tour,
        couleur.Painter(1024),
        selector,
        {"VISITE360_CARTE_URL": "https://serveur.exemple", "VISITE360_CARTE_JETON": "jeton"},
    )
    assert isinstance(jobs.factory(), FallbackGenerator)
    assert jobs.unavailable is None


# --- Réglages -------------------------------------------------------------------------------

BASE_ENV = {
    "VISITE360_CARTE_ZONE": "fr-par-2",
    "VISITE360_CARTE_IMAGE": "image-id",
    "VISITE360_CARTE_PROJET": "projet-id",
    "VISITE360_CARTE_SECRET": "s",
    "VISITE360_CARTE_RESEAU": "reseau-id",
    "SCW_SECRET_KEY": "k",
}


def test_not_configured_means_no_card() -> None:
    assert carte.from_env({}) is None


def test_defaults_and_overrides() -> None:
    result = carte.from_env(
        {**BASE_ENV, "VISITE360_CARTE_PLAFOND": "12,5", "VISITE360_CARTE_ATTENTE_MIN": "5"}
    )
    assert result is not None
    assert result.commercial_type == "L4-1-24G"
    assert result.cap_eur == 12.5 and result.idle_s == 300


@pytest.mark.parametrize("missing", ["VISITE360_CARTE_RESEAU", "VISITE360_CARTE_SECRET"])
def test_missing_setting_is_named(missing: str) -> None:
    environ = {key: value for key, value in BASE_ENV.items() if key != missing}
    with pytest.raises(CarteError, match=missing):
        carte.from_env(environ)


def test_invalid_number_is_refused() -> None:
    with pytest.raises(CarteError, match="VISITE360_CARTE_PLAFOND"):
        carte.from_env({**BASE_ENV, "VISITE360_CARTE_PLAFOND": "beaucoup"})


# --- Registre et relais du serveur ----------------------------------------------------------


def test_registre_keeps_the_monthly_usage(tmp_path: Path) -> None:
    reg = registre.Registre(registre.SQLiteDatabase(tmp_path / "r.sqlite"))
    reg.create_schema()
    assert reg.seconds("2026-11") == 0
    reg.add("2026-11", 90)
    reg.add("2026-11", 30)
    reg.add("2026-12", 5)
    assert reg.seconds("2026-11") == 120 and reg.seconds("2026-12") == 5


def test_server_relays_the_view_to_the_card(env: Env, worker) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    _, server = worker
    gpu, _ = make_carte(server, FakeProvider(), Clock())
    env.app.gpu = gpu
    token = env.login("agent@exemple.fr")
    image = view()
    body = {"image": carte.encode_png(image), "consigne": PROMPT, "graine": 5}
    status, answer, _ = env.request("POST", "/api/carte/generer", body, token=token)
    assert status == 200
    assert np.array_equal(carte.decode_png(answer["image"]), model(image, PROMPT, 5))


def test_relay_needs_a_login(env: Env) -> None:  # noqa: F811
    status, _, _ = env.request("POST", "/api/carte/generer", {"image": "x"})
    assert status == 401


def test_relay_without_a_card_says_so(env: Env) -> None:  # noqa: F811
    token = env.login("agent@exemple.fr")
    body = {"image": "x", "consigne": PROMPT, "graine": 1}
    status, answer, _ = env.request("POST", "/api/carte/generer", body, token=token)
    assert status == 503 and "pas configurée" in answer["message"]


def test_relay_refuses_a_bad_request(env: Env, worker) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    _, server = worker
    env.app.gpu = make_carte(server, FakeProvider(), Clock())[0]
    token = env.login("agent@exemple.fr")
    for body in (
        {"image": "x", "consigne": "", "graine": 1},
        {"image": "x", "consigne": PROMPT, "graine": "a"},
        {"consigne": PROMPT, "graine": 1},
    ):
        status, _, _ = env.request("POST", "/api/carte/generer", body, token=token)
        assert status == 400


def test_relay_reports_the_cap_as_unavailable(env: Env, worker) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    _, server = worker
    gpu, meter = make_carte(server, FakeProvider(), Clock(), cap_eur=1.0, price_per_hour=1.0)
    meter.add(carte.month_of(gpu.clock()), 3600)
    env.app.gpu = gpu
    token = env.login("agent@exemple.fr")
    body = {"image": carte.encode_png(view()), "consigne": PROMPT, "graine": 1}
    status, answer, _ = env.request("POST", "/api/carte/generer", body, token=token)
    assert status == 503 and "Plafond" in answer["message"]
