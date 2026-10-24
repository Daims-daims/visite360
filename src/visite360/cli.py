"""Point d'entrée en ligne de commande.

Les sous-commandes (doctor, stitch, ...) s'ajoutent ici au fil des étapes de PLAN.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from visite360 import __version__, doctor, serve, stitch


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
            "Sert le panorama d'un point dans une visionneuse 360°, à ouvrir sur le Mac "
            "ou sur un téléphone connecté au même Wi-Fi. Si le panorama n'existe pas encore, "
            "il est assemblé à partir des photos du point pendant que la page affiche l'avancement."
        ),
    )
    serve_parser.add_argument(
        "dossier",
        type=Path,
        help="dossier du point (visites/<visite>/<point>/) ou son dossier photos/",
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
    parser.print_help()
    return 0
