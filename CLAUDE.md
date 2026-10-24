# visite360

Outil qui transforme des photos prises en tournant sur soi-même avec un téléphone en panoramas 360°, assemblés en visite virtuelle d'un logement, puis permet de modifier ce qu'on voit (couleur d'un mur, modifications générées par IA) et de chiffrer ces modifications. À terme, la visite se partage par lien avec les clients de l'agent. Produit destiné aux agents immobiliers : l'usage final sera commercial.

Ce projet remplace le projet `scene3d` (reconstruction par Gaussian splatting), mis en pause. Raisons dans `docs/decisions.md`, décision D1.

## Avant de travailler

- Lire `PLAN.md`. L'étape à traiter est la première qui n'est pas « livrée ».
- Ne jamais entamer une étape tant que la précédente n'est pas « livrée » sur `main` à jour. La fusion de sa pull request par le propriétaire du dépôt vaut validation.
- Ne jamais dépasser un jalon sans la décision écrite du propriétaire dans `PLAN.md`.
- Lire `docs/decisions.md` avant de remettre en cause un choix technique. Un nouveau choix structurant s'y ajoute dans la même pull request.
- Proposer un plan court pour l'étape et attendre l'accord avant d'écrire du code.

## Commandes

- Installer : `pip install -e ".[dev]"` dans un environnement virtuel (Python 3.11 ou plus)
- Tests : `pytest`
- Style : `ruff check .` puis `ruff format --check .`
- Lancer : `visite360 --help`

Ces trois vérifications doivent passer avant tout commit.

## Déroulement d'une étape

- Une étape = une branche `etape-N-nom-court` = une pull request vers `main`. Aucun commit direct sur `main`.
- Passer l'étape à « en cours » dans `PLAN.md` au premier commit, à « livrée » dans le dernier.
- La description de la pull request suit `.github/pull_request_template.md` : ce qui a été fait, comment ça marche en clair, comment le tester, ce qui n'a pas été testé, questions ouvertes.
- La rubrique « Comment ça marche, en clair » est obligatoire (D18). Le propriétaire n'est pas spécialiste de vision par ordinateur ni d'IA générative, et il valide chaque étape sur le résultat : il doit pouvoir reconnaître un mauvais résultat et en deviner la cause. Chaque mot technique est expliqué à sa première apparition.
- Ne pas fusionner soi-même. Le propriétaire relit, teste sur son Mac, puis fusionne.
- Rester dans le périmètre de l'étape. Une idée hors périmètre se note dans « Questions ouvertes », elle ne se code pas.
- Dire clairement ce qui n'a pas pu être vérifié, en particulier ce qui demande de vraies photos ou un téléphone.

## Licences

- Toute nouvelle dépendance (paquet Python, programme externe, modèle, poids, bibliothèque web, paquet npm) est inscrite dans `docs/licences.md` dans la même pull request, avec sa licence vérifiée à la source et la date de vérification.
- Autorisées : MIT, BSD, Apache 2.0, ISC, zlib, libpng (PNG Reference Library License), IJG (Independent JPEG Group), MIT-CMU, PSF 2.0, Boost (BSL-1.0).
- MPL 2.0 : acceptée pour une bibliothèque utilisée sans modifier ses fichiers (décision du propriétaire du 2026-10-25, D29).
- Interdites : toute licence non commerciale ou « recherche uniquement », notamment CC BY-NC.
- Un modèle d'IA se vérifie en trois parties : code, poids, données d'entraînement. Un code sous MIT avec des poids entraînés sur des données réservées à la recherche est interdit. C'est le cas des modèles d'estimation de la forme des pièces entraînés sur ZInD.
- GPL, LGPL, AGPL : acceptées seulement pour un programme externe appelé en ligne de commande, jamais importé ni lié dans le code. À signaler dans la pull request.
- En cas de doute, ne pas ajouter la dépendance et poser la question.

## Architecture

- Le format pivot est le panorama équirectangulaire (image au rapport 2:1). Toute étape lit ou produit ce format.
- Les données d'une visite vivent dans `visites/<nom>/` : photos d'origine par point, panoramas, fichier `visite.json` (points, liens, orientations), modifications.
- **Modifications non destructives (D9) :** les photos et panoramas d'origine ne sont jamais réécrits. Une modification est une opération enregistrée (masque et paramètres) appliquée pour produire une image dérivée. On peut l'annuler, la combiner et la recalculer.
- Chaque étape de traitement est un module indépendant dans `src/visite360/`. Il lit un dossier de visite et y écrit son résultat. Pas d'état global, pas de chemin en dur.
- Relancer un module ne casse rien et ne refait pas ce qui est déjà fait, sauf option explicite pour forcer.
- Les programmes externes sont appelés par `subprocess` avec une liste d'arguments, jamais avec `shell=True`.
- L'absence ou l'échec d'un outil externe produit un message clair en français et un code de sortie non nul, pas une trace Python.
- Pas de dépendance Python d'exécution sans raison écrite dans la pull request.
- Organisation du dépôt (D15) : traitement Python dans `src/visite360/`, visionneuse web dans un dossier dédié à créer à l'étape 3, app mobile dans `app/` à partir de l'étape 5.

## Conventions

- Identifiants de code en anglais. Documentation, messages affichés et pull requests en français.
- Annotations de type sur les fonctions publiques. Chemins avec `pathlib`.
- Les tests automatiques utilisent des images générées pendant le test. Aucune photo réelle dans le dépôt.
- Ce qui exige de vraies photos ou un téléphone se décrit dans « Comment tester » de la pull request.
- Ne jamais ajouter au dépôt de photo, de panorama ni de visite : ce sont des données personnelles. `visites/` est ignoré par git.

## Matériel de référence

- Traitement : MacBook Air M4, 24 Go de mémoire partagée, sans ventilateur, sans CUDA.
- Prise de vue : le téléphone du propriétaire. Modèle à préciser avant l'étape 5.

## Hors périmètre

- Jusqu'à la v1 (D22) : hébergement, serveur distant, lien de partage, comptes utilisateurs, tout service payant. Le produit tourne en local, sur le Mac et le téléphone.
- Toute la durée du plan actuel : plan du logement, Gaussian splatting.
