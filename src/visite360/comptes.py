"""Étape 13 : comptes des agents, codes de connexion par e-mail (D39).

Le propriétaire tient depuis le Mac la liste fermée des adresses autorisées :

    visite360 compte ajouter agent@exemple.fr
    visite360 compte liste
    visite360 compte retirer agent@exemple.fr

Pour se connecter, l'agent donne son adresse dans l'app ou l'espace web. Si elle est dans la
liste, le serveur lui envoie un code à 6 chiffres, valable 10 minutes, par le service d'envoi
d'e-mails de Scaleway (Transactional Email, par le protocole SMTP de la bibliothèque standard).
Sinon, rien ne part, et l'écran affiche le même message : on ne révèle pas qui est client.

Retirer un agent ferme ses sessions et bloque sa connexion, sans toucher à ses visites : ce
qu'elles deviennent est une question ouverte de l'étape 13.

La commande lit l'adresse de la base dans la variable `VISITE360_BASE`, ou à défaut dans la clé
`base` de `~/.config/visite360/scaleway.json` (D37).
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol, TextIO

from visite360 import publier
from visite360.registre import Registre, RegistreError, open_database

SUBJECT = "Votre code de connexion"
SMTP_TIMEOUT = 30


class MailError(Exception):
    """L'e-mail n'a pas pu partir. Message en français."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


class ConsoleMailer:
    """Pour le serveur lancé sur le Mac : le code s'affiche dans le Terminal au lieu de partir."""

    def __init__(self, out: TextIO) -> None:
        self.out = out

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"[E-mail pour {to}] {subject}\n{text}", file=self.out, flush=True)


class SMTPMailer:
    """Envoi par SMTP chiffré (STARTTLS), vers le service Transactional Email de Scaleway."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender = sender

    def send(self, to: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            raise MailError(f"Envoi de l'e-mail impossible ({error}).") from None


def code_text(code: str) -> str:
    return (
        f"Votre code de connexion : {code[:3]} {code[3:]}\n\n"
        "Il est valable 10 minutes. Si vous n'avez rien demandé, ignorez ce message : "
        "personne ne peut se connecter sans ce code.\n"
    )


def mailer_from_env(environ: Mapping[str, str]) -> Mailer | None:
    """Service d'envoi d'après les variables d'environnement du serveur, ou None s'il manque."""
    names = ("VISITE360_SMTP_HOTE", "VISITE360_SMTP_UTILISATEUR", "VISITE360_SMTP_MOT_DE_PASSE")
    if not all(environ.get(name) for name in names):
        return None
    sender = environ.get("VISITE360_EXPEDITEUR", "")
    if not sender:
        raise MailError("Réglage VISITE360_EXPEDITEUR manquant (adresse d'envoi des codes).")
    try:
        port = int(environ.get("VISITE360_SMTP_PORT", "587"))
    except ValueError:
        raise MailError("Réglage VISITE360_SMTP_PORT invalide : un numéro est attendu.") from None
    return SMTPMailer(
        environ["VISITE360_SMTP_HOTE"],
        port,
        environ["VISITE360_SMTP_UTILISATEUR"],
        environ["VISITE360_SMTP_MOT_DE_PASSE"],
        sender,
    )


# --- Ligne de commande --------------------------------------------------------------------------


def database_url(environ: Mapping[str, str], config: Path = publier.CONFIG_PATH) -> str | None:
    """Adresse de la base : variable `VISITE360_BASE`, sinon clé `base` du fichier de réglages."""
    if environ.get("VISITE360_BASE"):
        return environ["VISITE360_BASE"]
    if not config.is_file():
        return None
    try:
        raw = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = raw.get("base") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value else None


def _date(stamp: int | None) -> str:
    if stamp is None:
        return ""
    return datetime.fromtimestamp(stamp, UTC).astimezone().strftime("%d/%m/%Y")


def run(
    action: str,
    email: str | None,
    environ: Mapping[str, str] | None = None,
    config: Path = publier.CONFIG_PATH,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Point d'entrée de `visite360 compte`. Renvoie le code de sortie."""
    out, err = out or sys.stdout, err or sys.stderr
    url = database_url(os.environ if environ is None else environ, config)
    if url is None:
        print(
            "Erreur : adresse de la base inconnue. La donner dans la variable VISITE360_BASE, "
            f"ou dans la clé « base » de {config} (voir docs/serveur.md).",
            file=err,
        )
        return 1
    if action in ("ajouter", "retirer") and not (email and "@" in email):
        print(f"Erreur : donner l'adresse e-mail de l'agent à {action}.", file=err)
        return 1
    try:
        registre = Registre(open_database(url))
        registre.create_schema()
        if action == "ajouter":
            assert email is not None
            agent, created = registre.add_agent(email)
            if created:
                print(f"{agent.email} peut maintenant se connecter.", file=out)
            else:
                print(f"{agent.email} était déjà autorisé.", file=out)
        elif action == "retirer":
            assert email is not None
            retired = registre.retire_agent(email)
            if retired is None:
                print(f"{email} n'est pas dans la liste : rien à faire.", file=out)
            else:
                count = registre.visit_count(retired.id)
                print(
                    f"{retired.email} ne peut plus se connecter, ses sessions sont fermées. "
                    f"Ses {count} visite(s) restent en ligne.",
                    file=out,
                )
        else:
            agents = registre.agents()
            if not agents:
                print("Aucun agent autorisé.", file=out)
            for agent in agents:
                state = f"retiré le {_date(agent.retired)}" if agent.retired else "autorisé"
                visits = registre.visit_count(agent.id)
                print(
                    f"{agent.email} : {state}, ajouté le {_date(agent.created)}, "
                    f"{visits} visite(s)",
                    file=out,
                )
    except RegistreError as error:
        print(f"Erreur : {error}", file=err)
        return 1
    return 0
