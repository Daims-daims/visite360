# Plan

Objectif : à partir de photos prises en tournant sur soi-même avec un téléphone, produire une visite 360° d'un logement, permettre d'y modifier ce qu'on voit, chiffrer ces modifications, puis partager la visite avec des clients et rendre compte à l'agent de leur intérêt.

## Règles de suivi

- Statuts : **à faire**, **en cours**, **livrée**.
- Une étape passe à « livrée » dans le dernier commit de sa pull request. Sur `main`, « livrée » signifie donc fusionnée et validée par le propriétaire du dépôt.
- Une étape ne démarre que si la précédente est « livrée » sur `main`. Seule exception : l'étape 12 avance en parallèle de la v0.3 (D35).
- Un jalon est une décision du propriétaire, pas du code. Il s'inscrit dans ce fichier avant qu'on passe à la suite.
- Chaque étape a un critère de validation à vérifier sur le Mac ou le téléphone. Les tests automatiques ne le remplacent pas.
- Tout a fonctionné en local jusqu'à la v1 : traitement sur le Mac, visite servie par le Mac, aucun hébergement ni service payant (D22). Depuis l'étape 12, une visite peut être publiée en fichiers statiques chez Scaleway (D35) ; serveur de traitement et comptes agents arrivent à l'étape 13, carte graphique louée à l'étape 14 (D38). Aucun utilisateur extérieur n'a accès au produit avant le jalon v1.
- Tout ce qui tourne en ligne est chez Scaleway : stockage, serveur, carte graphique, nom de domaine et services annexes (D38). Un service hors de Scaleway demande une décision écrite du propriétaire.
- Les jalons v0.1, v0.2 et v0.3 sont validés par le propriétaire seul. La première présentation à des agents immobiliers a lieu au jalon v1, une fois la v1 réalisée (D28).
- La version v1 est détaillée : étape 12 (D35), étapes 13 à 16 (D38).

## Vue d'ensemble

| # | Étape | Version | Statut |
|---|---|---|---|
| 0 | Cadrage du dépôt | — | livrée |
| 1 | Contrôle de l'installation et protocole de prise de vue | v0.1 | livrée |
| 2 | Assemblage d'un panorama | v0.1 | livrée |
| 3 | Visite d'un point | v0.1 | livrée |
| 4 | Visite de plusieurs points | v0.1 | livrée |
| 5 | App : capture guidée à un point | v0.1 | livrée |
| 6 | App : capture d'une visite et transfert vers le Mac | v0.1 | livrée |
| J1 | **Jalon v0.1 : validation de la visite par le propriétaire** | — | livrée |
| 7 | Sélection d'une surface au clic | v0.2 | livrée |
| 8 | Changement de couleur | v0.2 | livrée |
| 9 | Modification par génération d'image, en local | v0.2 | livrée |
| J2 | **Jalon v0.2 : validation des modifications par le propriétaire** | — | livrée |
| 10 | Dimensions des pièces | v0.3 | livrée |
| 11 | Chiffrage d'une modification | v0.3 | livrée |
| J3 | **Jalon v0.3 : validation du chiffrage par le propriétaire** | — | livrée |
| 12 | Hébergement et lien de partage | v1 | livrée |
| 13 | Envoi depuis l'app et assemblage sur serveur | v1 | livrée |
| 14 | Génération d'image sur une carte graphique louée | v1 | à faire |
| 15 | Modifications et chiffrage en ligne | v1 | à faire |
| 16 | Retours d'engagement pour l'agent | v1 | à faire |
| J4 | **Jalon v1 : présentation aux agents et premiers accès** | — | à faire |

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

- **Contenu :** plusieurs panoramas reliés par des flèches cliquables. Les liens et l'orientation de chaque point sont déclarés à la main dans `visite.json` (D14, format dans `docs/visite-json.md`). `visite360 serve <visite>` assemble les panoramas manquants, crée `visite.json` s'il manque et sert la visite. La déclaration automatique des liens par l'app est prévue à l'étape 6.
- **Tests automatiques :** lecture et validation de `visite.json`, détection des liens vers un point inexistant.
- **Validation :** parcours de l'appartement du propriétaire sur 4 à 8 points, sur ordinateur et téléphone.

