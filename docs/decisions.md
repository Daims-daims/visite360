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
- **Étape 4 (2026-10-24) :** les liens entre points passent par les scènes de Pannellum (`hotSpots` de type `scene`) et fonctionnent dans un navigateur de bureau. Reste à valider par le propriétaire le parcours sur son appartement, sur ordinateur et téléphone.
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

## D24 : `visite.json` en clés françaises, liens à la main, panoramas servis par numéro

- **Date :** 2026-10-24
- **Décision :** une visite de plusieurs points est décrite par `visite.json` (format dans `docs/visite-json.md`), validé strictement : clé inconnue, lien vers un point inexistant ou angle invalide arrêtent la commande avec un message en français. S'il manque, `serve` le crée avec un point par dossier et aucun lien, et ne réécrit jamais un fichier existant. Les angles sont ceux de Pannellum (0° au centre de l'image, positif vers la droite). La visionneuse affiche l'angle regardé et celui du dernier clic pour les lire sans calcul. Les panoramas sont servis sous `/p/<numéro du point>/`.
- **Raisons :** D14 (liens à la main jusqu'à l'app, étape 6). Un fichier que l'utilisateur édite doit signaler une faute de frappe plutôt que l'ignorer. Un numéro dans l'URL évite d'exposer ou d'encoder des noms de dossier arbitraires et garde la liste de chemins servis fermée (D23).
- **Prévu pour l'étape 6 :** les champs facultatifs `nord` et `position` sont déjà lus et vérifiés, pour que l'app puisse les remplir et que les liens se calculent sans saisie manuelle.
- **Conséquence :** la visite n'est affichée que quand tous les panoramas existent. Les points sont assemblés l'un après l'autre.

## D25 : app native en SwiftUI, installée par câble, orientations des capteurs pour l'assemblage

- **Date :** 2026-10-24
- **Décision :**
  - téléphone de référence : iPhone 15 du propriétaire ;
  - l'app de capture est une app iPhone native en SwiftUI, dans `app/`, sans bibliothèque extérieure : caméra par AVFoundation, orientation par Core Motion ;
  - installation par câble depuis Xcode avec l'identifiant Apple du propriétaire, sans compte développeur payant ;
  - l'orientation de chaque photo vient du gyroscope et de l'accéléromètre (référence Core Motion « X arbitraire, Z vertical »), sans la boussole. Elle est écrite dans `capture.json` (format dans `docs/capture-json.md`), dans le repère de l'assemblage ;
  - `visite360 stitch` s'en sert si chaque photo a la sienne : point de départ de l'ajustement, recherche de points communs limitée aux photos dont les axes sont à moins de 90°, horizon donné par les capteurs au lieu de la correction d'horizon d'OpenCV. Si l'écart médian entre capteurs et photos dépasse 10°, ou si l'alignement échoue avec eux, ils sont ignorés et l'assemblage se fait comme sans app. Le rapport dit lequel a servi ;
  - quand les capteurs sont retenus, une photo sans assez de points communs n'est plus rejetée : elle est placée à l'orientation mesurée par le téléphone, corrigée de la dérive du gyroscope constatée sur les photos prises juste avant et juste après. Premier essai réel (salon, 2026-10-24) : 7 photos sur 30, du haut et du plafond blancs, étaient rejetées et le plafond restait gris. Les capteurs y dérivaient de 3 à 10° par rapport aux photos au fil de la prise de vue : sans correction, les photos placées étaient décalées d'autant ;
  - avec ou sans app, les paires de photos incohérentes s'écartent en plusieurs passes, jusqu'à ce qu'il n'en reste plus (au plus 4) : sur le salon, une paire décalée de 6° restait après la première passe ;
  - avec ou sans app, les photos de l'horizon (axe à moins de 20° de l'horizon) sont prioritaires : dans la zone qu'elles voient à plus de 12 % de leurs bords, les photos des autres rangées ne sont pas candidates. Les raccords entre rangées passent ainsi plus haut et plus bas, là où le regard se pose moins (demande du propriétaire) ;
  - l'app propose les deux objectifs, ×0,5 par défaut : 21 photos (8 à l'horizon, 6 en haut et 6 en bas inclinées à 50°, le plafond) au lieu de 29 au ×1. Sur le salon, au ×1, les objets à un mètre de l'objectif (frigo, table, radiateur) étaient coupés par les raccords entre rangées ; les essais à la main du propriétaire donnaient de meilleurs résultats au ×0,5. La correction de déformation d'iOS est activée pour le grand-angle ;
  - les raccords se cherchent sur un panorama réduit de 1536 pixels de large au lieu de 512, et la fusion des raccords est 4 fois plus étroite (`BLEND_STRENGTH` 0,012 au lieu de 0,05). Sur le salon, le bord fantôme de la télé et une tête de guitare en double disparaissent, pour environ 1 min 20 de calcul en plus par point ;
  - la géométrie de l'app est en Swift pur et se teste sur le Mac par `swift test` (`app/Package.swift`).
- **Raisons :**
  - le propriétaire a un iPhone. Une app native accède directement à la caméra et aux capteurs, sans module natif à écrire en plus comme avec Expo, et sans paquet npm dont il faudrait vérifier la licence ;
  - l'installation gratuite évite le coût annuel du compte développeur, au prix d'une réinstallation tous les 7 jours ;
  - la boussole est perturbée par le métal et les appareils électriques d'un logement. Le gyroscope dérive peu sur les 2 à 3 minutes d'un point, et l'ajustement par les photos corrige ce qui reste ;
  - l'app ne voit pas sa position, seulement son orientation : elle ne corrige pas la parallaxe. Elle supprime les erreurs de départ de l'alignement (paires de photos confondues, motifs répétés) et garantit le recouvrement des photos ;
  - le contrôle par les photos protège d'une erreur de convention dans l'app, qu'on ne peut pas vérifier sans téléphone. L'app compare aussi la gravité mesurée à l'orientation calculée pour détecter une matrice transposée.
- **Modifie :** D15, l'app est en Swift. Garder un seul dépôt reste à confirmer.
- **Conséquences :**
  - l'app ne fonctionne que sur iPhone. Une version Android demanderait un second développement ;
  - un point se prend d'une traite : le cap 0 des capteurs change à chaque démarrage ;
  - les tests GitHub ne compilent pas l'app (ils tournent sous Linux). `swift test` et la compilation se lancent sur le Mac.

## D26 : visite prise dans l'app, flèches visées sur place, envoi au Mac par le Wi-Fi local

