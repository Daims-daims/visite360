# Sélectionner une surface au clic

Étape 7. Dans la visite, on clique sur un mur, un sol ou un plafond, et l'outil en trouve le contour. Cette sélection servira au changement de couleur (étape 8) et aux modifications générées par IA (étape 9).

## Installer le modèle, une fois

La sélection utilise SAM 2.1 small, un modèle de détourage publié par Meta (D10, D29). Il est facultatif : le reste de l'outil fonctionne sans. Environnement virtuel du projet activé :

```bash
bash scripts/installer-sam2.sh
visite360 doctor
```

Le script installe PyTorch et SAM 2 (environ 1 Go), puis télécharge les poids du modèle (176 Mo) et vérifie qu'ils sont bien ceux publiés par Meta. Les poids vont dans `~/.cache/visite360/modeles/`, hors du dépôt. Pour les ranger ailleurs, définir la variable `VISITE360_MODELES`. `visite360 doctor` doit afficher « ✓ SAM 2.1 (sélection au clic) ».

## Sélectionner

1. Lancer la visite : `visite360 serve visites/<visite>`, puis ouvrir l'adresse affichée.
2. Tourner la vue pour bien voir la surface, puis cliquer sur **Sélectionner une surface**. La vue s'immobilise. La première fois, le chargement du modèle prend quelques secondes.
3. Cliquer sur la surface. Le contour apparaît en violet, bordé de jaune.
4. Corriger si besoin :
   - **+ Ajouter** puis un clic sur une zone oubliée (un morceau de mur derrière une lampe) ;
   - **− Retirer** puis un clic sur une zone en trop (une porte, un meuble). Sur Mac, Alt + clic ou clic droit retirent aussi ;
   - **Annuler le dernier clic** retire le dernier point posé.
5. **Valider**, puis donner un nom (« Mur du canapé »). **Abandonner** ou la touche Échap annulent sans rien enregistrer.

Le bouton **Sélections** liste celles du point affiché. **Voir** montre la sélection teintée dans le panorama entier : on peut tourner autour pour vérifier qu'elle suit bien le mur sous tous les angles. **Supprimer** l'efface. Le panorama d'origine n'est jamais modifié (D9).

## Ce qui marche bien, ce qui marche mal

- **Bien** : mur uni, même blanc à côté d'une porte blanche ; mur avec des cadres ou des affiches, qui restent hors de la sélection ; parquet.
- **Moins bien** : un mur à motifs ou couvert de guirlandes. Un seul clic ne prend souvent qu'une bande : ajouter deux ou trois clics « + » ailleurs sur le mur.
- **Mal** : une zone floue ou mal assemblée du panorama (plafond avec des reflets étalés, par exemple). Le modèle n'y voit pas de contour net. La cause est l'assemblage ou la prise de vue, pas la sélection.
- **Une sélection ne couvre que ce qui est à l'écran.** Pour un long mur vu de près, reculer la vue (molette ou pincement) avant de cliquer sur « Sélectionner une surface ».
- Si le panorama est assemblé à nouveau, ses sélections sont marquées « à reprendre » : le contour risque d'être décalé.

## Où sont rangées les sélections

Dans le dossier du point, `visites/<visite>/<point>/modifications/` :

- `selection-<n>.png` : le masque, une image noir et blanc de la taille du panorama, blanc là où la surface est sélectionnée ;
- `selection-<n>.json` : la fiche de l'opération.

```json
{
  "version": 1,
  "type": "selection",
  "id": "selection-1",
  "nom": "Mur du canapé",
  "creee_le": "2026-10-25T14:02:11+02:00",
  "panorama_sha256": "9f2c…",
  "masque": "selection-1.png",
  "vue": { "cap": -62.0, "hauteur": 5.0, "champ": 90.0, "taille": 1024 },
  "clics": [{ "x": 512.0, "y": 512.0, "ajout": true }],
  "modele": "sam2.1_hiera_small",
  "score": 0.991
}
```

- `vue` : la vue carrée découpée dans le panorama pour la sélection. `cap` et `hauteur` sont l'angle du centre, dans les conventions de [visite-json.md](visite-json.md) ; `champ` est le champ de vision en degrés ; `taille` est le côté de la vue en pixels.
- `clics` : position des clics dans cette vue, en pixels ; `ajout` vaut `false` pour un clic « − Retirer ». Avec la vue et le modèle, ils suffisent à recalculer la sélection.
- `panorama_sha256` : empreinte du panorama au moment de la sélection, pour repérer un panorama refait depuis.
- `score` : confiance du modèle, de 0 à 1. Sous 0,8, le contour mérite souvent un clic de correction.

Un aperçu teinté est fabriqué à la demande dans `cache/selection-<n>.jpg`. Il peut être effacé sans risque.
