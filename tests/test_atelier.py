# ruff: noqa: F811
"""Étape 15 : les outils de modification sur le serveur du projet (atelier en ligne).

Le serveur, le stockage, la base et l'envoi d'e-mails sont ceux des tests de l'étape 13 (dossiers
et faux services). SAM 2.1 et le modèle de génération sont simulés, comme aux étapes 7 et 9.
"""

import copy
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import pytest

from synthetic import make_panorama
from test_generation import RECT, SCREEN, FakeGenerator
from test_selection import FakeSegmenter
from test_serveur import PUBLIC, Env, env, send, tour_files  # noqa: F401
from visite360 import (
    atelier,
    chiffrage,
    couleur,
    generation,
    selection,
    serve,
    serveur,
    stitch,
    traitement,
)

CLICKS = [{"x": 500, "y": 520, "ajout": True}]
LAUNCH = {
    "point": 0,
    "cap": SCREEN.yaw,
    "hauteur": SCREEN.pitch,
    "champ": SCREEN.fov,
    "cadre": list(RECT),
    "instruction": "Remplace le canapé gris par un canapé vert",
    "nom": "Canapé",
}


def simulated_tools(tour: Any) -> serve.Tools:
    selector = selection.Selector(tour, FakeSegmenter, "simulé")
    painter = couleur.Painter(1024)
    jobs = generation.Generations(
        tour,
        FakeGenerator,
        lambda point, without: painter.base(point.folders.point, point.folders.panorama, without),
        None,
        selector.release,
    )
    return serve.Tools(tour, selector, jobs, painter)


