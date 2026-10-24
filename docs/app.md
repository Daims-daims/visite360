# App de capture sur iPhone

L'app guide la prise de vue d'une visite, point par point : elle montre où viser, déclenche toute seule quand le téléphone est en place et note l'orientation de chaque photo dans `capture.json` ([format](capture-json.md)). À la fin de chaque point, on vise les portes pour placer les flèches vers les autres pièces. La visite s'envoie ensuite au Mac par le Wi-Fi ([transfert](transfert.md)). Code dans `app/`, en SwiftUI, sans bibliothèque extérieure (D25, D26).

## Installer l'app sur l'iPhone, par câble et sans frais

Il faut Xcode sur le Mac et un identifiant Apple, sans abonnement développeur.

1. **Sur le Mac :** ouvrir `app/Visite360Capture.xcodeproj` dans Xcode.
2. **Compte :** Xcode > Réglages > Comptes, ajouter son identifiant Apple s'il n'y est pas.
3. **Signature :** cliquer sur le projet Visite360Capture (en haut à gauche), cible Visite360Capture, onglet *Signing & Capabilities*. Laisser *Automatically manage signing* coché et choisir dans *Team* l'équipe « (Personal Team) » de son identifiant.
   - Si Xcode dit que l'identifiant `io.github.daims-daims.visite360.capture` est déjà pris, changer la fin de *Bundle Identifier*, par exemple en ajoutant `.damien`.
4. **iPhone :** le brancher au Mac par câble, le déverrouiller et répondre « Se fier » à la question « Faire confiance à cet ordinateur ? ».
5. **Mode développeur :** sur l'iPhone, Réglages > Confidentialité et sécurité > Mode développeur, l'activer puis redémarrer. Le réglage n'apparaît qu'après le premier branchement à Xcode.
6. **Lancer :** dans Xcode, choisir l'iPhone en haut de la fenêtre (à la place d'un simulateur), puis le bouton ▶ (ou Cmd+R).
7. **Premier lancement :** si l'iPhone refuse d'ouvrir l'app, aller dans Réglages > Général > VPN et gestion de l'appareil, toucher l'entrée « Apple Development » de son identifiant, puis « Faire confiance ».

**Limite de l'installation gratuite :** l'app cesse de s'ouvrir au bout de 7 jours. Il suffit de rebrancher l'iPhone et de relancer depuis Xcode (étape 6). Les points déjà pris restent sur le téléphone.

## Prendre une visite

Les conseils de [prise-de-vue.md](prise-de-vue.md) restent valables : objectif immobile au-dessus d'une marque au sol, portes ouvertes et lumières fixées, personne qui bouge.

