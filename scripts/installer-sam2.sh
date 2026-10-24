#!/usr/bin/env bash
# Installe SAM 2.1 small, le modèle de sélection d'une surface au clic (étape 7, D29).
#
# Installe PyTorch et SAM 2 dans l'environnement Python actif, aux versions vérifiées dans
# docs/licences.md, puis télécharge les poids publiés par Meta (176 Mo) et vérifie leur
# empreinte. Les poids sont rangés hors du dépôt, dans ~/.cache/visite360/modeles/
# (ou dans le dossier indiqué par la variable VISITE360_MODELES).
#
# Utilisation, environnement virtuel du projet activé :
#   bash scripts/installer-sam2.sh

set -euo pipefail

TORCH_VERSION="2.14.1"
TORCHVISION_VERSION="0.29.1"
# Version de SAM 2 publiée sur GitHub par Meta (commit du 2024-12-11, après la sortie de SAM 2.1).
SAM2_COMMIT="2b90b9f5ceec907a1c18123530e92e794ad901a4"
PYTHON="${PYTHON:-python}"

if [[ $# -gt 0 ]]; then
    echo "Erreur : ce script ne prend pas d'option." >&2
    exit 2
fi

if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Erreur : « $PYTHON -m pip » ne fonctionne pas. Activer l'environnement virtuel du projet." >&2
    exit 1
fi

if ! "$PYTHON" -c "import visite360" >/dev/null 2>&1; then
    echo "Erreur : visite360 n'est pas installé dans cet environnement. Lancer d'abord pip install -e \".[dev]\"." >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "Erreur : git est introuvable. L'installer avec : xcode-select --install" >&2
    exit 1
fi

echo "Installation de PyTorch $TORCH_VERSION et de SAM 2 (quelques minutes)..."
# SAM2_BUILD_CUDA=0 : pas de module pour les cartes graphiques NVIDIA, absentes des Mac.
SAM2_BUILD_CUDA=0 "$PYTHON" -m pip install \
    "torch==$TORCH_VERSION" \
    "torchvision==$TORCHVISION_VERSION" \
    "hydra-core==1.3.7" \
    "iopath==0.1.10" \
    "tqdm==4.70.1" \
    "pillow==13.0.0" \
    "sam-2 @ git+https://github.com/facebookresearch/sam2.git@$SAM2_COMMIT"

"$PYTHON" - <<'EOF'
import sys

from visite360 import segment

try:
    segment.download_weights()
except segment.SegmentError as error:
    sys.exit(f"Erreur : {error}")
problem = segment.missing()
if problem:
    sys.exit(f"Erreur : installation incomplète ({problem}).")
print("SAM 2.1 small est prêt. Vérifier avec : visite360 doctor")
EOF
