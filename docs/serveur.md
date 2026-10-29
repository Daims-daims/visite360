# Serveur du projet : envoi depuis l'app, assemblage et lien de partage

Étape 13. L'app de l'iPhone envoie une visite au serveur du projet chez Scaleway, sans passer par le Mac. Le serveur l'assemble, la publie comme à l'étape 12 et donne le lien. Choix et coûts : décision D39 et `docs/choix/etape-13.md`.

## Le principe

Trois pièces, toutes chez Scaleway, en région Paris :

- **le serveur** (`visite360 serveur`), qui tourne dans un conteneur facturé à l'usage (Serverless Containers). Un conteneur est un programme emballé avec tout ce dont il a besoin. Celui-ci s'éteint au bout de 15 minutes sans demande et se rallume en quelques secondes à la suivante. Il gère la connexion des agents, reçoit l'annonce des envois, tient la liste des visites et sert l'espace web des agents. Il ne fait aucun calcul lourd ;
- **l'assemblage** (`visite360 traiter`), une tâche lancée à la demande (Serverless Jobs), avec la même image que le serveur. Le serveur la lance à la fin de chaque envoi, et une programmation la relance une fois par jour au cas où un lancement se serait perdu. Elle assemble les panoramas avec le code des étapes 2 et 4, publie la visite, puis s'arrête ;
- **le stockage** : un stockage **privé**, jamais lisible par un lien, pour les photos d'origine et les panoramas de travail, et le stockage de l'étape 12 pour les visites publiées. S'y ajoute une **base de données** (PostgreSQL, Serverless SQL), qui garde les agents, les sessions, les visites et l'état des traitements.

### Un envoi, pas à pas

1. Dans l'app, « Envoyer au serveur ». L'app annonce la liste des fichiers de la visite, avec leur taille et leurs empreintes. Une empreinte est un résumé du fichier qui change si un seul octet change.
2. Pour chaque fichier qui lui manque, le serveur répond par une **adresse de dépôt temporaire**, signée avec la clé du stockage, valable 6 heures et seulement pour ce fichier-là. L'app dépose chaque photo directement dans le stockage privé, sans passer par le serveur. C'est un « morceau » de l'envoi.
3. Les dépôts se font par la session d'envoi en arrière-plan d'iOS. L'envoi continue quand l'app passe en arrière-plan, et iOS le reprend tout seul après une coupure de réseau. Si l'app est fermée de force, iOS annule les dépôts : « Reprendre l'envoi » refait l'annonce, et seuls les fichiers absents du stockage repartent.
4. Quand tout est déposé, l'app demande la fin de l'envoi. Le serveur vérifie, dans la liste du stockage, que chaque fichier est là avec la bonne empreinte. Il relit `visite.json` et les `capture.json`, met l'assemblage en attente et lance la tâche.
5. La tâche assemble chaque point, range le panorama dans le stockage privé dès qu'il est prêt, puis publie la visite. Relancée, elle reprend les panoramas déjà faits au lieu de les refaire.
6. L'agent suit l'état dans l'app (« Mes visites en ligne ») ou dans l'espace web : **Envoi en cours**, **En attente**, **Assemblage en cours** (avec le point en cours), **Prête** (avec le lien) ou **Échec** (avec la raison).

Le stockage refuse un fichier arrivé abîmé : son empreinte est fixée par l'adresse de dépôt. Un point déjà reçu avec une autre prise de vue est refusé, sans rien écraser (D9). Il faut renommer le point dans l'app.

### Connexion des agents

- Le propriétaire tient la **liste fermée** des adresses autorisées, depuis le Mac (voir plus bas).
- Pour se connecter, l'agent donne son adresse. Si elle est dans la liste, il reçoit par e-mail un **code à 6 chiffres**, valable 10 minutes. Sinon, rien ne part, et l'écran affiche le même message : on ne révèle pas qui est client.
- Un code ne sert qu'une fois. Cinq essais faux l'annulent. Au plus un code par minute et cinq par heure pour une même adresse.
- La session dure 90 jours. Dans l'app, elle est gardée dans le trousseau de l'iPhone ; sur le web, dans un cookie que la page elle-même ne peut pas lire.
- Codes et sessions ne sont rangés dans la base que sous forme d'empreinte : une copie volée de la base ne permet pas de se connecter.
- Un agent ne voit que ses visites. Celle d'un autre répond « introuvable ».

### Ce qui reste et ce qui s'efface

