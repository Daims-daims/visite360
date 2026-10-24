# visite360

Transforme des photos prises en tournant sur soi-même avec un téléphone en visite 360° d'un logement, puis permet de modifier ce qu'on voit (couleur d'un mur, modifications générées par IA) et de chiffrer ces modifications. Feuille de route par versions dans [PLAN.md](PLAN.md).

**État :** étape 7 (sélection d'une surface au clic). L'avancement est dans [PLAN.md](PLAN.md).

## Installation pour développer

Il faut Python 3.11 ou plus.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
bash scripts/installer-opencv.sh
```

Le script compile OpenCV sans FFmpeg, en 2 minutes environ, et l'installe dans l'environnement actif. Ne pas installer `opencv-python-headless` depuis PyPI : sur Mac, il embarque des bibliothèques sous GPL (décision D19).

Vérifier que tout est en place :

```bash
visite360 --version
visite360 doctor
pytest
ruff check .
ruff format --check .
```

`visite360 doctor` vérifie Python, OpenCV, la conversion des photos HEIC et, s'il est installé, SAM 2.1, et dit quoi installer s'il manque quelque chose.

Pour photographier un point de la visite : [docs/prise-de-vue.md](docs/prise-de-vue.md). Avec l'app iPhone, qui guide la prise de vue : [docs/app.md](docs/app.md) (installation par câble depuis Xcode).

## Recevoir une visite prise avec l'app

```bash
visite360 receive
```

La commande affiche un code à 6 chiffres et attend les visites envoyées par l'app iPhone sur le même Wi-Fi. Elles sont rangées dans `visites/<visite>/`, avec les flèches visées dans l'app. Mode d'emploi : [docs/transfert.md](docs/transfert.md).

## Assembler un panorama

Ranger les photos d'un point dans `visites/<visite>/<point>/photos/`, puis :

```bash
visite360 stitch visites/<visite>/<point>
```

Le panorama `panorama.jpg` (8192 × 4096 par défaut, option `--largeur`) et le rapport `rapport.json` sont écrits dans le dossier du point. Une relance ne refait rien si les photos n'ont pas changé, sauf avec `--force`.

## Parcourir une visite

```bash
visite360 serve visites/<visite>            # tous les points, reliés par des flèches
visite360 serve visites/<visite>/<point>    # un seul point
```

La commande affiche deux adresses : une pour le Mac, une pour un téléphone connecté au même Wi-Fi. Les panoramas qui n'existent pas encore sont assemblés à partir des photos, un point après l'autre, pendant que la page affiche une barre d'avancement, puis la visite s'ouvre toute seule. `Ctrl+C` arrête le serveur. L'option `--local` réserve la visite au Mac, `--port` change le port, `--force` recalcule les panoramas même s'ils existent.

Une visite reçue de l'app a déjà son `visite.json`, flèches comprises. Pour des photos prises sans l'app, `visite.json` est créé tout seul avec un point par dossier et aucun lien, et les flèches s'y ajoutent à la main : voir [docs/visite-json.md](docs/visite-json.md).

## Sélectionner une surface

Dans la visite, le bouton **Sélectionner une surface** trouve le contour d'un mur, d'un sol ou d'un plafond au clic, avec le modèle SAM 2.1 qui tourne sur le Mac. Il s'installe à part, une fois :

```bash
bash scripts/installer-sam2.sh
```

Les sélections sont enregistrées dans `visites/<visite>/<point>/modifications/`, sans toucher au panorama. Mode d'emploi : [docs/selection.md](docs/selection.md).

## Organisation du dépôt

```
visite360/
├── CLAUDE.md          règles du projet, lues par Claude Code à chaque session
├── PLAN.md            étapes, jalons et statuts
├── docs/
│   ├── decisions.md   journal des choix techniques
│   ├── licences.md    registre des dépendances et de leurs licences
│   ├── app.md         installer et utiliser l'app iPhone
│   ├── capture-json.md  orientations écrites par l'app
│   ├── transfert.md   envoyer une visite de l'iPhone au Mac
│   ├── visite-json.md  points et flèches d'une visite
│   ├── selection.md   sélectionner une surface au clic, format des sélections
│   ├── prise-de-vue.md  comment photographier un point
│   └── ressources.md  ce qu'il faut lire ou regarder pour comprendre chaque étape
├── app/               app iPhone de capture guidée (SwiftUI, D25)
├── visionneuse/       page web de la visite et Pannellum
├── scripts/           compilation d'OpenCV sans FFmpeg, installation de SAM 2.1
├── src/visite360/     le traitement en Python
├── tests/             tests automatiques
├── .github/           tests lancés à chaque pull request, modèle de pull request
└── visites/           photos, panoramas et modifications, jamais envoyés sur git
```

## Façon de travailler

- Une étape du plan = une branche = une pull request.
- La fusion d'une pull request dans `main` vaut validation de l'étape.
- Un jalon est une décision écrite du propriétaire, à inscrire dans `PLAN.md` avant de continuer.
- Chaque pull request dit ce qui a été fait, comment ça marche en clair, comment le tester, ce qui n'a pas été testé et les questions ouvertes.
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
