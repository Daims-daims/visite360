# visite360

Transforme des photos prises en tournant sur soi-même avec un téléphone en visite 360° d'un logement, puis permet de repeindre un mur et de voir la visite mise à jour.

**État :** étape 0 terminée (cadrage). Aucun traitement d'image n'existe encore. L'avancement est dans [PLAN.md](PLAN.md).

## Installation pour développer

Il faut Python 3.11 ou plus.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Vérifier que tout est en place :

```bash
visite360 --version
pytest
ruff check .
ruff format --check .
```

Les dépendances de traitement (OpenCV, puis SAM 2) arrivent avec les étapes qui en ont besoin.

## Organisation du dépôt

```
visite360/
├── CLAUDE.md          règles du projet, lues par Claude Code à chaque session
├── PLAN.md            étapes, jalons et statuts
├── docs/
│   ├── decisions.md   journal des choix techniques
│   └── licences.md    registre des dépendances et de leurs licences
├── src/visite360/     le traitement en Python
├── tests/             tests automatiques
├── .github/           tests lancés à chaque pull request, modèle de pull request
└── visites/           photos, panoramas et modifications, jamais envoyés sur git
```

La visionneuse web et l'app mobile auront leur dossier quand le plan y arrivera.

## Façon de travailler

- Une étape du plan = une branche = une pull request.
- La fusion d'une pull request dans `main` vaut validation de l'étape.
- Un jalon est une décision écrite du propriétaire, à inscrire dans `PLAN.md` avant de continuer.
- Chaque pull request dit ce qui a été fait, comment le tester, ce qui n'a pas été testé et les questions ouvertes.
- Toute nouvelle dépendance est inscrite dans [docs/licences.md](docs/licences.md).

## Démarrer une session Claude Code

Chaque session repart de zéro et ne connaît que ce qui est écrit dans ce dépôt. Pour lancer une étape :

```
Lis CLAUDE.md et PLAN.md. Propose-moi ton plan pour la prochaine étape, et attends mon accord avant d'écrire du code.
```

## Données personnelles

Des photos de logement montrent l'intérieur d'un domicile. Photos, panoramas et visites restent sur la machine et ne vont jamais dans le dépôt.

## Origine

Ce projet prend la suite de `scene3d` (reconstruction 3D par Gaussian splatting), mis en pause. Les raisons du changement sont dans [docs/decisions.md](docs/decisions.md), décision D1.
