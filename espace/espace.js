// Espace web des agents (étape 13) : connexion par code reçu par e-mail, liste des visites
// envoyées par l'app, lien à copier, dépublication, nouvelle publication et suppression.
// La session est un cookie que la page ne lit pas (HttpOnly). Chaque requête qui modifie
// quelque chose porte l'en-tête X-Visite360, exigé par le serveur.

"use strict";

const LABELS = {
  envoi: "Envoi en cours",
  en_attente: "En attente",
  en_cours: "Assemblage en cours",
  prete: "Prête",
  echec: "Échec",
};
const REFRESH_MS = 5000;

const $ = (id) => document.getElementById(id);
let email = "";
let timer = null;

function say(text, error = false) {
  $("message").textContent = text || "";
  $("message").classList.toggle("erreur", error);
}

async function api(method, path, body) {
  const options = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") options.headers["X-Visite360"] = "1";
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error("Le serveur ne répond pas. Vérifier la connexion à Internet.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || `Erreur ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function show(section) {
  $("connexion").hidden = section !== "connexion";
  $("liste").hidden = section !== "liste";
  $("compte").hidden = section !== "liste";
}

function date(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleDateString("fr-FR") : "";
}

function button(text, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = text;
  if (className) element.className = className;
  element.addEventListener("click", async () => {
    element.disabled = true;
    try {
      await action();
    } catch (error) {
      say(error.message, true);
    } finally {
      element.disabled = false;
    }
  });
  return element;
}

function render(visits) {
  const list = $("visites");
  list.replaceChildren();
  $("vide").hidden = visits.length > 0;
  for (const visit of visits) {
    const item = document.createElement("li");
    item.className = "visite";
    const title = document.createElement("h2");
    title.textContent = visit.nom;
    const state = document.createElement("p");
    state.className = "etat";
    const label = document.createElement("strong");
    label.className = visit.etat;
    label.textContent = LABELS[visit.etat] || visit.etat;
    state.append(label);
    const details = [];
    if (visit.message && visit.etat !== "prete") details.push(visit.message);
    details.push(`envoyée le ${date(visit.cree_le)}`);
    if (visit.photos_effacees) details.push("photos d'origine effacées (30 jours)");
    state.append(" — " + details.join(" · "));
    item.append(title, state);

    if (visit.lien) {
      const row = document.createElement("div");
      row.className = "lien";
      const field = document.createElement("input");
      field.readOnly = true;
      field.value = visit.lien;
      field.setAttribute("aria-label", "Lien de la visite");
      const copy = button("Copier le lien", async () => {
        await navigator.clipboard.writeText(visit.lien);
        say("Lien copié. Il est le seul accès à la visite : ne le donner qu'aux personnes voulues.");
      });
      row.append(field, copy);
      item.append(row);
    }

    const actions = document.createElement("div");
    actions.className = "actions";
    if (visit.lien) {
      actions.append(button("Dépublier", async () => {
        if (!confirm(`Retirer « ${visit.nom} » d'Internet ? Le lien n'affichera plus rien.`)) return;
        await api("POST", `/api/visites/${visit.id}/depublier`);
        say("Visite retirée d'Internet. Une nouvelle publication aura un autre lien.");
        await refresh();
      }));
    } else if (visit.etat === "prete" || visit.etat === "echec") {
      actions.append(button(visit.etat === "echec" ? "Relancer" : "Publier", async () => {
        await api("POST", `/api/visites/${visit.id}/publier`);
        say("Traitement relancé.");
        await refresh();
      }));
    }
    if (visit.etat !== "en_cours") {
      actions.append(button("Supprimer", async () => {
        if (!confirm(`Supprimer « ${visit.nom} » ? Photos, panoramas et lien seront effacés, sans retour possible.`)) return;
        const result = await api("DELETE", `/api/visites/${visit.id}`);
        say(result.message);
        await refresh();
      }, "danger"));
    }
    item.append(actions);
    list.append(item);
  }
}

async function refresh() {
  clearTimeout(timer);
  const data = await api("GET", "/api/visites");
  render(data.visites);
  if (data.visites.some((v) => ["envoi", "en_attente", "en_cours"].includes(v.etat))) {
    timer = setTimeout(() => refresh().catch(() => {}), REFRESH_MS);
  }
}

async function start() {
  try {
    const me = await api("GET", "/api/moi");
    $("adresse").textContent = me.email;
    show("liste");
    await refresh();
  } catch (error) {
    if (error.status !== 401) say(error.message, true);
    show("connexion");
    $("form-adresse").hidden = false;
    $("form-code").hidden = true;
  }
}

$("form-adresse").addEventListener("submit", async (event) => {
  event.preventDefault();
  email = $("email").value.trim();
  try {
    const result = await api("POST", "/api/connexion/code", { email });
    $("info-code").textContent = result.message;
    $("form-adresse").hidden = true;
    $("form-code").hidden = false;
    $("code").value = "";
    $("code").focus();
    say("");
  } catch (error) {
    say(error.message, true);
  }
});

$("form-code").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("POST", "/api/connexion", { email, code: $("code").value });
    say("");
    await start();
  } catch (error) {
    say(error.message, true);
  }
});

$("autre-adresse").addEventListener("click", () => {
  $("form-code").hidden = true;
  $("form-adresse").hidden = false;
  say("");
});

$("deconnexion").addEventListener("click", async () => {
  clearTimeout(timer);
  await api("POST", "/api/deconnexion").catch(() => {});
  $("visites").replaceChildren();
  say("Déconnecté.");
  show("connexion");
  $("form-adresse").hidden = false;
  $("form-code").hidden = true;
});

start();
