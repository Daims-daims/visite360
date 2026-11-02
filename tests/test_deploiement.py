"""Étape 13 bis : déploiement du serveur et de la tâche, contre une fausse API de Scaleway."""

import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from visite360 import deploiement
from visite360.deploiement import DeployError, Target

ROOT = Path(__file__).resolve().parent.parent
TARGET = Target(
    region="fr-par",
    container="conteneur-1",
    job="tache-1",
    images="rg.fr-par.scw.cloud/espace",
    address="https://api.example.test",
)
OLD = "rg.fr-par.scw.cloud/espace/visite360:ancien0000000"
NEW = "rg.fr-par.scw.cloud/espace/visite360:nouveau00000"


class FakeApi:
    """Garde l'image de chaque ressource ; un appel précis peut échouer (une fois, ou toujours)."""

    def __init__(self, fail: set[tuple[str, str]] | None = None, always: bool = False) -> None:
        self.container = OLD
        self.job = OLD
        self.deployed: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.fail = fail or set()
        self.always = always
        self.deploy_conflict = False
        self.busy_polls = 0

    def request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if url.endswith("/deploy"):
            kind = "deploy"
        else:
            kind = "job" if "job-definitions" in url else "container"
        self.calls.append((method, kind))
        if kind == "deploy" and self.deploy_conflict:
            raise DeployError("déjà en cours", 409)
        if (method, kind) in self.fail:
            if not self.always:
                self.fail.discard((method, kind))
            raise DeployError("refusé")
        if method == "GET":
            if kind == "container":
                if self.busy_polls > 0:
                    self.busy_polls -= 1
                    return {"registry_image": self.container, "status": "pending"}
                return {"registry_image": self.container, "status": "ready"}
            return {"image_uri": self.job}
        if kind == "job":
            assert body is not None
            self.job = body["image_uri"]
        elif kind == "container":
            assert body is not None
            self.container = body["registry_image"]
        else:
            self.deployed.append(self.container)
        return {}


def ok(_tag: str) -> None:
    return None


def deploy(api: FakeApi, check=ok, dry_run: bool = False) -> str:
    out = io.StringIO()
    deploiement.deploy(api, TARGET, "nouveau00000", check, dry_run, out, sleep=lambda _s: None)
    return out.getvalue()


def test_same_image_on_server_and_job_then_container_redeployed() -> None:
    api = FakeApi()
    deploy(api)
    assert api.container == api.job == NEW
    assert api.deployed == [NEW]


def test_dry_run_makes_no_call() -> None:
    api = FakeApi()
    output = deploy(api, dry_run=True)
    assert api.calls == []
    assert api.container == api.job == OLD
    assert NEW in output


def test_job_failure_leaves_the_server_untouched() -> None:
    api = FakeApi(fail={("PATCH", "job")})
    with pytest.raises(DeployError):
        deploy(api)
    assert ("PATCH", "container") not in api.calls
    assert api.container == api.job == OLD


def test_container_failure_puts_the_job_back() -> None:
    api = FakeApi(fail={("PATCH", "container")})
    with pytest.raises(DeployError, match="précédente a été remise"):
        deploy(api)
    assert api.container == api.job == OLD


def test_failed_check_puts_both_back_and_redeploys() -> None:
    api = FakeApi()

    def refuse(_tag: str) -> None:
        raise DeployError("mauvais commit")

    with pytest.raises(DeployError, match="mauvais commit"):
        deploy(api, check=refuse)
    assert api.container == api.job == OLD
    assert api.deployed == [NEW, OLD]


def test_rollback_failure_is_reported_loudly() -> None:
    api = FakeApi(fail={("POST", "deploy")}, always=True)
    with pytest.raises(DeployError, match="retour en arrière a lui aussi échoué"):
        deploy(api)


def test_conflict_on_deploy_means_already_deploying_and_is_not_a_failure() -> None:
    api = FakeApi()
    api.deploy_conflict = True
    deploy(api)
    assert api.container == api.job == NEW


