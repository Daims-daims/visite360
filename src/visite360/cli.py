"""Point d'entrée en ligne de commande.

Les sous-commandes (doctor, stitch, ...) s'ajoutent ici au fil des étapes de PLAN.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from visite360 import __version__, doctor, stitch


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Lance l'outil et renvoie le code de sortie du processus."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.run()
    if args.command == "stitch":
        return stitch.run(args.dossier, args.largeur, args.force)
    parser.print_help()
    return 0
