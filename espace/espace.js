// Espace web des agents (étape 13) : connexion par code reçu par e-mail, liste des visites
// envoyées par l'app, dépublication, nouvelle publication et suppression. Étape 16 : un lien
// par client, avec ce que le client a regardé quand il a accepté la mesure.
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
// Liens dont le détail est ouvert : gardés ouverts quand la liste se redessine.
const opened = new Set();

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

function duration(seconds) {
  if (!seconds) return "0 s";
  const minutes = Math.floor(seconds / 60);
  if (minutes >= 60) return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
  return minutes ? `${minutes} min ${String(seconds % 60).padStart(2, "0")} s` : `${seconds} s`;
}

function element(tag, text, className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
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

    // Étape 16 : les liens des clients remplacent le lien unique de l'étape 12.
    if (visit.lien && visit.etat === "prete") item.append(clientLinks(visit));

    const actions = document.createElement("div");
    actions.className = "actions";
    if (visit.etat === "prete") {
      // Étape 15 : les outils de modification (couleur, objets, mesure, chiffrage) en ligne.
      const edit = document.createElement("a");
      edit.className = "bouton";
      edit.href = `/atelier/${visit.id}/`;
      edit.target = "_blank";
      edit.rel = "noopener";
      edit.textContent = "Modifier";
      actions.append(edit);
    }
    if (visit.lien && visit.etat === "prete") {
      actions.append(button("Mettre à jour le lien", async () => {
        await api("POST", `/api/visites/${visit.id}/publier`);
        say("Mise à jour lancée : le lien reste le même et montre bientôt les modifications.");
        await refresh();
      }));
    }
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

// --- Liens des clients (étape 16) ---------------------------------------------------------------

function clientLinks(visit) {
  const box = element("div", "", "clients");
  box.append(element("h3", "Liens clients"));
  const list = element("ul", "", "liens-clients");
  box.append(list);
  const form = document.createElement("form");
  form.className = "nouveau-lien";
  const field = document.createElement("input");
  field.placeholder = "Nom du client, par exemple M. et Mme Martin";
  field.maxLength = 80;
  field.required = true;
  field.setAttribute("aria-label", "Libellé du nouveau lien");
  const create = element("button", "Créer un lien", "principal");
  create.type = "submit";
  form.append(field, create);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    create.disabled = true;
    try {
      const link = await api("POST", `/api/visites/${visit.id}/liens`, { libelle: field.value });
      field.value = "";
      await copyLink(link);
      await loadLinks(visit, list);
    } catch (error) {
      say(error.message, true);
    } finally {
      create.disabled = false;
    }
  });
  box.append(form);
  loadLinks(visit, list).catch((error) => say(error.message, true));
  return box;
}

const absolute = (link) => new URL(link.adresse, location.origin).href;

async function copyLink(link) {
  try {
    await navigator.clipboard.writeText(absolute(link));
    say(`Lien de « ${link.libelle} » copié. Ne le donner qu'à ce client : il lui permet de voir et de modifier la visite.`);
  } catch (error) {
    say(`Lien de « ${link.libelle} » : ${absolute(link)}`);
  }
}

async function loadLinks(visit, list) {
  const data = await api("GET", `/api/visites/${visit.id}/liens`);
  list.replaceChildren();
  if (!data.liens.length) {
    list.append(element("li", "Aucun lien pour l'instant : en créer un par client.", "aide"));
  }
  for (const link of data.liens) {
    const row = element("li", "", "lien-client");
    const head = element("div", "", "entete-lien");
    head.append(element("strong", link.libelle));
    const facts = link.ouvertures
      ? `${link.ouvertures} ouverture${link.ouvertures > 1 ? "s" : ""} · ${duration(link.secondes)} · dernière le ${date(link.derniere_ouverture)}`
      : "pas encore d'ouverture mesurée";
    head.append(element("span", facts, "aide"));
    const actions = element("div", "", "actions");
    const detail = element("div", "", "detail-lien");
    actions.append(
      button("Copier", () => copyLink(link)),
      button(opened.has(link.id) ? "Masquer" : "Détail", async () => {
        if (opened.has(link.id)) opened.delete(link.id); else opened.add(link.id);
        await loadLinks(visit, list);
      }),
      button("Supprimer", async () => {
        if (!confirm(`Supprimer le lien de « ${link.libelle} » ? Il n'affichera plus rien, ses mesures et les modifications du client seront effacées. Les autres liens ne changent pas.`)) return;
        const result = await api("DELETE", `/api/visites/${visit.id}/liens/${link.id}`);
        opened.delete(link.id);
        say(result.message);
        await loadLinks(visit, list);
      }, "danger"),
    );
    row.append(head, actions, detail);
    list.append(row);
    if (opened.has(link.id)) await showDetail(visit, link, detail, list);
  }
}

async function showDetail(visit, link, box, list) {
  const data = await api("GET", `/api/visites/${visit.id}/liens/${link.id}`);
  box.replaceChildren();
  box.append(element("p", absolute(link), "adresse-lien"));
  if (data.pieces.length) {
    const rooms = element("table");
    const header = rooms.insertRow();
    for (const text of ["Pièce", "Temps", "Bascules"]) header.append(element("th", text));
    for (const room of data.pieces) {
      const line = rooms.insertRow();
      line.insertCell().textContent = room.nom;
      line.insertCell().textContent = duration(room.secondes);
      line.insertCell().textContent = String(room.bascules);
    }
    box.append(rooms);
  }
  if (data.chiffrage_ouvert) {
    box.append(element("p", `Chiffrage ouvert pendant ${data.chiffrage_ouvert} ouverture${data.chiffrage_ouvert > 1 ? "s" : ""}.`));
  }
  if (data.liste.length) {
    const openings = element("ul", "", "ouvertures");
    for (const opening of data.liste) {
      const when = new Date(opening.debut * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
      openings.append(element("li", `${when} · ${duration(opening.secondes)}${opening.chiffrage ? " · chiffrage ouvert" : ""}`));
    }
    box.append(openings);
  } else {
    box.append(element("p", "Aucune ouverture mesurée : le client n'a pas encore ouvert le lien, ou a refusé la mesure.", "aide"));
  }
  const changes = data.modifications;
  const count = changes.couleurs + changes.remplacements;
  const summary = count
    ? `Modifications du client : ${changes.couleurs} couleur${changes.couleurs > 1 ? "s" : ""}, ${changes.remplacements} remplacement${changes.remplacements > 1 ? "s" : ""} d'objet.`
    : "Le client n'a fait aucune modification.";
  const line = element("div", "", "actions");
  line.append(element("span", summary, "aide"));
  if (count || changes.selections) {
    const view = element("a", "Voir", "bouton");
    view.href = absolute(link);
    view.target = "_blank";
    view.rel = "noopener";
    view.title = "Ouvre la visite comme le client : refuser la mesure pour ne pas compter cette ouverture.";
    line.append(view, button("Effacer ses modifications", async () => {
      if (!confirm(`Effacer les modifications de « ${link.libelle} » ? Sans retour possible.`)) return;
      const result = await api("POST", `/api/visites/${visit.id}/liens/${link.id}/effacer`);
      say(result.message);
      await loadLinks(visit, list);
    }, "danger"));
  }
  box.append(line);
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
