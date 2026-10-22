"""Point d'entrée en ligne de commande.

Les sous-commandes (doctor, stitch, ...) s'ajoutent ici au fil des étapes de PLAN.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from visite360 import __version__, doctor


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Lance l'outil et renvoie le code de sortie du processus."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.run()
    parser.print_help()
    return 0