### Étape 5 : app, capture guidée à un point

- **Contenu :** app sur le téléphone qui guide la prise de vue d'un point : cible à aligner à l'écran, rangées de `docs/prise-de-vue.md`, orientation de chaque photo enregistrée. Code dans `app/` (D15).
- **Tests automatiques :** lecture des orientations enregistrées par l'app et utilisation par l'assemblage, sur des données générées.
- **Validation :** sur le téléphone du propriétaire, moins de raccords visibles qu'avec la prise de vue à la main sur la même pièce.
- **À trancher avant l'étape :** modèle du téléphone ; Expo avec un module natif en Swift ou Kotlin, ou app native ; installation de l'app sur le téléphone du propriétaire sans frais si possible (le compte développeur Apple payant est un coût annuel).
- **Tranché le 2026-10-24 (D25) :** iPhone 15 ; app native en SwiftUI ; installation par câble depuis Xcode avec l'identifiant Apple du propriétaire, sans compte payant. Mode d'emploi dans `docs/app.md`.

### Étape 6 : app, capture d'une visite et transfert vers le Mac

- **Contenu :** dans l'app, enchaîner les points d'une visite, les nommer et déclarer à la main les liens entre eux (D14). Transfert des photos et de `visite.json` vers le Mac, qui assemble et sert la visite des étapes 2 à 4.
- **Tests automatiques :** réception d'une visite transférée, rangement dans `visites/<nom>/`, refus d'un envoi incomplet.
- **Validation :** une visite de l'appartement du propriétaire prise avec l'app, transférée, assemblée et parcourue sur le Mac et le téléphone, sans manipuler de fichiers à la main.
- **À trancher pendant l'étape :** suivi de position par la réalité augmentée du téléphone pour renseigner tout seul `position`, `nord` et les liens de `visite.json` (aujourd'hui à la main, D14, D24) ; quels points relier (par exemple ceux pris à la suite) ; moyen de transfert sans service payant : réception par le Mac sur le Wi-Fi local, AirDrop, ou câble.
- **Tranché le 2026-10-24 (D26) :** pas de réalité augmentée ; les flèches se visent dans l'app à la fin de chaque point, vers la porte de la pièce d'arrivée, choisie par l'utilisateur ; transfert par le Wi-Fi local avec `visite360 receive` sur le Mac, AirDrop et câble en secours. Mode d'emploi dans `docs/app.md` et `docs/transfert.md`.

## Jalon v0.1 : validation de la visite par le propriétaire

- **Contenu :** le propriétaire juge la visite de son appartement, prise avec l'app, transférée, assemblée et parcourue sur le Mac et le téléphone (étape 6).
- **Décision du propriétaire (2026-10-25) :** poursuivre avec la v0.2. La démo aux agents immobiliers prévue à ce jalon est repoussée à la fin du plan, après la réalisation de la v1 (jalon v1, D28).

## v0.2 : modifier ce qu'on voit, sans coût

On génère au maximum sans coût : calcul déterministe quand il suffit, modèle d'IA qui tourne sur le Mac sinon (D22).

### Étape 7 : sélection d'une surface au clic

- **Contenu :** l'utilisateur clique sur une surface, l'outil en trouve le contour avec SAM 2 (D10). La sélection se fait sur une vue normale découpée autour du clic, puis le masque est reporté dans le panorama. Le masque est enregistré comme opération (D9).
- **Tests automatiques :** découpage d'une vue et report du masque dans le panorama, aller-retour sans décalage, sur des images de synthèse. Le modèle est simulé.
- **Validation :** sur de vrais panoramas, le contour suit le mur, y compris derrière les meubles et le long des plinthes.
- **À trancher pendant l'étape :** taille du modèle SAM 2 et vitesse sur le Mac. Interface de clic : dans la visionneuse ou dans une page dédiée.
- **Tranché le 2026-10-25 (D29) :** SAM 2.1 small, sur la puce graphique du Mac, choisi après essai de MobileSAM et SAM 2.1 tiny ; sélection dans la visionneuse, sur la vue regardée, avec clics « en plus » et « en moins ». Mode d'emploi dans `docs/selection.md`.

