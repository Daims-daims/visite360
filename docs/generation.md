# Remplacer un objet par génération d'image

Étape 9. Dans la visite, on encadre un meuble et on écrit ce qu'il faut en faire : un modèle d'IA qui tourne sur le Mac refait l'image, et seul l'intérieur du cadre entre dans le panorama (D31). Le modèle est FLUX.2 [klein] 4B de Black Forest Labs, gratuit à faire tourner soi-même (licence Apache 2.0).

## Installer le modèle

Une fois, environnement virtuel du projet activé :

```bash
bash scripts/installer-generation.sh
```

Le script crée un environnement Python à part dans `~/.cache/visite360/generation/` (420 Mo) et y installe mflux, le programme qui fait tourner le modèle sur la puce graphique du Mac, aux versions de `scripts/generation-requirements.txt`. Il télécharge ensuite les poids du modèle, 15 Go, dans `~/.cache/visite360/modeles/huggingface/`, et vérifie leurs empreintes. Relancé, il ne retélécharge rien. `visite360 doctor` dit si le modèle est prêt.

Il faut un Mac à puce Apple et environ 17 Go de mémoire libre pendant une génération : fermer les applications gourmandes.

## Remplacer un objet

1. Lancer la visite : `visite360 serve visites/<visite>`, puis ouvrir l'adresse affichée.
2. Regarder l'objet, d'assez près pour qu'il remplisse une bonne partie de l'écran.
3. **Remplacer un objet**, puis tracer un cadre autour de l'objet **en entier**, pieds et accoudoirs compris, avec un peu de marge.
4. Écrire **ce qu'il faut faire**, comme on le dirait à quelqu'un, en nommant l'objet :
   - « Remplace le canapé gris par un canapé en velours vert » ;
   - « Retire complètement le meuble blanc et ce qui est posé dessus, montre le sol et le mur vides » ;
   - « Ajoute un four encastré sous les plaques ».

   Les suggestions sous le champ donnent le début de la phrase : remplacer « … » par le nom de l'objet.
5. **Générer**. Le suivi, en haut de l'écran, montre les 4 passes du calcul. On peut continuer la visite pendant ce temps. Sur le MacBook Air M4, une génération prend 2 à 3 minutes.

À la fin, la visite montre le panorama modifié. **Voir l'original** compare avec l'avant.

- **Remplacements**, puis **Refaire** : un autre essai avec le même cadre et la même consigne. Le résultat change à chaque fois : le modèle part d'un tirage au hasard (la « graine »). L'essai repart de la photo sans ce remplacement, et il le remplace s'il réussit.
- **Supprimer** annule un remplacement. Le panorama d'origine n'est jamais modifié (D9).
- Une seule génération à la fois.
- Si le modèle n'a presque rien changé dans le cadre, rien n'est enregistré et la visionneuse le dit. C'est le plus souvent une instruction qui ne dit pas clairement quoi faire : la reformuler, ou relancer.
- Les recolorations de l'étape 8 et les remplacements se combinent : les couleurs d'abord, puis les remplacements, dans l'ordre de leur numéro.

## Comment ça marche

1. **Une vue autour du cadre.** Le modèle a appris sur des photos ordinaires, pas sur des panoramas, dont les lignes droites sont courbées. Le serveur découpe donc dans le panorama une vue carrée de 1024 pixels, centrée sur le cadre. Le cadre en occupe le milieu, avec 20 % de marge de chaque côté : le modèle voit la pièce autour du meuble (lumière, perspective, sol), et le meuble y tient en entier. La vue est prise dans le panorama modifié s'il existe : un mur repeint reste repeint autour du nouvel objet.
2. **Le modèle refait la vue d'après la consigne.** Il part d'un brouillard de points aléatoires et le nettoie en 4 passes, guidé par la vue et par la consigne : votre instruction, suivie de « Le changement se fait au centre de l'image. Garde le reste de la pièce, la lumière et la perspective identiques. »
3. **On ne garde que le cadre.** Le modèle retouche souvent un peu toute l'image : on jette tout ce qui est hors du cadre. Dans une bande de 40 pixels autour du cadre, où la photo et l'image générée montrent la même chose, on mesure leur écart de couleur et de contraste et on le corrige. Le bord du cadre s'adoucit sur 24 pixels vers l'intérieur.
4. **Vérification.** Si l'intérieur du cadre n'a pas changé plus que le reste de la vue, le modèle n'a pas suivi l'instruction : la génération n'est pas enregistrée.
5. **Report dans le panorama.** L'intérieur du cadre est reporté à sa place dans le panorama. Hors du cadre, aucun pixel ne change.

