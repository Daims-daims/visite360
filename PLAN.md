# Plan

Objectif : à partir de photos prises en tournant sur soi-même avec un téléphone, produire une visite 360° d'un logement, permettre d'y modifier ce qu'on voit, chiffrer ces modifications, puis partager la visite avec des clients et rendre compte à l'agent de leur intérêt.

## Règles de suivi

- Statuts : **à faire**, **en cours**, **livrée**.
- Une étape passe à « livrée » dans le dernier commit de sa pull request. Sur `main`, « livrée » signifie donc fusionnée et validée par le propriétaire du dépôt.
- Une étape ne démarre que si la précédente est « livrée » sur `main`.
- Un jalon est une décision du propriétaire, pas du code. Il s'inscrit dans ce fichier avant qu'on passe à la suite.
- Chaque étape a un critère de validation à vérifier sur le Mac ou le téléphone. Les tests automatiques ne le remplacent pas.
- Tout fonctionne en local jusqu'à la v1 : traitement sur le Mac, visite servie par le Mac, aucun hébergement ni service payant (D22). Les présentations se font en local. Aucun utilisateur extérieur n'a accès au produit avant la v1.
- Les versions v0.3 et v1 sont esquissées. Chacune sera détaillée dans une pull request dédiée après le jalon de la version précédente.

## Vue d'ensemble

| # | Étape | Version | Statut |
|---|---|---|---|
| 0 | Cadrage du dépôt | — | livrée |
| 1 | Contrôle de l'installation et protocole de prise de vue | v0.1 | livrée |
| 2 | Assemblage d'un panorama | v0.1 | livrée |
| 3 | Visite d'un point | v0.1 | à faire |
| 4 | Visite de plusieurs points | v0.1 | à faire |
| 5 | App : capture guidée à un point | v0.1 | à faire |
| 6 | App : capture d'une visite et transfert vers le Mac | v0.1 | à faire |
| J1 | **Jalon v0.1 : présentation locale de la visite** | — | à faire |
| 7 | Sélection d'une surface au clic | v0.2 | à faire |
| 8 | Changement de couleur | v0.2 | à faire |
| 9 | Modification par génération d'image, en local | v0.2 | à faire |
| J2 | **Jalon v0.2 : présentation locale des modifications** | — | à faire |
| 10 | Dimensions des pièces | v0.3 | à faire |
| 11 | Chiffrage d'une modification | v0.3 | à faire |
| J3 | **Jalon v0.3 : présentation locale du chiffrage** | — | à faire |
| 12 | Hébergement et lien de partage | v1 | à faire |
| 13 | Envoi depuis l'app et traitement sur serveur | v1 | à faire |
| 14 | Retours d'engagement pour l'agent | v1 | à faire |
| J4 | **Jalon v1 : premiers accès utilisateurs** | — | à faire |

## Étape 0 : cadrage du dépôt

- **Contenu :** structure du dépôt, règles du projet, ce plan, journal des décisions, registre des licences, squelette Python, tests automatiques GitHub.
- **Validation :** `pytest` et `ruff check .` passent, `visite360 --version` répond, les fichiers de cadrage ont été relus.

## v0.1 : prendre et consulter une visite, en local

Les étapes 1 à 4 valident l'assemblage et la visite avec des photos prises à la main. Les étapes 5 et 6 remplacent la prise de vue à la main par une app.

### Étape 1 : contrôle de l'installation et protocole de prise de vue

- **Contenu :** commande `visite360 doctor` qui vérifie les dépendances nécessaires et dit quoi installer s'il en manque. Fiche `docs/prise-de-vue.md` : nombre de photos par point, rangées (horizon, haut, bas, plafond), recouvrement entre photos, tourner autour du téléphone et non autour de soi, lumières, portes ouvertes.
- **Tests automatiques :** dépendance présente, absente, version trop ancienne, avec des appels simulés.
- **Validation :** la commande passe sur le Mac. Le propriétaire a pris un jeu de photos d'un point en suivant la fiche.
- **À trancher pendant l'étape :** version minimale d'OpenCV, conversion des photos HEIC de l'iPhone.

### Étape 2 : assemblage d'un panorama

