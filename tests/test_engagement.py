# ruff: noqa: F811
"""Étape 16 : un lien par client, mesure de sa consultation, ses modifications à part (D43).

Le serveur, le stockage, la base et l'atelier sont ceux des tests des étapes 13 et 15. SAM 2.1 et
le modèle de génération sont simulés.
"""

from typing import Any

from test_atelier import CLICKS, create_selection, ready_visit, workshop  # noqa: F401
from test_atelier import call as agent_call
from test_serveur import Env, env  # noqa: F401
from visite360 import engagement, registre, serve, traitement

MEASURES_KEPT = registre.MEASURES_KEPT


def new_link(env: Env, token: str, visit: str, label: str = "M. et Mme Martin") -> dict[str, Any]:
    status, answer, _ = env.request(
        "POST", f"/api/visites/{visit}/liens", {"libelle": label}, token
    )
    assert status == 200, answer
    return answer


def client(
    env: Env, method: str, link: dict[str, Any], rest: str, body: Any = None
) -> tuple[int, Any]:
    """Requête du client : sans session, par l'adresse de son lien."""
    status, answer, _ = env.request(method, link["adresse"].rstrip("/") + rest, body)
    return status, answer


def paint(env: Env, link: dict[str, Any]) -> None:
    """Le client sélectionne un mur et le repeint."""
    _, view = client(
        env, "POST", link, "/api/selection/vue", {"point": 0, "cap": 10, "hauteur": -5, "champ": 90}
    )
    status, answer = client(
        env, "POST", link, "/api/selection/valider",
        {"vue": view["vue"], "clics": CLICKS, "nom": "Mur"},
    )  # fmt: skip
    assert status == 200, answer
    status, answer = client(
        env, "POST", link, "/api/couleur/appliquer",
        {"point": 0, "selection": "selection-1", "couleur": "#8fa58a"},
    )  # fmt: skip
    assert status == 200, answer


def stored(env: Env, visit: str) -> set[str]:
    return {key.split("/", 1)[1] for key in env.app.depot.list(f"{visit}/")}


def measure(opening: str = "a" * 32, **fields: Any) -> dict[str, Any]:
    return {"consultation": opening, "pieces": {"salon": 15}, **fields}


# --- Liens de l'agent ---------------------------------------------------------------------------


def test_the_agent_creates_one_link_per_client(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)

    first = new_link(workshop, token, visit, "  M. et   Mme Martin ")
    workshop.clock.now += 1
    second = new_link(workshop, token, visit, "Famille Durand")
    _, listing, _ = workshop.request("GET", f"/api/visites/{visit}/liens", token=token)

    assert [link["libelle"] for link in listing["liens"]] == ["M. et Mme Martin", "Famille Durand"]
    assert first["adresse"].startswith("/l/") and first["adresse"] != second["adresse"]
    assert listing["liens"][0]["ouvertures"] == 0
    status, answer, _ = workshop.request(
        "POST", f"/api/visites/{visit}/liens", {"libelle": " "}, token
    )
    assert status == 400 and "libellé" in answer["message"]


def test_links_belong_to_the_agent_of_the_visit(workshop: Env) -> None:
    owner = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, owner)
    link = new_link(workshop, owner, visit)
    other = workshop.login("b@exemple.fr")

    assert workshop.request("GET", f"/api/visites/{visit}/liens", token=other)[0] == 404
    assert (
        workshop.request("GET", f"/api/visites/{visit}/liens/{link['id']}", token=other)[0] == 404
    )
    assert (
        workshop.request("DELETE", f"/api/visites/{visit}/liens/{link['id']}", token=other)[0]
        == 404
    )
    assert (
        workshop.request("POST", f"/api/visites/{visit}/liens", {"libelle": "x"}, other)[0] == 404
    )
    # Sans session, rien.
    assert workshop.request("GET", f"/api/visites/{visit}/liens")[0] == 401
    assert workshop.request("POST", f"/api/visites/{visit}/liens", {"libelle": "x"})[0] == 401


# --- Page du client -----------------------------------------------------------------------------