L'image générée est gardée : refaire le panorama modifié (après une recoloration, par exemple) ne relance pas le modèle.

## Ce qui marche bien, ce qui marche mal

Essai du 2026-10-25 sur 11 meubles des visites du propriétaire :

- **Bien :** un meuble isolé remplacé par un autre (bibliothèque, chaise, buffet, vitrine, fauteuil, canapé, lit). Les objets posés dessus ou devant sont souvent conservés : livres, coussins, plaid, guitare.
- **Moins bien :**
  - une scène encombrée : le modèle peut faire disparaître ce qui est dans le cadre (un chat sur une table, des objets) ;
  - une grande surface (toutes les façades d'une cuisine) : il en oublie des parties ou modifie un élément voisin (la hotte).
- **Mauvais résultat et sa cause :**
  - **un morceau de l'ancien meuble dépasse** : le cadre ne le prenait pas en entier. Le retracer plus large ;
  - **un trait net ou un changement de teinte au bord du cadre** : le cadre coupe un objet ou une ombre. Le tracer sur du mur ou du sol uni ;
  - **rien n'a changé** (« Le modèle n'a presque rien changé ») : l'instruction ne disait pas clairement quoi faire. Écrire un verbe (remplace, retire, ajoute) et nommer l'objet ; « Met un four » à la place d'un « vide » n'a rien donné à l'essai ;
  - **le mauvais objet a changé** : l'instruction était ambiguë. Nommer l'objet par sa couleur et sa matière ;
  - **résultat flou** : la vue de 1024 pixels est un peu moins fine que le panorama (environ 15 pixels par degré contre 23). Un meuble plus gros à l'écran donne un résultat plus net.
- Le résultat est inventé par le modèle : il donne une idée, pas un meuble réel qu'on pourrait acheter.

## Où sont rangés les remplacements

Dans le dossier du point, `visites/<visite>/<point>/modifications/`, deux fichiers par remplacement : l'image générée `generation-<n>.png` (la vue de 1024 pixels refaite par le modèle) et sa fiche `generation-<n>.json` :

```json
{
  "version": 1,
  "type": "generation",
  "id": "generation-1",
  "nom": "Remplace le canapé gris par un canapé en velours vert",
  "instruction": "Remplace le canapé gris par un canapé en velours vert",
  "consigne": "Remplace le canapé gris par un canapé en velours vert. Le changement se fait …",
  "graine": 1234567,
  "pas": 4,
  "modele": {
    "nom": "FLUX.2 [klein] 4B",
    "depot": "black-forest-labs/FLUX.2-klein-4B",
    "revision": "e7b7dc27f91deacad38e78976d1f2b499d76a294"
  },
  "vue": { "cap": 61.8, "hauteur": -21.4, "champ": 72.5, "taille": 1024 },
  "zone": {
    "ecran": { "cap": 55.0, "hauteur": -15.0, "champ": 100.0, "taille": 1024 },
    "cadre": [310.0, 380.0, 780.0, 850.0]
  },
  "image": "generation-1.png",
  "panorama_sha256": "…",
  "duree_s": 128.8,
  "creee_le": "2026-10-25T18:12:00+02:00"
}
```