- **Contenu :** `visite360 stitch <dossier de photos>` produit un panorama équirectangulaire 2:1. Rapport : photos utilisées et rejetées, couverture, zones manquantes.
- **Tests automatiques :** sur des photos générées par découpage d'un panorama de synthèse, jamais stockées dans le dépôt.
- **Validation :** sur de vraies photos, aucun raccord visible sur les murs. Une tache floue au sol, sous le photographe, est acceptée à ce stade.
- **Risque principal de la v0.1 :** la parallaxe d'une prise de vue à main levée. Repli prévu : Hugin en programme externe (D7). Si l'assemblage échoue trop souvent, proposer d'avancer la capture guidée (étape 5).
- **À trancher pendant l'étape :** résolution de sortie, traitement du plafond et du sol.

### Étape 3 : visite d'un point

- **Contenu :** page web servie en local, où l'on regarde autour de soi dans un panorama. Visionneuse : Pannellum (D8).
- **Tests automatiques :** le serveur local répond et sert le panorama.
- **Validation :** fluide sur le Mac, puis sur un téléphone connecté au même Wi-Fi.

### Étape 4 : visite de plusieurs points

- **Contenu :** plusieurs panoramas reliés par des flèches cliquables. Les liens et l'orientation de chaque point sont déclarés à la main dans `visite.json` (D14).
- **Tests automatiques :** lecture et validation de `visite.json`, détection des liens vers un point inexistant.
- **Validation :** parcours de l'appartement du propriétaire sur 4 à 8 points, sur ordinateur et téléphone.

### Étape 5 : app, capture guidée à un point

- **Contenu :** app sur le téléphone qui guide la prise de vue d'un point : cible à aligner à l'écran, rangées de `docs/prise-de-vue.md`, orientation de chaque photo enregistrée. Code dans `app/` (D15).
- **Tests automatiques :** lecture des orientations enregistrées par l'app et utilisation par l'assemblage, sur des données générées.
- **Validation :** sur le téléphone du propriétaire, moins de raccords visibles qu'avec la prise de vue à la main sur la même pièce.
- **À trancher avant l'étape :** modèle du téléphone ; Expo avec un module natif en Swift ou Kotlin, ou app native ; installation de l'app sur le téléphone du propriétaire sans frais si possible (le compte développeur Apple payant est un coût annuel).

### Étape 6 : app, capture d'une visite et transfert vers le Mac

- **Contenu :** dans l'app, enchaîner les points d'une visite, les nommer et déclarer à la main les liens entre eux (D14). Transfert des photos et de `visite.json` vers le Mac, qui assemble et sert la visite des étapes 2 à 4.
- **Tests automatiques :** réception d'une visite transférée, rangement dans `visites/<nom>/`, refus d'un envoi incomplet.
- **Validation :** une visite de l'appartement du propriétaire prise avec l'app, transférée, assemblée et parcourue sur le Mac et le téléphone, sans manipuler de fichiers à la main.
- **À trancher pendant l'étape :** moyen de transfert sans service payant : réception par le Mac sur le Wi-Fi local, AirDrop, ou câble.

## Jalon v0.1 : présentation locale de la visite

- **Contenu :** visite de l'appartement du propriétaire, prise avec l'app, montrée en local à 2 ou 3 agents immobiliers.
- **Livrable :** leurs retours, notés dans `docs/retours-agents.md` sans données personnelles.
- **Décision :** le propriétaire décide de poursuivre, d'ajuster ou d'arrêter, et l'écrit ici.

## v0.2 : modifier ce qu'on voit, sans coût

On génère au maximum sans coût : calcul déterministe quand il suffit, modèle d'IA qui tourne sur le Mac sinon (D22).

### Étape 7 : sélection d'une surface au clic

- **Contenu :** l'utilisateur clique sur une surface, l'outil en trouve le contour avec SAM 2 (D10). La sélection se fait sur une vue normale découpée autour du clic, puis le masque est reporté dans le panorama. Le masque est enregistré comme opération (D9).
- **Tests automatiques :** découpage d'une vue et report du masque dans le panorama, aller-retour sans décalage, sur des images de synthèse. Le modèle est simulé.
- **Validation :** sur de vrais panoramas, le contour suit le mur, y compris derrière les meubles et le long des plinthes.
- **À trancher pendant l'étape :** taille du modèle SAM 2 et vitesse sur le Mac. Interface de clic : dans la visionneuse ou dans une page dédiée.

### Étape 8 : changement de couleur