- **Date :** 2026-10-24
- **Décision :**
  - l'app range les points dans des visites, sur le téléphone comme sur le Mac : `Documents/<visite>/<point>/`. Elle tient à jour `visite.json` au format du Mac (points pris et flèches entre eux), et garde son état complet dans `visite-app.json`, qui contient en plus les pièces annoncées par une flèche mais pas encore prises ;
  - les flèches se visent dans l'app à la fin de la prise de vue d'un point, téléphone toujours à sa place : on vise la porte, puis on choisit la pièce d'arrivée. L'angle est l'écart entre le cap visé et le cap de départ du point, la hauteur est l'inclinaison du téléphone ;
  - l'app note ce cap de départ dans `capture.json` (`cap_depart`). Quand les orientations du téléphone servent à l'assemblage, le centre du panorama est ce cap, et non plus la première photo retenue ;
  - pas de réalité augmentée : la position des points (`position`, `nord`) n'est pas mesurée, et les flèches ne se calculent pas toutes seules (D22) ;
  - le transfert se fait par le Wi-Fi local : `visite360 receive` sur le Mac (serveur HTTP de la bibliothèque standard, port 8361), annoncé par Bonjour avec `dns-sd`, programme fourni avec macOS. L'app le trouve avec le framework Network d'iOS ;
  - un code à 6 chiffres, affiché par le Mac et nouveau à chaque lancement, est exigé pour tout échange. 10 codes faux bloquent la réception jusqu'au relancement ;
  - chaque fichier est vérifié par sa taille et son empreinte SHA-256. Les fichiers passent par un dossier caché et ne sont rangés que si l'envoi est complet et si `visite.json` et les `capture.json` sont valides. Un renvoi ne transfère que ce qui manque ;
  - sur le Mac, une photo ou un `capture.json` existant n'est jamais réécrit : un point du même nom avec d'autres photos fait refuser l'envoi. `visite.json` est remplacé, l'ancien est gardé sous `visite-avant-<date>.json` ;
  - AirDrop et le câble restent possibles en secours : le dossier de la visite est utilisable tel quel sur le Mac.
- **Raisons :**
  - une visée sur place ne demande ni calcul ni saisie d'angle. Elle utilise l'orientation que l'app mesure déjà, dans le même repère que les photos, tant que le point n'est pas terminé ;
  - centrer sur la première photo retenue aurait décalé toutes les flèches d'un point dont la première photo est écartée par l'assemblage. Le cap de départ, lui, ne dépend pas des photos ;
  - le Wi-Fi évite le câble et la décompression d'un ZIP, qui demandent de manipuler des fichiers, ce que le critère de validation de l'étape exclut. Aucun service en ligne ni compte (D22). Bonjour évite de recopier une adresse ;
  - sans code, n'importe quel appareil du même Wi-Fi pourrait déposer des fichiers sur le Mac. La vérification par empreinte détecte un fichier tronqué par une coupure du Wi-Fi ;
  - le serveur et l'annonce n'ajoutent aucune dépendance (D16), et `dns-sd` est un programme externe appelé sans shell, comme `sips` (D17).
- **Modifie :** D14 et D24 : `nord` et `position` restent lus et vérifiés mais ne seront pas remplis par l'app dans le plan actuel. D25 : le centre du panorama est le cap de départ quand `capture.json` le donne.
- **Limites :**
  - l'échange n'est pas chiffré : à n'utiliser que sur un Wi-Fi de confiance, ce qui est le cas jusqu'à la v1 ;
  - une flèche visée au jugé tombe à quelques degrés près. Si l'assemblage ignore les orientations du téléphone (écart de plus de 10°), le centre redevient la première photo et les flèches de ce point peuvent être décalées ;
  - une flèche ne se vise que pendant la prise de vue du point. Pour la refaire, reprendre le point ou corriger `visite.json` sur le Mac.

## D27 : réglage « ×1 + AR » qui suit la position de l'objectif

- **Date :** 2026-10-24
- **Décision :**
  - l'app propose un troisième réglage, « ×1 + AR », à côté de ×0,5 et ×1. ARKit (réalité augmentée d'Apple) pilote la caméra pendant tout le point, prend les photos en pleine résolution et mesure la position de l'objectif ;
  - la place de départ est la position de l'objectif au verrouillage. Au-delà de 5 cm de déplacement, l'écran passe au rouge, le téléphone vibre et la photo ne part pas. L'alerte s'efface sous 3,5 cm ;
  - un guide de placement montre en permanence, vu de dessus et dans le sens où vise le photographe, où est l'objectif par rapport à sa place, avec une jauge de hauteur et une consigne en centimètres (« ramenez le téléphone vers vous de 5 cm ») ;
  - l'orientation des photos vient toujours de Core Motion, comme dans les autres réglages (D25). ARKit ne fournit que la position ;
  - le déplacement de chaque photo est noté dans `capture.json` (`suivi_position`, `deplacement_m`), sans être utilisé par l'assemblage.