- Les **photos d'origine** sont effacées du stockage privé **30 jours** après que la visite est prête (D39). `visite.json`, les `capture.json`, les panoramas et les rapports d'assemblage restent tant que la visite existe. Renvoyer la visite ensuite ne redemande pas les photos des points déjà assemblés.
- **Dépublier** retire la visite d'Internet. Une nouvelle publication aura un autre lien.
- **Supprimer** efface tout, en ligne comme sur le serveur. La visite reste sur le téléphone.
- Retirer un agent de la liste ferme ses sessions et bloque sa connexion. Ses visites restent : ce qu'elles deviennent est une question ouverte de l'étape 13.

## Gérer les agents, depuis le Mac

L'adresse de la base se règle une fois, dans la clé `base` de `~/.config/visite360/scaleway.json`, ou dans la variable `VISITE360_BASE` :

```bash
visite360 compte ajouter agent@exemple.fr
visite360 compte liste
visite360 compte retirer agent@exemple.fr
```

## Essayer sur le Mac, sans Scaleway

Le mode local fait tourner le serveur sur le Mac. La base est un fichier SQLite, les stockages sont des dossiers, sous `visites/.serveur/`. Les codes de connexion s'affichent dans le Terminal au lieu de partir par e-mail. L'assemblage tourne dans le serveur, une visite à la fois. Les visites publiées sont servies à l'adresse `/v/…` du Mac.

```bash
visite360 compte ajouter moi@exemple.fr --local
visite360 serveur --local
```

Le serveur affiche son adresse, par exemple `http://192.168.1.20:8080`. L'espace web s'ouvre à cette adresse, sur le Mac ou sur un téléphone du même Wi-Fi. Pour l'app, mettre cette adresse dans `app/Config/Local.xcconfig` (voir `docs/app.md`), puis réinstaller l'app.

## Mettre en ligne chez Scaleway, une fois

Dans la console de Scaleway (console.scaleway.com), projet du stockage de l'étape 12, région **Paris (fr-par)**. Les noms entre chevrons sont à choisir.

1. **Domaine** : Domains and DNS → acheter `hesti-scan.fr` (5,98 € HT par an).
2. **Stockage privé des photos** : Object Storage → Create bucket, visibilité **privée**, nom neutre, par exemple `photos-<quelque chose>`. Le stockage des visites publiées est celui de l'étape 12.
3. **Base de données** : Databases → Serverless SQL Database → créer `visite360`. Noter son adresse (`<identifiant>.pg.sdb.fr-par.scw.cloud`).
4. **Clé d'accès du serveur** : IAM → Applications → créer `visite360-serveur`, avec une politique limitée au projet qui donne `ObjectStorageFullAccess`, `ContainerRegistryFullAccess`, `ServerlessSQLDatabaseReadWrite`, `ServerlessJobsFullAccess` et `TransactionalEmailEmailApiAccess`, puis générer une clé API. La clé secrète ne s'affiche qu'une fois. Une seconde application, `visite360-tache`, peut se limiter au stockage et à la base.
5. **Envoi des e-mails** : Transactional Email → ajouter le domaine `hesti-scan.fr`. Scaleway donne les enregistrements DNS qui prouvent que les e-mails viennent du domaine (SPF, DKIM) : les ajouter dans Domains and DNS, puis attendre la vérification. L'adresse d'envoi sera par exemple `connexion@hesti-scan.fr`.
6. **Secrets** : trois valeurs ne doivent jamais apparaître en clair : la clé secrète (`SCW_SECRET_KEY`), l'adresse de la base (`VISITE360_BASE`, qui contient un mot de passe) et le mot de passe SMTP (`VISITE360_SMTP_MOT_DE_PASSE`). Elles se donnent différemment au conteneur et à la tâche :
   - **conteneur du serveur** : dans son formulaire, section **variables d'environnement secrètes** (« Secret environment variables »). On y tape la valeur ; Scaleway la chiffre et ne l'affiche plus ensuite. Pas besoin de Secret Manager ;
   - **tâche d'assemblage** : Scaleway n'accepte ses secrets que par **Secret Manager**. Créer un secret par valeur (nom libre, par exemple `scw-secret-key` et `visite360-base`), **puis une version** qui contient la valeur : un secret sans version ne peut pas être choisi. Dans le formulaire de la tâche, ajouter une référence de secret et lui donner le nom de la variable. La tâche n'a besoin que de `SCW_SECRET_KEY` et de `VISITE360_BASE`.