- **Contenu :** recoloration de la surface sélectionnée qui garde les ombres et la lumière, sans IA générative (D11). Affichage avant et après dans la visite. Annulation possible.
- **Tests automatiques :** la luminosité relative est conservée, les pixels hors du masque sont inchangés, l'annulation restaure l'original.
- **Validation :** résultat crédible sur trois murs : un blanc, un coloré, un éclairé par une fenêtre.
- **Limite connue :** passer d'un mur foncé à un mur clair est plus difficile que l'inverse.
- À ce stade, un mur visible depuis plusieurs points se repeint dans chaque panorama séparément.

### Étape 9 : modification par génération d'image, en local

- **Contenu :** au moins un exemple de modification générée par IA, par exemple remplacer un meuble ou changer un revêtement de sol. Le modèle tourne sur le Mac. La génération se fait sur une vue normale découpée dans le panorama, limitée au masque de l'étape 7, puis le résultat est reporté (projeté) dans le panorama. La modification est enregistrée comme opération (D9).
- **Coût de génération :** mesurer le temps et la mémoire par image sur le Mac. Estimer, à partir des tarifs publiés, ce que coûterait la même génération par une API payante, sans l'utiliser.
- **Tests automatiques :** découpage, report dans le panorama et pixels hors du masque inchangés, sur des images de synthèse. Le modèle est simulé.
- **Validation :** sur de vrais panoramas, la modification est crédible vue dans la visite, sans raccord au bord de la zone modifiée.
- **À trancher avant l'étape :** modèle utilisé. Code, poids et données d'entraînement doivent avoir une licence autorisée (`CLAUDE.md`), et beaucoup de modèles de génération d'image ont des poids non commerciaux. Le modèle doit aussi tenir dans les 24 Go du Mac. Si aucun modèle local ne convient, le propriétaire décide s'il accepte une API payante.

## Jalon v0.2 : présentation locale des modifications

- **Contenu :** la visite du jalon v0.1 avec un mur repeint et au moins une modification générée, montrée en local.
- **Livrable :** retours ajoutés à `docs/retours-agents.md`, temps et coût de génération mesurés.
- **Décision :** le propriétaire décide de la suite et l'écrit ici.

## v0.3 : chiffrage (esquisse)

- **Étape 10 : dimensions des pièces.** L'utilisateur pointe les coins au sol et au plafond dans le panorama, l'outil en déduit une boîte 3D (D13). Tourner sur soi-même ne donne pas l'échelle : une mesure réelle est saisie, par exemple la hauteur sous plafond. Validation : surface d'un mur à moins de 10 % de la mesure au mètre.
- **Étape 11 : chiffrage d'une modification.** Surface touchée en m², multipliée par un prix unitaire tiré d'une grille modifiable (peinture, revêtement, pose). Validation : ordre de grandeur cohérent avec un devis réel.
- **À trancher :** source des prix ; chiffrage des modifications générées, comme un meuble remplacé.

## Jalon v0.3 : présentation locale du chiffrage

- **Décision :** le propriétaire décide du passage à la v1, qui engage les premiers coûts d'hébergement, et l'écrit ici.

## v1 : partage et retours pour l'agent (esquisse)

Les coûts d'hébergement et de traitement commencent ici, au moment du déploiement (D22).

- **Étape 12 : hébergement et lien de partage.** Une visite est publiée et consultable par un lien difficile à deviner, sans installer d'app.
- **Étape 13 : envoi depuis l'app et traitement sur serveur.** L'agent prend la visite, l'envoie, le serveur assemble et produit le lien à transmettre au client.
- **Étape 14 : retours d'engagement pour l'agent.** Comptes agents. Statistiques par lien : ouvertures, durée, pièces vues, modifications essayées.
- **À trancher :** hébergeur et coût mensuel ; consentement des clients au suivi de leur consultation (RGPD).

## Jalon v1 : premiers accès utilisateurs

- **Contenu :** premiers agents qui utilisent le produit eux-mêmes, avec de vrais clients.
- **Décision :** le propriétaire écrit ici les conditions de ces premiers accès.

## Hors plan, pour plus tard

- Suivi de position entre les points par la réalité augmentée du téléphone, pour placer les liens tout seuls (D14).
- Modèle 3D commun à toutes les pièces et propagation d'une modification d'un panorama à l'autre.
- Abattre une cloison.
