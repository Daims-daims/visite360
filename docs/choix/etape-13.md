# Étape 13 : choix faits avant l'étape

Validés par le propriétaire le 2026-10-27, pour avancer. À rediscuter en temps voulu. Décision correspondante : D39 dans `docs/decisions.md`.

Prix relevés le 2026-10-26 et le 2026-10-27 sur les pages publiques de Scaleway, hors taxes. Ils changent : les revérifier avant de s'y fier.

## 1. Nom de domaine

- **Choix :** `hesti-scan.fr`, acheté chez Scaleway (5,98 € HT par an pour un `.fr`). Le propriétaire fait l'achat lui-même.
- **Adresses prévues :** `api.hesti-scan.fr` pour le serveur et l'espace web des agents ; `hesti-scan.fr` comme expéditeur des e-mails de connexion. Les visites publiées gardent pour l'instant l'adresse fournie par Scaleway (D37).
- **État au 2026-10-27 :** le nom n'apparaissait pas encore au registre des `.fr` (AFNIC). Il était donc libre, ou acheté depuis quelques heures seulement.
- **À rediscuter :** l'adresse des visites publiées sous le domaine du projet, par exemple `visites.hesti-scan.fr`, avant le jalon v1 ; l'adresse de l'environnement d'intégration (`integration.hesti-scan.fr`, D38).
- **Ce qui le rend réversible :** toutes ces adresses sont des réglages (D37, D38). Changer de domaine avant le jalon v1 ne coûte rien, puisqu'aucun lien n'a été envoyé à un client.

## 2. Service qui fait tourner le serveur

- **Choix :** les services Scaleway facturés à l'usage, sans machine à entretenir :
  - **Serverless Containers** pour le serveur web. Il se met en veille au bout de 15 minutes sans demande, et Scaleway fournit le HTTPS et le domaine ;
  - **Serverless Jobs** pour l'assemblage, une tâche lancée à la demande (jusqu'à 6 processeurs, 16 Go de mémoire et 24 h) ;
  - **Object Storage**, avec un stockage privé pour les photos et les panoramas de travail, et celui de l'étape 12 pour les visites publiées ;
  - **le réseau privé de Scaleway (VPC)**, auquel le serveur est rattaché. La carte graphique de l'étape 14 y sera, sans adresse publique.
- **Coût estimé :** moins de 1 € par mois à l'activité du propriétaire. Chaque mois, 200 000 vCPU-s et 400 000 Go-s sont gratuits ; au-delà, 0,00001 € par vCPU-s et 0,000002 € par Go-s. Une visite de 8 points prendrait environ 10 000 vCPU-s, soit environ 20 visites par mois gratuites, puis environ 0,20 € par visite. C'est une estimation, à remplacer par le temps d'assemblage mesuré à la validation.
- **Options écartées :**
  - machine louée au mois sans carte graphique : DEV1-S à environ 6,42 € par mois plus l'adresse IPv4 à environ 2,92 € par mois, mais 2 Go de mémoire, trop justes pour assembler ; PLAY2-NANO (4 Go) à environ 19,71 € par mois. Dans les deux cas, les mises à jour du système et la surveillance restent à la charge du projet ;
  - une seule machine avec carte graphique qui ferait tout : L4 à 0,79 € de l'heure, environ 575 € par mois allumée en permanence.
- **Limites connues :**
  - après 15 minutes sans demande, la première réponse du serveur prend quelques secondes. Une copie toujours allumée coûterait environ 35 € par mois ;
  - Scaleway n'accepte que des images pour processeur Intel/AMD (`linux/amd64`), alors que le Mac a une puce Apple. Elles se fabriquent sur le Mac avec Podman (Apache 2.0), par émulation, donc lentement la première fois.
- **À rediscuter :** passer sur une machine louée deviendrait intéressant à forte activité continue, à partir de 100 à 200 visites par mois (estimation), ou si les temps de réveil gênent les agents. Ce serait un changement de déploiement et non de code : la même image tourne sur une machine.

