#!/usr/bin/env bash
# Télécharge l'image fabriquée par GitHub (.github/workflows/image.yml) et l'envoie dans l'espace
# d'images de Scaleway (Container Registry), depuis le Mac, avec Podman (étape 13, docs/serveur.md).
#
# Utilisation, depuis la racine du dépôt :
#   bash deploiement/envoyer.sh rg.fr-par.scw.cloud/<espace d'images> [numéro d'exécution]
#
# Sans numéro, prend la dernière exécution réussie de la branche courante. La clé secrète de
# Scaleway reste sur le Mac : elle est lue dans SCW_SECRET_KEY, sinon dans
# ~/.config/visite360/scaleway.json (D37). GitHub n'en reçoit aucune. Il faut la commande `gh`
# connectée au dépôt (gh auth status) et Podman.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || "$1" != */* ]]; then
    echo "Erreur : donner l'espace d'images, par exemple rg.fr-par.scw.cloud/<espace>," >&2
    echo "et éventuellement le numéro d'une exécution de GitHub Actions." >&2
    exit 2
fi
REGISTRY="${1%/}"
HOST="${REGISTRY%%/*}"
RUN_ID="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for program in gh podman; do
    if ! command -v "$program" >/dev/null 2>&1; then
        echo "Erreur : la commande « $program » est introuvable (brew install $program)." >&2
        exit 1
    fi
done

SECRET="${SCW_SECRET_KEY:-}"
if [[ -z "$SECRET" ]]; then
    SECRET="$(python3 - <<'EOF'
import json
from pathlib import Path

path = Path.home() / ".config" / "visite360" / "scaleway.json"
try:
    print(json.loads(path.read_text(encoding="utf-8")).get("cle_secrete", ""))
except (OSError, ValueError):
    print("")
EOF
)"
fi
if [[ -z "$SECRET" ]]; then
    echo "Erreur : clé secrète de Scaleway introuvable (SCW_SECRET_KEY ou" >&2
    echo "~/.config/visite360/scaleway.json, voir docs/publication.md)." >&2
    exit 1
fi

cd "$ROOT"
if [[ -z "$RUN_ID" ]]; then
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    RUN_ID="$(gh run list --workflow image.yml --branch "$BRANCH" --status success \
        --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
    if [[ -z "$RUN_ID" ]]; then
        echo "Erreur : aucune exécution réussie de « image » pour la branche $BRANCH." >&2
        echo "La lancer : gh workflow run image.yml --ref $BRANCH (ou ouvrir une pull request" >&2
        echo "qui modifie deploiement/), puis attendre qu'elle finisse." >&2
        exit 1
    fi
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "Téléchargement de l'image (exécution $RUN_ID)..."
gh run download "$RUN_ID" --name image --dir "$WORK"

TAG="$(tr -d '[:space:]' < "$WORK/etiquette.txt")"
if [[ ! "$TAG" =~ ^[0-9a-f]{12}$ ]]; then
    echo "Erreur : étiquette d'image illisible dans l'archive téléchargée." >&2
    exit 1
fi
IMAGE="$REGISTRY/visite360:$TAG"

echo "Chargement dans Podman..."
# Podman dit lui-même sous quel nom il a rangé l'image (docker.io/library/visite360:…, selon le
# programme qui l'a fabriquée) : on le lit au lieu de le deviner.
LOADED="$(podman load --quiet --input "$WORK/image.tar" | tail -n 1)"
if [[ -z "$LOADED" ]]; then
    echo "Erreur : Podman n'a pas chargé l'image." >&2
    exit 1
fi
podman tag "${LOADED#Loaded image: }" "$IMAGE"

echo "Envoi dans l'espace d'images..."
printf '%s' "$SECRET" | podman login "$HOST" --username nologin --password-stdin >/dev/null
podman push "$IMAGE"

echo "Image envoyée : $IMAGE (commit $TAG)"
echo "La donner au conteneur du serveur et à la tâche d'assemblage dans la console de Scaleway."