1. **Choisir le réglage** sur l'écran d'accueil :
   - **×1 + AR (conseillé, réglage par défaut)** : 29 photos par point (12 à l'horizon, 8 en haut, 8 en bas, le plafond). ARKit, la réalité augmentée d'Apple, suit la position de l'objectif pendant tout le point et montre où tenir le téléphone (voir plus bas). Aux essais du propriétaire, c'est le réglage qui donne les meilleurs raccords ;
   - **×1** : les mêmes 29 photos, sans suivi de l'objectif ;
   - **×0,5** : 21 photos (8, 6, 6 et le plafond), sans suivi. Chaque photo voit plus large, mais la parallaxe n'est pas contrôlée.

   Le choix est gardé pour les points suivants.
2. **Nouvelle visite**, puis lui donner un nom (`Appartement Dupont`). Le dossier sur le Mac portera ce nom simplifié (`appartement-dupont`).
3. **Nouveau point**, puis donner le nom de la pièce (`Salon`, `Cuisine`…). Le premier point pris est celui où la visite s'ouvre.
4. **Prendre le point** comme ci-dessous, puis **viser les portes** (paragraphe suivant).
5. **Point suivant :** une pièce annoncée par une flèche apparaît dans « Pièces à prendre » : la toucher pour la prendre, son nom est déjà le bon. Sinon, **Nouveau point**.
6. **Envoyer au Mac** quand la visite est finie, ou au fil de l'eau : voir [transfert.md](transfert.md).

### Prendre un point

1. **Viser un mur moyennement éclairé** (pas une fenêtre), puis **Verrouiller et commencer**. L'exposition, la mise au point et la couleur sont figées pour tout le point. La direction visée devient la première photo de l'horizon, et le centre du panorama sur le Mac.
2. **Suivre les ronds :** chaque direction à photographier est un rond dans l'image. Le rond orange est le prochain conseillé. Amener le rond dans le cercle blanc du centre et ne plus bouger : la photo part toute seule (petite vibration) et le rond devient vert. On peut aussi prendre les ronds dans un autre ordre.
3. **Consignes à l'écran :** « Tournez vers la droite », « Inclinez vers le haut », « Tenez le téléphone droit » (téléphone penché sur le côté), « Ne bougez plus ».
4. **Refaire la dernière** supprime la dernière photo pour la reprendre.
5. Quand les rangées horizon, haut, bas et plafond sont complètes, le bouton bleu **Flèche ici** apparaît. La photo du sol est facultative.

Un point se prend d'une traite. Quitter l'écran de prise de vue termine le point : pour reprendre une pièce, supprimer le point (le toucher dans la visite, puis **Supprimer ce point**) et le reprendre. Le cap 0 des capteurs change à chaque démarrage : des photos ou des flèches de deux séances ne s'assembleraient pas avec leurs orientations.

### Réglage « ×1 + AR » : garder l'objectif à sa place

Toutes les photos d'un point doivent être prises du même endroit. Si l'objectif bouge, par exemple quand on pivote sur ses talons au lieu de tourner autour du téléphone, un objet proche ne se superpose plus au fond de la même façon d'une photo à l'autre : c'est la parallaxe, et les raccords se voient ([prise-de-vue.md](prise-de-vue.md)).

En réglage « ×1 + AR », ARKit repère la pièce par la caméra et mesure en continu la position de l'objectif, au centimètre près. La place de départ est celle de l'objectif au moment de **Verrouiller et commencer**.

**Le guide de placement**, en bas de l'écran au-dessus des boutons, montre en permanence où est l'objectif :

- **le cercle, vu de dessus :** la croix au centre est la place de départ, le point de couleur est l'objectif. Le haut du cercle (petit chevron) est la direction où vise le téléphone : un point en haut veut dire que l'objectif est parti vers l'avant, un point à gauche qu'il est parti vers la gauche. Le cercle blanc marque la limite de 5 cm. Le pointillé montre le chemin pour revenir ;
- **la jauge verticale,** à droite du cercle, donne la hauteur : le trait blanc est la hauteur de départ, le point la hauteur actuelle ;
- **la couleur :** vert, l'objectif est à sa place ; orange, il s'en éloigne ; rouge, il est trop loin ;
- **le texte** donne la distance (« Objectif à 5 cm de sa place ») et la correction à faire, par exemple « Ramenez le téléphone vers vous de 5 cm, puis décalez-le vers la gauche de 2 cm ».

Au-delà de **5 cm**, le cadre du haut devient rouge, le téléphone vibre et **aucune photo ne part**. Suivre la consigne et amener le point sur la croix : l'alerte s'efface sous 3,5 cm et les photos reprennent. Pour un objet à 1 m, 5 cm de déplacement font environ 3° d'écart entre deux photos.

Limites de ce mode :

- **seulement au ×1** : ARKit garde la caméra pour lui et n'utilise pas le ×0,5 ;
- ARKit a besoin de voir la pièce : au démarrage, ou face à un mur uni, la ligne dit « bougez doucement pour qu'ARKit repère la pièce ». Tant qu'il ne suit pas la position, les photos partent sans contrôle ;
- le seuil de 5 cm se règle dans le code (`LensDrift.limit`, `app/Visite360Capture/Geometry/Geometry.swift`).

Le déplacement de chaque photo est noté dans `capture.json` (`deplacement_m`, [format](capture-json.md)), pour relier après coup un raccord raté à un objectif qui avait bougé.

### Viser les portes : les flèches

Toujours depuis la même place, sans déplacer le téléphone de sa marque au sol :

1. **Viser le milieu d'une porte** qui mène à une autre pièce de la visite, le cercle blanc sur la porte.
2. **Flèche ici**, puis choisir la pièce où mène cette porte : un point déjà pris, une pièce annoncée, ou une nouvelle pièce à saisir (« Vers une pièce pas encore prise »). La direction est notée au moment où l'on touche **Flèche ici** : on peut bouger ensuite.
3. Un rond bleu marque chaque flèche placée. Recommencer pour chaque porte, puis **Terminer**.

Une flèche va dans un seul sens. Pour revenir, la flèche retour se vise depuis l'autre pièce, quand on la prend. Viser une flèche une seconde fois vers la même pièce remplace la première.

L'angle n'a pas besoin d'être exact au degré près : la flèche apparaît dans la visite là où l'on a visé, à quelques degrés près. Pour la corriger après coup, modifier son `angle` dans `visite.json` sur le Mac ([format](visite-json.md)). Attention : un nouvel envoi depuis l'app remplace ce fichier (l'ancien est gardé à côté).

### Points pris avant les visites

Les points pris avec la première version de l'app (étape 5) apparaissent sur l'écran d'accueil sous « Points pris hors visite ». Toucher un point pour le ranger dans une visite. Ces points n'ont pas de flèches visées : leur centre est la première photo. Leurs flèches se déclarent à la main dans `visite.json` sur le Mac, comme à l'étape 4.

## Envoyer la visite au Mac

Par le Wi-Fi, sans manipuler de fichiers : lancer `visite360 receive` sur le Mac, puis **Envoyer au Mac (Wi-Fi)** dans la visite. Le mode d'emploi complet et les solutions aux problèmes sont dans [transfert.md](transfert.md).

En secours :

- **AirDrop :** dans la visite, **Envoyer par AirDrop**. Le Mac reçoit `<visite>.zip` dans Téléchargements. Le décompresser dans `visites/`.
- **Câble :** iPhone branché, ouvrir le Finder, cliquer sur l'iPhone dans la barre latérale, onglet *Fichiers*, déplier *Visite360* et glisser le dossier de la visite dans `visites/`.

Le dossier de la visite sur l'iPhone contient `visite.json` à jour : il marche tel quel sur le Mac. `visite-app.json`, à côté, garde en plus les pièces annoncées pas encore prises ; le Mac l'ignore.

Puis sur le Mac :

```bash
visite360 serve visites/<visite>
```

Pour un seul point, `visite360 stitch visites/<visite>/<point>` affiche le détail de l'assemblage. La ligne « Orientations » du résumé doit dire « mesurées par le téléphone (capture.json) ». Si elle dit « ignorées », la raison suit, et les flèches de ce point peuvent être décalées.

## Tests de l'app

La géométrie (cibles, orientation, alignement, angle des flèches) et le modèle de visite (points, flèches, `visite.json` exporté, liste des fichiers à envoyer) se testent sur le Mac, sans iPhone :

```bash
cd app
swift test
```

La caméra et les capteurs ne se testent que sur un vrai iPhone : le simulateur n'en a pas. Les écrans de visite et l'envoi au Mac, eux, marchent dans le simulateur.
