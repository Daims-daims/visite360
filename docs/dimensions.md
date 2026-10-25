# Mesurer une pièce dans son panorama

Étape 10. L'agent pointe les coins de la pièce dans le panorama. L'outil en déduit la longueur et la surface de chaque mur, la surface au sol et le périmètre (D13, D34). Le client ne fait rien : ces dimensions serviront au chiffrage de l'étape 11.

## Ce qu'il faut à la prise de vue

Le réglage **« ×1 + AR »** de l'app, celui par défaut. Pendant les photos vers le bas, ARKit (la réalité augmentée d'Apple) repère le sol et mesure **la hauteur de l'objectif au-dessus du sol**. C'est elle qui donne les mètres. L'écran de prise de vue l'affiche sous le guide de placement : « Sol repéré : objectif à 1,48 m ». Tant que le sol n'est pas repéré, il dit « Sol pas encore repéré ».

Rien d'autre à faire sur place, ni mètre ruban, ni saisie.

Sans hauteur mesurée (réglages ×1 ou ×0,5, sol pas repéré, visite prise avant cette étape), la mesure reste possible : il faut alors saisir la hauteur sous plafond, mesurée au mètre.

## Mesurer

1. Lancer la visite : `visite360 serve visites/<visite>`. La commande affiche l'adresse des outils de l'agent : `http://localhost:8360/agent`. Sur le téléphone, c'est l'adresse Wi-Fi suivie de `/agent`.
2. Aller au point de la pièce, puis **Mesurer la pièce**. Le bouton n'existe qu'à l'adresse `/agent`.
3. Cliquer **les coins de la pièce dans l'ordre**, en faisant le tour, dans un sens ou dans l'autre :
   - **au sol** (rond jaune), là où le coin touche le sol, si on le voit ;
   - **au plafond** (rond bleu), là où le coin touche le plafond, si un meuble cache le bas ;
   - **au moins un coin aux deux** : son bas, puis aussitôt son haut, presque à la verticale. Les deux clics ne font alors qu'un coin. C'est ce coin qui donne la hauteur sous plafond.
4. Dès 3 coins, le contour calculé se dessine sur le panorama : le sol en jaune, le plafond en bleu, les angles en blanc, chaque mur avec son numéro. Les dimensions s'affichent dans le panneau.
5. **Enregistrer**. Le contour doit suivre les angles réels des murs ; sinon, **Annuler le dernier clic** ou **Tout effacer**.

On tourne la vue en glissant, comme d'habitude : seul un clic sans glissement pose un coin. Une pièce déjà mesurée se rouvre avec ses clics, pour les corriger. **Supprimer la mesure** l'efface.

Un clic à moins de 3° de l'horizon est refusé : à mi-hauteur du mur, l'angle ne dit presque rien de la distance.

## Comment ça marche

Le panorama est pris d'un seul endroit, et son horizon est bien horizontal : les capteurs du téléphone donnent la verticale. Un coin au sol vu à 30° sous l'horizon, avec l'objectif à 1,50 m du sol, est à 1,50 / tan 30° = 2,60 m de l'objectif. Plus on regarde bas pour le voir, plus il est près.

Le même coin vu au plafond donne la hauteur du plafond au-dessus de l'objectif : 2,60 m × tan de l'angle au-dessus de l'horizon. Ajoutée à la hauteur de l'objectif, c'est la hauteur sous plafond. Elle permet ensuite de placer les coins pointés seulement au plafond. Si plusieurs coins sont cliqués aux deux, l'outil fait la moyenne.

Les coins forment le plan de la pièce vu de dessus. Un mur va d'un coin au suivant : sa surface est sa longueur × la hauteur sous plafond, portes et fenêtres comprises. La surface au sol est celle du plan.

Sans hauteur mesurée par l'app, c'est l'inverse : la hauteur sous plafond saisie et les coins cliqués aux deux donnent la hauteur de l'objectif.

## Précision

Calculée sur des pièces de synthèse (tests automatiques) :

| Erreur | Effet sur la longueur d'un mur | Effet sur sa surface |
|---|---|---|
| Horizon penché d'1°, ou clics tous trop bas d'1° | environ 4 % | environ 8 % |
| Horizon penché d'un demi-degré | environ 2 % | environ 4 % |
| Hauteur de l'objectif fausse d'1 cm | moins de 1 % | moins de 1 % |