def test_the_client_page_shows_the_agents_published_changes(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    create_selection(workshop, token, visit)
    agent_call(
        workshop, "POST", visit, "/api/couleur/appliquer", token,
        {"point": 0, "selection": "selection-1", "couleur": "#8fa58a"},
    )  # fmt: skip
    workshop.request("POST", f"/api/visites/{visit}/publier", token=token)
    traitement.process_all(workshop.context)
    link = new_link(workshop, token, visit)
    root = link["adresse"]

    status, page, response = workshop.request("GET", root)
    assert status == 200
    assert f'<meta name="base" content="{root.rstrip("/")}">' in page["_texte"]
    assert response.getheader("X-Frame-Options") == "DENY"
    _, info = client(workshop, "GET", link, "/info.json")
    assert info["client"] is True and info["mesure"] == f"{root}api/mesure"
    assert info["points"][0]["agent"]["full"] == f"{root}agent/p/0/apres.jpg"
    assert "agent" not in info["points"][1]
    assert info["chiffrage_agent"] == f"{root}agent/chiffrage.json"
    assert client(workshop, "GET", link, "/agent/p/0/apres.jpg")[0] == 200
    assert client(workshop, "GET", link, "/p/0/panorama.jpg")[0] == 200
    _, pricing = client(workshop, "GET", link, "/agent/chiffrage.json")
    assert pricing["points"][0]["lignes"]
    # Rien d'autre de la visite publiée, ni du dossier de travail.
    assert client(workshop, "GET", link, "/agent/info.json")[0] == 404
    assert client(workshop, "GET", link, "/salon/photos/IMG_0001.jpg")[0] == 404


def test_a_wrong_or_deleted_link_shows_nothing(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)

    status, page, response = workshop.request("GET", "/l/" + "x" * 22 + "/")
    assert status == 404 and "ne mène plus" in page["_texte"]
    assert response.getheader("Content-Type").startswith("text/html")
    workshop.request("DELETE", f"/api/visites/{visit}/liens/{link['id']}", token=token)
    assert workshop.request("GET", link["adresse"])[0] == 404
    assert client(workshop, "POST", link, "/api/mesure", measure())[0] == 404


def test_an_unpublished_visit_closes_every_client_link(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    assert workshop.request("GET", link["adresse"])[0] == 200

    workshop.request("POST", f"/api/visites/{visit}/depublier", token=token)

    assert workshop.request("GET", link["adresse"])[0] == 404
    assert client(workshop, "GET", link, "/info.json")[0] == 404


def test_the_client_reaches_no_route_reserved_to_the_agent(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)

    for rest in ("/api/piece/enregistrer", "/api/piece/supprimer", "/api/tarifs/enregistrer",
                 "/api/tarifs/reinitialiser", "/api/chiffrage/meuble", "/api/autre"):  # fmt: skip
        assert client(workshop, "POST", link, rest, {"point": 0})[0] == 404, rest
    for rest in ("/api/tarifs", "/p/0/piece.json", "/p/0/piece.jpg", "/agent"):
        assert client(workshop, "GET", link, rest)[0] == 404, rest
    # Sans l'en-tête X-Visite360, aucune écriture.
    status, _, _ = workshop.request(
        "POST", link["adresse"] + "api/couleur/annuler", {"point": 0}, guard=False
    )
    assert status == 403
    # Le jeton du lien n'ouvre ni l'espace de l'agent ni son atelier.
    assert workshop.request("GET", "/api/visites", token=link["adresse"][3:-1])[0] == 401
    assert workshop.request("GET", f"/atelier/{visit}/api/selection")[0] == 401


# --- Modifications du client, à part -----------------------------------------------------------


def test_client_changes_are_stored_apart_and_touch_nobody_else(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    martin = new_link(workshop, token, visit, "Martin")
    durand = new_link(workshop, token, visit, "Durand")

    paint(workshop, martin)

    prefix = f"liens/{martin['id']}/"
    files = stored(workshop, visit)
    assert {prefix + "salon/modifications/selection-1.json"} <= files
    assert any(name.startswith(prefix + "salon/modifications/couleur-") for name in files)
    # Ni l'agent ni l'autre client ne voient ces modifications.
    assert not any(name.startswith("salon/modifications/") for name in files)
    _, theirs = client(workshop, "GET", durand, "/p/0/couleurs.json")
    _, mine = client(workshop, "GET", martin, "/p/0/couleurs.json")
    assert not theirs["version"] and mine["version"]
    _, agent = agent_call(workshop, "GET", visit, "/p/0/couleurs.json", token)
    assert not agent["version"]
    # La visite publiée n'en contient rien.
    workshop.request("POST", f"/api/visites/{visit}/publier", token=token)
    traitement.process_all(workshop.context)
    assert not any("apres" in key or "liens" in key for key in workshop.public.files)


def test_the_client_prices_his_colors_with_the_agents_grid_without_seeing_it(
    workshop: Env,
) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    paint(workshop, link)

    status, pricing = client(workshop, "GET", link, "/api/chiffrage")

    assert status == 200 and pricing["points"][0]["lignes"]
    assert "tarifs" not in pricing
    assert workshop.app.registre.grid(workshop.app.registre.visit(visit).agent_id) is None  # type: ignore[union-attr]


def test_the_agent_sees_and_clears_the_changes_of_a_client(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    paint(workshop, link)
    path = f"/api/visites/{visit}/liens/{link['id']}"

    _, detail, _ = workshop.request("GET", path, token=token)
    assert detail["modifications"] == {"selections": 1, "couleurs": 1, "remplacements": 0}

    status, _, _ = workshop.request("POST", path + "/effacer", token=token)
    assert status == 200
    assert not any(name.startswith("liens/") for name in stored(workshop, visit))
    _, mine = client(workshop, "GET", link, "/p/0/couleurs.json")
    assert not mine["version"]


def test_at_most_five_replacements_per_link_and_per_day(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    reg = workshop.app.registre
    today = engagement.day(reg.now())
    for _ in range(engagement.MAX_GENERATIONS):
        reg.add_generation(link["id"], today)

    status, answer = client(workshop, "POST", link, "/api/generation/lancer", {"point": 0})
    assert status == 429 and "5 remplacements" in answer["erreur"]
    # Les couleurs ne sont pas limitées, ni les autres liens.
    paint(workshop, link)
    other = new_link(workshop, token, visit, "Autre")
    assert reg.generations_today(other["id"], today) == 0
    # Le lendemain, de nouveau possible (la demande arrive jusqu'au modèle et y est jugée).
    workshop.clock.now += 24 * 3600
    status, answer = client(workshop, "POST", link, "/api/generation/lancer", {"point": 0})
    assert status == 400 and "Limite" not in answer["erreur"]


# --- Mesures ------------------------------------------------------------------------------------


def test_measures_are_stored_by_link_and_added_up(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    other = new_link(workshop, token, visit, "Autre")
    first, second = "a" * 32, "b" * 32

    assert client(workshop, "POST", link, "/api/mesure", measure(first))[0] == 200
    workshop.clock.now += 15
    body = measure(first, pieces={"salon": 5, "cuisine": 10}, bascules={"salon": 2}, chiffrage=True)
    assert client(workshop, "POST", link, "/api/mesure", body)[0] == 200
    workshop.clock.now += 3600
    assert client(workshop, "POST", link, "/api/mesure", measure(second))[0] == 200

    _, detail, _ = workshop.request("GET", f"/api/visites/{visit}/liens/{link['id']}", token=token)
    assert detail["ouvertures"] == 2 and detail["secondes"] == 45
    assert detail["chiffrage_ouvert"] == 1
    assert detail["pieces"] == [
        {"point": "salon", "nom": "Salon", "secondes": 35, "bascules": 2},
        {"point": "cuisine", "nom": "Cuisine", "secondes": 10, "bascules": 0},
    ]
    assert [opening["secondes"] for opening in detail["liste"]] == [15, 30]
    _, untouched, _ = workshop.request(
        "GET", f"/api/visites/{visit}/liens/{other['id']}", token=token
    )
    assert untouched["ouvertures"] == 0 and untouched["pieces"] == []


def test_malformed_or_impossible_measures_are_refused(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)

    bad = [
        {"pieces": {"salon": 5}},
        measure("pas-un-identifiant"),
        measure(pieces={"grenier": 5}),
        measure(pieces={"salon": -1}),
        measure(pieces={"salon": 61}),
        measure(pieces={"salon": 40, "cuisine": 40}),
        measure(pieces={"salon": True}),
        measure(chiffrage="oui"),
        [1, 2],
    ]
    for body in bad:
        assert client(workshop, "POST", link, "/api/mesure", body)[0] == 400, body
    assert workshop.request("POST", link["adresse"] + "api/mesure", raw=b" " * 5000)[0] == 413

    assert client(workshop, "POST", link, "/api/mesure", measure())[0] == 200
    workshop.clock.now += 2
    assert client(workshop, "POST", link, "/api/mesure", measure())[0] == 429
    workshop.clock.now += 8
    status, answer = client(workshop, "POST", link, "/api/mesure", measure(pieces={"salon": 40}))
    assert status == 400 and "temps écoulé" in answer["erreur"]
    # Une consultation d'un autre lien ne se complète pas par celui-ci.
    other = new_link(workshop, token, visit, "Autre")
    workshop.clock.now += 20
    assert client(workshop, "POST", other, "/api/mesure", measure())[0] == 404


def test_measures_sent_in_bursts_are_refused(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)

    for number in range(engagement.MAX_OPENINGS_PER_HOUR):
        assert client(workshop, "POST", link, "/api/mesure", measure(f"{number:032x}"))[0] == 200
    assert client(workshop, "POST", link, "/api/mesure", measure("f" * 32))[0] == 429
    workshop.clock.now += 3601
    assert client(workshop, "POST", link, "/api/mesure", measure("f" * 32))[0] == 200


def test_the_page_sends_nothing_without_the_clients_agreement() -> None:
    page = (serve.viewer_folder() / "index.html").read_text(encoding="utf-8")
    start = page.index("function setupMeasure")
    code = page[start : page.index("async function postJson")]

    # Un seul envoi, gardé par l'accord ; la question est posée tant qu'il n'y a pas de réponse.
    assert code.count("fetch(") == 1
    send = code[code.index("const send") :]
    assert send.index('if (choice !== "oui") return;') < send.index("fetch(")
    assert 'if (choice !== "oui" && choice !== "non")' in code
    assert "Aider votre agent ?" in page and "accord-non" in page
    # Le temps ne s'accumule qu'après l'accord, et un refus oublie ce qui attendait.
    assert 'if (choice === "oui" && visible && current)' in code
    assert 'if (value !== "oui") { pending = {};' in code


# --- Suppression et effacement après 12 mois ----------------------------------------------------


def test_deleting_a_link_leaves_the_other_links_alone(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    martin = new_link(workshop, token, visit, "Martin")
    durand = new_link(workshop, token, visit, "Durand")
    paint(workshop, martin)
    paint(workshop, durand)
    for link, opening in ((martin, "a" * 32), (durand, "b" * 32)):
        assert client(workshop, "POST", link, "/api/mesure", measure(opening))[0] == 200

    status, _, _ = workshop.request(
        "DELETE", f"/api/visites/{visit}/liens/{martin['id']}", token=token
    )

    assert status == 200
    names = stored(workshop, visit)
    assert not any(name.startswith(f"liens/{martin['id']}/") for name in names)
    assert any(name.startswith(f"liens/{durand['id']}/") for name in names)
    _, listing, _ = workshop.request("GET", f"/api/visites/{visit}/liens", token=token)
    assert [link["libelle"] for link in listing["liens"]] == ["Durand"]
    assert workshop.app.registre.openings(martin["id"]) == []


def test_deleting_the_visit_deletes_its_links(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    link = new_link(workshop, token, visit)
    paint(workshop, link)

    workshop.request("DELETE", f"/api/visites/{visit}", token=token)

    assert workshop.app.registre.link(link["id"]) is None
    assert stored(workshop, visit) == set()
    assert workshop.request("GET", link["adresse"])[0] == 404


def test_measures_and_client_changes_are_erased_after_twelve_months(workshop: Env) -> None:
    token = workshop.login("a@exemple.fr")
    visit = ready_visit(workshop, token)
    old = new_link(workshop, token, visit, "Ancien")
    recent = new_link(workshop, token, visit, "Récent")
    workshop.request("GET", old["adresse"])
    paint(workshop, old)
    assert client(workshop, "POST", old, "/api/mesure", measure("a" * 32))[0] == 200

    workshop.clock.now += MEASURES_KEPT + 3600
    workshop.request("GET", recent["adresse"])
    assert client(workshop, "POST", recent, "/api/mesure", measure("b" * 32))[0] == 200
    workshop.app.ateliers.drop(visit)  # type: ignore[union-attr]
    traitement.process_all(workshop.context)

    reg = workshop.app.registre
    assert reg.openings(old["id"]) == [] and len(reg.openings(recent["id"])) == 1
    assert not any(name.startswith(f"liens/{old['id']}/") for name in stored(workshop, visit))
    # Le lien lui-même reste : l'agent décide de le supprimer.
    assert reg.link(old["id"]) is not None
