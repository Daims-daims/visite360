# Registre des licences

Toute dépendance du projet figure ici avant d'être fusionnée dans `main`. Les règles sont dans `CLAUDE.md`.

Ce registre est un outil de suivi, pas un avis juridique. À faire relire par un juriste avant la mise en vente.

Les licences changent : revérifier chaque ligne avant une mise en production.

## Utilisé actuellement

| Composant | Rôle | Licence | Mode d'utilisation | Vérifié le | Source |
|---|---|---|---|---|---|
| pytest | Tests (développement) | MIT | Paquet Python, non livré | 2026-10-09 | pypi.org/project/pytest |
| ruff | Style du code (développement) | MIT | Paquet Python, non livré | 2026-10-09 | pypi.org/project/ruff |
| hatchling | Construction du paquet | MIT | Paquet Python, non livré | 2026-10-09 | pypi.org/project/hatchling |
| sips | Conversion des photos HEIC (étape 1) | Logiciel Apple fourni avec macOS, licence de macOS | Programme externe, non livré | 2026-10-22 | Présent dans /usr/bin de macOS, voir D17 |
| OpenCV 4.14 | Alignement et fusion des photos (étape 2) | Apache 2.0 | Bibliothèque Python, **compilée par `scripts/installer-opencv.sh`**, sans FFmpeg (D19) | 2026-10-24 | LICENSE des sources opencv-python-headless 4.14.0.94 |
| libjpeg-turbo (dans OpenCV) | Lecture et écriture JPEG | IJG, BSD 3 clauses, zlib | Intégrée à la compilation d'OpenCV | 2026-10-24 | opencv/3rdparty/libjpeg-turbo/LICENSE.md |
| libpng (dans OpenCV) | Lecture et écriture PNG | PNG Reference Library License v2 | Intégrée à la compilation d'OpenCV | 2026-10-24 | opencv/3rdparty/libpng/LICENSE |
| zlib (dans OpenCV) | Compression | zlib | Intégrée à la compilation d'OpenCV | 2026-10-24 | opencv/3rdparty/zlib/LICENSE |
| carotene (dans OpenCV) | Calculs accélérés sur processeur Arm | BSD 3 clauses (NVIDIA) | Intégrée à la compilation d'OpenCV | 2026-10-24 | en-têtes de opencv/hal/carotene |
| KleidiCV (dans OpenCV) | Calculs accélérés sur processeur Arm | Apache 2.0 | Téléchargée et intégrée à la compilation d'OpenCV | 2026-10-24 | gitlab.arm.com/kleidi/kleidicv, version 26.03, dossier LICENSES |
| numpy | Calcul sur les images (étape 2) | BSD 3 clauses, avec des parties sous MIT, Apache 2.0, zlib, 0BSD et domaine public (CC0) | Paquet Python | 2026-10-24 | métadonnées et dossier licenses du paquet numpy 2.5.4 |
| Pannellum 2.5.7 | Visionneuse 360° de la visite (étape 3) | MIT | Fichiers `pannellum.js` et `pannellum.css` copiés tels quels dans `visionneuse/pannellum/`, livrés avec le projet | 2026-10-24 | fichier COPYING et package.json du paquet npm pannellum 2.5.7 |
| cmake, scikit-build, setuptools, wheel, packaging, distro | Compilation d'OpenCV | Apache 2.0, BSD ou MIT | Outils de compilation, non livrés | 2026-10-24 | pypi.org, page de chaque paquet |
| Frameworks d'iOS : SwiftUI, UIKit, AVFoundation, Core Motion, simd, Foundation, Network, CryptoKit, ARKit, SceneKit, Core Image | App de capture (étapes 5 et 6) | Logiciel Apple fourni avec iOS, Xcode and Apple SDKs Agreement | Frameworks du système, appelés par l'app, non copiés dans l'app | 2026-10-24 | developer.apple.com/support/terms, voir D25 |
| dns-sd | Annonce du Mac sur le Wi-Fi par Bonjour (étape 6) | Logiciel Apple fourni avec macOS, licence de macOS | Programme externe, appelé sans shell, non livré | 2026-10-24 | Présent dans /usr/bin de macOS, voir D26 |
| Xcode 26.3, Swift, XCTest | Compilation, installation et tests de l'app (développement) | Xcode and Apple SDKs Agreement ; Swift sous Apache 2.0 avec exception de bibliothèque d'exécution | Outils de développement, non livrés | 2026-10-24 | developer.apple.com/support/terms, swift.org/legal/license.html |
| PyTorch 2.14.1 (`torch`) | Fait tourner SAM 2.1 sur la puce graphique du Mac (étape 7) | Apache 2.0, BSD 2 et 3 clauses, MIT, Boost (BSL-1.0), Apache 2.0 avec exception LLVM | Paquet Python facultatif, installé par `scripts/installer-sam2.sh` | 2026-10-25 | métadonnées et LICENSE du paquet torch 2.14.1 |
| torchvision 0.29.1 | Dépendance de SAM 2 | BSD 3 clauses | Paquet Python facultatif | 2026-10-25 | LICENSE du paquet torchvision 0.29.1 |
| SAM 2 (code, commit 2b90b9f) | Sélection d'une surface au clic (étape 7) | Apache 2.0 ; module CUDA adapté de cc_torch sous BSD 3 clauses, non compilé sur Mac | Paquet Python facultatif, installé depuis github.com/facebookresearch/sam2 | 2026-10-25 | LICENSE et LICENSE_cctorch du dépôt, README (« model checkpoints … licensed under Apache 2.0 ») |
| Poids SAM 2.1 small (`sam2.1_hiera_small.pt`) | Modèle de sélection (étape 7) | Apache 2.0 | Téléchargés depuis dl.fbaipublicfiles.com, empreinte vérifiée, rangés hors du dépôt dans `~/.cache/visite360/modeles/` | 2026-10-25 | README de github.com/facebookresearch/sam2. Données d'entraînement : voir la remarque sur SA-1B |
| hydra-core 1.3.7, iopath 0.1.10 | Dépendances de SAM 2 (réglages, fichiers) | MIT | Paquets Python facultatifs | 2026-10-25 | LICENSE de chaque paquet |
| omegaconf 2.3.1, antlr4-python3-runtime 4.9.3, portalocker 4.4.1 | Dépendances de hydra-core et iopath | BSD 3 clauses | Paquets Python facultatifs | 2026-10-25 | LICENSE ou métadonnées de chaque paquet |
| Pillow 13.0.0 | Dépendance de SAM 2 (images) | MIT-CMU (proche de MIT) | Paquet Python facultatif | 2026-10-25 | LICENSE du paquet pillow 13.0.0 |
| tqdm 4.70.1 | Dépendance de SAM 2 (barres d'avancement) | MPL 2.0 et MIT | Paquet Python facultatif, utilisé sans modification (D29) | 2026-10-25 | LICENCE du paquet tqdm 4.70.1 |
| typing_extensions 4.16.0 | Dépendance de PyTorch | PSF 2.0 (licence de Python) | Paquet Python facultatif | 2026-10-25 | LICENSE du paquet |
| sympy 1.14.0, mpmath 1.3.0, networkx 3.7, Jinja2 3.1.6, MarkupSafe 3.0.4, fsspec 2026.9.0 | Dépendances de PyTorch | BSD | Paquets Python facultatifs | 2026-10-25 | LICENSE ou métadonnées de chaque paquet |
| filelock 4.2.4, PyYAML 6.0.3, setuptools 84.2.1 | Dépendances de PyTorch et hydra-core | MIT | Paquets Python facultatifs | 2026-10-25 | LICENSE de chaque paquet |
| mflux 0.23.0 | Fait tourner FLUX.2 klein sur la puce graphique du Mac (étape 9) | MIT | Programme externe facultatif, dans un environnement Python à part créé par `scripts/installer-generation.sh`, appelé sans shell | 2026-10-25 | métadonnées du paquet mflux 0.23.0 |
| MLX 0.32.4, mlx-metal 0.32.4 (Apple) | Calcul sur la puce graphique, pour mflux | MIT | Paquets de l'environnement de génération | 2026-10-25 | métadonnées des paquets |
| Poids FLUX.2 [klein] 4B, révision e7b7dc2 | Modèle de génération d'image (étape 9) | Apache 2.0 (« Open weights available for commercial use under the Apache 2.0 license ») | Téléchargés depuis huggingface.co/black-forest-labs/FLUX.2-klein-4B, empreintes vérifiées, rangés hors du dépôt dans `~/.cache/visite360/modeles/` | 2026-10-25 | fiche du modèle sur Hugging Face. Données d'entraînement : voir la remarque sur FLUX.2 klein |
| transformers 5.20.2, huggingface_hub 1.33.0, hf-xet 1.7.0, tokenizers 0.23.3, safetensors 0.8.0, sentencepiece 0.2.2, requests 2.34.2 | Lecture de la consigne, téléchargement et lecture des poids, pour mflux | Apache 2.0 | Paquets de l'environnement de génération | 2026-10-25 | métadonnées de chaque paquet |
| regex 2026.9.29 | Découpage de la consigne en mots, pour transformers | Apache 2.0 ; partie reprise du module `re` de Python sous CNRI Python 1.6 | Paquet de l'environnement de génération, sans modification | 2026-10-25 | LICENSE.txt du paquet |
| packaging 26.3 | Dépendance de transformers | Apache 2.0 ou BSD 2 clauses | Paquet de l'environnement de génération | 2026-10-25 | métadonnées du paquet |
| httpx 0.28.1, httpcore 1.0.9, idna 3.20, click 8.5.0, Pygments 2.21.0, protobuf 7.36.2, fsspec 2026.9.0, Jinja2 3.1.6, MarkupSafe 3.0.4, numpy 2.5.4 | Dépendances de huggingface_hub, transformers et mflux | BSD (numpy : voir sa ligne) | Paquets de l'environnement de génération | 2026-10-25 | métadonnées de chaque paquet |
| anyio 4.15.1, h11 0.16.0, charset-normalizer 3.5.2, urllib3 2.8.0, piexif 1.1.3, platformdirs 4.13.5, rich 15.0.0, markdown-it-py 4.2.0, mdurl 0.1.2, toml 0.10.2, typer 0.27.3, annotated-doc 0.0.5, filelock 4.2.4, PyYAML 6.0.3 | Dépendances de mflux et huggingface_hub | MIT | Paquets de l'environnement de génération | 2026-10-25 | métadonnées de chaque paquet |
| shellingham 1.5.4 | Dépendance de typer | ISC | Paquet de l'environnement de génération | 2026-10-25 | métadonnées du paquet |
| certifi 2026.10.23 | Certificats pour le téléchargement des poids | MPL 2.0 | Paquet de l'environnement de génération, sans modification (D29) | 2026-10-25 | métadonnées du paquet |
| Pillow 12.3.0, tqdm 4.70.1, typing_extensions 4.16.0 | Dépendances de mflux | MIT-CMU ; MPL 2.0 et MIT ; PSF 2.0 | Paquets de l'environnement de génération. Pillow 12.3 et non 13.0 : la 13.0 ne s'importe pas avec mflux sous Python 3.13 | 2026-10-25 | LICENSE de chaque paquet |

## Prévu par le plan

À déplacer dans la section précédente dans la pull request qui l'ajoute.

| Composant | Rôle | Licence | Mode d'utilisation | Vérifié le | Source |
|---|---|---|---|---|---|
| Hugin | Repli pour l'assemblage (étape 2) | GPL 2 ou ultérieure | Programme externe uniquement | 2026-10-22 | Wikipédia, page Hugin (software) |
| Marzipano | Alternative à Pannellum | Apache 2.0 | Bibliothèque web | 2026-10-22 | github.com/google/marzipano |

Remarques :

- **OpenCV compilé** : `cv2` ne dépend que de bibliothèques d'Apple (AppKit, OpenCL, Accelerate, libc++, libSystem), vérifié avec `otool -L` le 2026-10-24. Le fichier `LICENSE-3RD-PARTY.txt` copié dans le paquet compilé est générique : il cite FFmpeg et d'autres composants absents de cette compilation. Le paquet contient aussi des fichiers de détection de visages (licence Intel, de type BSD), non utilisés.
- **numpy** sur Mac ne dépend que d'Accelerate (Apple). Sur Linux, utilisé seulement par les tests GitHub, son paquet embarque OpenBLAS (BSD), libgfortran (GPL 3 avec exception pour les bibliothèques d'exécution de GCC) et libquadmath (LGPL 2.1), vérifié le 2026-10-24 sur numpy 2.5.4. Rien n'est livré depuis Linux, mais ce point reste à trancher avant tout déploiement sur un serveur Linux.
- **Tests GitHub sur Linux** : OpenCV y est compilé par le même script. La compilation de Linux n'a pas été inspectée comme celle du Mac.
- **Hugin** : source secondaire. Revérifier sur le site officiel de Hugin avant de l'ajouter.
- **SAM 2.1 et ses données d'entraînement** : SAM 2 a été entraîné en partie sur SA-1B, collection de photos de Meta réservée à la recherche (« Research purposes only » sur ai.meta.com/datasets/segment-anything, vérifié le 2026-10-25). Meta, propriétaire de ces données, publie elle-même les poids sous Apache 2.0 : ils sont considérés comme autorisés. C'est une interprétation, à faire confirmer par un juriste avec le reste de ce registre. La démo web de SAM 2 et ses polices ne sont pas utilisées.
- **SAM 2.1 est facultatif** : il n'est pas déclaré dans `pyproject.toml` et s'installe par `scripts/installer-sam2.sh`, aux versions de ce tableau. Sans lui, tout fonctionne sauf la sélection.
- **PyTorch** embarque d'autres composants, listés dans son fichier LICENSE ; les licences déclarées par le paquet sont celles du tableau. Aucun n'est sous GPL.
- **Licences ajoutées à la liste autorisée** le 2026-10-25 par le propriétaire (D29) : MIT-CMU, PSF 2.0, Boost (BSL-1.0), et MPL 2.0 pour une bibliothèque utilisée sans modifier ses fichiers.
- **FLUX.2 klein et ses données d'entraînement** : code et poids sont sous Apache 2.0, mais Black Forest Labs ne publie pas les données d'entraînement. Sa fiche dit seulement qu'elles ont été filtrées contre les contenus illicites. Elles ne sont pas déclarées réservées à la recherche, mais elles sont inconnues. Risque accepté par écrit par le propriétaire le 2026-10-25 (D31). La fiche du modèle liste aussi des usages interdits (activité illégale, contenu trompeur ou frauduleux, entre autres) et conseille des filtres de contenu pour un service ouvert au public : à prévoir en v1.
- **Environnement de génération** : il est séparé de celui du projet et installé sans résolution automatique (`pip --no-deps`), aux versions de `scripts/generation-requirements.txt`. mflux déclare aussi matplotlib (licence propre à matplotlib), opencv-python (embarque FFmpeg, voir la section Interdit) et hf-transfer : ils ne servent pas à l'édition d'image par klein et ne sont pas installés. mflux est appelé en ligne de commande, jamais importé par visite360.
- **CNRI Python 1.6** (dans regex) : ajoutée à la liste autorisée le 2026-10-25 par le propriétaire, pour ce paquet utilisé sans modification (D31). C'est l'ancienne licence de Python, permissive, dont dérive la PSF 2.0.

