# Changer la couleur d'une surface

Étape 8. Dans la visite, on repeint une surface sélectionnée à l'étape 7 (voir [selection.md](selection.md)) : ombres, lumière et texture du mur restent en place, seule la couleur change. Aucune IA générative : c'est un calcul, toujours identique pour la même couleur (D11, D30).

## Repeindre

1. Lancer la visite : `visite360 serve visites/<visite>`, puis ouvrir l'adresse affichée.
2. Sélectionner la surface si ce n'est pas déjà fait (**Sélectionner une surface**).
3. **Sélections**, puis **Repeindre** sur la ligne de la surface.
4. Choisir une teinte dans le nuancier, en bas de l'écran. Les teintes sont rangées par famille (blancs, gris, beiges, verts, bleus, roses) ; passer la souris sur une pastille donne son nom. La case **+** de « Sur mesure » ouvre un sélecteur libre pour n'importe quelle autre couleur. Un aperçu du panorama entier s'affiche au bout d'une seconde environ : on peut tourner autour pour juger.
5. Si le mur n'est pas blanc aujourd'hui, l'indiquer dans **Couleur actuelle du mur** : **Autre couleur…** pour donner sa couleur, ou **Je ne sais pas (comme sur la photo)**. Voir plus bas pourquoi.
6. **Appliquer** enregistre la couleur. **Annuler** ou la touche Échap reviennent à la visite sans rien enregistrer.

Une fois la couleur appliquée, la visite montre le panorama modifié, sur le Mac comme sur le téléphone. Le bouton **Voir l'original** montre le panorama d'origine, et **Voir les modifications** y revient : c'est la comparaison avant et après.

- Repeindre une surface déjà repeinte remplace sa couleur.
- **Sans couleur**, sur la ligne de la surface, annule sa recoloration.
- Supprimer une sélection annule aussi sa couleur.
- Plusieurs surfaces repeintes s'appliquent ensemble, dans l'ordre où elles ont été repeintes la première fois. Si deux sélections se chevauchent, la dernière l'emporte sur la partie commune.

La première ouverture après un changement prend quelques secondes : le serveur fabrique le panorama modifié en pleine taille.

## Comment c'est calculé

1. **Le contour est recalé sur les bords réels.** Le contour de l'étape 7 suit mal un bord peu marqué (porte blanche sur mur blanc) et, reporté dans le panorama, il est agrandi en marches d'escalier. Un « filtre guidé » le recale sur le bord visible le plus proche de la photo (ligne d'ombre, cadre de porte, angle avec le plafond), dans un rayon de 1,4° (32 pixels sur un panorama de 8192). Au-delà, rien ne change. La sélection enregistrée n'est pas modifiée : le recalage est refait à chaque calcul.
2. **La couleur est changée en lumière linéaire.** Les valeurs d'une photo sont compressées pour l'œil ; on les ramène à la quantité de lumière reçue. Un pixel du mur vaut alors « couleur de la peinture × éclairage ». On divise par la couleur de peinture actuelle du mur, ce qui laisse l'éclairage seul (ombres, reflets, teinte chaude d'une lampe), puis on multiplie par la couleur de peinture choisie. C'est ce que ferait la lumière sur un mur vraiment repeint.

### Couleur de peinture, couleur actuelle du mur

La teinte choisie est celle du pot de peinture, pas celle qu'aura le mur sur la photo. Un mur blanc paraît gris-beige sur une photo prise à l'intérieur (environ `#cac1b6` sur le mur de la cuisine de `appart-x1`) : repeint en « Bleu gris », il paraîtra plus sombre que la pastille, comme le serait un vrai mur sous la même lumière. Repeindre un mur blanc en « Blanc pur » ne change rien.

Pour cela, l'outil doit connaître la couleur de peinture actuelle du mur :

- **Blanc** (par défaut) : le cas de la plupart des murs.
- **Autre couleur…** : si le mur est déjà peint d'une couleur connue. Une couleur actuelle mal donnée décale le résultat : un mur crème déclaré blanc ressortira un peu trop jaune.
- **Je ne sais pas (comme sur la photo)** : l'outil prend la couleur du mur sur la photo. La teinte choisie est alors celle qu'aura le mur **sur la photo**, et plus celle du pot : le mur paraît plus clair que dans la réalité.
3. **Le bord s'adoucit** sur deux pixels à l'intérieur du contour recalé.

## Ce qui marche bien, ce qui marche mal

- **Bien :** un mur clair repeint en une couleur moyenne ou foncée ; un mur coloré repeint dans une autre couleur de même clarté.
- **Moins bien :** un mur foncé repeint en clair. La clarté est très agrandie : le grain de la photo ressort, et les zones déjà claires (reflet de fenêtre) deviennent blanc pur. C'est la limite connue de D11.
- **Mal :** une bande de couleur sur une porte, ou un mur qui s'arrête bien avant la plinthe. Le recalage ne corrige que les écarts de moins de 1,4° : au-delà, la cause est la sélection (étape 7). La corriger avec des clics « + » et « − », de préférence avec une vue rapprochée (une sélection faite à 120° de champ est plus grossière), puis repeindre.
- La couleur à l'écran n'est pas celle d'un pot de peinture : elle dépend de l'éclairage au moment de la photo et de l'écran. Choisir la couleur à l'œil, sur l'aperçu.

## Modifier le nuancier

Le nuancier est le fichier `visionneuse/nuancier.json` : des familles, chacune avec des teintes (un nom de 40 caractères au plus, une couleur `#rrggbb`). On peut y ajouter, retirer ou renommer des teintes à la main, puis relancer `visite360 serve`. Les noms et les valeurs sont propres au projet, sans référence à une marque de peinture.

## Où sont rangées les recolorations

Dans le dossier du point, `visites/<visite>/<point>/modifications/`, une fiche par surface repeinte :

```json
{
  "version": 1,
  "type": "couleur",
  "id": "couleur-1",
  "selection": "selection-2",
  "couleur": "#a3b09a",
  "teinte": "Vert sauge",
  "couleur_actuelle": "#f4f4f0",
  "creee_le": "2026-10-25T16:20:03+02:00"
}
```

- `selection` : la sélection repeinte. Son masque `selection-2.png` dit quels pixels changent.
- `couleur` : la couleur choisie, en code hexadécimal (rouge, vert, bleu).
- `teinte` : le nom de la teinte du nuancier. Absent pour une couleur choisie sur mesure.
- `couleur_actuelle` : la couleur de peinture du mur avant modification, `#f4f4f0` (blanc) par défaut, ou `photo` pour « comme sur la photo ».
- Le numéro de `id` donne l'ordre d'application.

Le panorama modifié est une image fabriquée à partir du panorama d'origine et de ces fiches. Il est rangé dans `cache/` du point : `apres.jpg`, sa copie réduite pour téléphone `apres-mobile.jpg`, et `apres.json`, qui sert à savoir s'il est à jour. Ces trois fichiers peuvent être effacés sans risque : ils sont refaits à la demande. Le panorama d'origine n'est jamais modifié (D9).
