from pathlib import Path

import pytest

from visite360 import comptes, registre
from visite360.registre import Registre, SQLiteDatabase


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def reg(clock: Clock) -> Registre:
    instance = Registre(SQLiteDatabase(":memory:"), clock)
    instance.create_schema()
    return instance


def test_schema_creation_is_idempotent(reg: Registre) -> None:
    reg.create_schema()
    reg.add_agent("a@exemple.fr")
    reg.create_schema()
    assert [agent.email for agent in reg.agents()] == ["a@exemple.fr"]


def test_unknown_address_gets_no_code(reg: Registre) -> None:
    assert reg.new_code("inconnu@exemple.fr") is None


def test_code_opens_a_session_once(reg: Registre) -> None:
    agent, created = reg.add_agent(" Agent@Exemple.FR ")
    assert created and agent.email == "agent@exemple.fr"
    code = reg.new_code("agent@exemple.fr")
    assert code is not None and len(code) == 6

    found = reg.check_code("AGENT@exemple.fr", f"{code[:3]} {code[3:]}")
    assert found is not None and found.id == agent.id
    assert reg.check_code("agent@exemple.fr", code) is None  # un code ne sert qu'une fois

    token = reg.open_session(found)
    assert reg.session_agent(token) == found
    reg.close_session(token)
    assert reg.session_agent(token) is None


def test_codes_and_sessions_are_never_stored_in_clear(reg: Registre) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    code = reg.new_code("a@exemple.fr")
    token = reg.open_session(agent)
    rows = reg.db.execute("SELECT empreinte FROM codes UNION SELECT empreinte FROM sessions", {})[0]
    stored = " ".join(row[0] for row in rows)
    assert code not in stored and token not in stored


def test_five_wrong_attempts_cancel_the_code(reg: Registre) -> None:
    reg.add_agent("a@exemple.fr")
    code = reg.new_code("a@exemple.fr")
    assert code is not None
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(registre.CODE_ATTEMPTS):
        assert reg.check_code("a@exemple.fr", wrong) is None
    assert reg.check_code("a@exemple.fr", code) is None


def test_code_expires_after_ten_minutes(reg: Registre, clock: Clock) -> None:
    reg.add_agent("a@exemple.fr")
    code = reg.new_code("a@exemple.fr")
    assert code is not None
    clock.now += registre.CODE_LIFETIME + 1
    assert reg.check_code("a@exemple.fr", code) is None


def test_codes_are_rate_limited(reg: Registre, clock: Clock) -> None:
    reg.add_agent("a@exemple.fr")
    assert reg.new_code("a@exemple.fr") is not None
    assert reg.new_code("a@exemple.fr") is None  # moins d'une minute après
    for _ in range(registre.CODES_PER_HOUR - 1):
        clock.now += registre.CODE_INTERVAL
        assert reg.new_code("a@exemple.fr") is not None
    clock.now += registre.CODE_INTERVAL
    assert reg.new_code("a@exemple.fr") is None  # cinq dans l'heure
    clock.now += registre.HOUR
    assert reg.new_code("a@exemple.fr") is not None


def test_only_the_latest_code_works(reg: Registre, clock: Clock) -> None:
    reg.add_agent("a@exemple.fr")
    first = reg.new_code("a@exemple.fr")
    clock.now += registre.CODE_INTERVAL
    second = reg.new_code("a@exemple.fr")
    assert first and second
    if first != second:
        assert reg.check_code("a@exemple.fr", first) is None
    assert reg.check_code("a@exemple.fr", second) is not None


def test_retired_agent_loses_sessions_and_codes(reg: Registre, clock: Clock) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    token = reg.open_session(agent)
    reg.retire_agent("a@exemple.fr")
    assert reg.session_agent(token) is None
    assert reg.new_code("a@exemple.fr") is None
    restored, created = reg.add_agent("a@exemple.fr")
    assert created and restored.id == agent.id and restored.retired is None


def test_session_expires(reg: Registre, clock: Clock) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    token = reg.open_session(agent)
    clock.now += registre.SESSION_LIFETIME + 1
    assert reg.session_agent(token) is None


def test_claim_takes_each_job_once(reg: Registre) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    visit = reg.save_upload(agent.id, "appart", {"fichiers": {}})
    job = reg.queue(visit.id)
    assert reg.queue(visit.id).id == job.id  # pas deux attentes pour la même visite

    taken = reg.claim()
    assert taken is not None and taken.id == job.id and taken.state == registre.RUNNING
    assert reg.claim() is None


def test_lost_job_is_taken_again_then_failed(reg: Registre, clock: Clock) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    visit = reg.save_upload(agent.id, "appart", {"fichiers": {}})
    reg.queue(visit.id)
    for attempt in range(1, registre.MAX_ATTEMPTS + 1):
        job = reg.claim()
        assert job is not None and job.attempts == attempt
        clock.now += registre.STALE_AFTER + 1
    assert reg.claim() is None
    last = reg.last_job(visit.id)
    assert last is not None and last.state == registre.FAILED


def test_photos_to_delete_after_thirty_days(reg: Registre, clock: Clock) -> None:
    agent, _ = reg.add_agent("a@exemple.fr")
    visit = reg.save_upload(agent.id, "appart", {"fichiers": {}})
    reg.set_ready(visit.id)
    assert reg.photos_to_delete() == []
    clock.now += registre.PHOTOS_KEPT + 1
    assert [v.id for v in reg.photos_to_delete()] == [visit.id]
    reg.set_photos_deleted(visit.id)
    assert reg.photos_to_delete() == []


def test_account_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    environ = {"VISITE360_BASE": f"sqlite:///{tmp_path / 'registre.sqlite'}"}
    config = tmp_path / "absent.json"

    assert comptes.run("ajouter", "a@exemple.fr", environ, config) == 0
    assert comptes.run("ajouter", "a@exemple.fr", environ, config) == 0
    assert comptes.run("liste", None, environ, config) == 0
    assert comptes.run("retirer", "a@exemple.fr", environ, config) == 0
    assert comptes.run("ajouter", "pas-une-adresse", environ, config) == 1
    output = capsys.readouterr()
    assert "peut maintenant se connecter" in output.out
    assert "déjà autorisé" in output.out
    assert "a@exemple.fr : autorisé" in output.out
    assert "ne peut plus se connecter" in output.out
    assert "adresse e-mail" in output.err


def test_account_command_without_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert comptes.run("liste", None, {}, tmp_path / "absent.json") == 1
    assert "VISITE360_BASE" in capsys.readouterr().err


def test_postgres_without_pg8000_gives_a_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("pg8000"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(registre.RegistreError, match=r"\.\[serveur\]"):
        registre.open_database("postgresql://u:p@hote:5432/base")


def test_account_command_says_which_database_it_uses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "absent.json"
    environ = {"VISITE360_BASE": f"sqlite:///{tmp_path / 'registre.sqlite'}"}
    assert comptes.run("liste", None, environ, config) == 0
    assert "Base : SQLite local, sur ce Mac" in capsys.readouterr().out

    secret = "mot-de-passe-secret"
    url = f"postgresql://utilisateur:{secret}@exemple.pg.sdb.fr-par.scw.cloud:5432/visite360"
    assert comptes.describe_database(url) == "PostgreSQL en ligne (exemple.pg.sdb.fr-par.scw.cloud)"
    assert secret not in comptes.describe_database(url)