def test_waits_for_the_container_to_be_ready_between_commands() -> None:
    api = FakeApi()
    api.busy_polls = 3
    deploy(api)
    assert api.container == api.job == NEW


def test_container_that_never_gets_ready_is_reported() -> None:
    api = FakeApi()
    api.busy_polls = 10_000
    now = [0.0]
    with pytest.raises(DeployError, match="pas prêt"):
        deploiement.wait_ready(
            api,
            TARGET,
            timeout=10,
            interval=1,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
            clock=lambda: now[0],
        )


def test_invalid_tag_is_refused_before_any_call() -> None:
    api = FakeApi()
    with pytest.raises(DeployError, match="invalide"):
        deploiement.deploy(api, TARGET, "../x", ok)
    assert api.calls == []


def test_missing_setting_is_named() -> None:
    with pytest.raises(DeployError, match="VISITE360_CONTENEUR"):
        deploiement.target_from_env({"VISITE360_JOB": "j"})


def test_run_returns_1_with_a_message_instead_of_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert deploiement.run("abc", environ={}) == 1
    assert "Erreur" in capsys.readouterr().err


def test_run_dry_run_needs_no_key(capsys: pytest.CaptureFixture[str]) -> None:
    environ = {
        "VISITE360_CONTENEUR": "c",
        "VISITE360_JOB": "j",
        "VISITE360_IMAGES": "rg.fr-par.scw.cloud/x",
        "VISITE360_ADRESSE_API": "https://a.example/",
    }
    assert deploiement.run("abc", dry_run=True, environ=environ, config=Path("/inexistant")) == 0
    assert "https://a.example/api/info" in capsys.readouterr().out


def test_secret_key_from_environment_then_file(tmp_path: Path) -> None:
    config = tmp_path / "scaleway.json"
    config.write_text(json.dumps({"cle_secrete": "du-fichier"}))
    assert deploiement.secret_key({"SCW_SECRET_KEY": "de-l-env"}, config) == "de-l-env"
    assert deploiement.secret_key({}, config) == "du-fichier"
    with pytest.raises(DeployError):
        deploiement.secret_key({}, tmp_path / "absent.json")


def test_wait_for_commit_gives_up_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, commit: str) -> None:
            self.commit = commit

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"commit": self.commit}).encode()

    answers = iter(["ancien", "ancien", "nouveau"])
    monkeypatch.setattr(
        deploiement.urllib.request, "urlopen", lambda *_a, **_k: Response(next(answers))
    )
    now = [0.0]
    deploiement.wait_for_commit(
        "https://a",
        "nouveau",
        timeout=100,
        interval=1,
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert now[0] == 2

    monkeypatch.setattr(deploiement.urllib.request, "urlopen", lambda *_a, **_k: Response("ancien"))
    with pytest.raises(DeployError, match="n'annonce pas"):
        deploiement.wait_for_commit(
            "https://a",
            "nouveau",
            timeout=3,
            interval=1,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
            clock=lambda: now[0],
        )


# --- Workflow et image ---------------------------------------------------------------------------


def test_workflow_only_deploys_after_the_tests_succeeded() -> None:
    text = (ROOT / ".github" / "workflows" / "deploiement.yml").read_text(encoding="utf-8")
    assert re.search(r"workflows:\s*\[tests\]", text)
    assert "workflow_run.conclusion == 'success'" in text
    # Le déploiement ne part jamais après une fabrication échouée.
    assert "needs.image.result == 'success'" in text
    assert "cancel-in-progress: false" in text


def test_workflow_gives_the_commit_to_the_image() -> None:
    text = (ROOT / ".github" / "workflows" / "deploiement.yml").read_text(encoding="utf-8")
    assert '--build-arg "COMMIT=$tag"' in text
    assert "ARG COMMIT" in (ROOT / "deploiement" / "Containerfile").read_text(encoding="utf-8")
