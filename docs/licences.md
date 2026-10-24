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
| cmake, scikit-build, setuptools, wheel, packaging, distro | Compilation d'OpenCV | Apache 2.0, BSD ou MIT | Outils de compilation, non livrés | 2026-10-24 | pypi.org, page de chaque paquet |

## Prévu par le plan

À déplacer dans la section précédente dans la pull request qui l'ajoute.

| Composant | Rôle | Licence | Mode d'utilisation | Vérifié le | Source |
|---|---|---|---|---|---|
| Hugin | Repli pour l'assemblage (étape 2) | GPL 2 ou ultérieure | Programme externe uniquement | 2026-10-22 | Wikipédia, page Hugin (software) |
| Pannellum | Visite web (étape 3) | MIT | Bibliothèque web | 2026-10-22 | github.com/mpetroff/pannellum |
| Marzipano | Alternative à Pannellum | Apache 2.0 | Bibliothèque web | 2026-10-22 | github.com/google/marzipano |
| SAM 2 | Sélection d'une surface (étape 5) | Apache 2.0, code et poids | Modèle d'IA | 2026-10-22 | github.com/facebookresearch/sam2 |

Remarques :

- **OpenCV compilé** : `cv2` ne dépend que de bibliothèques d'Apple (AppKit, OpenCL, Accelerate, libc++, libSystem), vérifié avec `otool -L` le 2026-10-24. Le fichier `LICENSE-3RD-PARTY.txt` copié dans le paquet compilé est générique : il cite FFmpeg et d'autres composants absents de cette compilation. Le paquet contient aussi des fichiers de détection de visages (licence Intel, de type BSD), non utilisés.
- **numpy** sur Mac ne dépend que d'Accelerate (Apple). Sur Linux, utilisé seulement par les tests GitHub, son paquet embarque OpenBLAS (BSD), libgfortran (GPL 3 avec exception pour les bibliothèques d'exécution de GCC) et libquadmath (LGPL 2.1), vérifié le 2026-10-24 sur numpy 2.5.4. Rien n'est livré depuis Linux, mais ce point reste à trancher avant tout déploiement sur un serveur Linux.
- **Tests GitHub sur Linux** : OpenCV y est compilé par le même script. La compilation de Linux n'a pas été inspectée comme celle du Mac.
- **Hugin** : source secondaire. Revérifier sur le site officiel de Hugin avant de l'ajouter.
- **SAM 2** dépend de PyTorch, à inscrire ici à l'étape 5 avec sa licence vérifiée. Les polices de la démo de SAM 2 sont sous SIL Open Font License, sans objet si la démo n'est pas utilisée.

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

## Zone grise, à éviter sans vérification complète

| Composant | Problème | Vérifié le |
|---|---|---|
| HorizonNet | Code sous MIT. Poids publiés entraînés sur des jeux de données dont ZInD et Structured3D, à licence restrictive ou non vérifiée | 2026-10-22 |
| LGT-Net | Même situation que HorizonNet | 2026-10-22 |

## Brevets

Ce registre ne couvre que les licences. Des brevets existent sur l'estimation automatique de la forme d'une pièce à partir d'un panorama 360°, par exemple le brevet US 11 507 713. À faire examiner par un conseil en propriété intellectuelle avant de commercialiser une estimation automatique (décision D13).

## Ajouter une ligne

1. Trouver la licence à la source : fichier de licence du dépôt, ou page du paquet.
2. Pour un modèle, vérifier le code, les poids et les données d'entraînement.
3. Regarder les sous-modules et les composants embarqués.
4. Inscrire la ligne avec la date du jour et la source.
