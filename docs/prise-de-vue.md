# Prise de vue d'un point

Cette fiche décrit comment photographer un point de la visite avec l'appareil photo du téléphone, sans app dédiée.

**Avec l'app de capture** (étape 5, [app.md](app.md)) : les rangées, le nombre de photos, le recouvrement et le verrouillage de l'exposition sont gérés par l'app. Les conseils sur le logement, l'emplacement et le geste (objectif immobile) restent à suivre. Elle sera ajustée à l'étape 2 selon la qualité de l'assemblage sur de vraies photos.

Un point est un endroit du logement d'où l'on regarde tout autour de soi. Une pièce moyenne en demande un, une grande pièce ou une pièce en L deux.

## En résumé

- Environ **30 photos** par point, en **4 rangées** : horizon, haut, bas, plafond.
- Chaque photo recouvre la précédente d'**un bon tiers**.
- L'**objectif du téléphone ne bouge pas** : il reste au-dessus d'une marque au sol, seule son orientation change. C'est vous qui vous déplacez autour.
- Exposition **verrouillée**, mêmes lumières du début à la fin.

## Avant de commencer

- **Réglages du téléphone :**
  - objectif principal (zoom ×1), ni grand-angle ×0,5 ni téléobjectif ;
  - téléphone tenu **en hauteur** (portrait) ;
  - flash, mode Portrait, mode Nuit et Live Photo désactivés ;
  - ne pas utiliser le mode Panorama du téléphone ;
  - format : JPEG ou HEIC, les deux sont acceptés. Sur iPhone, le réglage Réglages > Appareil photo > Formats > « Le plus compatible » donne directement du JPEG.
- **Le logement :**
  - portes intérieures ouvertes, sauf celles qu'on veut montrer fermées ;
  - toutes les lumières allumées, ou toutes éteintes en plein jour : choisir et ne plus changer pendant le point ;
  - éviter le soleil direct dans l'objectif, baisser un store si besoin ;
  - personne ne bouge dans la pièce pendant la prise de vue, animaux compris ;
  - ranger ce qui est personnel : courrier, photos de famille, écrans allumés.
- **L'emplacement :** au milieu de l'espace, à plus d'un mètre des meubles. Plus un objet est proche, plus le raccord autour de lui sera difficile. Marquer l'endroit au sol, par exemple avec un morceau de ruban adhésif.

## Le geste : l'objectif reste au même endroit

Le réflexe naturel est de rester planté au milieu et de pivoter sur ses talons, téléphone devant soi. Mais le téléphone est alors à 30 ou 40 cm de l'axe de rotation : à chaque photo, il se déplace sur un cercle autour de vous. Vu de deux endroits différents, un objet proche ne se superpose plus au fond de la même façon (parallaxe), et les raccords se voient.

Ce qu'il faut : que l'**objectif du téléphone reste au même point dans l'espace** pour toutes les photos, et que seule la direction dans laquelle il vise change.

En pratique :

- tenir le téléphone au-dessus de la marque au sol, à hauteur de poitrine (environ 1,50 m), et garder cette hauteur pour tout le point ;
- pour viser la direction suivante, **ne pas pivoter sur place** : faire un petit pas de côté autour de la marque, comme si vous tourniez autour d'un poteau, en gardant le téléphone au-dessus d'elle ;
- vous restez donc toujours derrière l'écran, et vous faites un tour complet autour de la marque pendant chaque rangée ;
- pour les rangées haut et bas, incliner le téléphone sans l'avancer ni le reculer ;
- un trépied avec une rotule panoramique fait ce travail tout seul et supprime presque toute parallaxe.

## Les rangées

Faire les rangées dans cet ordre, en tournant toujours dans le même sens.

| Rangée | Inclinaison du téléphone | Photos | Écart entre deux photos |
|---|---|---|---|
| Horizon | droit, face au mur | 12 | 30°, une heure sur un cadran |
| Haut | penché vers le haut, à mi-chemin du plafond (45°) | 8 | 45° |
| Bas | penché vers le bas, à mi-chemin du sol (45°) | 8 | 45° |
| Plafond | à la verticale vers le haut | 1 | — |
| Sol (facultatif) | à la verticale vers le bas, en tenant le téléphone devant soi | 1 à 2 | — |

Repères pratiques :

- pour l'horizon, viser un repère du décor (angle de mur, fenêtre) et compter 12 photos pour revenir à ce repère ;
- **recouvrement :** un objet au bord droit d'une photo doit se retrouver vers le premier tiers gauche de la suivante ;
- dans le doute, prendre une photo de plus plutôt qu'une de moins : une photo en trop ne gêne pas l'assemblage, un trou ne se rattrape pas ;
- le sol sous le photographe sera flou ou manquant : c'est accepté à ce stade.

## Murs unis et objets proches

Premier essai réel (chambre, octobre 2026) :

- une photo qui ne montre qu'un mur blanc ou un plafond lisse n'offre presque aucun repère : elle est **rejetée** et laisse un trou gris. Cadrer chaque photo pour qu'elle contienne un **bord** : un angle de mur, une plinthe, un cadre de porte, un meuble, une prise ;
- pour le plafond, prendre la photo verticale en gardant un **morceau de mur** ou la **lampe et un angle** dans le cadre ;
- les objets à moins d'un mètre (porte ouverte, chaise, lit) se dédoublent facilement au raccord. Placer le point **au milieu de l'espace libre**, et soigner particulièrement le geste (objectif immobile) quand un objet est proche.

## Exposition et netteté

- Avant la première photo, viser une zone moyennement éclairée (un mur, pas une fenêtre) et **verrouiller l'exposition et la mise au point**. Sur iPhone : appui long sur l'écran jusqu'à « Verrouillage AE/AF ».
- Garder ce verrouillage pour tout le point. Sinon la luminosité change d'une photo à l'autre et les raccords se voient.
- Rester immobile au déclenchement : une photo floue est rejetée par l'assemblage.

## Après la prise de vue

- Vérifier vite les photos : pas de photo floue, pas de doigt devant l'objectif.
- Transférer les photos d'origine sur le Mac (AirDrop ou câble), **sans les retoucher ni les recadrer**. Sur iPhone, AirDrop garde le HEIC d'origine.
- Un dossier par point, nommé d'après la pièce (`salon`, `cuisine`, …), avec les photos dans un sous-dossier `photos/` : `visites/<nom de la visite>/<point>/photos/`. Ensuite : `visite360 stitch visites/<nom de la visite>/<point>`.
- Ne jamais ajouter ces photos au dépôt git : ce sont des données personnelles. Le dossier `visites/` est ignoré par git.

## Points à confirmer à l'étape 2

- Le nombre de photos par rangée, en particulier si le grand-angle ×0,5 permettrait d'en prendre moins.
- Le besoin réel des rangées haut et bas, et de la photo du sol.
- La tolérance de l'assemblage à la prise de vue à main levée, sans trépied.
