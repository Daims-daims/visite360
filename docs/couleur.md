# Changer la couleur d'une surface

Étape 8. Dans la visite, on repeint une surface sélectionnée à l'étape 7 (voir [selection.md](selection.md)) : ombres, lumière et texture du mur restent en place, seule la couleur change. Aucune IA générative : c'est un calcul, toujours identique pour la même couleur (D11, D30).

## Repeindre

1. Lancer la visite : `visite360 serve visites/<visite>`, puis ouvrir l'adresse affichée.
2. Sélectionner la surface si ce n'est pas déjà fait (**Sélectionner une surface**).
3. **Sélections**, puis **Repeindre** sur la ligne de la surface.
4. Choisir une couleur dans la barre du bas. Un aperçu du panorama entier s'affiche au bout d'une seconde environ : on peut tourner autour pour juger.
5. **Appliquer** enregistre la couleur. **Annuler** ou la touche Échap reviennent à la visite sans rien enregistrer.

Une fois la couleur appliquée, la visite montre le panorama modifié, sur le Mac comme sur le téléphone. Le bouton **Voir l'original** montre le panorama d'origine, et **Voir les modifications** y revient : c'est la comparaison avant et après.

- Repeindre une surface déjà repeinte remplace sa couleur.
- **Sans couleur**, sur la ligne de la surface, annule sa recoloration.
- Supprimer une sélection annule aussi sa couleur.
- Plusieurs surfaces repeintes s'appliquent ensemble, dans l'ordre où elles ont été repeintes la première fois. Si deux sélections se chevauchent, la dernière l'emporte sur la partie commune.

La première ouverture après un changement prend quelques secondes : le serveur fabrique le panorama modifié en pleine taille.

## Comment c'est calculé

Chaque pixel est décrit par sa clarté (du noir au blanc) et sa teinte, dans l'espace de couleur Lab.

- **Clarté :** on mesure la clarté typique de la surface, puis on multiplie la clarté de chaque pixel par un même facteur, choisi pour que la surface prenne la clarté de la couleur choisie. Une ombre deux fois plus sombre que le reste du mur le reste après.
- **Teinte :** chaque pixel prend la teinte choisie, plus 30 % de son écart de teinte d'origine, pour que le reflet chaud d'une lampe reste visible.
- **Bord :** sur deux pixels à l'intérieur du contour, le changement s'adoucit pour éviter un bord en escalier. Hors de la sélection, aucun pixel ne change.

## Ce qui marche bien, ce qui marche mal

- **Bien :** un mur clair repeint en une couleur moyenne ou foncée ; un mur coloré repeint dans une autre couleur de même clarté.
- **Moins bien :** un mur foncé repeint en clair. La clarté est très agrandie : le grain de la photo ressort, et les zones déjà claires (reflet de fenêtre) deviennent blanc pur. C'est la limite connue de D11.
- **Mal :** un bord de couleur qui déborde sur un meuble ou s'arrête avant la plinthe. La cause est la sélection (étape 7), pas la couleur : corriger la sélection avec des clics « + » et « − », puis repeindre.
- La couleur à l'écran n'est pas celle d'un pot de peinture : elle dépend de l'éclairage au moment de la photo et de l'écran. Choisir la couleur à l'œil, sur l'aperçu.

## Où sont rangées les recolorations

Dans le dossier du point, `visites/<visite>/<point>/modifications/`, une fiche par surface repeinte :

```json
{
  "version": 1,
  "type": "couleur",
  "id": "couleur-1",
  "selection": "selection-2",
  "couleur": "#8fa58a",
  "creee_le": "2026-10-25T16:20:03+02:00"
}
```

- `selection` : la sélection repeinte. Son masque `selection-2.png` dit quels pixels changent.
- `couleur` : la couleur choisie, en code hexadécimal (rouge, vert, bleu).
- Le numéro de `id` donne l'ordre d'application.

Le panorama modifié est une image fabriquée à partir du panorama d'origine et de ces fiches. Il est rangé dans `cache/` du point : `apres.jpg`, sa copie réduite pour téléphone `apres-mobile.jpg`, et `apres.json`, qui sert à savoir s'il est à jour. Ces trois fichiers peuvent être effacés sans risque : ils sont refaits à la demande. Le panorama d'origine n'est jamais modifié (D9).
