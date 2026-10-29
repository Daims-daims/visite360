#!/usr/bin/env bash
# Fabrique l'image du serveur pour linux/amd64 et l'envoie dans l'espace d'images de Scaleway
# (Container Registry), sur le Mac, avec Podman (étape 13, docs/serveur.md).
#
# Utilisation, depuis la racine du dépôt :
#   bash deploiement/construire.sh rg.fr-par.scw.cloud/<espace d'images>
#
# L'adresse de l'espace d'images est un réglage, donné à chaque fois (D38). La clé secrète de
# Scaleway est lue dans SCW_SECRET_KEY, sinon dans ~/.config/visite360/scaleway.json (D37).
# L'image est étiquetée avec le commit courant : la même étiquette se donne ensuite au conteneur
# et à la tâche dans la console de Scaleway.

set -euo pipefail

if [[ $# -ne 1 || "$1" != */* ]]; then
    echo "Erreur : donner l'espace d'images, par exemple rg.fr-par.scw.cloud/<espace>." >&2
    exit 2
fi
REGISTRY="${1%/}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v podman >/dev/null 2>&1; then
    echo "Erreur : Podman est introuvable. L'installer (brew install podman), puis lancer" >&2
    echo "« podman machine init » et « podman machine start »." >&2
    exit 1
fi

if [[ -n "$(git -C "$ROOT" status --porcelain -- src visionneuse espace pyproject.toml)" ]]; then
    echo "Erreur : des changements du code ne sont pas enregistrés (git commit) : l'image ne" >&2
    echo "correspondrait à aucun commit." >&2
    exit 1
fi
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
IMAGE="$REGISTRY/visite360:$TAG"

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

MEMORY_MB="$(podman machine inspect --format '{{.Resources.Memory}}' 2>/dev/null || echo 0)"
if [[ "$MEMORY_MB" =~ ^[0-9]+$ && "$MEMORY_MB" -gt 0 && "$MEMORY_MB" -lt 6144 ]]; then
    echo "Erreur : la machine virtuelle de Podman n'a que $MEMORY_MB Mo de mémoire ; la compilation" >&2
    echo "d'OpenCV y serait tuée. Lui en donner 8 Go, puis recommencer :" >&2
    echo "  podman machine stop && podman machine set --memory 8192 && podman machine start" >&2
    exit 1
fi

echo "Fabrication de $IMAGE (la première fois : longue, OpenCV est compilé par émulation)..."
podman build --platform linux/amd64 -f "$ROOT/deploiement/Containerfile" -t "$IMAGE" "$ROOT"

echo "Envoi dans l'espace d'images..."
# Scaleway demande l'espace d'images en entier (hôte et nom), le nom d'utilisateur « nologin »
# et la clé secrète comme mot de passe. La clé doit avoir le droit ContainerRegistryFullAccess.
if ! printf '%s' "$SECRET" | podman login "$REGISTRY" --username nologin --password-stdin >/dev/null; then
    echo "Erreur : Scaleway refuse la connexion à $REGISTRY." >&2
    echo "Vérifier que la clé a le droit « ContainerRegistryFullAccess » (IAM, politique de" >&2
    echo "l'application), que le nom de l'espace d'images est exact, et que la clé secrète" >&2
    echo "lue est celle de cette application (SCW_SECRET_KEY, sinon scaleway.json)." >&2
    exit 1
fi
podman push "$IMAGE"

echo "Image envoyée : $IMAGE"
echo "La donner au conteneur du serveur et à la tâche d'assemblage dans la console de Scaleway."
