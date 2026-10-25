# Orientations mesurées par l'app : `capture.json`

L'app de capture (dossier `app/`, étape 5) écrit ce fichier dans le dossier du point, à côté du dossier `photos/` :

```
visites/<visite>/<point>/
├── capture.json
└── photos/
    ├── IMG_0001.jpg
    └── …
```

Personne n'a besoin de le modifier à la main. `visite360 stitch` le lit tout seul s'il est présent (D25).

## Exemple

```json
{
  "format": 1,
  "app": "Visite360 Capture 0.1.0",
  "appareil": "iPhone15,4",
  "objectif": "x0.5",
  "debut": "2026-10-24T18:02:11Z",
  "repere": "rotation caméra vers monde ; photo : x droite, y bas, z objectif ; monde : y vers le bas, cap de départ arbitraire",
  "exposition": { "iso": 400, "duree_s": 0.02 },
  "cap_depart": -12.4,
  "photos": [
    {
      "fichier": "IMG_0001.jpg",
      "rangee": "horizon",
      "numero": 1,
      "cap": -12.4,
      "inclinaison": 0.8,
      "rotation": [[0.976, -0.003, -0.215], [0.001, 1.0, -0.014], [0.215, 0.014, 0.976]],
      "heure": "2026-10-24T18:02:15Z"
    }
  ]
}
```

## Champs lus par l'assemblage

- `format` : version du fichier, 1 aujourd'hui. Un autre numéro arrête l'assemblage avec un message.
- `photos` : une ligne par photo.
  - `fichier` : nom de la photo dans `photos/`.
  - `rotation` : orientation du téléphone au déclenchement, en 3 lignes de 3 nombres. Elle dit dans quelle direction de la pièce regarde chaque point de la photo, dans le même repère que l'assemblage (`src/visite360/spherical.py`) : pour la photo, x vers la droite de l'image, y vers le bas, z dans l'axe de l'objectif ; pour la pièce, y vers le bas, et le cap 0 est une direction quelconque fixée au démarrage de l'app.

- `cap_depart` (facultatif, étape 6) : cap visé au verrouillage, en degrés, dans le repère des rotations. Quand les orientations servent, le panorama est centré sur ce cap, et non sur la première photo retenue : les flèches visées dans l'app gardent leur angle même si la première photo est écartée (D26). Absent des fichiers de l'étape 5 : le centre est alors la première photo.

- `suivi_position` (facultatif) : `"arkit"` quand la position de l'objectif a été suivie (réglage « ×1 + AR » de l'app). Chaque photo a alors `deplacement_m` : déplacement de l'objectif depuis sa place de départ au déclenchement, en mètres, `[x, y, z]` dans le repère d'ARKit (y vers le haut). Absent si ARKit ne suivait pas la position à ce moment. L'assemblage ne s'en sert pas : c'est un outil de diagnostic de la parallaxe.
- `hauteur_objectif_m` (facultatif, étape 10) : hauteur de l'objectif au-dessus du sol, à sa place de départ, en mètres. ARKit la mesure en repérant le sol pendant les photos vers le bas (réglage « ×1 + AR »). Elle donne l'échelle des dimensions de la pièce ([dimensions.md](dimensions.md), D34). Absente si le sol n'a pas été repéré ou sans ARKit.

Les autres champs servent à relire une prise de vue : `rangee` et `numero` (la cible visée), `cap` et `inclinaison` (en degrés, cap positif vers la droite, inclinaison positive vers le haut), `exposition` (réglages verrouillés), `objectif` (`x0.5` ou `x1`, absent des premiers fichiers, qui sont au ×1), `appareil`, `app`, `debut`, `heure`. Un champ inconnu est ignoré, pour qu'une version plus récente de l'app reste lisible.

## Ce que fait l'assemblage

- Si chaque photo a sa ligne, les orientations servent de départ à l'ajustement, limitent la recherche de points communs aux photos voisines (axes à moins de 90°) et donnent l'horizon.
- Une photo qui n'a pas assez de points communs avec les autres (mur ou plafond unis) n'est plus rejetée : elle est placée à l'orientation mesurée par le téléphone. Les capteurs sont précis à environ 1°, ce qui ne se voit pas là où il n'y a rien à raccorder. Le résumé l'indique (« Placée par les capteurs »), comme `placed_by_sensors` dans `rapport.json`.
- Si une photo n'a pas de ligne, ou si les orientations s'écartent de plus de 10° de ce que montrent les photos, elles sont ignorées : l'assemblage se fait comme sans app. Le rapport le dit (`orientations` dans `rapport.json`, et la ligne « Orientations » affichée en fin d'assemblage).
- Un fichier illisible ou mal formé arrête l'assemblage avec un message en français. Le supprimer permet d'assembler sans les orientations.
- Modifier `capture.json` relance l'assemblage au prochain `stitch` ou `serve`, comme une photo modifiée.