### Étape 8 : changement de couleur

- **Contenu :** recoloration de la surface sélectionnée qui garde les ombres et la lumière, sans IA générative (D11). Affichage avant et après dans la visite. Annulation possible.
- **Tests automatiques :** la luminosité relative est conservée, les pixels hors du masque sont inchangés, l'annulation restaure l'original.
- **Validation :** résultat crédible sur trois murs : un blanc, un coloré, un éclairé par une fenêtre.
- **Limite connue :** passer d'un mur foncé à un mur clair est plus difficile que l'inverse.
- À ce stade, un mur visible depuis plusieurs points se repeint dans chaque panorama séparément.
- **Tranché le 2026-10-25 (D30) :** contour recalé sur les bords de la photo par un filtre guidé, puis couleur changée en lumière linéaire (« couleur du mur × éclairage ») ; la couleur choisie est celle du pot de peinture, le mur étant supposé blanc sauf indication ; nuancier de 24 teintes avec couleur sur mesure ; une fiche par surface repeinte dans `modifications/`, panorama modifié refait à la demande dans `cache/` ; « Repeindre » dans la liste des sélections, bascule avant et après dans la visite. Mode d'emploi dans `docs/couleur.md`.

### Étape 9 : modification par génération d'image, en local

- **Contenu :** au moins un exemple de modification générée par IA, par exemple remplacer un meuble ou changer un revêtement de sol. Le modèle tourne sur le Mac. La génération se fait sur une vue normale découpée dans le panorama, limitée au masque de l'étape 7, puis le résultat est reporté (projeté) dans le panorama. La modification est enregistrée comme opération (D9).
- **Coût de génération :** mesurer le temps et la mémoire par image sur le Mac. Estimer, à partir des tarifs publiés, ce que coûterait la même génération par une API payante, sans l'utiliser.
- **Tests automatiques :** découpage, report dans le panorama et pixels hors du masque inchangés, sur des images de synthèse. Le modèle est simulé.
- **Validation :** sur de vrais panoramas, la modification est crédible vue dans la visite, sans raccord au bord de la zone modifiée.
- **À trancher avant l'étape :** modèle utilisé. Code, poids et données d'entraînement doivent avoir une licence autorisée (`CLAUDE.md`), et beaucoup de modèles de génération d'image ont des poids non commerciaux. Le modèle doit aussi tenir dans les 24 Go du Mac. Si aucun modèle local ne convient, le propriétaire décide s'il accepte une API payante.
- **Tranché le 2026-10-25 (D31) :** FLUX.2 [klein] 4B (Apache 2.0, données d'entraînement non publiées, risque accepté par le propriétaire), sur le Mac par mflux ; exemple retenu : remplacement d'un meuble ; la zone modifiée est un cadre tracé dans la vue, pas le masque de l'étape 7. Mode d'emploi, temps et coût dans `docs/generation.md`.

## Jalon v0.2 : validation des modifications par le propriétaire

- **Contenu :** la visite du jalon v0.1 avec un mur repeint et au moins une modification générée, jugée par le propriétaire.
- **Livrable :** temps et coût de génération mesurés.
- **Décision :** le propriétaire décide de la suite et l'écrit ici.
- **Décision du propriétaire (2026-10-25) :** le mur repeint et le meuble remplacé lui conviennent. Poursuivre avec la v0.3. Les temps et coûts de génération sont dans `docs/generation.md`. L'essai de cloison abattue est repoussé après l'étape 13 (D33), puis abandonné (D38).

## v0.3 : chiffrage

Mesurer une pièce dans son panorama, puis chiffrer une modification à partir de la surface touchée. Tout reste calculé sur le Mac, sans coût (D22).

### Étape 10 : dimensions des pièces

- **Contenu :** pendant la prise de vue « ×1 + AR », l'app mesure la hauteur de l'objectif au-dessus du sol : tourner sur soi-même ne donne pas l'échelle. Une fois le panorama fait, l'agent pointe les coins de la pièce dans un mode qui lui est réservé, que le client ne voit pas. L'outil en déduit le contour de la pièce, la longueur et la surface de chaque mur, et la surface au sol (D13). Le contour calculé est dessiné par-dessus le panorama pour qu'on voie s'il suit les murs. La pièce est enregistrée dans le dossier du point.
- **Tests automatiques :** sur une pièce de synthèse aux dimensions connues, les directions de ses coins redonnent ses dimensions ; effet chiffré d'une erreur d'horizon ou de clic ; lecture et refus d'une fiche mal formée ; choix du sol parmi les surfaces repérées par ARKit.
- **Validation :** sur l'appartement du propriétaire, hauteur de l'objectif notée par l'app à 2 cm près de la mesure au mètre ; surface d'un mur à moins de 10 % de la mesure au mètre.
- **Tranché le 2026-10-25 (D34) :** l'échelle vient de la hauteur de l'objectif mesurée par ARKit, sans mètre ruban ; hauteur sous plafond saisie en secours ; coins pointés par l'agent à l'adresse `/agent` de la visionneuse, après l'assemblage, au sol ou au plafond quand un meuble cache le bas ; pièces de forme libre, murs droits et verticaux. Mode d'emploi et précision dans `docs/dimensions.md`.

### Étape 11 : chiffrage d'une modification

- **Contenu :** surface touchée en m², multipliée par un prix unitaire tiré d'une grille modifiable (peinture, revêtement, pose). La surface vient des dimensions de l'étape 10 et de la sélection de l'étape 7.
- **Validation :** ordre de grandeur cohérent avec un devis réel.
- **À trancher avant l'étape :** source des prix ; chiffrage des modifications générées, comme un meuble remplacé ; déduction des portes et fenêtres de la surface d'un mur.
- **Tranché le 2026-10-26 (D36) :** un ordre de grandeur en fourchette, pas un devis ; grille indicative par défaut aux prix relevés dans des guides de travaux, sources citées, remplaçable par l'agent visite par visite ; seule la surface sélectionnée est chiffrée, portes et fenêtres laissées hors de la sélection exclues d'elles-mêmes ; objet remplacé chiffré au forfait selon son type, reconnu dans la demande de génération et corrigeable par l'agent. Mode d'emploi, sources et précision dans `docs/chiffrage.md`.

## Jalon v0.3 : validation du chiffrage par le propriétaire

- **Décision :** le propriétaire décide de la suite de la v1 (étapes 13 et 14) et l'écrit ici. Les premiers coûts d'hébergement commencent dès l'étape 12, menée en parallèle (D35).
- **Décision du propriétaire (2026-10-26) :** chiffrage validé, jalon v0.3 franchi. Poursuivre avec la v1. Les étapes qui suivent l'étape 12 sont détaillées ci-dessous : l'ancienne étape 13 est coupée en trois (assemblage sur serveur, génération sur une carte graphique louée, modifications en ligne) et les retours d'engagement deviennent l'étape 16 (D38).

## v1 : partage et retours pour l'agent

Les coûts d'hébergement commencent à l'étape 12, ceux du serveur à l'étape 13, ceux de la carte graphique louée à l'étape 14 (D22, D35, D38). Jusqu'au jalon v1, seul le propriétaire utilise le serveur, avec des comptes de test.

### Étape 12 : hébergement et lien de partage

- **Lancée en parallèle de la v0.3 (D35)**, sans attendre l'étape 11 ni le jalon v0.3.
- **Contenu :** la commande `visite360 publier <visite>` dépose chez Scaleway (stockage de fichiers, région Paris) la visionneuse, `visite.json` et les panoramas, et affiche le lien. Le lien contient un long identifiant tiré au hasard. N'importe quel téléphone ou ordinateur ouvre la visite dans son navigateur, sans app ni compte, et passe d'un point à l'autre. `visite360 depublier <visite>` supprime tout ce qui est en ligne. Relancer `publier` n'envoie que ce qui a changé et garde le même lien. La visionneuse gagne un mode en lecture seule à adresses relatives. Pas de modifications, de chiffrage ni de mode `/agent` en ligne : ils viendront avec l'étape 13.
- **Tests automatiques :** liste des fichiers publiés à partir d'une visite de synthèse, sans photo d'origine ni fichier de travail ; identifiant de taille suffisante et stable d'une publication à l'autre ; message clair en français sans clés d'accès ou sans réseau ; envois et suppressions vérifiés contre un faux stockage, sans appel réel à Scaleway.
- **Validation :** sur un téléphone en 4G, hors du Wi-Fi du Mac, le lien ouvre la visite de l'appartement du propriétaire et la navigation fonctionne ; un lien modifié d'un caractère n'affiche rien ; la liste des visites n'est pas consultable ; après `depublier`, le lien n'affiche plus rien ; temps d'ouverture du premier panorama noté.
- **Tranché le 2026-10-26 (D35) :** hébergeur Scaleway, fichiers statiques sans serveur, identifiant aléatoire, publication depuis le Mac, conservation jusqu'à dépublication, visite sans modifications.
- **À trancher pendant l'étape :** adresse des liens (nom de domaine du projet ou adresse fournie par Scaleway) ; services Scaleway exacts et coût mensuel estimé ; taille des panoramas envoyés ; bibliothèque d'envoi des fichiers et sa licence ; rangement des clés d'accès sur le Mac.
- **Tranché le 2026-10-26 (D37) :** adresse fournie par Scaleway en attendant un éventuel nom de domaine, à décider avant le jalon v1 ; Object Storage Standard en région Paris, moins d'un centime par mois et par visite, trafic gratuit jusqu'à 75 Go par mois ; panoramas de 8192 et 4096 pixels, choisis par la page ; envoi par le protocole S3 en bibliothèque standard, sans dépendance ; clés dans `~/.config/visite360/scaleway.json`, hors du dépôt. Mode d'emploi et coût dans `docs/publication.md`.

### Étape 13 : envoi depuis l'app et assemblage sur serveur

- **Contenu :** à la fin d'une visite, l'app l'envoie au serveur du projet chez Scaleway au lieu du Mac. L'envoi se fait en arrière-plan, par morceaux, et reprend où il s'était arrêté après une coupure de réseau. Le serveur vérifie que l'envoi est complet, assemble les panoramas avec le code des étapes 2 et 4, publie la visite comme à l'étape 12 et donne le lien. L'agent retrouve ses visites dans l'app et dans un espace web : état du traitement (en attente, en cours, prête, échec), lien à copier, dépublication, suppression. Les comptes agents sont créés par le propriétaire, sans inscription libre ; un agent ne voit que ses visites. Les photos d'origine restent dans un stockage privé, jamais lisible par un lien. Le Mac garde tous ses outils (`receive`, `serve`, `publier`) : le mode local reste la référence pour le développement et le secours. Un seul environnement en ligne, la **production**, utilisé par le seul propriétaire jusqu'au jalon v1 ; le Mac sert d'environnement de développement. Adresses, noms de stockage et clés sont des réglages, jamais écrits dans le code, y compris dans l'app, qui lit l'adresse de son serveur dans un réglage de compilation : un environnement d'intégration s'ajoutera sans réécrire de code (D38). Ni modifications, ni chiffrage, ni mode `/agent` en ligne : ils viennent à l'étape 15.
- **Tests automatiques :** réception d'un envoi par morceaux, reprise après coupure, refus d'un envoi incomplet ou d'un agent non connecté ; un agent ne voit ni ne supprime la visite d'un autre ; traitement relancé sans refaire ce qui est fait ; publication contre le faux stockage de l'étape 12 ; assemblage simulé ; aucune adresse, aucun nom de stockage ni aucune clé écrits dans le code. Côté app : reprise d'un envoi interrompu, sur des données générées.
- **Validation :** sur l'iPhone, en 4G, une visite de l'appartement du propriétaire prise avec l'app est envoyée, assemblée sur le serveur et ouverte par son lien sur un autre téléphone, sans passer par le Mac. Une coupure de réseau pendant l'envoi (mode avion) ne fait pas tout recommencer. Un deuxième compte de test ne voit pas la visite du premier. Temps d'envoi, temps d'assemblage et coût du mois notés.
- **À trancher avant l'étape :**
  - nom de domaine du projet : un serveur qui reçoit des connexions a besoin de sa propre adresse HTTPS (D37 laissait la question ouverte jusqu'au jalon v1). Domaine pris chez Scaleway. L'adresse reste un réglage (D37) : changer de domaine avant le jalon v1 ne coûte rien, aucun lien n'ayant été envoyé à un client ;
  - service Scaleway qui fait tourner le serveur et l'assemblage (machine louée au mois, conteneurs facturés à l'usage, tâches lancées à la demande) et coût mensuel estimé sur les tarifs publiés ;
  - connexion des agents : mot de passe, lien de connexion envoyé par e-mail (par le service d'envoi de Scaleway) ou clé d'accès remise par le propriétaire ;
  - durée de conservation des photos d'origine sur le serveur une fois les panoramas faits ;
  - numpy et OpenCV compilés pour Linux : composants LGPL et GPL embarqués à examiner avant tout déploiement (`docs/licences.md`).
- **À trancher pendant l'étape :** taille des morceaux ; dépôt des photos directement dans le stockage ou en passant par le serveur ; rangement des secrets sur le serveur (par le gestionnaire de secrets de Scaleway ou non) ; emplacement des fichiers de déploiement dans le dépôt (D15).
- **Tranché le 2026-10-27 (D39) :** domaine `hesti-scan.fr` chez Scaleway ; serveur en Serverless Containers, assemblage en Serverless Jobs, photos dans un stockage privé, réseau privé prêt pour la carte graphique de l'étape 14 ; connexion par un code envoyé par e-mail, liste fermée d'agents gérée par le propriétaire ; photos d'origine effacées 30 jours après que la visite est prête ; base de données PostgreSQL de Scaleway ; bibliothèques LGPL et GPL avec exception d'exécution acceptées sur le serveur seulement. Choix détaillés, à rediscuter en temps voulu, dans `docs/choix/etape-13.md`.

### Étape 14 : génération d'image sur une carte graphique louée

- **Contenu :** le remplacement d'un objet de l'étape 9 tourne sur une carte graphique NVIDIA louée chez Scaleway, avec le même modèle (FLUX.2 klein 4B), et non plus sur le Mac par mflux (D32). La carte s'allume à la première demande et s'éteint après un temps sans demande. La visionneuse du Mac s'en sert telle quelle : le cadre, la demande, le report dans le panorama et la fiche de modification ne changent pas, seul l'endroit du calcul change. Les vues envoyées ne passent que par le serveur du projet, jamais par un service de génération, et ne sont pas gardées sur la carte après le calcul. Le calcul sur le Mac reste possible, en secours ou sans réseau.
- **Tests automatiques :** une demande envoyée à la carte et la fiche obtenue sont les mêmes qu'avec le calcul sur le Mac ; allumage à la première demande et extinction après le délai, simulés ; message clair en français quand la carte ne répond pas, avec repli sur le Mac ; vue effacée après le calcul. Le modèle est simulé.
- **Validation :** sur l'appartement du propriétaire, le même meuble remplacé sur le Mac et sur la carte louée donne un résultat de même qualité. Temps d'une génération à froid (carte éteinte) et à chaud, coût d'une séance d'essais et coût estimé du mois notés, comparés aux 2 à 3 minutes du Mac et au prix de l'API (`docs/generation.md`).
- **À trancher avant l'étape :** type de carte graphique et mode de location (machine allumée à l'heure, service facturé à l'usage) ; logiciel qui fait tourner FLUX.2 klein sur carte NVIDIA (diffusers, licence à vérifier, D32) ; plafond de dépense mensuel et ce qui se passe quand il est atteint.
- **À trancher pendant l'étape :** réduction du temps d'allumage (modèle préchargé, image système prête) ; délai avant extinction ; résolution de la vue envoyée.

### Étape 15 : modifications et chiffrage en ligne

- **Contenu :** les outils réservés jusqu'ici au Mac passent sur le serveur, dans l'espace web de l'agent connecté : sélection au clic (étape 7), changement de couleur (étape 8), remplacement d'un objet sur la carte graphique de l'étape 14, dimensions des pièces (étape 10) et chiffrage (étape 11). La visite publiée gagne les modifications de l'agent, la bascule avant et après, et le chiffrage en fourchette. Le client regarde, il ne modifie rien. Le mode `/agent` en ligne exige d'être connecté.
- **Tests automatiques :** mêmes fiches de modification en local et sur le serveur ; un visiteur non connecté n'atteint aucune route d'écriture ; liste des fichiers d'une visite publiée avec modifications, sans photo d'origine ni fichier de travail. Les modèles sont simulés.
- **Validation :** sur l'appartement du propriétaire, depuis un navigateur hors du Wi-Fi du Mac : un mur repeint, un meuble remplacé, une pièce mesurée et chiffrée, avec un résultat aussi bon que sur le Mac ; puis le tout vu par le lien sur un téléphone en 4G. Coût du mois noté.
- **À trancher avant l'étape :** SAM 2 sur la carte graphique de l'étape 14 ou sur le processeur du serveur.
- **À trancher pendant l'étape :** grille de prix propre à chaque agent plutôt qu'à chaque visite (question ouverte de l'étape 11).

### Étape 16 : retours d'engagement pour l'agent

- **Contenu :** pour une même visite, l'agent crée un lien par client, avec un libellé de son choix. Pour chaque lien, il voit dans son espace : nombre d'ouvertures et leurs dates, durée, pièces vues et temps passé dans chacune, modifications regardées (bascule avant et après), chiffrage ouvert. La page publiée envoie ces mesures au serveur pendant la consultation. À l'ouverture, le client est informé de la mesure et peut la refuser : la visite fonctionne alors sans rien envoyer. Supprimer un lien ne touche pas les autres liens de la visite.
- **Tests automatiques :** mesures reçues, rangées par lien et totalisées ; rien n'est envoyé après un refus ; un agent ne voit que les liens de ses visites ; lien supprimé ; mesures mal formées ou envoyées en rafale refusées.
- **Validation :** le propriétaire ouvre deux liens d'une même visite sur deux téléphones, accepte la mesure sur l'un et la refuse sur l'autre. L'espace agent montre les pièces vues et les durées du premier, et rien du second.
- **À trancher avant l'étape (RGPD, à faire vérifier) :** base légale de la mesure et texte d'information au client : consentement demandé à l'ouverture, ou mesure d'audience dispensée de consentement selon les conditions de la CNIL ; durée de conservation des mesures ; contrat de sous-traitance entre le projet et les agents, qui confient au projet des données de leurs clients et des photos de logements ; détail montré à l'agent (totaux par lien ou chaque consultation).
- **À trancher pendant l'étape :** stockage des mesures chez Scaleway (base de données gérée ou fichiers) et licence du logiciel ; fréquence d'envoi depuis la page.

## Jalon v1 : présentation aux agents et premiers accès

- **Condition avant les premiers accès :** un environnement d'**intégration** chez Scaleway, séparé de la production (serveur, stockage, clés et adresse propres, par exemple `integration.<domaine>`). Une nouvelle version y est vérifiée avant de passer en production par une commande explicite, pour ne jamais toucher aux visites des agents et de leurs clients pendant le développement. L'app installée depuis Xcode vise l'intégration, celle distribuée aux agents la production (D38).
- **Contenu :** d'abord une démo de la v1 à 2 ou 3 agents immobiliers : prise d'une visite avec l'app, lien de partage, modifications, chiffrage et retours d'engagement. Puis, selon leurs retours, premiers agents qui utilisent le produit eux-mêmes, avec de vrais clients.
- **Livrable :** les retours des agents, notés dans `docs/retours-agents.md` sans données personnelles.
- **Décision :** le propriétaire décide de poursuivre, d'ajuster ou d'arrêter, et écrit ici les conditions des premiers accès.

## Hors plan, pour plus tard

- Suivi de position entre les points par la réalité augmentée du téléphone, pour placer les liens tout seuls (D14).
- Modèle 3D commun à toutes les pièces et propagation d'une modification d'un panorama à l'autre.
- Abattre une cloison. L'essai prévu (ancienne étape 9.5) est abandonné pour commercialiser au plus vite (D38).
