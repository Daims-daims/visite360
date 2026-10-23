# Plan

Objectif : à partir de photos prises en tournant sur soi-même avec un téléphone, produire une visite 360° d'un logement, puis permettre de repeindre un mur et voir la visite mise à jour.

## Règles de suivi

- Statuts : **à faire**, **en cours**, **livrée**.
- Une étape passe à « livrée » dans le dernier commit de sa pull request. Sur `main`, « livrée » signifie donc fusionnée et validée par le propriétaire du dépôt.
- Une étape ne démarre que si la précédente est « livrée » sur `main`.
- Un jalon est une décision du propriétaire, pas du code. Il s'inscrit dans ce fichier avant qu'on passe à la suite.
- Chaque étape a un critère de validation à vérifier sur le Mac ou le téléphone. Les tests automatiques ne le remplacent pas.
- Les phases 3 à 5 sont esquissées. Elles seront détaillées dans une pull request dédiée après le jalon A.

## Vue d'ensemble

| # | Étape | Phase | Statut |
|---|---|---|---|
| 0 | Cadrage du dépôt | — | livrée |
| 1 | Contrôle de l'installation et protocole de prise de vue | 1 | livrée |
| 2 | Assemblage d'un panorama | 1 | en cours |
| 3 | Visite d'un point | 1 | à faire |
| 4 | Visite de plusieurs points | 1 | à faire |
| 5 | Sélection d'une surface au clic | 2 | à faire |
| 6 | Changement de couleur | 2 | à faire |
| A | **Jalon : démo à des agents immobiliers** | — | à faire |
| 7 | Capture guidée à un point | 3 | à faire |
| 8 | Suivi de position entre les points | 3 | à faire |
| 9 | Forme de chaque pièce | 4 | à faire |
| 10 | Assemblage des pièces | 4 | à faire |
| 11 | Propagation d'une modification | 4 | à faire |
| 12 | Remplacer un meuble ou la déco | 5 | à faire |
| 13 | Abattre une cloison | 5 | à faire |

## Étape 0 : cadrage du dépôt

- **Contenu :** structure du dépôt, règles du projet, ce plan, journal des décisions, registre des licences, squelette Python, tests automatiques GitHub.
- **Validation :** `pytest` et `ruff check .` passent, `visite360 --version` répond, les fichiers de cadrage ont été relus.

## Phase 1 : de photos à une visite 360°, sans app

Les photos sont prises à la main avec l'appareil photo du téléphone. Le but est de valider l'assemblage avant d'investir dans une app.

### Étape 1 : contrôle de l'installation et protocole de prise de vue

- **Contenu :** commande `visite360 doctor` qui vérifie les dépendances nécessaires et dit quoi installer s'il en manque. Fiche `docs/prise-de-vue.md` : nombre de photos par point, rangées (horizon, haut, bas, plafond), recouvrement entre photos, tourner autour du téléphone et non autour de soi, lumières, portes ouvertes.
- **Tests automatiques :** dépendance présente, absente, version trop ancienne, avec des appels simulés.
- **Validation :** la commande passe sur le Mac. Le propriétaire a pris un jeu de photos d'un point en suivant la fiche.
- **À trancher pendant l'étape :** version minimale d'OpenCV, conversion des photos HEIC de l'iPhone.

### Étape 2 : assemblage d'un panorama

- **Contenu :** `visite360 stitch <dossier de photos>` produit un panorama équirectangulaire 2:1. Rapport : photos utilisées et rejetées, couverture, zones manquantes.
- **Tests automatiques :** sur des photos générées par découpage d'un panorama de synthèse, jamais stockées dans le dépôt.
- **Validation :** sur de vraies photos, aucun raccord visible sur les murs. Une tache floue au sol, sous le photographe, est acceptée à ce stade.
- **Risque principal de la phase :** la parallaxe d'une prise de vue à main levée. Repli prévu : Hugin en programme externe (D7). Si l'assemblage échoue trop souvent, proposer d'avancer la capture guidée (étape 7).
- **À trancher pendant l'étape :** résolution de sortie, traitement du plafond et du sol.

### Étape 3 : visite d'un point