@pytest.fixture
def workshop(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    work = tmp_path / "atelier"
    work.mkdir()
    env.app.ateliers = atelier.Ateliers(env.app.depot, simulated_tools, work)

    # Des panoramas assez grands pour les cadres et les vues des tests de génération.
    def stitch_2048(folders: stitch.Folders, width: int, force: bool, out: Any) -> None:
        cv2.imwrite(str(folders.panorama), make_panorama(2048))
        folders.report.write_text("{}")

    monkeypatch.setattr(stitch, "stitch", stitch_2048)
    yield env


def ready_visit(env: Env, token: str, name: str = "appart") -> str:
    status, answer, _ = send(env, token, name, tour_files(["salon", "cuisine"]))
    assert status == 200, answer
    assert traitement.process_all(env.context) >= 1
    return str(answer["id"])


def call(
    env: Env, method: str, visit: str, rest: str, token: str, body: Any = None
) -> tuple[int, Any]:
    status, answer, response = env.request(method, f"/atelier/{visit}{rest}", body, token)
    return status, answer


def stored(env: Env, visit: str) -> set[str]:
    return {key.split("/", 1)[1] for key in env.app.depot.list(f"{visit}/")}


def create_selection(env: Env, token: str, visit: str) -> None:
    _, view = call(
        env, "POST", visit, "/api/selection/vue", token,
        {"point": 0, "cap": 10, "hauteur": -5, "champ": 90},
    )  # fmt: skip
    status, answer = call(
        env, "POST", visit, "/api/selection/valider", token,
        {"vue": view["vue"], "clics": CLICKS, "nom": "Mur"},
    )  # fmt: skip
    assert status == 200, answer


# --- Accès --------------------------------------------------------------------------------------


def test_workshop_needs_a_session_and_the_guard_header(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    status, _, response = workshop.request("GET", f"/atelier/{visit}/")
    assert status == 302 and response.getheader("Location") == "/"
    assert call(workshop, "GET", visit, "/api/selection", "")[0] == 401
    status, answer, _ = workshop.request(
        "POST", f"/atelier/{visit}/api/selection/vue", {"point": 0}, token, guard=False
    )
    assert status == 403
    # Sans session, aucune route d'écriture ne répond, même avec l'en-tête.
    status, _, _ = workshop.request("POST", f"/atelier/{visit}/api/tarifs/reinitialiser", {})
    assert status == 401
    assert stored(workshop, visit).isdisjoint({"salon/piece.json"})


def test_an_agent_cannot_open_another_agents_workshop(workshop: Env) -> None:
    first = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, first)
    second = workshop.login("b@exemple.fr")

    assert call(workshop, "GET", visit, "/api/selection", second)[0] == 404
    assert call(workshop, "POST", visit, "/api/tarifs/reinitialiser", second, {})[0] == 404
    assert call(workshop, "GET", visit, "/api/selection", first)[0] == 200


def test_workshop_waits_for_the_assembly(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    status, answer, _ = send(workshop, token, "appart", tour_files(["salon"]))
    assert status == 200

    status, body = call(workshop, "GET", answer["id"], "/api/selection", token)

    assert status == 409 and "pas prête" in body["erreur"]


def test_page_and_info_use_the_workshop_prefix(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    status, page, response = workshop.request("GET", f"/atelier/{visit}/", token=token)
    assert status == 200
    text = page["_texte"]
    assert f'<meta name="base" content="/atelier/{visit}">' in text
    assert "script-src 'self' 'unsafe-inline'" in response.getheader("Content-Security-Policy")
    assert response.getheader("X-Frame-Options") == "DENY"
    _, info = call(workshop, "GET", visit, "/info.json", token)
    assert info["points"][0]["full"]["url"] == f"/atelier/{visit}/p/0/panorama.jpg"
    status, _ = call(workshop, "GET", visit, "/p/0/panorama.jpg", token)
    assert status == 200
    status, _ = call(workshop, "GET", visit, "/pannellum/pannellum.js", token)
    assert status == 200
    assert call(workshop, "GET", visit, "/p/9/panorama.jpg", token)[0] == 404
    # Les photos d'origine et les fichiers de travail ne sont jamais servis.
    assert call(workshop, "GET", visit, "/salon/photos/IMG_0001.jpg", token)[0] == 404
    assert call(workshop, "GET", visit, "/visite.json", token)[0] == 404


# --- Modifications rangées avec la visite -------------------------------------------------------


def test_modifications_are_stored_with_the_visit_and_survive_a_restart(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    photos_before = {key for key in stored(workshop, visit) if "/photos/" in key}

    create_selection(workshop, token, visit)
    status, answer = call(
        workshop, "POST", visit, "/api/couleur/appliquer", token,
        {"point": 0, "selection": "selection-1", "couleur": "#8fa58a"},
    )  # fmt: skip
    assert status == 200, answer

    keys = stored(workshop, visit)
    assert {
        "salon/modifications/selection-1.json",
        "salon/modifications/selection-1.png",
        "salon/modifications/couleur-1.json",
    } <= keys
    # Les originaux ne sont pas touchés (D9).
    assert {key for key in keys if "/photos/" in key} == photos_before

    # Le serveur redémarre : l'atelier disparaît, les modifications reviennent du stockage.
    workshop.app.ateliers.drop(visit)  # type: ignore[union-attr]
    _, state = call(workshop, "GET", visit, "/p/0/couleurs.json", token)
    assert [c["selection"] for c in state["couleurs"]] == ["selection-1"] and state["version"]
    status, _ = call(workshop, "GET", visit, "/p/0/apres.jpg", token)
    assert status == 200

    status, answer = call(
        workshop, "POST", visit, "/api/couleur/annuler", token, {"point": 0, "id": "couleur-1"}
    )
    assert status == 200
    assert "salon/modifications/couleur-1.json" not in stored(workshop, visit)


def test_a_second_copy_of_the_server_sees_the_changes_of_the_first(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    create_selection(workshop, token, visit)

    other = atelier.Ateliers(workshop.app.depot, simulated_tools, workshop.context.work_root)
    first = workshop.app.ateliers
    workshop.app.ateliers = other
    _, listing = call(workshop, "GET", visit, "/p/0/selections.json", token)
    assert [r["nom"] for r in listing] == ["Mur"]
    status, _ = call(
        workshop,
        "POST",
        visit,
        "/api/selection/supprimer",
        token,
        {"point": 0, "id": "selection-1"},
    )
    assert status == 200

    workshop.app.ateliers = first  # la première copie relit la liste avant de répondre
    _, listing = call(workshop, "GET", visit, "/p/0/selections.json", token)
    assert listing == []


def test_generation_runs_in_the_workshop_and_is_stored(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    status, answer = call(workshop, "POST", visit, "/api/generation/lancer", token, LAUNCH)
    assert status == 200, answer
    open_workshop = next(iter(workshop.app.ateliers._open.values()))  # type: ignore[union-attr]
    open_workshop.tools.generations.wait(30)
    _, state = call(workshop, "GET", visit, "/api/generation", token)

    assert state["travail"]["etat"] == "terminee"
    assert {
        "salon/modifications/generation-1.json",
        "salon/modifications/generation-1.png",
    } <= stored(workshop, visit)


def test_measuring_a_room_is_stored(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    _, state = call(workshop, "GET", visit, "/p/0/piece.json", token)

    assert state["piece"] is None
    assert call(workshop, "POST", visit, "/api/piece/supprimer", token, {"point": 0})[0] == 200


def test_bad_requests_get_clear_errors(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    status, answer = call(workshop, "POST", visit, "/api/selection/vue", token, {"point": 7})
    assert status == 400 and answer["erreur"]
    assert call(workshop, "POST", visit, "/api/autre/chose", token, {})[0] == 404
    status, _, _ = workshop.request(
        "POST", f"/atelier/{visit}/api/selection/vue", token=token, raw=b"[1]"
    )
    assert status == 400
    status, _, _ = workshop.request(
        "POST", f"/atelier/{visit}/api/selection/vue", token=token, raw=b" " * (serve.MAX_BODY + 1)
    )
    assert status == 413


def test_nothing_is_stored_after_the_visit_is_deleted(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    create_selection(workshop, token, visit)

    status, _, _ = workshop.request("DELETE", f"/api/visites/{visit}", token=token)

    assert status == 200
    assert stored(workshop, visit) == set()
    assert workshop.app.ateliers._open == {}  # type: ignore[union-attr]


def test_the_oldest_workshop_stores_what_is_left_before_leaving(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    first = ready_visit(workshop, token, "un")
    second = ready_visit(workshop, token, "deux")
    workshop.app.ateliers.limit = 1  # type: ignore[union-attr]
    create_selection(workshop, token, first)

    assert call(workshop, "GET", second, "/p/0/selections.json", token)[0] == 200

    assert list(workshop.app.ateliers._open) == [second]  # type: ignore[union-attr]
    assert "salon/modifications/selection-1.json" in stored(workshop, first)


# --- Grille de prix de l'agent ------------------------------------------------------------------


def test_the_price_grid_belongs_to_the_agent_not_to_the_visit(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    one = ready_visit(workshop, token, "un")
    two = ready_visit(workshop, token, "deux")
    other = workshop.login("b@exemple.fr")
    elsewhere = ready_visit(workshop, other, "ailleurs")
    _, grid = call(workshop, "GET", one, "/api/tarifs", token)
    assert grid["par_defaut"] is True

    edited = copy.deepcopy(chiffrage.DEFAULT_GRID)
    edited["surfaces"]["mur"]["bas"] = 33
    status, answer = call(
        workshop, "POST", one, "/api/tarifs/enregistrer", token, {"tarifs": edited}
    )
    assert status == 200, answer

    _, same = call(workshop, "GET", two, "/api/tarifs", token)
    assert same["par_defaut"] is False and same["tarifs"]["surfaces"]["mur"]["bas"] == 33
    _, theirs = call(workshop, "GET", elsewhere, "/api/tarifs", other)
    assert theirs["par_defaut"] is True
    # La grille n'est pas un fichier de la visite : rien dans le stockage.
    assert not any(key.endswith("tarifs.json") for key in stored(workshop, one))

    status, _ = call(workshop, "POST", two, "/api/tarifs/reinitialiser", token, {})
    assert status == 200
    assert call(workshop, "GET", one, "/api/tarifs", token)[1]["par_defaut"] is True


# --- Visite publiée -----------------------------------------------------------------------------


def test_the_published_visit_gets_the_modifications_and_the_pricing(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    create_selection(workshop, token, visit)
    call(
        workshop, "POST", visit, "/api/couleur/appliquer", token,
        {"point": 0, "selection": "selection-1", "couleur": "#8fa58a"},
    )  # fmt: skip
    status, _, _ = workshop.request("POST", f"/api/visites/{visit}/publier", token=token)
    assert status == 200

    assert traitement.process_all(workshop.context) == 1

    _, listing, _ = workshop.request("GET", "/api/visites", token=token)
    identifier = listing["visites"][0]["lien"].split("/")[-2]
    published = {
        key.split("/", 1)[1]: file[0]
        for key, file in workshop.public.files.items()
        if key.startswith(identifier)
    }
    assert {"p/0/apres.jpg", "p/0/apres-mobile.jpg", "chiffrage.json"} <= set(published)
    assert "p/1/apres.jpg" not in published
    info = json.loads(workshop.public.files[f"{identifier}/info.json"][0])
    assert info["points"][0]["apres"]["full"] == "p/0/apres.jpg"
    assert "apres" not in info["points"][1] and info["chiffrage"] == "chiffrage.json"
    pricing = json.loads(published["chiffrage.json"])
    assert pricing["points"][0]["lignes"]
    # Ni photo d'origine, ni masque, ni fiche de travail : seulement ce que le client voit.
    assert not any(
        word in name for name in published for word in ("photos", "modifications", "capture")
    )
    assert not any(
        name.endswith(("selection-1.png", "piece.json", "tarifs.json")) for name in published
    )


def test_a_visit_without_modifications_is_published_as_before(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    ready_visit(workshop, token)

    names = {key.partition("/")[2] for key in workshop.public.files}

    assert "chiffrage.json" not in names and not any("apres" in name for name in names)
    assert PUBLIC.bucket


def test_the_published_page_is_read_only() -> None:
    page = (serve.viewer_folder() / "index.html").read_text(encoding="utf-8")

    # En ligne, chaque outil est caché ; la page publiée n'appelle jamais /api/ ni l'atelier.
    start = page.index("function setupPublished")
    published = page[start : page.index("// Étape 16 (D43) : à la première ouverture")]
    assert "BASE" not in published and "/api/" not in published and "postJson" not in published
    assert 'querySelectorAll("#outils button")' in page


def test_local_server_builds_its_default_tools(tmp_path: Path) -> None:
    """`visite360 serveur --local` branche les outils par défaut : ils doivent exister."""
    from visite360 import reglages

    settings = reglages.local_settings(tmp_path, "http://127.0.0.1:0", 0)
    app = serveur.local_app(settings, io.StringIO())

    assert app.ateliers is not None and app.ateliers.make_tools is serve.default_tools
