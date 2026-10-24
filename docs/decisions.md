# Journal des décisions

Chaque décision a un numéro stable. Pour revenir sur l'une d'elles, ajouter une nouvelle entrée qui la remplace, sans effacer l'ancienne.

## D1 : visite par panoramas 360° plutôt que reconstruction 3D par splatting

- **Date :** 2026-10-22
- **Décision :** le produit repose sur des panoramas 360° pris en tournant sur soi-même à plusieurs points du logement. Le projet `scene3d`, qui reconstruisait une scène 3D par Gaussian splatting à partir d'une vidéo, est mis en pause, pas supprimé.
- **Raisons :** prise de vue plus simple et plus robuste, compatible avec tout téléphone, visite légère à afficher, images de qualité photo puisque ce sont de vraies photos.
- **Conséquences :**
  - la visite saute d'un point à l'autre, sans déplacement libre ;
  - tourner sur soi-même ne donne aucune 3D, puisque toutes les photos d'un point sont prises du même endroit. La 3D vient d'ailleurs : forme des pièces indiquée par l'utilisateur, suivi de position du téléphone ;
  - la capture et la visite 360° existent déjà sur le marché. La différence du produit est la modification de ce qu'on voit.

## D2 : Python pour le traitement

- **Date :** 2026-10-22
- **Décision :** l'assemblage et les modifications d'images sont codés en Python.
- **Raisons :** OpenCV et SAM 2 sont dans cet écosystème. Repris du projet `scene3d`.

## D3 : MacBook Air M4 comme machine de référence pour le traitement

- **Date :** 2026-10-22
- **Décision :** le traitement doit tourner sur un MacBook Air M4 avec 24 Go de mémoire.
- **Conséquences :** aucun outil dépendant de CUDA. Les modèles d'IA doivent fonctionner sur la puce Apple ou sur le processeur.

## D4 : GitHub, une étape par pull request

- **Date :** 2026-10-22
- **Décision :** dépôt privé sur GitHub. Une étape du plan = une branche = une pull request. La fusion par le propriétaire vaut validation.
- **Raisons :** permettre au propriétaire de piloter et de vérifier chaque étape avant la suivante.

## D5 : licences compatibles avec un usage commercial uniquement

- **Date :** 2026-10-22
- **Décision :** aucune dépendance sous licence non commerciale, même pour un prototype. Registre tenu dans `docs/licences.md`.
- **Raisons :** le produit sera vendu. Dans ce domaine, beaucoup de modèles ont un code sous licence libre mais des poids entraînés sur des données réservées à la recherche.

## D6 : panorama équirectangulaire comme format pivot

- **Date :** 2026-10-22
- **Décision :** chaque point de la visite est représenté par un panorama équirectangulaire au rapport 2:1.
- **Raisons :** format standard, lu par toutes les visionneuses 360° et par les portails immobiliers qui acceptent la 360°.
- **Conséquence :** l'image est déformée près du sol et du plafond. Les traitements d'image se font sur des vues normales découpées dans le panorama, puis reportées (voir D10).

## D7 : assemblage par OpenCV, Hugin en repli

- **Date :** 2026-10-22
- **Décision :** l'assemblage des photos en panorama utilise le module d'assemblage d'OpenCV, via le paquet `opencv-python-headless`. Hugin est le repli s'il ne suffit pas.
- **Raisons :** OpenCV est sous Apache 2.0 et s'utilise directement en Python. Hugin, sous GPL, est l'outil de référence pour les panoramas complets, mais ne peut être appelé que comme programme externe.
- **À confirmer à l'étape 2 :** qualité sur des photos prises à main levée.

## D8 : Pannellum pour la visite (à confirmer)

- **Date :** 2026-10-22
- **Décision provisoire :** la visite web s'appuie sur Pannellum, visionneuse 360° sous licence MIT.
- **Alternative :** Marzipano, sous Apache 2.0.
- **À confirmer à l'étape 3 :** fluidité sur téléphone, gestion des liens entre points, possibilité d'afficher un avant/après.
- **Étape 3 (2026-10-24) :** Pannellum 2.5.7 est livré dans `visionneuse/pannellum/`, sans téléchargement depuis internet, pour que la visite marche hors ligne. Le panorama s'affiche correctement dans un navigateur de bureau. Restent à valider par le propriétaire : la fluidité sur téléphone, puis aux étapes 4 et 8 les liens entre points et l'avant/après. La décision reste provisoire jusque-là.

## D9 : modifications non destructives