L'objectif de l'étape est une surface de mur à moins de 10 % de la mesure au mètre. Il demande un horizon juste à moins d'un degré, ce que donne normalement l'app, et des clics précis : zoomer sur le coin avant de cliquer.

## Mauvais résultats et leur cause

- **Le contour ne suit pas les murs, partout à peu près de la même façon** (trop grand ou trop petit) : la hauteur de l'objectif est fausse. Avec l'app, ARKit a pris une table basse ou un tapis épais pour le sol ; sans l'app, la hauteur sous plafond saisie est fausse.
- **Le contour est penché, plus haut d'un côté de la pièce que de l'autre** : l'horizon du panorama est penché. C'est l'assemblage qui est en cause, souvent avec des photos prises sans l'app. Les dimensions seront fausses de plusieurs pour cent.
- **Message « les coins donnent des hauteurs de plafond qui diffèrent de … cm »** : un clic au plafond ou au sol est à côté de son coin, ou l'horizon est penché.
- **« Les murs … se croisent »** : un coin a été cliqué hors de l'ordre du tour de la pièce.
- **Un mur manque ou en coupe un autre** : un coin a été oublié, ou deux clics ont été pris pour un seul coin parce qu'ils étaient presque à la verticale l'un de l'autre. Annuler et recliquer.
- **Plafond en pente, mansarde, mur arrondi** : hors de cette étape. L'outil suppose des murs droits et verticaux, un sol et un plafond plats.

## Où est rangée la mesure

Dans le dossier du point, `visites/<visite>/<point>/piece.json` :

```json
{
  "version": 1,
  "type": "piece",
  "clics": [{ "cap": -41.3, "hauteur": -27.9 }, { "cap": -41.2, "hauteur": 20.5 }, "…"],
  "hauteur_objectif_app_m": 1.452,
  "hauteur_plafond_saisie_m": null,
  "resultat": {
    "hauteur_objectif_m": 1.452,
    "source_hauteur_objectif": "app",
    "hauteur_plafond_m": 2.5,
    "source_hauteur_plafond": "coins",
    "ecart_hauteur_plafond_m": 0.03,
    "murs": [{ "numero": 1, "longueur_m": 4.2, "surface_m2": 10.5 }, "…"],
    "surface_sol_m2": 13.0,
    "perimetre_m": 14.6,
    "plan_m": [[-1.6, 1.9], "…"]
  },
  "panorama_sha256": "…",
  "creee_le": "2026-10-25T18:12:00+02:00"
}
```

- `clics` : les clics dans l'ordre, en degrés, dans le repère de la visionneuse (cap 0° au centre du panorama, positif vers la droite ; hauteur positive vers le haut). Ils sont regroupés en coins à la lecture : un clic au plafond complète le coin précédent s'il n'avait que son clic au sol, à moins de 4° de cap (ou l'inverse).
- `hauteur_objectif_app_m` : la hauteur mesurée par l'app au moment de l'enregistrement (`hauteur_objectif_m` de [capture.json](capture-json.md)), ou `null`. `hauteur_plafond_saisie_m` : la hauteur saisie, ou `null`.
- `resultat` : les dimensions, recalculées à chaque lecture à partir des clics. `plan_m` donne les coins vus de dessus, en mètres, l'objectif à l'origine : x vers la droite du centre du panorama, z vers ce centre. `source_hauteur_objectif` vaut `app` ou `plafond_saisi`, `source_hauteur_plafond` vaut `coins` ou `saisie`.
- `panorama_sha256` : si le panorama est refait, la visionneuse prévient que les clics ne tombent peut-être plus sur les coins.
- Le panorama avec le contour dessiné est fabriqué à la demande dans `cache/piece.jpg`. Le panorama d'origine n'est jamais modifié (D9).

## L'adresse `/agent`

Jusqu'à la v1, l'adresse `/agent` sépare l'usage de l'agent de celui du client sans rien protéger : tout appareil du même Wi-Fi peut l'ouvrir, et les routes de mesure répondent à tous. La vraie séparation viendra avec l'hébergement et les comptes (étapes 12 à 14).