7. **Réseau privé** : VPC → Private Networks → créer `visite360` en Paris. Il servira à la carte graphique de l'étape 14.
8. **Espace d'images** : Container Registry → créer un espace privé, par exemple `<espace>`. L'image du serveur se fabrique pour Intel/AMD, ce que ton Mac (puce Apple) ne sait faire que par émulation : plusieurs heures. Deux voies :

   - **Par GitHub, recommandée (rapide, sans clé chez GitHub).** Lancer la fabrication, puis attendre qu'elle finisse :

     ```bash
     gh workflow run image.yml --ref <branche>
     ```

     Elle tourne chez GitHub sur une machine Intel/AMD, sans émulation (la première fois, 15 à 30 minutes environ, estimation non mesurée ; ensuite OpenCV vient du cache). Elle se lance aussi toute seule sur une pull request qui modifie `deploiement/`. L'image n'est envoyée nulle part : elle reste 2 jours comme fichier téléchargeable. Puis, sur le Mac, avec `gh` connecté et Podman installé :

     ```bash
     bash deploiement/envoyer.sh rg.fr-par.scw.cloud/<espace>
     ```

     Le script télécharge la dernière image réussie de la branche courante, la charge et l'envoie chez Scaleway. **La clé de Scaleway reste sur le Mac** : GitHub n'en reçoit aucune (D37).
   - **Sur le Mac seulement**, avec Podman (secours) : `bash deploiement/construire.sh rg.fr-par.scw.cloud/<espace>`. OpenCV est compilé par émulation : de une heure à plusieurs heures selon l'émulateur (estimation). Donner d'abord 8 Go à la machine virtuelle de Podman (2 Go par défaut, trop peu) : `podman machine stop && podman machine set --memory 8192 && podman machine start`. Sinon la compilation s'arrête avec « Killed signal terminated program cc1plus », ce qui veut dire mémoire pleine ; le script le vérifie avant de commencer.
9. **Tâche d'assemblage** : Serverless → Jobs → créer `visite360-assemblage` avec l'image envoyée, la commande `visite360 traiter`, 4 vCPU, 12 Go de mémoire, durée maximale 6 h. Ajouter une programmation quotidienne (par exemple `0 4 * * *`), puis les variables du tableau ci-dessous, sauf `VISITE360_JOB` et les réglages SMTP. Noter l'identifiant de la tâche.
10. **Serveur** : Serverless → Containers → créer `visite360-serveur` avec la même image, port 8080, minimum 0 et maximum 2 copies, 1 vCPU et 1 Go de mémoire, rattaché au réseau privé `visite360`. Ajouter toutes les variables du tableau. Dans « Custom domains », ajouter `api.hesti-scan.fr` et créer l'enregistrement DNS demandé. Scaleway fournit le certificat HTTPS.
11. **Premier agent**, sur le Mac : ajouter la clé `"base": "<adresse de la base>"` dans `~/.config/visite360/scaleway.json`, puis `visite360 compte ajouter <votre adresse>`.

### Réglages (variables d'environnement)

| Variable | Rôle | Serveur | Tâche |
|---|---|---|---|
| `VISITE360_BASE` (secret) | adresse de la base : `postgresql://<identifiant de l'application>:<clé secrète>@<adresse de la base>:5432/visite360` | oui | oui |
| `SCW_ACCESS_KEY` | clé d'accès de Scaleway | oui | oui |
| `SCW_SECRET_KEY` (secret) | clé secrète de Scaleway | oui | oui |
| `VISITE360_DEPOT` | nom du stockage privé des photos | oui | oui |
| `VISITE360_BUCKET` | nom du stockage des visites publiées (étape 12) | oui | oui |
| `VISITE360_ADRESSE_VISITES` | facultatif : adresse de base des liens publiés (D37) | oui | oui |
| `VISITE360_ADRESSE_API` | adresse publique du serveur : `https://api.hesti-scan.fr` | oui | oui |
| `VISITE360_JOB` | identifiant de la tâche d'assemblage | oui | non |
| `VISITE360_SMTP_HOTE` | `smtp.tem.scw.cloud` | oui | non |
| `VISITE360_SMTP_PORT` | `587` (par défaut) | oui | non |
| `VISITE360_SMTP_UTILISATEUR` | identifiant du projet Scaleway | oui | non |
| `VISITE360_SMTP_MOT_DE_PASSE` (secret) | clé secrète autorisée à envoyer des e-mails | oui | non |
| `VISITE360_EXPEDITEUR` | adresse d'envoi des codes, par exemple `Visite360 <connexion@hesti-scan.fr>` | oui | non |

