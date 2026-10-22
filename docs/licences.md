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

## Prévu par le plan

À déplacer dans la section précédente dans la pull request qui l'ajoute.

| Composant | Rôle | Licence | Mode d'utilisation | Vérifié le | Source |
|---|---|---|---|---|---|
| OpenCV | Assemblage des panoramas (étape 2) | Apache 2.0 | Bibliothèque Python | 2026-10-22 | github.com/opencv/opencv |
| opencv-python-headless | Paquet Python d'OpenCV | Scripts sous MIT, OpenCV sous Apache 2.0, FFmpeg embarqué sous LGPL 2.1 | Paquet Python | 2026-10-22 | github.com/opencv/opencv-python |
| Hugin | Repli pour l'assemblage (étape 2) | GPL 2 ou ultérieure | Programme externe uniquement | 2026-10-22 | Wikipédia, page Hugin (software) |
| Pannellum | Visite web (étape 3) | MIT | Bibliothèque web | 2026-10-22 | github.com/mpetroff/pannellum |
| Marzipano | Alternative à Pannellum | Apache 2.0 | Bibliothèque web | 2026-10-22 | github.com/google/marzipano |
| SAM 2 | Sélection d'une surface (étape 5) | Apache 2.0, code et poids | Modèle d'IA | 2026-10-22 | github.com/facebookresearch/sam2 |

Remarques :

- **opencv-python-headless** embarque FFmpeg sous LGPL 2.1. C'est compatible avec un usage commercial tant que la bibliothèque n'est pas modifiée. La liste complète des composants embarqués est dans `LICENSE-3RD-PARTY.txt` du dépôt opencv-python, à relire à l'étape 2. La version sans « headless » embarque aussi Qt sous LGPL 3 : ne pas l'utiliser.
- **Hugin** : source secondaire. Revérifier sur le site officiel de Hugin avant de l'ajouter.
- **SAM 2** dépend de PyTorch, à inscrire ici à l'étape 5 avec sa licence vérifiée. Les polices de la démo de SAM 2 sont sous SIL Open Font License, sans objet si la démo n'est pas utilisée.

## Interdit

| Composant | Raison | Vérifié le |
|---|---|---|
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