- **Date :** 2026-10-22
- **Décision :** les photos et panoramas d'origine ne sont jamais réécrits. Chaque modification est une opération enregistrée (masque, paramètres) qu'on applique pour produire une image dérivée.
- **Raisons :** annuler, combiner, recalculer après un changement de réglage. En phase 4, une opération pourra être rattachée à une surface du modèle 3D plutôt qu'à des pixels, sans changer le principe.

## D10 : sélection d'une surface au clic avec SAM 2

- **Date :** 2026-10-22
- **Décision :** l'utilisateur clique sur une surface, SAM 2 en trouve le contour. Le traitement se fait sur une vue normale découpée autour du clic, puis le masque est reporté dans le panorama.
- **Raisons :** code et poids sous Apache 2.0. Le clic évite de dépendre d'un modèle qui reconnaît les murs par catégorie, souvent entraîné sur des données à licence restrictive.
- **À confirmer à l'étape 5 :** vitesse sur le Mac et taille de modèle adaptée.

## D11 : recoloration sans IA générative

- **Date :** 2026-10-22
- **Décision :** le changement de couleur d'une surface est un calcul déterministe qui garde la luminosité de chaque pixel et change la teinte.
- **Raisons :** rien n'est inventé, le résultat est reproductible, rapide et sans coût de calcul important. Ombres, lumière et texture du mur sont conservées.
- **Limite :** passer d'une surface foncée à une surface claire est moins réussi.

## D12 : démo aux agents avant l'app mobile

- **Date :** 2026-10-22
- **Décision :** le jalon A (démo à des agents immobiliers) arrive après la phase 2 et avant toute app mobile.
- **Raisons :** valider la fonction qui différencie le produit, la modification, avant d'investir dans le développement mobile.

## D13 : forme des pièces indiquée par l'utilisateur

- **Date :** 2026-10-22
- **Décision :** en phase 4, la forme de chaque pièce vient de l'utilisateur, qui pointe les coins au sol et au plafond dans le panorama.
- **Raisons :** les modèles automatiques ouverts (HorizonNet, LGT-Net) ont un code sous MIT, mais leurs poids sont entraînés sur des jeux de données réservés à un usage académique, comme ZInD. Des brevets existent aussi sur l'estimation automatique.
- **Évolution possible :** réentraîner un modèle sur des données utilisables commercialement, après avis d'un conseil en propriété intellectuelle.

## D14 : liens entre points déclarés à la main, puis mesurés par le téléphone

- **Date :** 2026-10-22
- **Décision :** en phase 1, les liens entre points et leur orientation sont déclarés à la main dans `visite.json`. En phase 3, l'app mesure le déplacement entre deux points grâce à la réalité augmentée du téléphone.
- **Raisons :** ne pas bloquer la visite sur un calcul automatique difficile. Le suivi de position du téléphone est la méthode la plus fiable une fois l'app disponible.

## D15 : un seul dépôt pour le traitement, la visionneuse et l'app

- **Date :** 2026-10-22
- **Décision :** traitement Python dans `src/visite360/`, visionneuse web dans un dossier dédié créé à l'étape 3, app mobile dans `app/` à partir de la phase 3.
- **À confirmer en phase 3 :** garder un seul dépôt ou séparer l'app.

## D16 : aucune dépendance Python d'exécution au départ

- **Date :** 2026-10-22
- **Décision :** le squelette n'utilise que la bibliothèque standard. pytest et ruff sont des outils de développement.
- **Raisons :** chaque dépendance est une licence à vérifier et une source de casse. On n'en ajoute que lorsqu'une étape en a besoin.

## D17 : photos HEIC converties par sips, OpenCV 4.10 ou plus

- **Date :** 2026-10-22
- **Décision :**
  - les photos HEIC de l'iPhone sont converties par `sips`, programme fourni avec macOS, appelé en ligne de commande. Pas de bibliothèque Python de lecture du HEIC ;
  - la version minimale d'OpenCV est 4.10. `visite360 doctor` la vérifie dès l'étape 1, mais `opencv-python-headless` n'entre dans les dépendances de `pyproject.toml` qu'à l'étape 2, qui l'utilise (D16).
- **Raisons :**
  - `pillow-heif` s'importe dans le code et ses paquets embarquent libheif et libde265, sous LGPL : interdit pour une bibliothèque importée. `sips` est déjà sur la machine de référence (D3) et ne s'importe pas ;
  - OpenCV 4.10 a des paquets pour Python 3.11 à 3.13 sur puce Apple. OpenCV 5.0, version installée par défaut au 2026-10-22, garde le module d'assemblage (`cv2.Stitcher`) : il est accepté.