Un réglage manquant donne au démarrage un message qui le nomme (le conteneur s'arrête alors avec « Container crashed with exit code 1 » et ce message dans ses journaux). Aucune de ces valeurs n'est écrite dans le code ni dans l'app (D38). Ajouter un environnement d'intégration revient à refaire ces étapes avec d'autres noms.

Les noms des droits IAM, le format exact de l'adresse de la base et les réglages SMTP viennent de la documentation de Scaleway et n'ont pas été essayés avec le compte du propriétaire : à confirmer à la première mise en ligne.

### Mettre à jour

Après une fusion dans `main` : relancer la fabrication de l'image (étape 8, voie GitHub : `gh workflow run image.yml --ref main`, puis `bash deploiement/envoyer.sh …`), puis donner la nouvelle étiquette d'image au conteneur et à la tâche dans la console.

## Coût

Tarifs publics de Scaleway, hors taxes, relevés le 2026-10-27 :

| Poste | Tarif | À l'usage du propriétaire |
|---|---|---|
| Domaine `.fr` | 5,98 € par an | 0,50 € par mois |
| Conteneur du serveur | 0,00001 € par vCPU-s et 0,000002 € par Go-s, 200 000 vCPU-s et 400 000 Go-s gratuits par mois (part commune avec la tâche) | gratuit : il dort sans demande |
| Tâche d'assemblage | mêmes tarifs | environ 10 000 vCPU-s par visite de 8 points (estimation) : une vingtaine de visites par mois dans la part gratuite, puis environ 0,20 € par visite |
| Base Serverless SQL | 0,136 € par heure d'activité, 5 minutes au minimum | quelques dizaines de centimes |
| Stockage privé | 0,016 € par Go et par mois | environ 1 Go par visite pendant 30 jours, puis 40 Mo |
| E-mails | 300 gratuits par mois | gratuit |
| Espace d'images, secrets | quelques centimes par mois | quelques centimes |

Soit **moins de 1 € par mois** en plus du domaine, à mesurer pendant la validation.

Temps mesurés le 2026-10-27, en mode local sur le MacBook Air M4, avec une visite de synthèse de 2 points de 30 photos : assemblage et publication en 146 à 155 s. Le temps sur la tâche de Scaleway reste à mesurer.

## Ce qu'il faut vérifier avec le vrai compte et un vrai téléphone

- envoi d'une visite de l'appartement depuis l'iPhone en 4G, puis lien ouvert sur un autre téléphone, sans passer par le Mac ;
- mode avion pendant l'envoi : l'envoi reprend sans tout recommencer ;
- un deuxième compte de test ne voit pas la visite du premier ;
- l'e-mail du code arrive, et pas dans les indésirables (dépend de SPF et DKIM) ;
- temps d'envoi, temps d'assemblage sur la tâche et coût du mois.

## Mauvais résultats et causes probables

| Symptôme | Cause probable |
|---|---|
| Pas d'e-mail de code | adresse absente de la liste (`visite360 compte liste`), domaine pas encore vérifié dans Transactional Email, ou e-mail rangé dans les indésirables |
| « Code faux ou expiré » | code de plus de 10 minutes, ou un code plus récent a été demandé : seul le dernier fonctionne |
| L'envoi reste à « Fichier 0 sur N » | pas de réseau, ou adresse du serveur mal réglée dans l'app (`Local.xcconfig`) |
| « Le stockage a refusé … » | adresse de dépôt expirée (plus de 6 heures) : reprendre l'envoi |
| « Envoi incomplet » | des dépôts n'ont pas abouti : reprendre l'envoi |
| « autre prise de vue » | un point du même nom a déjà été reçu avec d'autres photos : renommer le point dans l'app |
| Reste « En attente » | la tâche n'a pas pu être lancée (droits de la clé, `VISITE360_JOB`) : elle partira à la programmation quotidienne ; voir les journaux de la tâche dans la console |
| « Échec » avec un message d'assemblage | même cause que sur le Mac (étape 2) : prise de vue, recouvrement insuffisant |
| La fabrication de l'image s'arrête sur « Killed signal terminated program cc1plus » | mémoire pleine dans la machine virtuelle de Podman : lui donner 8 Go (voir l'étape 8), ou baisser `CMAKE_BUILD_PARALLEL_LEVEL` dans `deploiement/Containerfile` |
| Première ouverture de l'espace web lente | le serveur dormait : il se réveille en quelques secondes |