- **Contenu :** page web servie en local, où l'on regarde autour de soi dans un panorama. Visionneuse : Pannellum (D8).
- **Tests automatiques :** le serveur local répond et sert le panorama.
- **Validation :** fluide sur le Mac, puis sur un téléphone connecté au même Wi-Fi.

### Étape 4 : visite de plusieurs points

- **Contenu :** plusieurs panoramas reliés par des flèches cliquables. Les liens et l'orientation de chaque point sont déclarés à la main dans `visite.json` (D14).
- **Tests automatiques :** lecture et validation de `visite.json`, détection des liens vers un point inexistant.
- **Validation :** parcours de l'appartement du propriétaire sur 4 à 8 points, sur ordinateur et téléphone.

## Phase 2 : repeindre un mur

### Étape 5 : sélection d'une surface au clic

- **Contenu :** l'utilisateur clique sur une surface, l'outil en trouve le contour avec SAM 2 (D10). La sélection se fait sur une vue normale découpée autour du clic, puis le masque est reporté dans le panorama. Le masque est enregistré comme opération (D9).
- **Tests automatiques :** découpage d'une vue et report du masque dans le panorama, aller-retour sans décalage, sur des images de synthèse. Le modèle est simulé.
- **Validation :** sur de vrais panoramas, le contour suit le mur, y compris derrière les meubles et le long des plinthes.
- **À trancher pendant l'étape :** taille du modèle SAM 2 et vitesse sur le Mac. Interface de clic : dans la visionneuse ou dans une page dédiée.

### Étape 6 : changement de couleur

- **Contenu :** recoloration de la surface sélectionnée qui garde les ombres et la lumière, sans IA générative (D11). Affichage avant et après dans la visite. Annulation possible.
- **Tests automatiques :** la luminosité relative est conservée, les pixels hors du masque sont inchangés, l'annulation restaure l'original.
- **Validation :** résultat crédible sur trois murs : un blanc, un coloré, un éclairé par une fenêtre.
- **Limite connue :** passer d'un mur foncé à un mur clair est plus difficile que l'inverse.
- À ce stade, un mur visible depuis plusieurs points se repeint dans chaque panorama séparément.

## Jalon A : démo à des agents immobiliers

- **Contenu :** visite de l'appartement du propriétaire avec un mur repeint, montrée à 2 ou 3 agents.
- **Livrable :** leurs retours, notés dans `docs/retours-agents.md` sans données personnelles.
- **Décision :** le propriétaire décide de poursuivre, d'ajuster ou d'arrêter, et l'écrit ici.

## Phase 3 : app de capture guidée (esquisse)

- **Étape 7 : capture guidée à un point.** Cible à aligner à l'écran, orientation de chaque photo enregistrée, envoi des photos. Validation : moins de raccords qu'avec la prise de vue à la main.
- **Étape 8 : suivi de position entre les points.** La réalité augmentée du téléphone (ARKit, ARCore) mesure le déplacement entre deux points. Validation : les flèches entre les points se placent toutes seules.
- **À trancher :** Expo avec un module natif en Swift ou Kotlin, ou app native.

## Phase 4 : modèle 3D commun (esquisse)

- **Étape 9 : forme de chaque pièce.** L'utilisateur pointe les coins au sol et au plafond dans le panorama, l'outil en déduit une boîte 3D (D13). Validation : les murs tombent juste quand on les superpose au panorama.
- **Étape 10 : assemblage des pièces** avec les positions de l'étape 8. Validation : les pièces voisines se raccordent aux portes.
- **Étape 11 : propagation.** Une modification est rattachée à une surface du modèle 3D, plus à des pixels. Un mur repeint une fois change dans tous les panoramas qui le voient. Validation : même mur, même couleur, vu depuis trois points.

## Phase 5 : exploratoire (esquisse)

Résultat non garanti. Viser d'abord une esquisse crédible.

- **Étape 12 : remplacer un meuble ou la déco** par IA générative, via une API payante pour rester en règle sur les licences.
- **Étape 13 : abattre une cloison.** Faire apparaître la pièce voisine à partir de ses propres panoramas et inventer les zones jamais photographiées.