### Lien avec la carte graphique louée (étapes 14 et 15)

Vérifié le 2026-10-27 :
- Scaleway ne propose pas de carte graphique facturée à l'usage. Les Serverless Containers n'ont que du processeur. Le déploiement de modèles géré par Scaleway (Generative APIs, déploiement dédié) est facturé à l'heure même sans demande, et n'accepte un modèle à soi que par programme ;
- l'étape 14 passera donc par une machine avec une carte L4 (24 Go de mémoire graphique, 0,79 € HT de l'heure, zone Paris 1), allumée et éteinte par l'interface de programmation de Scaleway. Facturation à la minute, démarrage compris, selon la FAQ de Scaleway. Une fois éteinte, son disque reste facturé : 125 Go au minimum pour le système prévu pour les cartes graphiques, environ 11 € par mois ;
- un conteneur peut appeler une machine du même réseau privé, mais pas l'inverse : la carte répondra directement à la demande, ou déposera son résultat dans le stockage ;
- le temps d'allumage n'est publié nulle part. Estimation : 2 à 5 minutes pour une première génération à froid, 10 à 30 secondes ensuite. À mesurer à l'étape 14 ;
- une machine éteinte libère peut-être sa carte : au rallumage, il faudrait alors en retrouver une libre, et les L4 sont parfois en rupture. Non confirmé, à vérifier en premier à l'étape 14.

Ce que l'étape 13 prévoit pour l'étape 14, sans la coder :
- des traitements génériques : la file d'attente et les états (en attente, en cours, prête, échec) servent à l'assemblage et serviront à la génération ;
- le serveur rattaché au réseau privé ;
- des clés aux droits séparés, celle qui allumera la carte à côté de celle du stockage ;
- le même outillage d'images dans `deploiement/`.

## 3. Connexion des agents

- **Choix :** un code à 6 chiffres envoyé par e-mail, valable 10 minutes, par le service d'envoi de Scaleway (Transactional Email, 300 e-mails gratuits par mois, puis 0,25 € les 1 000). La session dure ensuite longtemps : dans le trousseau de l'iPhone pour l'app, par un cookie pour l'espace web. Aucun mot de passe.
- **Liste fermée :** le propriétaire gère depuis le Mac la liste des adresses autorisées (`visite360 compte`). Pour une adresse qui n'est pas dans la liste, l'écran affiche le même message neutre et aucun e-mail ne part : personne ne peut s'inscrire seul, ni savoir qui est client.
- **Options écartées :**
  - mot de passe : il faut le stocker, et une réinitialisation par e-mail serait de toute façon nécessaire ;
  - clé d'accès remise par le propriétaire : simple pour l'app, mais pénible sur le web, et c'est un secret de plus à transmettre à chaque agent ;
  - lien de connexion qui ouvre directement l'app : il exige le compte développeur Apple payant (« liens universels »). Le lien cliquable ne sert donc qu'au web ; l'app demande de taper le code.
- **Prérequis :** déclarer `hesti-scan.fr` au service d'envoi de Scaleway, avec les enregistrements DNS qui prouvent que les e-mails viennent bien du domaine (SPF, DKIM).
- **À rediscuter :** ce que deviennent les visites d'un agent retiré de la liste (tout supprimer et dépublier, ou garder les visites en ligne et bloquer seulement la connexion) ; la durée d'une session.

## 4. Conservation des photos d'origine

- **Choix :** 30 jours après que la visite est prête, puis le serveur les efface tout seul. `capture.json` et `visite.json` sont gardés : petits, ils resserviront à l'étape 15 (hauteur de l'objectif, liens). Les panoramas sont gardés tant que la visite existe. Supprimer une visite efface tout de suite tout ce qui la concerne.
- **Raisons :** 30 jours laissent le temps de refaire un assemblage raté ; au-delà, les photos sont des données personnelles qui ne servent plus.
- **À rediscuter :** la durée, avec le contrat de sous-traitance prévu avant l'étape 16.

## 5. Licences sur Linux

