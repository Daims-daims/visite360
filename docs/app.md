# App de capture sur iPhone

L'app guide la prise de vue d'un point : elle montre où viser, déclenche toute seule quand le téléphone est en place et note l'orientation de chaque photo dans `capture.json` ([format](capture-json.md)). Code dans `app/`, en SwiftUI, sans bibliothèque extérieure (D25).

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

## Prendre un point

Les conseils de [prise-de-vue.md](prise-de-vue.md) restent valables : objectif immobile au-dessus d'une marque au sol, portes et lumières fixées, personne qui bouge.

1. **Nouveau point**, puis donner le nom de la pièce (`salon`, `cuisine`…). Ce sera le nom du dossier sur le Mac.
2. **Viser un mur moyennement éclairé** (pas une fenêtre), puis **Verrouiller et commencer**. L'exposition, la mise au point et la couleur sont figées pour tout le point. La direction visée devient la première photo de l'horizon.
3. **Suivre les ronds :** chaque direction à photographier est un rond dans l'image. Le rond orange est le prochain conseillé. Amener le rond dans le cercle blanc du centre et ne plus bouger : la photo part toute seule (petite vibration) et le rond devient vert. On peut aussi prendre les ronds dans un autre ordre.
4. **Consignes à l'écran :** « Tournez vers la droite », « Inclinez vers le haut », « Tenez le téléphone droit » (téléphone penché sur le côté), « Ne bougez plus ».
5. **Refaire la dernière** supprime la dernière photo pour la reprendre.
6. **Terminer** apparaît quand les rangées horizon, haut, bas et plafond sont complètes (29 photos). La photo du sol est facultative.

Un point se prend d'une traite. Quitter l'écran de prise de vue termine le point : pour reprendre, créer un nouveau point. Le cap 0 des capteurs change à chaque démarrage, des photos de deux séances ne s'assembleraient pas avec leurs orientations.

## Envoyer le point au Mac

Deux possibilités :

- **AirDrop :** dans l'app, toucher le point, puis **Envoyer au Mac (AirDrop)**. Le Mac reçoit `<point>.zip` dans Téléchargements. Le décompresser et placer le dossier obtenu dans `visites/<visite>/`.
- **Câble :** iPhone branché, ouvrir le Finder, cliquer sur l'iPhone dans la barre latérale, onglet *Fichiers*, déplier *Visite360* et glisser le dossier du point dans `visites/<visite>/`.

Puis sur le Mac :

```bash
visite360 stitch visites/<visite>/<point>
```

La ligne « Orientations » du résumé doit dire « mesurées par le téléphone (capture.json) ». Si elle dit « ignorées », la raison suit.

Le transfert sans manipulation de fichiers est prévu à l'étape 6.

## Tests de l'app

La géométrie (cibles, orientation, alignement) se teste sur le Mac, sans iPhone :

```bash
cd app
swift test
```

La caméra et les capteurs ne se testent que sur un vrai iPhone : le simulateur n'en a pas.
