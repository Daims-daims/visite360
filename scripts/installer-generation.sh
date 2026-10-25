#!/usr/bin/env bash
# Installe FLUX.2 [klein] 4B, le modèle de remplacement d'un objet par génération d'image
# (étape 9, D31).
#
# Crée un environnement Python à part, hors du dépôt, dans ~/.cache/visite360/generation/ (ou le
# dossier de la variable VISITE360_GENERATION), et y installe mflux et ses dépendances aux
# versions de scripts/generation-requirements.txt, vérifiées dans docs/licences.md. Télécharge
# ensuite les poids publiés par Black Forest Labs (15 Go, une seule fois) et vérifie leurs
# empreintes. Les poids sont rangés dans ~/.cache/visite360/modeles/ (ou VISITE360_MODELES).
#
# Utilisation, environnement virtuel du projet activé :
#   bash scripts/installer-generation.sh

set -euo pipefail

PYTHON="${PYTHON:-python}"
REQUIREMENTS="$(cd "$(dirname "$0")" && pwd)/generation-requirements.txt"

if [[ $# -gt 0 ]]; then
    echo "Erreur : ce script ne prend pas d'option." >&2
    exit 2
fi

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "Erreur : la génération demande un Mac à puce Apple (M1 ou plus récent)." >&2
    exit 1
fi

if ! "$PYTHON" -c "import visite360" >/dev/null 2>&1; then
    echo "Erreur : visite360 n'est pas installé dans cet environnement. Lancer d'abord pip install -e \".[dev]\"." >&2
    exit 1
fi

ENV_DIR="$("$PYTHON" -c "from visite360 import generation; print(generation.environment_folder())")"

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
    echo "Création de l'environnement de génération : $ENV_DIR"
    "$PYTHON" -m venv "$ENV_DIR"
fi

echo "Installation de mflux et de ses dépendances (quelques minutes)..."
# --no-deps : uniquement les paquets listés, à leur version. mflux en déclare d'autres
# (matplotlib, opencv-python, hf-transfer) qui ne servent pas ici.
"$ENV_DIR/bin/python" -m pip install --quiet --upgrade "pip==25.2"
"$ENV_DIR/bin/python" -m pip install --quiet --no-deps -r "$REQUIREMENTS"

"$PYTHON" - <<'EOF'
import sys

from visite360 import generation

try:
    generation.download_weights()
except generation.GenerationError as error:
    sys.exit(f"Erreur : {error}")
problem = generation.missing()
if problem:
    sys.exit(f"Erreur : installation incomplète ({problem}).")
print(f"{generation.MODEL_NAME} est prêt. Vérifier avec : visite360 doctor")
EOF