- **Constat :** sur Linux, Python lui-même s'appuie sur la bibliothèque C du système, glibc, qui est sous LGPL. Le paquet numpy pour Linux embarque aussi libgfortran (GPL 3 avec exception pour les bibliothèques d'exécution de GCC) et libquadmath (LGPL 2.1). La règle « LGPL jamais liée » est donc inapplicable telle quelle sur un serveur Linux.
- **Choix :** sur le serveur seulement, les bibliothèques LGPL, et GPL avec exception d'exécution, sont acceptées quand elles sont utilisées sans modification et jamais distribuées : le code tourne sur le serveur du projet, rien n'est remis aux agents. OpenCV reste compilé sans FFmpeg, par le même script que sur le Mac.
- **Option écartée :** recompiler numpy sans OpenBLAS pour retirer libgfortran et libquadmath. glibc resterait, et la décision serait nécessaire de toute façon.
- **À rediscuter :** avec un juriste avant la mise en vente, comme tout le registre (`docs/licences.md`). L'app installée sur les téléphones des agents, elle, est distribuée : la règle stricte continue de s'y appliquer.

## 6. Base de données

- **Choix (ajouté le 2026-10-27) :** la base de données Serverless SQL de Scaleway (PostgreSQL) dès l'étape 13, pour les agents, les codes, les sessions, les visites et les traitements. Elle se met en veille sans demande : environ 0,14 € de l'heure d'activité, plus quelques centimes par mois de stockage.
- **Bibliothèque :** pg8000 1.31.6 (BSD 3 clauses), avec ses dépendances scramp (MIT-0), asn1crypto (MIT), python-dateutil (Apache 2.0 ou BSD), six (MIT) et tzdata (Apache 2.0). Installées seulement sur le serveur. psycopg, l'autre bibliothèque courante, est sous LGPL 3.
- **MIT-0 :** la licence MIT sans obligation de citer l'auteur, plus permissive que MIT. Ajoutée à la liste autorisée par le propriétaire le 2026-10-27.
- **Sur le Mac et dans les tests :** la même base, en SQLite, fournie avec Python, avec les mêmes requêtes. Aucune dépendance de plus sur le Mac.
- **Option écartée :** ranger comptes et visites en fichiers JSON dans le stockage. C'est plus simple, mais il faut alors une seule copie du serveur pour éviter deux écritures en même temps. La solution ne tient que pour quelques dizaines d'agents, et l'étape 16 aura besoin d'une base de toute façon.

## Questions laissées pour pendant l'étape

- taille des morceaux d'un envoi : une photo de quelques Mo par morceau ;
- photos déposées directement dans le stockage, par des adresses temporaires signées, ou en passant par le serveur ;
- rangement des secrets sur le serveur : gestionnaire de secrets de Scaleway ou non ;
- emplacement des fichiers de déploiement dans le dépôt (D15).

## Sources

- Tarifs Serverless (Containers et Jobs) : scaleway.com/en/pricing/serverless/
- Limites des Jobs : scaleway.com/en/docs/serverless-jobs/reference-content/jobs-limitations/
- Limites des Containers : scaleway.com/en/docs/serverless-containers/reference-content/containers-limitations/
- Containers et réseau privé : scaleway.com/en/docs/serverless-containers/reference-content/containers-private-networks/
- Tarifs des machines : scaleway.com/en/pricing/virtual-instances/
- Tarifs des cartes graphiques : scaleway.com/en/pricing/gpu/
- Facturation à la minute des cartes graphiques : scaleway.com/en/docs/faq/instances/
- Tarifs des déploiements dédiés : scaleway.com/en/pricing/deployment/
- Service d'envoi d'e-mails : scaleway.com/en/pricing/managed-services
- Domaines : scaleway.com/en/domain
- Base de données Serverless SQL : scaleway.com/en/pricing/managed-databases/
- Licences de pg8000 et scramp : fichiers LICENSE des sources publiées sur PyPI (pg8000 1.31.6, scramp 1.5.0)
