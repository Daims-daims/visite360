# Publier une visite et la partager par lien

Étape 12. Une visite assemblée sur le Mac est mise en ligne chez Scaleway, puis s'ouvre dans le navigateur de n'importe quel téléphone ou ordinateur, sans app ni compte. Décisions D35 et D36.

## Le principe

- `visite360 publier` copie dans un **stockage de fichiers** de Scaleway (Object Storage, en France, région Paris) une version de la visionneuse **en lecture seule**, la liste des points et des flèches, et les panoramas. Aucun programme ne tourne chez Scaleway : le navigateur du visiteur lit ces fichiers comme il lirait des images sur un site.
- Ce qui part : `index.html` (la page), Pannellum (la visionneuse 360°), `info.json` (noms des points, flèches, tailles des panoramas), `status.json` et, pour chaque point, `panorama.jpg` (8192 pixels de large) et `panorama-mobile.jpg` (4096 pixels). La page choisit la taille que l'appareil sait afficher, comme en local.
- Ce qui ne part **jamais** : les photos d'origine, `visite.json`, `capture.json`, `rapport.json`, `piece.json`, les sélections, recolorations et remplacements (`modifications/`). La liste des fichiers envoyés est fermée : un fichier qui n'y est pas ne peut pas partir.
- La visite en ligne n'a ni sélection, ni couleur, ni remplacement d'objet, ni mesure, ni affichage des angles : ces outils ont besoin du Mac. Ils viendront en ligne à l'étape 13.

## Le lien

Le lien ressemble à :

```
https://<bucket>.s3.fr-par.scw.cloud/X9qohliWDJmSd480jcxGCw/index.html
```

- `<bucket>` est le nom du stockage, choisi à sa création. Il se voit dans le lien : prendre un nom neutre, sans nom de client.
- `X9qohliWDJmSd480jcxGCw` est un **identifiant tiré au hasard** (128 bits, environ 3 × 10³⁸ possibilités) : c'est la seule clé de la visite. Impossible à deviner, mais quiconque a le lien voit la visite. Ne le transmettre qu'aux personnes voulues.
- L'identifiant est rangé dans `visites/<visite>/publication.json`. Republier garde le même lien.
- La liste des visites du stockage n'est pas consultable : chaque fichier est lisible par tous, mais le stockage lui-même reste privé. Un `robots.txt` à la racine du stockage et une balise `noindex` dans la page demandent aux moteurs de recherche de ne rien indexer.
- Un nom de domaine du projet (`https://visites.<domaine>/…`) pourra remplacer l'adresse de Scaleway avant le jalon v1 : il suffira d'ajouter `"adresse": "https://visites.<domaine>"` au fichier de réglages et de configurer Edge Services chez Scaleway. Les liens déjà envoyés avec l'ancienne adresse cesseront de fonctionner.

## Préparer Scaleway, une fois

Dans la console de Scaleway (console.scaleway.com) :

1. **Créer le stockage** : Object Storage → Create bucket. Région **Paris (fr-par)**, visibilité **privée** (« Private »). Nom neutre, par exemple `visites-<quelque chose>` : il doit être unique chez Scaleway.
2. **Créer une clé d'accès** : IAM → Applications → créer une application `visite360-publication`, lui donner une politique avec le droit `ObjectStorageFullAccess` limité au projet du stockage, puis Générer une clé API pour cette application. Noter la clé d'accès (commence par `SCW`) et la clé secrète : la clé secrète ne s'affiche qu'une fois.
3. **Enregistrer les réglages sur le Mac**, environnement du projet activé :

```bash
visite360 publier --configurer
```

La commande demande la clé d'accès, la clé secrète (qui ne s'affiche pas pendant la frappe) et le nom du stockage, puis les range dans `~/.config/visite360/scaleway.json`, lisible par votre seul compte du Mac, **hors du dépôt**. Ne jamais copier ce fichier dans le dépôt ni l'envoyer.

En secours, les variables d'environnement `SCW_ACCESS_KEY`, `SCW_SECRET_KEY` et `VISITE360_BUCKET` passent avant le fichier.

## Publier, republier, retirer

```bash
visite360 publier visites/<visite>
```

La commande affiche chaque fichier envoyé, puis le lien. Les panoramas doivent déjà exister (`visite360 serve` les assemble). Relancer après un changement (panorama refait, flèche ajoutée dans `visite.json`) n'envoie que ce qui a changé, et retire en ligne ce qui n'existe plus. Une publication interrompue (réseau coupé) se reprend en relançant la même commande, avec le même lien.

```bash
visite360 depublier visites/<visite>
```

Supprime tous les fichiers de la visite chez Scaleway, vérifie qu'il n'en reste aucun, et oublie l'identifiant : le lien n'affiche plus rien, et une nouvelle publication aura un autre lien. C'est ainsi qu'on révoque un lien transmis par erreur.

## Coût

Tarifs publiés par Scaleway, relevés le 2026-10-26, hors taxes, région Paris :

| Poste | Tarif | Pour une visite de 8 points |
|---|---|---|
| Stockage (Standard Multi-AZ) | 0,016 € par Go et par mois | environ 40 Mo (4 Mo par panorama de 8192 pixels, 1 Mo par copie de 4096), soit **moins de 0,001 € par mois** |
| Requêtes, envoi depuis le Mac | inclus | 0 € |
| Trafic vers les visiteurs | 75 Go gratuits par mois, puis 0,01 € par Go | une visite parcourue en entier charge 8 Mo (copies de 4096 pixels) à 35 Mo (8192 pixels) selon l'appareil : au moins 2 000 parcours gratuits par mois, puis moins d'un millième d'euro chacun |

Un nom de domaine du projet ajouterait Edge Services (offre Starter : 0,99 € par mois, certificat en plus) et le domaine lui-même (une dizaine d'euros par an).

## Ce qu'il faut vérifier sur un vrai téléphone

1. Publier la visite de l'appartement, ouvrir le lien sur un téléphone **en 4G, Wi-Fi coupé** : la visite s'affiche, les flèches mènent d'un point à l'autre. Noter le temps d'ouverture du premier panorama.
2. Modifier un caractère de l'identifiant dans le lien : la page affiche une erreur de Scaleway (« NoSuchKey » ou « AccessDenied »), pas la visite.
3. Ouvrir `https://<bucket>.s3.fr-par.scw.cloud/` : erreur « AccessDenied », pas la liste des visites.
4. `visite360 depublier`, puis rouvrir le lien : erreur, plus de visite.

## Mauvais résultats et causes probables

- **« Scaleway refuse les clés d'accès »** : clé mal recopiée, clé supprimée, ou application sans droit sur le stockage. Refaire `visite360 publier --configurer`.
- **« Le stockage … n'existe pas »** : nom du stockage mal recopié, ou stockage créé dans une autre région que Paris.
- **« Scaleway est injoignable »** : pas d'Internet sur le Mac. Relancer une fois connecté, rien n'est perdu.
- **La page s'ouvre mais reste noire ou indique « Impossible de charger la visite »** sur un vieux téléphone : panorama trop grand pour sa carte graphique ; à signaler avec le modèle du téléphone.
- **Ouverture lente en 4G** : un iPhone récent charge sans doute la version de 8192 pixels (environ 4 Mo par point, contre 1 Mo pour la copie de 4096). Si c'est trop lent, réduire la taille envoyée (question ouverte de l'étape 12).
