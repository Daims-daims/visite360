# Déclarer les liens d'une visite : `visite.json`

Une visite de plusieurs points est un dossier `visites/<visite>/` qui contient un dossier par point (avec ses `photos/`) et un fichier `visite.json`. Ce fichier dit quels points existent et quelles flèches les relient. Jusqu'à l'étape 6, les liens se déclarent à la main (D14).

## Créer le fichier

```bash
visite360 serve visites/<visite>
```

Si `visite.json` n'existe pas, la commande le crée avec un point par dossier et aucun lien, puis sert la visite. Les panoramas manquants sont assemblés un point après l'autre. Un fichier existant n'est jamais réécrit.

## Exemple

```json
{
  "nom": "Appartement",
  "depart": "1",
  "points": [
    { "id": "1", "nom": "Salon" },
    { "id": "2", "nom": "Cuisine" }
  ],
  "liens": [
    { "de": "1", "vers": "2", "angle": 90 },
    { "de": "2", "vers": "1", "angle": -90, "texte": "Retour au salon" }
  ]
}
```

- `points` : un `id` par point, qui est le nom de son dossier. `nom` est le texte affiché (par défaut l'`id`).
- `depart` : le point où la visite s'ouvre (par défaut le premier).
- `liens` : une flèche par ligne. `de` est le point où elle apparaît, `vers` le point où elle mène. Pour aller dans les deux sens, il faut deux liens.
- `texte` (facultatif) : l'étiquette de la flèche (par défaut le nom du point d'arrivée).
- `hauteur` (facultatif) : hauteur de la flèche en degrés, 0 à l'horizon, négatif vers le sol. Par défaut -10.

## Lire l'angle d'une flèche

L'`angle` est la direction de la flèche dans le panorama du point de départ, en degrés. 0° est le centre de l'image, c'est-à-dire la direction vers laquelle la vue s'ouvre. Les angles positifs vont vers la droite, les négatifs vers la gauche, 180° est derrière toi. 90° est un quart de tour à droite, -90° un quart de tour à gauche.

Inutile de calculer : dans la visionneuse, tourne la vue vers la porte, puis lis le chiffre affiché en bas à gauche. « Centre » est la direction au milieu de l'écran, « clic » est la direction du dernier endroit où tu as cliqué. Recopie ce chiffre dans `angle`.

## Champs prévus pour l'app (étape 6)

`nord` (cap de la boussole vers lequel le panorama a été pris, en degrés) et `position` (`[x, y]` ou `[x, y, z]` en mètres) sont lus et vérifiés, mais pas encore utilisés. L'app les remplira plus tard, pour que les flèches se placent toutes seules.

## Erreurs détectées

L'outil s'arrête avec un message en français si : un lien désigne un point inexistant, un point est déclaré deux fois, un dossier de point manque, un angle est absent ou n'est pas un nombre entre -360 et 360, une clé est mal orthographiée (par exemple `angel`), ou le JSON est mal formé (une virgule oubliée ou en trop).