## Interdit

| Composant | Raison | Vérifié le |
|---|---|---|
| opencv-python-headless publié sur PyPI | Sur macOS, embarque FFmpeg et les encodeurs x264 et x265 sous GPL 2, chargés dès `import cv2` (vérifié de 4.10 à 5.0, non mentionnés dans son LICENSE-3RD-PARTY.txt). Sur Linux, FFmpeg sous LGPL lié. Remplacé par la compilation de D19 | 2026-10-24 |
| opencv-python (non « headless ») | Embarque en plus Qt sous LGPL 3 | 2026-10-22 |
| Depth Any Panoramas (DAP) | Licence CC BY-NC 4.0 | 2026-10-22 |
| Données ZInD (Zillow) | Usage académique uniquement, explicitement interdit pour améliorer un produit | 2026-10-22 |
| Poids d'un modèle entraîné sur ZInD | Même raison, quelle que soit la licence du code | 2026-10-22 |
| FLUX [dev] auto-hébergé | Licence non commerciale. Passer par l'API payante ou une licence commerciale | 2026-10-09 |
| Hunyuan3D | La licence communautaire Tencent exclut l'Union européenne | 2026-10-09 |
| Depth Anything V2 Base, Large, Giant | CC BY-NC 4.0. La version Small est sous Apache 2.0 | 2026-10-09 |
| FLUX.2 [klein] 9B, FLUX.2 [dev], FLUX.1 Fill [dev] | Licence non commerciale de Black Forest Labs. Seul klein 4B est sous Apache 2.0 | 2026-10-25 |
| LaMa (poids publiés) | Code sous Apache 2.0, poids entraînés sur Places365, réservé à la recherche et à l'enseignement | 2026-10-25 |
| MobileSAM (poids) | Code sous Apache 2.0, mais poids entraînés par un tiers sur 1 % des images de SA-1B, réservées à la recherche. Même cas que ZInD | 2026-10-25 |

