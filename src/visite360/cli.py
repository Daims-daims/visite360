"""Point d'entrée en ligne de commande.

Les sous-commandes (doctor, stitch, ...) s'ajoutent ici au fil des étapes de PLAN.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from visite360 import (
    __version__,
    chiffrage,
    comptes,
    doctor,
    publier,
    receive,
    reglages,
    serve,
    serveur,
    stitch,
    traitement,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visite360",
        description="Transforme des photos prises au téléphone en visite 360° modifiable.",
    )
    parser.add_argument("--version", action="version", version=f"visite360 {__version__}")
    subparsers = parser.add_subparsers(dest="command", title="commandes")
    subparsers.add_parser(
        "doctor",
        help="vérifie l'installation et dit quoi installer s'il manque quelque chose",
        description="Vérifie l'installation et dit quoi installer s'il manque quelque chose.",
    )
    stitch_parser = subparsers.add_parser(
        "stitch",
        help="assemble les photos d'un point en panorama 360°",
        description=(
            "Assemble les photos d'un point en panorama équirectangulaire 2:1. "
            "Écrit panorama.jpg et rapport.json dans le dossier du point."
        ),
    )
    stitch_parser.add_argument(
        "dossier",
        type=Path,
        help="dossier du point (visites/<visite>/<point>/) ou son dossier photos/",
    )
    stitch_parser.add_argument(
        "--largeur",
        type=int,
        default=stitch.DEFAULT_WIDTH,
        help=f"largeur du panorama en pixels (par défaut {stitch.DEFAULT_WIDTH})",
    )
    stitch_parser.add_argument(
        "--force", action="store_true", help="recalcule même si le panorama est à jour"
    )
    serve_parser = subparsers.add_parser(
        "serve",
        help="sert la visite d'un point dans le navigateur",
        description=(
            "Sert une visite (un point, ou plusieurs points reliés par des flèches) dans une "
            "visionneuse 360°, à ouvrir sur le Mac ou sur un téléphone connecté au même Wi-Fi. "
            "Les panoramas qui n'existent pas encore sont assemblés à partir des photos pendant "
            "que la page affiche l'avancement. Pour une visite de plusieurs points, "
            "visite.json est créé s'il manque ; les liens s'y déclarent à la main."
        ),
    )
    serve_parser.add_argument(
        "dossier",
        type=Path,
        help=(
            "dossier d'une visite (visites/<visite>/), d'un point (visites/<visite>/<point>/) "
            "ou son dossier photos/"
        ),
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=serve.DEFAULT_PORT,
        help=f"port du serveur (par défaut {serve.DEFAULT_PORT})",
    )
    serve_parser.add_argument(
        "--local",
        action="store_true",
        help="réserve la visite à ce Mac (pas d'accès depuis le téléphone)",
    )
    serve_parser.add_argument(
        "--force",
        action="store_true",
        help="recalcule le panorama même s'il existe déjà, puis sert la visite",
    )
    receive_parser = subparsers.add_parser(
        "receive",
        help="reçoit les visites envoyées par l'app de l'iPhone sur le Wi-Fi",
        description=(
            "Attend les visites envoyées par l'app de l'iPhone, sur le même Wi-Fi, et les range "
            "dans le dossier des visites. Affiche un code à saisir dans l'app. Un envoi "
            "incomplet ou abîmé est refusé ; les photos déjà sur le Mac ne sont jamais écrasées."
        ),
    )
    receive_parser.add_argument(
        "dossier",
        type=Path,
        nargs="?",
        default=receive.DEFAULT_FOLDER,
        help=f"dossier des visites (par défaut {receive.DEFAULT_FOLDER}/)",
    )
    receive_parser.add_argument(
        "--port",
        type=int,
        default=receive.DEFAULT_PORT,
        help=f"port du serveur (par défaut {receive.DEFAULT_PORT})",
    )
    pricing_parser = subparsers.add_parser(
        "chiffrage",
        help="donne l'ordre de grandeur du prix des modifications d'une visite",
        description=(
            "Donne, pour chaque modification d'une visite (mur repeint, objet remplacé), une "
            "fourchette de prix tirée de la grille tarifs.json de la visite, ou de la grille "
            "indicative par défaut. Les surfaces viennent des pièces mesurées à l'adresse /agent."
        ),
    )
    pricing_parser.add_argument(
        "dossier", type=Path, help="dossier d'une visite (visites/<visite>/) ou d'un point"
    )
    publish_parser = subparsers.add_parser(
        "publier",
        help="met la visite en ligne chez Scaleway et affiche le lien de partage",
        description=(
            "Envoie la visite (visionneuse en lecture seule, points, liens et panoramas) dans le "
            "stockage de fichiers de Scaleway, puis affiche le lien à partager. Relancer garde "
            "le même lien et n'envoie que ce qui a changé. Les photos d'origine et les "
            "modifications ne sont jamais envoyées. Voir docs/publication.md."
        ),
    )
    publish_parser.add_argument(
        "dossier",
        type=Path,
        nargs="?",
        help="dossier d'une visite (visites/<visite>/) ou d'un point seul",
    )
    publish_parser.add_argument(
        "--configurer",
        action="store_true",
        help=f"enregistre les clés d'accès de Scaleway dans {publier.CONFIG_PATH}",
    )
    unpublish_parser = subparsers.add_parser(
        "depublier",
        help="retire de Scaleway tout ce qui est en ligne pour cette visite",
        description=(
            "Supprime chez Scaleway tous les fichiers de la visite : le lien n'affiche plus "
            "rien. Une nouvelle publication aura un autre lien."
        ),
    )
    unpublish_parser.add_argument(
        "dossier", type=Path, help="dossier de la visite publiée (visites/<visite>/)"
    )
    server_parser = subparsers.add_parser(
        "serveur",
        help="lance le serveur qui reçoit les visites de l'app et les assemble (étape 13)",
        description=(
            "Lance le serveur du projet : connexion des agents par code envoyé par e-mail, "
            "réception des visites envoyées par l'app, assemblage, publication et espace web. "
            "En ligne, ses réglages viennent des variables d'environnement (docs/serveur.md). "
            "Avec --local, tout tourne sur ce Mac, sans Scaleway."
        ),
    )
    server_parser.add_argument(
        "--local",
        action="store_true",
        help=f"tout sur ce Mac : base et stockages dans {reglages.LOCAL_FOLDER}/",
    )
    server_parser.add_argument(
        "--dossier",
        type=Path,
        default=reglages.LOCAL_FOLDER,
        help=f"avec --local : dossier des données (par défaut {reglages.LOCAL_FOLDER}/)",
    )
    server_parser.add_argument(
        "--port",
        type=int,
        help=f"port du serveur (par défaut {reglages.DEFAULT_PORT}, ou la variable PORT)",
    )
    subparsers.add_parser(
        "traiter",
        help="assemble et publie les visites en attente sur le serveur (tâche Scaleway)",
        description=(
            "Fait les traitements en attente du serveur : assemblage des panoramas, publication, "
            "puis effacement des photos d'origine des visites prêtes depuis plus de 30 jours. "
            "Lancé chez Scaleway par le serveur et une fois par jour ; réglages dans les "
            "variables d'environnement (docs/serveur.md)."
        ),
    )
    account_parser = subparsers.add_parser(
        "compte",
        help="gère la liste des agents autorisés à se connecter au serveur",
        description=(
            "Ajoute, liste ou retire les adresses e-mail des agents autorisés à se connecter. "
            "Retirer un agent ferme ses sessions sans toucher à ses visites. La base est donnée "
            "par la variable VISITE360_BASE ou la clé « base » de "
            f"{publier.CONFIG_PATH}."
        ),
    )
    account_parser.add_argument("action", choices=("ajouter", "liste", "retirer"))
    account_parser.add_argument("email", nargs="?", help="adresse e-mail de l'agent")
    account_parser.add_argument(
        "--local",
        action="store_true",
        help=f"agit sur la base du serveur lancé sur ce Mac ({reglages.LOCAL_FOLDER}/)",
    )
    account_parser.add_argument(
        "--dossier",
        type=Path,
        default=reglages.LOCAL_FOLDER,
        help="avec --local : dossier des données du serveur local",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Lance l'outil et renvoie le code de sortie du processus."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.run()
    if args.command == "stitch":
        return stitch.run(args.dossier, args.largeur, args.force)
    if args.command == "serve":
        return serve.run(args.dossier, args.port, args.local, args.force)
    if args.command == "chiffrage":
        return chiffrage.run(args.dossier)
    if args.command == "receive":
        return receive.run(args.dossier, args.port)
    if args.command == "publier":
        if args.configurer:
            return publier.run_configure()
        if args.dossier is None:
            parser.error("publier : indiquer le dossier de la visite, ou --configurer")
        return publier.run_publish(args.dossier)
    if args.command == "depublier":
        return publier.run_unpublish(args.dossier)
    if args.command == "serveur":
        return serveur.run(args.local, args.dossier, args.port)
    if args.command == "traiter":
        return traitement.run()
    if args.command == "compte":
        environ = None
        if args.local:
            settings = reglages.local_settings(args.dossier, "", 0)
            environ = {"VISITE360_BASE": settings.database}
        return comptes.run(args.action, args.email, environ)
    parser.print_help()
    return 0