- `zone` : la vue de l'écran au moment du tracé (même convention que les sélections, voir [selection.md](selection.md)) et le cadre dans cette vue, en pixels : gauche, haut, droite, bas.
- `vue` : la vue envoyée au modèle, calculée à partir du cadre.
- `instruction` : ce qu'a écrit l'utilisateur ; `consigne` : ce qui a été donné au modèle.
- `graine` : avec la même vue, la même consigne et la même graine, le modèle redonne la même image.
- Le panorama modifié, avec recolorations et remplacements, est fabriqué à la demande dans `cache/apres.jpg`.

## Temps, mémoire et coût

Mesuré le 2026-10-25 sur le MacBook Air M4 de 24 Go, image de 1024 × 1024, 4 passes :

| | Mesure |
|---|---|
| Temps d'une génération | 123 à 174 s, chargement du modèle compris. Le Mac, sans ventilateur, ralentit d'environ 40 % sur une série de 11 images |
| Mémoire au plus haut | 16,6 Go |
| Report dans le panorama de 8192 pixels | environ 0,3 s |

Ce que coûterait une génération ailleurs, sans rien utiliser ni souscrire :

| Où | Coût par image | Source, vérifiée le 2026-10-25 |
|---|---|---|
| Sur le Mac | électricité, environ 0,0002 € (estimation : 20 W pendant 2 min à 0,20 €/kWh, non mesurée) | — |
| API de Black Forest Labs, même modèle | environ 0,014 $ (0,014 $ le premier mégapixel, 0,001 $ chaque mégapixel suivant) | comparateurs [OpenRouter](https://openrouter.ai/models/black-forest-labs/flux.2-klein-4b) et [Price Per Token](https://pricepertoken.com/image/model/black-forest-labs-flux-2-klein-4b). La page de prix de Black Forest Labs n'affichait pas les montants |
| Replicate, fal.ai | environ 0,015 à 0,016 $ | [Price Per Token](https://pricepertoken.com/image/model/black-forest-labs-flux-2-klein-4b), chiffres contradictoires pour fal.ai |
| Carte graphique louée (v1, D32) | prix à l'heure, de l'ordre de 0,30 à 2 € selon la carte (estimation non vérifiée), quelques secondes par image | — |

En v1, la génération tournera sur du matériel loué, pas par une API, pour que les images des logements ne sortent pas du serveur du projet (D32).

## Sur une carte graphique louée (étape 14, D41)

Le calcul peut partir sur une carte NVIDIA louée chez Scaleway au lieu du Mac. Le cadre, la demande, le report dans le panorama et la fiche de modification ne changent pas : seul l'endroit du calcul change.

### Comment ça marche, en clair

Une **instance GPU** est un ordinateur loué avec une carte graphique puissante, facturé à la minute tant qu'il existe. Le serveur du projet la crée à la première demande de génération et elle se supprime toute seule après 10 minutes sans demande : sans demande, aucune facture. Le premier calcul après une pause est donc plus long (création de l'ordinateur et chargement du modèle, de l'ordre de quelques minutes), les suivants prennent quelques secondes.

Le chemin d'une vue : visionneuse du Mac → serveur du projet (connexion d'agent exigée) → carte, par un **réseau privé** (réseau fermé, invisible d'Internet). La vue reste en mémoire, n'est écrite sur aucun disque et n'apparaît dans aucun journal.

Si la carte ne répond pas (quota, panne, plafond de dépense atteint), le Terminal de `visite360 serve` l'écrit et le calcul se fait sur le Mac, s'il est installé.

### Réglages

Sur le serveur (variables d'environnement du conteneur) :

| Variable | Rôle |
|---|---|
| `VISITE360_CARTE_IMAGE` | identifiant de l'image système de la carte. Absente : la carte est désactivée |
| `VISITE360_CARTE_ZONE` | zone, par exemple `fr-par-2` |
| `VISITE360_CARTE_PROJET` | identifiant du projet Scaleway |
| `VISITE360_CARTE_RESEAU` | identifiant du réseau privé (obligatoire) |
| `VISITE360_CARTE_SECRET` | secret partagé entre le serveur et la carte (secret du conteneur) |
| `VISITE360_CARTE_TYPE` | type d'instance (défaut `L4-1-24G`, `RENDER-S` pour la P100) |
| `VISITE360_CARTE_GROUPE_SECURITE` | identifiant d'un groupe de sécurité Scaleway qui bloque les connexions entrantes venues d'Internet (facultatif, recommandé) |
| `VISITE360_CARTE_PRIX_HEURE` | prix à l'heure pour le décompte (défaut 0,7875) |
| `VISITE360_CARTE_PLAFOND` | plafond mensuel en euros (défaut 30) |
| `VISITE360_CARTE_ATTENTE_MIN` | minutes sans demande avant suppression (défaut 10) |

Sur le Mac : `VISITE360_CARTE_URL` (adresse du serveur du projet) et `VISITE360_CARTE_JETON` (jeton de session d'un compte agent). Sans eux, la génération se fait sur le Mac comme avant.

La carte lit les mêmes variables, plus `SCW_SECRET_KEY` (clé limitée à la suppression d'instances), et se lance par `visite360 carte-serveur`.

### Préparer l'image système, une fois

1. Créer une instance `L4-1-24G` avec une image Ubuntu GPU, dans le réseau privé `visite360`.
2. Y installer le projet, `torch` (avec ses bibliothèques CUDA ; sur une P100, `torch` 2.14 depuis l'index CUDA 12.6 de PyTorch, les versions plus récentes ne gèrent plus les cartes Pascal), `diffusers` (version de développement, comme l'indique la fiche du modèle), `Pillow`, et télécharger les poids FLUX.2 klein 4B (révision de `generation.py`).
3. Faire lancer `visite360 carte-serveur` au démarrage (service systemd), avec les variables ci-dessus.
4. En faire une image dans la console Scaleway, supprimer l'instance, et mettre l'identifiant de l'image dans `VISITE360_CARTE_IMAGE`.

### Ce qui n'est pas vérifié

L'API d'instances de Scaleway, la liaison au réseau privé, l'adresse privée lue sur l'instance, le chargement du modèle par `diffusers` sur la carte, le temps de démarrage à froid et le coût réel d'une séance : tout cela demande le quota GPU du compte et se mesure pendant la validation de l'étape. Les tests automatiques simulent Scaleway et le modèle.

### Avec un RENDER-S (carte P100, 16 Go)

Choix du propriétaire du 2026-11-04 : seul le RENDER-S est accessible pour l'instant, démarrage à froid uniquement. Réglages : `VISITE360_CARTE_TYPE=RENDER-S` et `VISITE360_CARTE_PRIX_HEURE=1.2426` (pour que le plafond compte le bon tarif, d'après la FAQ de Scaleway, à vérifier dans la console).

- **Adresse publique et groupe de sécurité.** L'instance est créée avec une adresse publique, sinon elle ne pourrait pas appeler Scaleway pour se supprimer et resterait facturée. Créer dans la console un groupe de sécurité qui refuse les connexions entrantes et mettre son identifiant dans `VISITE360_CARTE_GROUPE_SECURITE`. Le serveur du projet parle à la carte par le réseau privé, que ce groupe ne bloque pas (à vérifier à l'essai).
- **Type de calcul.** La P100 ne calcule pas bien en `bfloat16` : le programme de la carte passe en `float16` sur les cartes d'avant 2020. Les images noires ou abîmées seraient le signe d'un dépassement de capacité de ce format.
- **Mémoire.** Le modèle demande environ 13 Go sur 16 : une vue de 1024 pixels peut faire échouer le calcul faute de mémoire.
- **Vitesse.** Plus lente que le L4 (non mesurée).
- **Rupture de stock.** Aucune carte de secours ni file d'attente n'est prévue pour l'instant : si Scaleway n'a pas de RENDER-S libre à la création, la génération échoue avec un message clair (et retombe sur le Mac, s'il est installé). À reprendre avant le jalon v1 (le serveur ne doit pas dépendre d'un Mac allumé).