- **Conséquences :** la conversion HEIC ne fonctionne que sur macOS. Ailleurs, régler l'iPhone sur « Le plus compatible » pour obtenir du JPEG.
- **À confirmer à l'étape 2 :** fixer ou non une version maximale d'OpenCV après les essais d'assemblage.

## D18 : une explication en clair dans chaque pull request

- **Date :** 2026-10-24
- **Décision :** chaque pull request contient une rubrique « Comment ça marche, en clair » : le principe de l'étape sans jargon, ses limites, et à quoi ressemble un mauvais résultat. `docs/ressources.md` liste ce qu'il faut lire ou regarder pour aller plus loin, étape par étape.
- **Raisons :** le code est écrit avec Claude, mais le propriétaire valide chaque étape sur le résultat. Pour piloter, il doit savoir reconnaître un échec et en deviner la cause (prise de vue, réglage ou code), sans devoir suivre un cours complet.

## D19 : OpenCV compilé sans FFmpeg, assemblage en deux temps

- **Date :** 2026-10-24
- **Décision :**
  - OpenCV 4.14 est compilé depuis ses sources officielles par `scripts/installer-opencv.sh`, avec seulement les modules utiles (core, imgproc, imgcodecs, features2d, flann, calib3d, stitching) et sans FFmpeg. Le paquet `opencv-python-headless` de PyPI est interdit. `visite360 doctor` et `visite360 stitch` refusent un OpenCV compilé avec FFmpeg ;
  - OpenCV n'est pas déclaré dans `pyproject.toml`, sinon `pip install` irait chercher le paquet de PyPI. numpy l'est ;
  - l'assemblage se fait en deux temps : alignement avec les briques détaillées d'OpenCV (points SIFT, appariement, ajustement des rotations et de la focale, correction de l'horizon), puis rendu équirectangulaire par notre code, avec compensation d'exposition et fusion multibande d'OpenCV ;
  - les licences zlib, libpng et IJG, intégrées à OpenCV, sont ajoutées à la liste autorisée de `CLAUDE.md` par décision du propriétaire.
- **Raisons :**
  - sur macOS, tous les paquets PyPI d'OpenCV de 4.10 à 5.0 embarquent les encodeurs x264 et x265 sous GPL 2, chargés dès `import cv2`. Le projet n'accepte la GPL que pour un programme externe ;
  - la compilation prend environ 2 minutes sur la machine de référence (mesuré le 2026-10-24) ;
  - l'assembleur tout-en-un d'OpenCV (`cv2.Stitcher`) produit une image recadrée à une échelle quelconque, pas un panorama 2:1 complet avec l'horizon au milieu. Avec notre rendu, la première photo regarde la longitude 0 et le résultat se compare pixel à pixel à un panorama de synthèse dans les tests.
- **Remplace :** la partie de D7 qui prévoyait le paquet `opencv-python-headless`, et la version minimale de D17 (4.10 reste le minimum vérifié par `doctor`).
- **Conséquence :** il faut recompiler OpenCV sur chaque nouvelle machine, et pour chaque version de Python. Les tests GitHub le font aussi, avec un cache.

## D20 : organisation d'un point de la visite et résolution du panorama

- **Date :** 2026-10-24
- **Décision :**
  - un point vit dans `visites/<visite>/<point>/` : photos d'origine dans `photos/`, conversions HEIC dans `cache/`, puis `panorama.jpg` et `rapport.json` ;
  - panorama de 8192 × 4096 pixels par défaut, modifiable avec `--largeur` ;
  - les trous qui touchent le sol ou le plafond et restent à moins de 45° du pôle sont bouchés par un flou. Les autres restent en gris. Tous sont décrits dans le rapport.
- **Raisons :** 8192 pixels de large suffisent pour une visite web et restent lisibles par les visionneuses sur téléphone. Les photos permettraient environ 20 000 pixels. Le flou sous le photographe est accepté à ce stade (PLAN.md, étape 2). Un grand trou flouté ferait croire à une vraie surface, d'où le gris.

## D21 : ajustement des photos par notre code, raccords placés par coupe minimale

- **Date :** 2026-10-24
- **Décision :**
  - l'orientation des photos et la focale sont ajustées par notre code (`src/visite360/adjust.py`) et non plus par l'ajusteur d'OpenCV. Une seule focale pour toutes les photos, écarts mesurés en pixels, poids réduit pour les correspondances aberrantes, puis mise à l'écart des paires de photos incohérentes. OpenCV reste utilisé pour les points caractéristiques, l'appariement et la correction de l'horizon ;
  - le point de départ est calculé paire par paire (rotation qui superpose au mieux les points communs), en enchaînant les paires les plus riches ;
  - les raccords sont placés par la coupe minimale d'OpenCV (`GraphCutSeamFinder`) sur un panorama réduit : ils passent là où les photos voisines se ressemblent.
- **Raisons :** sur le premier vrai jeu de photos (chambre, 33 photos à main levée), l'ajusteur d'OpenCV échouait ou donnait des focales de 113 à 787 pixels pour un même objectif. La parallaxe des objets proches produit des correspondances qu'aucune rotation n'explique, et ces correspondances faisaient diverger le calcul. Avec notre ajustement, la focale trouvée (640 pixels à l'échelle de travail) correspond aux 26 mm annoncés par l'iPhone 15, et la moitié des paires s'aligne à moins de 2,6 pixels près.
- **Remplace :** la partie « ajustement » de D19.
- **Limite :** la parallaxe elle-même ne se corrige pas. Les raccords l'évitent quand ils le peuvent. Un objet proche vu de deux positions différentes peut rester dédoublé.

## D22 : feuille de route par versions, tout en local jusqu'à la v1

- **Date :** 2026-10-24
- **Décision :**
  - le plan est découpé en versions : v0.1 prise et consultation d'une visite avec une app de capture, v0.2 modification par génération d'images, v0.3 chiffrage, v1 partage par lien et retours d'engagement pour l'agent ;
  - jusqu'à la v1, tout fonctionne en local : traitement et visite sur le Mac, transfert depuis l'app sans service payant. Hébergement, serveur, lien de partage et comptes arrivent en v1 ;
  - les présentations avant la v1 se font en local. Aucun utilisateur extérieur n'a accès au produit avant la v1 ;
  - en v0.2, on génère au maximum sans coût : recoloration calculée (D11) pour la peinture, modèle d'IA qui tourne sur le Mac pour le reste. Le coût d'une API payante est estimé, pas engagé ;
  - suivi de position par réalité augmentée, modèle 3D commun, propagation d'une modification entre panoramas et suppression de cloison sortent du plan.
- **Raisons :** feuille de route fixée par le propriétaire avant les premières présentations. Le partage impose des coûts d'hébergement qu'on ne veut payer qu'au déploiement.
- **Remplace :** D12. L'app de capture passe avant la démo aux agents, puisque la démo de la v0.1 se fait avec elle. Le jalon A devient le jalon v0.1.
- **Modifie :**
  - D14 : la mesure du déplacement par le téléphone est reportée hors plan. L'app de l'étape 6 déclare les liens à la main ;
  - D15 : l'app mobile arrive dans `app/` à l'étape 5.
- **Conséquences :**
  - un modèle de génération d'image local doit avoir code, poids et données d'entraînement sous licence autorisée et tenir dans les 24 Go du Mac (D3, D5). Si aucun ne convient, le propriétaire décide d'une API payante ;
  - le chiffrage a besoin de surfaces en m², donc des dimensions des pièces (D13) et d'une mesure réelle pour l'échelle.

## D23 : serveur de visite en bibliothèque standard, copie réduite pour téléphone

- **Date :** 2026-10-24
- **Décision :** `visite360 serve` utilise le serveur HTTP de la bibliothèque standard Python (aucune dépendance), avec une liste fermée de chemins servis. Le panorama d'origine est servi tel quel ; une copie de 4096 px de large est fabriquée dans `cache/` pour les appareils dont la carte graphique n'accepte pas 8192 px, et la page choisit selon la limite de l'appareil.
- **Raisons :** pas de dépendance (D16), pas d'exposition du reste du disque, panorama d'origine jamais réécrit (D9). Beaucoup de téléphones limitent les images à 4096 px.
- **Ajout :** si le panorama manque (ou avec `--force`), `serve` l'assemble dans un fil d'exécution en arrière-plan avec `stitch.stitch` et expose l'avancement (`/status.json`) à la page, qui l'interroge chaque seconde. L'avancement est déduit des messages de `stitch`, donc approximatif : l'alignement des photos n'a pas de message intermédiaire.
- **Conséquence :** la visite est accessible à tout appareil du même Wi-Fi tant que le serveur tourne ; `--local` la réserve au Mac (D22).
