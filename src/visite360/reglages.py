"""Étape 13 : réglages du serveur et de l'assemblage en ligne, lus dans l'environnement (D38).

Aucune adresse, aucun nom de stockage ni aucune clé n'est écrit dans le code : chez Scaleway, ils
sont donnés au conteneur du serveur et à la tâche d'assemblage par des variables
d'environnement, les clés venant du gestionnaire de secrets. Changer de domaine ou ajouter un
environnement d'intégration ne demande donc pas de code. Liste et rôle de chaque variable :
`docs/serveur.md`.

Sur le Mac, `visite360 serveur --local` remplace tout par des dossiers locaux (`local_settings`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from visite360 import publier

DEFAULT_PORT = 8080
LOCAL_FOLDER = Path("visites") / ".serveur"


class SettingsError(Exception):
    """Réglage manquant ou invalide. Message en français."""


@dataclass(frozen=True)
class Settings:
    """Tout ce qui distingue un environnement d'un autre."""

    database: str
    # Stockage privé des photos (None : dossier local `local_root / "depot"`).
    depot: publier.Settings | None
    # Stockage des visites publiées (None : dossier local servi par le serveur).
    public: publier.Settings | None
    # Adresse publique du serveur, sans « / » final.
    address: str
    port: int = DEFAULT_PORT
    # Identifiant de la tâche d'assemblage chez Scaleway (None : assemblage dans le serveur).
    job: str | None = None
    local_root: Path | None = None

    @property
    def local(self) -> bool:
        return self.local_root is not None


def _required(environ: Mapping[str, str], name: str, role: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"Réglage {name} manquant ({role}). Voir docs/serveur.md.")
    return value


def from_env(environ: Mapping[str, str], need_job: bool = True) -> Settings:
    """Réglages du serveur en ligne (`need_job`) ou de la tâche d'assemblage."""
    database = _required(environ, "VISITE360_BASE", "adresse de la base de données")
    access = _required(environ, "SCW_ACCESS_KEY", "clé d'accès de Scaleway")
    secret = _required(environ, "SCW_SECRET_KEY", "clé secrète de Scaleway")
    region = environ.get("VISITE360_REGION", publier.DEFAULT_REGION)
    endpoint = environ.get("VISITE360_S3_ENDPOINT")
    depot = publier.Settings(
        access,
        secret,
        _required(environ, "VISITE360_DEPOT", "nom du stockage privé des photos"),
        region,
        None,
        endpoint,
    )
    public = publier.Settings(
        access,
        secret,
        _required(environ, "VISITE360_BUCKET", "nom du stockage des visites publiées"),
        region,
        environ.get("VISITE360_ADRESSE_VISITES") or None,
        endpoint,
    )
    try:
        port = int(environ.get("PORT", str(DEFAULT_PORT)))
    except ValueError:
        raise SettingsError("Réglage PORT invalide : un numéro est attendu.") from None
    address = _required(environ, "VISITE360_ADRESSE_API", "adresse publique du serveur")
    job = _required(environ, "VISITE360_JOB", "tâche d'assemblage") if need_job else None
    return Settings(database, depot, public, address.rstrip("/"), port, job)


def local_settings(root: Path, address: str, port: int) -> Settings:
    """Réglages du serveur lancé sur le Mac : base SQLite et stockages dans `root`."""
    database = f"sqlite:///{(root / 'registre.sqlite').resolve()}"
    return Settings(database, None, None, address.rstrip("/"), port, None, root)