## Zone grise, à éviter sans vérification complète

| Composant | Problème | Vérifié le |
|---|---|---|
| HorizonNet | Code sous MIT. Poids publiés entraînés sur des jeux de données dont ZInD et Structured3D, à licence restrictive ou non vérifiée | 2026-10-22 |
| LGT-Net | Même situation que HorizonNet | 2026-10-22 |
| Stable Diffusion (versions de remplissage d'une zone) | Licence OpenRAIL, hors de la liste autorisée, avec des restrictions d'usage ; entraîné sur LAION, contesté | 2026-10-25 |
| FLUX.3 image klein | Licence « other » et accès sur demande, non lue en détail ; 43 Go | 2026-10-25 |
| Qwen-Image-Edit-2511 | Code et poids sous Apache 2.0, données d'entraînement non publiées, comme FLUX.2 klein. Non retenu : 20 milliards de paramètres, trop lourd pour le Mac (D31) | 2026-10-25 |

## Brevets

Ce registre ne couvre que les licences. Des brevets existent sur l'estimation automatique de la forme d'une pièce à partir d'un panorama 360°, par exemple le brevet US 11 507 713. À faire examiner par un conseil en propriété intellectuelle avant de commercialiser une estimation automatique (décision D13).

## Ajouter une ligne

1. Trouver la licence à la source : fichier de licence du dépôt, ou page du paquet.
2. Pour un modèle, vérifier le code, les poids et les données d'entraînement.
3. Regarder les sous-modules et les composants embarqués.
4. Inscrire la ligne avec la date du jour et la source.