- **Raisons :**
  - demande du propriétaire, qui veut prévenir la parallaxe pendant la prise de vue. ARKit mesure la position en croisant caméra et capteurs : c'est plus fiable qu'une estimation tirée des seuls capteurs de mouvement, envisagée puis écartée pour ce motif ;
  - garder l'orientation de Core Motion évite de revérifier sans téléphone les conventions de repère d'ARKit. Une distance, elle, ne dépend pas du repère ;
  - premiers essais du propriétaire (2026-10-24) : raccords bien meilleurs au « ×1 + AR » qu'aux autres réglages. L'alerte à 5 cm bloquait souvent sans dire où aller : le guide de placement a été ajouté. Le seuil a été passé un temps à 8 cm, puis ramené à 5 cm par le propriétaire, le guide permettant de revenir facilement à sa place (environ 3° d'écart pour un objet à 1 m) ;
  - un réglage « ×0,5 + capteurs » a aussi été essayé : gyroscope et accéléromètre estimaient la distance entre le téléphone et l'axe de rotation. Mesure instable et raccords moyens à l'essai : il est retiré. Son code reste dans l'historique git (commit fe3acfa) pour une amélioration ultérieure.
- **Limites :**
  - ARKit garde la caméra pour lui et n'utilise que l'objectif ×1 : pas de suivi au ×0,5 ;
  - sans repères visuels (démarrage, mur uni), ARKit ne suit pas la position et les photos partent sans contrôle ;
  - les photos d'ARKit ne passent pas par la chaîne photo habituelle d'iOS : rendu et netteté à comparer avec le ×1 normal.
- **Décision du propriétaire (2026-10-24) :** « ×1 + AR » devient le réglage conseillé et le réglage par défaut de l'app. ×1 et ×0,5 restent proposés, sans suivi.
- **Modifie :** D25, où le ×0,5 était le réglage par défaut.


## D28 : démo aux agents repoussée après la v1

- **Date :** 2026-10-25
- **Décision :**
  - la démo aux agents immobiliers prévue au jalon v0.1 est repoussée à la fin du plan, après la réalisation de la v1. Elle ouvre le jalon v1, avant les premiers accès ;
  - les jalons v0.1, v0.2 et v0.3 deviennent des validations par le propriétaire seul. Chacun reste une décision écrite dans `PLAN.md` avant de passer à la version suivante ;
  - le jalon v0.1 est validé : on poursuit avec la v0.2.
- **Raisons :** décision du propriétaire, qui préfère montrer aux agents un produit complet : visite partagée par lien, modifications, chiffrage et retours d'engagement.
- **Modifie :** D22, où les présentations aux agents se faisaient en local avant la v1. Tout reste en local jusqu'à la v1 et aucun utilisateur extérieur n'a accès au produit avant.
- **Conséquences :**
  - aucun retour d'agent avant la v1 : les choix des versions v0.2 à v1 se font sans avis extérieur, au risque de développer des fonctions qui ne les intéressent pas ;
  - le passage à la v1, qui engage les premiers coûts d'hébergement (D22), se décide au jalon v0.3 sans retour d'agent ;
  - `docs/retours-agents.md` sera créé au jalon v1.

## D29 : sélection au clic avec SAM 2.1 small, dans la vue regardée

- **Date :** 2026-10-25
- **Décision :**
  - le modèle de sélection est SAM 2.1 small (`sam2.1_hiera_small`), sur la puce graphique du Mac par PyTorch (MPS). Il est facultatif : `scripts/installer-sam2.sh` installe PyTorch et SAM 2 à des versions fixées, puis télécharge les poids et vérifie leur empreinte SHA-256. Les poids sont rangés hors du dépôt, dans `~/.cache/visite360/modeles/` ;
  - la sélection se fait dans la visionneuse servie par `visite360 serve`, pas dans une page dédiée. La vue regardée est figée, le serveur en découpe une image carrée de 1024 pixels (champ de vision de l'écran, 120° au plus), SAM 2.1 y cherche le contour, et la page pose ce contour par-dessus la visionneuse ;
  - clics « en plus » et « en moins » pour corriger. Le masque est nettoyé : seuls les morceaux qui contiennent un clic « en plus » sont gardés, et les trous de moins de 0,05 % de la vue sont bouchés ;
  - une sélection validée est reportée dans le panorama et enregistrée comme opération dans `<point>/modifications/` : masque PNG à la taille du panorama, fiche JSON avec la vue, les clics, le modèle et l'empreinte du panorama (format dans `docs/selection.md`). Le panorama d'origine n'est jamais modifié (D9) ;
  - nouvelles licences autorisées par le propriétaire, pour les dépendances de SAM 2 : MIT-CMU (Pillow), PSF 2.0 (typing_extensions), Boost BSL-1.0 (une partie de PyTorch) et MPL 2.0 pour une bibliothèque utilisée sans modifier ses fichiers (tqdm).
- **Raisons :**
  - essai du 2026-10-25 sur 6 vues des panoramas du propriétaire : MobileSAM, SAM 2.1 tiny et SAM 2.1 small sont tous quasi instantanés (0,1 à 0,25 s par vue, 0,015 s par clic). SAM 2.1 small donne les contours les plus justes avec un seul clic (mur avec affiches, parquet, plafond). Choix du propriétaire ;
  - MobileSAM est écarté : ses poids sont entraînés par un tiers sur des images réservées à la recherche (SA-1B), le même cas que ZInD ;
  - sélectionner dans la vue regardée évite de choisir une taille de découpe : on sélectionne ce qu'on voit. La visionneuse est figée pour que le contour reste à sa place à l'écran ;
  - le nettoyage efface la frange de petits points que SAM 2 laisse au bord des surfaces texturées, observée pendant l'essai ;
  - le masque à la taille du panorama sert directement aux étapes 8 et 9. Les clics et la vue suffisent à recalculer une sélection.
- **Modifie :** D10, dont la vitesse et la taille de modèle restaient à confirmer.
- **Limites :**
  - une sélection ne couvre que la vue de l'écran : un mur plus large se sélectionne en reculant la vue ;
  - un mur à motifs demande plusieurs clics « en plus » ;
  - sur une zone floue du panorama, le contour est mauvais : la cause est l'assemblage ;
  - les routes de sélection du serveur acceptent les requêtes de tout appareil du Wi-Fi, comme la visite elle-même. Elles n'écrivent que dans `modifications/` et `cache/`, avec des noms choisis par le serveur. À revoir avant tout hébergement (v1).

## D30 : recoloration en lumière linéaire sur un contour recalé, panorama modifié fabriqué à la demande

- **Date :** 2026-10-25
- **Décision :**
  - le contour de la sélection est d'abord recalé sur les bords de la photo par un filtre guidé (He, Sun et Tang, 2010), guidé par la clarté du panorama, dans un rayon de 1,4° (32 pixels sur 8192). Le masque enregistré à l'étape 7 n'est pas modifié ; le recalage est refait à chaque calcul ;
  - la couleur est changée en lumière linéaire (norme sRGB) : chaque canal de chaque pixel est divisé par la couleur de peinture actuelle de la surface, puis multiplié par la couleur de peinture choisie. Le changement s'adoucit sur deux pixels à l'intérieur du contour recalé ;
  - la couleur choisie est celle du pot de peinture. La couleur actuelle est blanche (`#f4f4f0`) par défaut ; on peut en donner une autre, ou « comme sur la photo » (médiane de la surface, canal par canal), où la couleur choisie devient celle qu'aura le mur sur la photo. Elle est gardée dans la fiche (`couleur_actuelle`) ;
  - une recoloration est une fiche `couleur-<n>.json` dans `<point>/modifications/`, qui désigne une sélection de l'étape 7 et une couleur `#rrggbb` (format dans `docs/couleur.md`). Une sélection a au plus une couleur : la repeindre remplace sa fiche, qui garde son numéro. Les fiches s'appliquent par numéro croissant. Supprimer une sélection supprime sa fiche ;
  - le panorama modifié, toutes recolorations du point appliquées, est fabriqué à la demande dans `cache/apres.jpg`, avec sa copie pour téléphone. Une empreinte des fiches, des masques et du panorama (taille et date de chaque fichier) dit s'il est à jour ;
  - un nuancier de 24 teintes murales en six familles, dans `visionneuse/nuancier.json`, modifiable à la main, avec une case « sur mesure » pour une couleur libre. Le nom de la teinte est gardé dans la fiche (`teinte`), pour le chiffrage de l'étape 11. Noms et valeurs propres au projet : aucune donnée de fabricant, donc aucune licence à vérifier ;
  - dans la visionneuse : « Repeindre » dans la liste des sélections, avec un aperçu du panorama réduit à 4096 pixels qui n'enregistre rien ; la visite s'ouvre sur le panorama modifié, et un bouton bascule entre avant et après ;
  - aucune nouvelle dépendance : NumPy et OpenCV, déjà présents.
- **Raisons :**
  - un premier essai calculait dans l'espace Lab : clarté multipliée par un facteur, teinte remplacée avec 30 % des écarts d'origine. Sur un mur du propriétaire (mur blanc repeint en ocre, à côté d'une porte blanche), le résultat a été jugé très mauvais. Deux causes : le contour de l'étape 7 s'écartait de 10 à 30 pixels des vrais bords, en marches d'escalier, car la sélection était faite à 120° de champ sur 1024 pixels, soit près de trois fois moins fin que le panorama ; et la couleur paraissait plate ;
  - le recalage par filtre guidé redresse le bord de la porte et l'angle avec le plafond sur ce même mur, en un dixième de seconde, sans nouvelle dépendance. Il se fait au moment de peindre, pour servir aussi aux sélections déjà enregistrées ;
  - en lumière linéaire, « couleur du mur × éclairage » est le modèle physique d'un mur mat : diviser puis multiplier garde exactement les ombres, la lueur d'une lampe et sa teinte. Sur le même mur, le relief de la lumière y est nettement plus visible qu'avec Lab ;
  - la couleur du pot plutôt que la couleur sur la photo, à la demande du propriétaire : un mur blanc photographié en intérieur paraît gris-beige (`#cac1b6` sur le mur de la cuisine de `appart-x1`). Dans le premier calcul, qui divisait par cette couleur, « Bleu gris » donnait un bleu ciel bien plus clair que la pastille, et « Blanc pur » éclaircissait un mur déjà blanc. Avec la couleur actuelle « blanc », « Blanc pur » ne change rien et « Bleu gris » donne un gris-bleu crédible ;
  - en mode « comme sur la photo », la médiane plutôt que la moyenne : une affiche oubliée dans la sélection ou un reflet de fenêtre ne déplace pas la couleur obtenue ;
  - un nuancier plutôt qu'un sélecteur seul, à la demande du propriétaire : un sélecteur libre pousse vers des couleurs très saturées (l'ocre du premier essai) que peu de peintures murales atteignent ;
  - une couleur par sélection évite d'empiler des couches invisibles sur la même surface ; l'annulation est la suppression d'une fiche, et le panorama modifié se refait sans elle (D9).
- **Limites :**
  - une couleur actuelle mal donnée décale tout le résultat (un mur crème déclaré blanc ressort trop jaune) ;
  - le recalage peut changer des pixels jusqu'à 1,4° hors de la sélection, pour atteindre un bord réel ; au-delà, aucun pixel ne change. Il ne corrige pas une grosse erreur de sélection (une bande de porte prise pour du mur) ;
  - passer d'une surface foncée à une couleur claire agrandit beaucoup la clarté : grain visible, reflets qui saturent en blanc (D11) ;
  - les zones du mur déjà presque blanches sur la photo (reflet, surexposition) ont perdu leur information : repeintes, elles restent claires ;
  - la couleur choisie à l'écran dépend de l'éclairage de la photo. Ce n'est pas une référence de peinture ;
  - un mur visible depuis plusieurs points se repeint dans chaque point ;
  - comme les routes de sélection (D29), les routes de couleur acceptent les requêtes de tout appareil du Wi-Fi et n'écrivent que dans `modifications/` et `cache/`, avec des noms choisis par le serveur. À revoir avant tout hébergement (v1).

## D31 : remplacement d'un objet par FLUX.2 klein 4B sur le Mac, dans un cadre tracé

- **Date :** 2026-10-25
- **Décision :**
  - le modèle de génération est FLUX.2 [klein] 4B de Black Forest Labs (code et poids sous Apache 2.0), à la révision `e7b7dc2` de Hugging Face, en 4 passes, sur une vue de 1024 pixels. Il tourne sur la puce graphique du Mac par mflux 0.23.0 (MIT), installé par `scripts/installer-generation.sh` dans un environnement Python à part (`~/.cache/visite360/generation/`), sans résolution automatique des dépendances, et appelé en ligne de commande, jamais importé. Les poids (15 Go) sont rangés dans `~/.cache/visite360/modeles/` et leurs empreintes vérifiées à l'installation ;
  - le propriétaire accepte par écrit que les données d'entraînement du modèle ne soient pas publiées : code et poids sont sous Apache 2.0, les données ne sont pas déclarées réservées à la recherche, mais elles sont inconnues. Il ajoute la licence CNRI Python 1.6 à la liste autorisée, pour le paquet regex utilisé sans modification ;
  - l'exemple de l'étape est le **remplacement d'un meuble**, à la place du revêtement de sol, à la demande du propriétaire, qui juge la sélection de surface de l'étape 7 peu probante ;
  - la zone modifiée est un **cadre tracé** dans la vue regardée, et non le masque de l'étape 7 comme le prévoyait le plan : un nouveau meuble n'a pas la forme de l'ancien. Le serveur découpe une vue centrée sur le cadre, qui en occupe le milieu avec 20 % de marge de chaque côté. Le modèle refait toute la vue d'après l'instruction écrite librement en français par l'utilisateur (« Remplace … par … », « Retire … », « Ajoute … »), suivie d'une phrase fixe qui limite le changement au centre de l'image, et seul l'intérieur du cadre est gardé : couleurs recalées dans une bande de 40 pixels autour du cadre, bord adouci sur 24 pixels vers l'intérieur, report dans le panorama. Hors du cadre, aucun pixel ne change ;
  - une génération est une fiche `generation-<n>.json` et l'image générée `generation-<n>.png` dans `<point>/modifications/` (format dans `docs/generation.md`). Le report est refait sans relancer le modèle. La vue est prise dans le panorama modifié du moment ; les générations s'appliquent après les recolorations, par numéro croissant. « Refaire » relance la même demande avec une autre graine et garde le numéro ;
  - dans `visite360 serve`, une seule génération à la fois, dans un fil à part, avec l'avancement passe par passe. SAM 2 est libéré de la mémoire avant chaque génération ;
  - une génération où l'intérieur du cadre n'a pas changé de plus de 5 (sur 255, en moyenne) au-delà du reste de la vue n'est pas enregistrée, et la visionneuse dit de reformuler.
- **Raisons :**
  - essai du 2026-10-25 sur 11 meubles des visites du propriétaire : 9 nettement réussis (bibliothèque, chaise, buffet, vitrine, meuble télé, canapé, fauteuil, lit, chaise de bureau). Les objets posés dessus ou devant sont souvent conservés. Moins bons : une table encombrée (un chat et des objets ont disparu) et des façades de cuisine (hotte modifiée, colonne oubliée) ;
  - klein 4B est le plus petit modèle d'édition d'image sous licence autorisée connu, et le seul à l'aise dans les 24 Go du Mac : 16,6 Go au plus haut. Qwen-Image-Edit-2511 (Apache 2.0, données non publiées aussi) fait 20 milliards de paramètres ; la comparaison a été abandonnée par le propriétaire pour ne pas télécharger 29 à 58 Go de plus. Les autres candidats sont non commerciaux (FLUX.2 klein 9B, FLUX.2 dev, FLUX.1 Fill), sous OpenRAIL (Stable Diffusion) ou entraînés sur des données de recherche (LaMa) ;
  - temps mesurés : 123 à 174 s par génération, le Mac sans ventilateur ralentissant sur une série. Le propriétaire ne cherche pas à réduire ce temps en local : il le sera sur du matériel loué (D32) ;
  - un environnement à part évite trois conflits : Pillow 13.0, utilisé par SAM 2, ne s'importe pas avec mflux sous Python 3.13 ; mflux déclare opencv-python, qui embarque FFmpeg (interdit, D19) et masquerait l'OpenCV du projet ; il déclare aussi matplotlib, sous une licence propre. Ni opencv-python, ni matplotlib, ni PyTorch ne servent à l'édition par klein : ils ne sont pas installés ;
  - le cadre au milieu d'une vue plus large montre au modèle la lumière et la perspective de la pièce, et garde tout le meuble dans l'image. Un premier essai, avec une vue qui coupait le canapé, avait laissé l'accoudoir hors champ inchangé ;
  - le recalage des couleurs corrige le léger décalage de teinte et de contraste que le modèle donne à toute l'image : sur le canapé et la bibliothèque, le bord du cadre est invisible ;
  - une instruction libre plutôt que deux champs « objet » et « par quoi » : aux premiers essais du propriétaire, deux générations sur trois n'ont rien changé. « Met un four » à la place d'un « vide » donnait au modèle une phrase bancale ; un retrait dont la consigne disait « ne change pas les autres meubles » était ignoré. Avec une instruction complète (« Supprime complètement le meuble blanc… »), le même retrait réussit, en français comme en anglais. L'écart mesuré sépare nettement les essais : 0,4 et 1,3 pour les ratés, 14 et plus pour les réussis ;
  - garder l'image générée rend le panorama modifié reproductible et rapide à refaire, sans dépendre du hasard du modèle (D9).
- **Modifie :** l'étape 9 du plan, qui prévoyait une génération limitée au masque de l'étape 7.
- **Limites :**
  - le résultat est inventé : il donne une idée, pas un meuble réel ;
  - la vue de 1024 pixels est moins fine que le panorama (environ 15 pixels par degré contre 23) : un meuble petit à l'écran ressort flou ;
  - un cadre trop serré laisse dépasser l'ancien meuble ; un cadre qui coupe un objet ou une ombre laisse un trait au bord ;
  - une recoloration ajoutée après une génération n'apparaît pas à l'intérieur de son cadre : refaire la génération ;
  - un objet visible depuis plusieurs points se remplace dans chaque point, avec un résultat différent ;
  - comme les autres routes de la visionneuse (D29, D30), les routes de génération acceptent les requêtes de tout appareil du Wi-Fi et n'écrivent que dans `modifications/` et `cache/`, avec des noms choisis par le serveur. À revoir avant tout hébergement (v1), avec les filtres de contenu conseillés par Black Forest Labs pour un service ouvert au public.

## D32 : génération sur du matériel loué en v1, pas par une API de génération

- **Date :** 2026-10-25
- **Décision :** à partir de la v1 (étape 13), la génération d'image tourne sur une carte graphique louée par le projet, avec le modèle retenu à l'étape 9. On n'envoie pas les images à l'API de Black Forest Labs ni à un autre service de génération. Le temps d'allumage du matériel loué (chargement du modèle à froid) sera optimisé à l'étape 13.
- **Raisons :**
  - la confidentialité des images, jugée trop importante par le propriétaire : les vues envoyées au modèle montrent l'intérieur des logements des clients des agents. Avec une API, chaque vue part chez un prestataire, avec un contrat de sous-traitance à prévoir (RGPD) et une conservation qu'on ne maîtrise pas. Sur du matériel loué, les images ne sortent pas du serveur du projet ;
  - à matériel équivalent, la vitesse est la même : quelques secondes par image sur une carte NVIDIA récente, contre environ 2 minutes sur le MacBook Air M4 (estimation, non mesurée) ;
  - le modèle de l'étape 9 est gratuit à héberger soi-même (poids sous Apache 2.0) : le coût est celui de la location, pas du modèle.
- **Conséquences :**
  - le coût de génération devient un coût fixe à l'heure de location, au lieu d'environ 0,014 $ par image par l'API. En dessous de quelques dizaines de milliers d'images par mois, une carte louée en permanence coûte plus cher que l'API : une location à la seconde, éteinte quand personne ne génère, réduit l'écart au prix de démarrages à froid ;
  - mflux ne tourne que sur Mac : sur une carte NVIDIA, le modèle passera par un autre logiciel (diffusers, Apache 2.0, à vérifier dans `docs/licences.md` le moment venu). Le découpage de la vue, le report dans le panorama et les fiches ne changent pas.

## D33 : essai de cloison abattue repoussé après l'étape 13

- **Date :** 2026-10-25
- **Décision :** l'essai de l'étape 9.5 (montrer la pièce voisine à la place d'une cloison) quitte la v0.2. Il se fera après l'étape 13, quand la génération tournera sur la carte graphique louée (D32). Son contenu et sa validation ne changent pas.
- **Raisons :** décision du propriétaire. Une génération prend 2 à 3 minutes sur le Mac, sans doute plus avec une deuxième image en référence. Sur une carte graphique, quelques secondes suffisent : on enchaîne les essais d'instruction et de vue de référence bien plus vite.
- **Conséquences :**
  - la v0.2 se termine sans cet essai. Le jalon v0.2 n'en dépend pas : la modification générée qu'il demande est celle de l'étape 9 ;
  - la décision de faire de la cloison abattue une vraie étape arrive après la v1 commencée, donc après la préparation des versions v0.3 et v1 ;
  - l'essai se fera avec le logiciel retenu à l'étape 13 pour la carte graphique, et non avec mflux (D32).

## D34 : dimensions des pièces, échelle mesurée par ARKit, coins pointés par l'agent

- **Date :** 2026-10-25
- **Décision :**
  - l'échelle vient de la **hauteur de l'objectif au-dessus du sol**, mesurée par ARKit pendant la prise de vue « ×1 + AR » (D27), et non d'une mesure saisie. La séance ARKit détecte aussi les surfaces horizontales ; le sol est la plus basse sous l'objectif, d'au moins 0,25 m², parmi celles qu'ARKit classe comme sol quand il sait classer. L'app note sa dernière estimation dans `capture.json` (`hauteur_objectif_m`) à chaque photo, et l'affiche sous le guide de placement ;
  - les coins se pointent **après l'assemblage, par l'agent**, dans un mode de la visionneuse servi à l'adresse `/agent`. La visite à l'adresse habituelle, celle du client, n'a pas ce bouton. Jusqu'à la v1, l'adresse sépare les usages sans rien protéger ;
  - l'agent clique les coins dans l'ordre du tour de la pièce, au sol, ou au plafond quand un meuble cache le bas, et au moins un coin aux deux, qui donne la hauteur sous plafond. Un clic à moins de 4° de cap du clic de l'autre niveau du coin précédent le complète. Les clics à moins de 3° de l'horizon sont refusés ;
  - en secours, sans hauteur mesurée (sol non repéré, réglages ×1 ou ×0,5, anciennes visites), l'agent saisit la hauteur sous plafond, et les coins cliqués aux deux donnent la hauteur de l'objectif ;
  - la pièce est de forme libre, à murs droits et verticaux, sol et plafond plats. Une mesure est une fiche `<point>/piece.json` qui garde les clics et les hauteurs connues à l'enregistrement ; les dimensions en sont recalculées à chaque lecture. Le panorama avec le contour dessiné est fabriqué à la demande dans `cache/` (D9). Aucune nouvelle dépendance.
- **Raisons :**
  - une hauteur saisie au mètre ruban obligeait quelqu'un à mesurer sur place. ARKit tourne déjà pendant toute la prise de vue conseillée (D27) et voit le sol pendant la rangée de photos vers le bas : la mesure ne demande rien de plus à l'agent. Une erreur d'1 cm sur cette hauteur change les longueurs de moins de 1 % ;
  - viser les coins sur place, en réalité augmentée, a été écarté : sans LiDAR (iPhone 15), ARKit repère mal les murs unis et le plafond, la mesure dériverait sans qu'on le voie, et elle ne serait pas dans le repère du panorama dont l'étape 11 a besoin. Viser les coins avec la croix de l'app, comme les flèches (D26), a été écarté par le propriétaire au profit d'un pointage après l'assemblage : plus précis (on zoome), contrôlable (le contour s'affiche sur la photo) et corrigeable sans retourner dans le logement ;
  - le client ne doit avoir aucune charge : la mesure est un travail de l'agent, fait une fois ;
  - dans le panorama, une arête verticale est une ligne de cap constant : le haut et le bas d'un même coin ont le même cap, à l'erreur de clic près. Le seuil de 4° évite de fondre deux coins différents vus presque dans la même direction ;
  - ne pas imposer de pièce rectangulaire : un L, un couloir ou une entrée se mesurent de la même façon.
- **Ne modifie pas** D22 ni D26 : la réalité augmentée reste limitée à un point à la fois. La position des points entre eux n'est toujours pas mesurée.
- **Limites :**
  - précision calculée sur des pièces de synthèse : un horizon penché d'1° fausse la longueur d'un mur d'environ 4 % et sa surface d'environ 8 %. L'objectif de 10 % sur la surface demande un horizon juste à moins d'un degré ;
  - si ARKit prend une table basse ou un tapis épais pour le sol, toutes les dimensions sont fausses dans la même proportion. Le contour tracé trop grand ou trop petit le montre ;
  - la surface d'un mur comprend portes et fenêtres ; plafonds en pente, mansardes et murs arrondis sont hors de l'étape ;
  - la mesure ARKit n'a été que compilée et testée sur des données simulées : elle reste à vérifier sur l'iPhone ;
  - un clic posé, la visionneuse recharge le panorama réduit avec le contour, ce qui prend une fraction de seconde.

## D35 : étape 12 lancée en parallèle de la v0.3, visites publiées sur Scaleway

- **Date :** 2026-10-26
- **Décision :**
  - l'étape 12 (hébergement et lien de partage) démarre sans attendre la livraison de l'étape 11 ni le jalon v0.3. Les deux avancent en parallèle, sur deux branches distinctes. C'est la seule exception à la règle « une étape ne démarre que si la précédente est livrée » ; le jalon v0.3 garde sa place et reste décidé par le propriétaire ;
  - l'hébergeur est **Scaleway**, avec les données en France (région Paris) ;
  - une visite publiée est un ensemble de **fichiers statiques** : visionneuse, `visite.json` et panoramas, déposés dans un stockage de fichiers (Object Storage de Scaleway). Aucun serveur ne tourne pour la consulter ;
  - le lien contient un **long identifiant tiré au hasard** (au moins 128 bits), seul secret de la visite. La liste du contenu du stockage n'est pas publique et les pages demandent aux moteurs de recherche de ne pas les indexer ;
  - la publication se fait **depuis le Mac**, par une commande `visite360 publier`. Une commande `visite360 depublier` supprime tous les fichiers en ligne de la visite. Une visite reste en ligne jusqu'à sa dépublication, sans durée automatique ;
  - la visite publiée montre les panoramas et la navigation entre points. Elle ne contient ni modifications, ni chiffrage, ni le mode `/agent` : ils arriveront en ligne à l'étape 13, avec la carte graphique louée (D32) ;
  - les clés d'accès Scaleway ne sont jamais dans le dépôt.
- **Raisons :**
  - décision du propriétaire : l'hébergement ne dépend pas du chiffrage, rien ne justifie de l'attendre ;
  - Scaleway : hébergeur français, données en France pour des photos d'intérieur qui sont des données personnelles, et location de cartes graphiques possible chez le même fournisseur pour l'étape 13 (à confirmer à cette étape) ;
  - des fichiers statiques ne coûtent presque rien au repos, ne demandent ni mise à jour ni surveillance, et n'exposent aucune des routes d'écriture de la visionneuse locale (D29, D30, D31) ;
  - un identifiant aléatoire suffit pour une visite qu'on partage soi-même et se révoque en dépubliant. Les liens qui expirent demandent un service pour les produire et des liens à renvoyer.
- **Assouplit D22 :** l'hébergement de visites statiques, les liens de partage et leur coût commencent à l'étape 12, avant la fin de la v0.3. Le reste de D22 tient : jusqu'au jalon v1, les liens ne sont partagés que pour les essais du propriétaire, sans utilisateur extérieur (D28). Serveur de traitement, comptes et carte graphique louée restent aux étapes 13 et 14.
- **Conséquences :**
  - la visionneuse charge aujourd'hui ses fichiers par des adresses fixes servies par le Mac (`/info.json`, `/p/<numéro>/…`, `/api/…`). L'étape 12 doit lui apprendre un mode en lecture seule à adresses relatives, sans les boutons qui appellent le serveur ;
  - le coût mensuel commence : stockage et trafic sortant, à estimer à l'étape 12 sur les tarifs publiés par Scaleway ;
  - `PLAN.md` et `CLAUDE.md` sont mis à jour dans la même pull request.

## D36 : chiffrage en fourchette, surfaces projetées sur la pièce mesurée, forfait par type d'objet

- **Date :** 2026-10-26
- **Décision :**
  - le chiffrage donne un **ordre de grandeur en fourchette** (prix bas, prix haut), pas un devis. Montants arrondis à la dizaine d'euros (décision du propriétaire : « le but n'est pas d'avoir un prix précis mais un ordre d'idée ») ;
  - **source des prix (décision du propriétaire) :** une grille par défaut, indicative, aux prix TTC relevés le 2026-10-26 dans des guides de travaux publics, sources citées dans la grille et dans `docs/chiffrage.md`. L'agent peut la remplacer, visite par visite, dans `visites/<visite>/tarifs.json`, depuis l'adresse `/agent` ou à la main ;
  - **surface d'une recoloration :** chaque pixel du masque est projeté sur la pièce mesurée à l'étape 10 (mur, sol ou plafond), et son aire réelle (distance² × angle solide ÷ cosinus de l'incidence) est additionnée. Peinture des murs, du plafond et nouveau revêtement de sol ont chacun leur prix au m². Calcul sur le masque réduit à 2048 pixels de large, mis de côté dans `cache/` ;
  - **portes et fenêtres (décision du propriétaire) :** seule la surface sélectionnée est chiffrée. Une ouverture laissée hors de la sélection n'est pas comptée, sans rien pointer de plus ;
  - **objet remplacé (décision du propriétaire : une estimation) :** forfait par type d'objet (canapé, fauteuil, table, lit…), reconnu par une recherche de mots dans la demande de génération, d'abord après « par ». L'agent peut corriger le type à l'adresse `/agent`. Sans mot reconnu : « Autre objet » ;
  - le client voit le chiffrage dans la visite. La correction des types et des prix n'est proposée qu'à l'adresse `/agent`, qui ne protège rien jusqu'à la v1 (D34) ;
  - commande `visite360 chiffrage <visite>` pour le lire dans le terminal. Aucune nouvelle dépendance.
- **Raisons :**
  - un prix au m² varie du simple au double selon la région, l'état du support et l'artisan. Une fourchette le montre honnêtement, et son écart reste plus grand que les erreurs de mesure (quelques pour cent) ;
  - la projection pixel par pixel donne la surface réellement sélectionnée, sur plusieurs murs à la fois, sans demander à l'agent de pointer les ouvertures ;
  - une IA qui lirait la demande ou l'image pour reconnaître l'objet coûterait du temps de calcul pour un gain faible : l'agent corrige en un clic les rares erreurs.
- **Limites :**
  - aucun prix public moyen par type de meuble n'a été trouvé. Le bas suit les plafonds de la CAF pour de l'entrée de gamme ; le haut est une estimation du projet ;
  - la grille appartient à la visite : un agent qui veut ses prix partout doit les reporter dans chaque visite (question ouverte de la pull request) ;
  - un mur visible depuis deux points et repeint dans les deux est compté deux fois (D30 : la propagation d'un point à l'autre est hors plan) ;
  - préparation d'un mur abîmé, démolition, livraison et montage des meubles ne sont pas chiffrés.

## D37 : publication par un client S3 en bibliothèque standard, réglages dans un fichier local

- **Date :** 2026-10-26
- **Décision :**
  - `visite360 publier` et `visite360 depublier` parlent au stockage de Scaleway par le protocole S3 avec la bibliothèque standard de Python : quatre opérations (lister, déposer, supprimer, lire une erreur), requêtes signées par la méthode « Signature Version 4 ». Aucune dépendance ajoutée (D16). La signature est vérifiée par les tests contre l'exemple publié par Amazon ;
  - le lien est l'adresse fournie par Scaleway, `https://<bucket>.s3.fr-par.scw.cloud/<identifiant>/index.html`, en attendant que le propriétaire décide d'un nom de domaine du projet, au plus tard avant le jalon v1. L'adresse de base est un réglage (`adresse`) : passer à un domaine ne demande pas de code ;
  - l'identifiant fait 128 bits (`secrets.token_urlsafe(16)`), rangé dans `<visite>/publication.json`. `depublier` l'oublie : republier après une dépublication donne un nouveau lien ;
  - chaque fichier est déposé lisible par tous (`public-read`), le stockage reste privé : la liste de son contenu est refusée aux visiteurs. Un `robots.txt` à sa racine interdit l'indexation, et la page porte la balise `noindex` ;
  - on publie les deux tailles de panorama, 8192 et 4096 pixels, et la page choisit comme en local (D23), selon le choix du propriétaire ;
  - on publie `info.json`, fabriqué par le même code que `serve`, et non `visite.json` : les noms de dossiers et les positions ne sortent pas du Mac ;
  - un relancement compare l'empreinte MD5 de chaque fichier à celle que donne le stockage, et n'envoie que ce qui diffère ;
  - les clés d'accès sont dans `~/.config/visite360/scaleway.json`, hors du dépôt, lisible par le seul compte de l'utilisateur, écrit par `visite360 publier --configurer`, au choix du propriétaire. Les variables `SCW_ACCESS_KEY`, `SCW_SECRET_KEY` et `VISITE360_BUCKET` passent avant ;
  - la visionneuse charge ses fichiers par des adresses relatives (`info.json`, `status.json`, `pannellum/…`). `info.json` d'une visite publiée porte `"publiee": true`, qui retire tous les outils et l'affichage des angles.
- **Raisons :**
  - boto3, la bibliothèque d'Amazon (Apache 2.0), aurait ajouté cinq paquets à suivre pour quatre requêtes, et ses versions depuis la 1.36 envoient par défaut des sommes de contrôle que plusieurs stockages compatibles S3 refusent, à désactiver par un réglage (non vérifié chez Scaleway) ;
  - les secrets de GitHub, envisagés par le propriétaire, ne sont lisibles que par les tâches qui tournent chez GitHub. La publication part du Mac, où sont les panoramas, qui ne vont jamais dans le dépôt ;
  - des adresses relatives servent telles quelles en local (`/` et `/agent`) et en ligne (`/<identifiant>/`), sans deux versions de la page ;
  - la comparaison avec le stockage plutôt qu'avec une liste gardée sur le Mac reste juste après une publication interrompue ou un fichier supprimé à la main dans la console.
- **Limites :**
  - quiconque a le lien voit la visite, et peut le retransmettre : la seule révocation est `depublier` ;
  - l'adresse de Scaleway montre le nom du stockage dans le lien ;
  - un fichier envoyé reste en cache dans le navigateur d'un visiteur jusqu'à sa prochaine visite, où il est revérifié (`Cache-Control: no-cache`) ;
  - le comportement réel de Scaleway (droits par fichier, refus de la liste, type des pages) n'a été vérifié que sur un faux stockage : à confirmer avec le compte du propriétaire.

## D38 : jalon v0.3 franchi, v1 détaillée en quatre étapes, deux environnements

- **Date :** 2026-10-26
- **Décision :**
  - le propriétaire valide le chiffrage : le jalon v0.3 est franchi et on poursuit avec la v1 ;
  - l'ancienne étape 13 (« envoi depuis l'app et traitement sur serveur ») est coupée en trois. **Étape 13 :** l'app envoie la visite au serveur du projet chez Scaleway, qui l'assemble, la publie comme à l'étape 12 et donne le lien. **Étape 14 (demandée par le propriétaire) :** la génération d'image de l'étape 9 tourne sur une carte graphique louée (D32), d'abord appelée depuis la visionneuse du Mac. **Étape 15 :** sélection, couleur, génération, dimensions et chiffrage passent sur le serveur, et la visite publiée montre les modifications ;
  - les retours d'engagement deviennent l'**étape 16** ;
  - les **comptes agents** arrivent dès l'étape 13, et non à l'étape des retours d'engagement : un serveur qui reçoit des photos de logements doit savoir qui les envoie. Les comptes sont créés par le propriétaire, sans inscription libre, et chaque agent ne voit que ses visites ;
  - le Mac garde tous ses outils : le mode local reste la référence pour le développement et le secours. Le serveur fait tourner les mêmes modules Python ;
  - les retours d'engagement se mesurent **par lien** : l'agent crée un lien par client pour une même visite. Le client est informé de la mesure à l'ouverture et peut la refuser sans perdre la visite ;
  - **deux environnements** à partir de l'étape 13, séparés chez Scaleway : intégration (essais du propriétaire, comptes et visites de test) et production (agents et clients, à partir du jalon v1). Chacun a son serveur, son stockage, ses clés et son adresse. Une version passe en production après l'intégration, par une commande explicite. Un seul nom de domaine, une adresse par environnement ;
  - **l'essai de cloison abattue (étape 9.5) est abandonné** (décision du propriétaire : faire au plus simple pour commercialiser au plus vite). L'idée retourne dans « Hors plan ».
- **Raisons :**
  - l'ancienne étape 13 réunissait l'envoi depuis l'app, l'assemblage sur serveur, les comptes, cinq outils de modification et la location d'une carte graphique : trop pour une seule pull request à relire et à tester sur le résultat (D4, D18) ;
  - une étape dédiée à la carte graphique isole son risque propre (allumage à froid, coût à l'heure, logiciel différent de mflux) et se valide simplement : même meuble, même résultat, plus vite. Elle ne dépend pas des comptes ni des outils en ligne ;
  - l'assemblage tourne sur processeur : l'étape 13 ne paie pas encore de carte graphique ;
  - deux environnements : les essais du propriétaire, les comptes de test et les versions en cours ne touchent jamais les visites des agents et de leurs clients, qui sont des données personnelles ;
  - le nom de domaine reste un réglage (D37) : en changer avant le jalon v1 ne coûte rien. Après, les liens déjà envoyés aux clients cesseraient de marcher, sauf à garder l'ancien domaine avec une redirection ;
  - un lien par client est le seul moyen de dire à l'agent quel client s'intéresse à quoi sans identifier le visiteur par un cookie ou un compte.
- **Modifie :** D22 (serveur et comptes commencent à l'étape 13, la carte graphique à l'étape 14).
- **Remplace :** D33 (l'essai de cloison abattue n'a plus lieu).
- **Conséquences :**
  - avant l'étape 13 : choix d'un nom de domaine (D37), du service Scaleway pour le serveur, du mode de connexion des agents et de la durée de conservation des photos d'origine ; examen des paquets numpy et OpenCV pour Linux, qui embarquent des composants LGPL et GPL (`docs/licences.md`) ;
  - avant l'étape 14 : type de carte, mode de location, logiciel sur carte NVIDIA et sa licence, plafond de dépense ;
  - avant l'étape 16 : base légale de la mesure, texte d'information au client, durée de conservation, contrat de sous-traitance avec les agents. Ces points juridiques sont à faire vérifier, le projet n'en est pas juge ;
  - le coût du serveur et du stockage est payé deux fois, une par environnement ; l'intégration peut rester éteinte hors des essais ;
  - les coûts fixes commencent à l'étape 13 (serveur), les coûts à l'usage de la carte graphique à l'étape 14. Chacune note le coût du mois dans sa validation.
