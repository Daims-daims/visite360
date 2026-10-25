# Chiffrer les modifications d'une visite

Étape 11. Pour chaque modification d'une visite, l'outil donne **un ordre de grandeur du prix, en fourchette**. Une modification, c'est un mur repeint (étape 8) ou un objet remplacé (étape 9). Ce n'est pas un devis : le but est de dire au client « plutôt 300 € » ou « plutôt 3 000 € » (D36).

## Ce qu'il faut avant

- **La pièce mesurée** à l'adresse `/agent` (étape 10, [dimensions.md](dimensions.md)). Sans mesure, un mur repeint n'a pas de prix : la ligne le dit, et le total ne compte pas ce mur.
- **Des modifications.** Une recoloration ou un objet remplacé, dans la visite.

## Voir le chiffrage

1. Lancer la visite : `visite360 serve visites/<visite>`.
2. Dans la visite, bouton **Chiffrage**. Le panneau montre, pour la pièce affichée :
   - chaque mur repeint, avec sa surface en m², les murs touchés (numéros de l'étape 10) et la fourchette de prix ;
   - chaque objet remplacé, avec le type d'objet reconnu et sa fourchette ;
   - le total de la pièce et, s'il y a plusieurs points, celui de toute la visite.
3. Les montants sont arrondis à la dizaine d'euros : la précision n'irait pas plus loin.

Dans le terminal, sans ouvrir la visite :

```bash
visite360 chiffrage visites/<visite>
```

Le client voit le chiffrage dans la visite. Seul l'agent, à l'adresse `/agent`, peut corriger un type d'objet et modifier les prix.

## Corriger le type d'un objet remplacé (agent)

L'outil cherche le type d'objet dans la demande de génération. Il regarde d'abord ce qui suit « par » : pour « Remplace le canapé par un fauteuil », c'est un fauteuil. S'il ne reconnaît aucun mot, l'objet est classé « Autre objet ».

À l'adresse `/agent`, chaque objet remplacé a une liste déroulante pour choisir un autre type. Revenir au type reconnu efface le choix.

## Modifier les prix (agent)

À l'adresse `/agent`, **Chiffrage**, puis **Modifier les prix**. Chaque poste a un prix bas et un prix haut :

| Poste | Unité | Prix par défaut |
|---|---|---|
| Peinture des murs, fournie et posée | m² | 20 à 50 € |
| Peinture du plafond, fournie et posée | m² | 30 à 50 € |
| Nouveau revêtement de sol, fourni et posé | m² | 35 à 110 € |
| Canapé, fauteuil, table, lit, armoire, etc. | objet | voir la grille |

**Enregistrer les prix** les range dans `visites/<visite>/tarifs.json`, pour cette visite seulement. **Revenir aux prix par défaut** efface ce fichier.

Le fichier se modifie aussi à la main, par exemple pour ajouter un type d'objet ou des mots qui le désignent. Un fichier mal formé est refusé avec un message qui dit quoi corriger.

### D'où viennent les prix par défaut

Ce sont des prix indicatifs TTC, relevés le 2026-10-26. Ils sont à remplacer par les vôtres.

- **Peinture :** fourchettes publiées par [Travaux.com](https://www.travaux.com/peinture/guide-des-prix/peinture-tva) et [La Maison Saint-Gobain](https://www.lamaisonsaintgobain.fr/guides-travaux/amenagement-interieur/prix-peinture-au-m2), pour un support en bon état. Un mur abîmé coûte plus cher : il faut le reboucher et le lisser avant.
- **Sol :** du stratifié ([Obat](https://travaux.obat.fr/guides/prix-pose-parquet/)) au vinyle ([La Maison Saint-Gobain](https://www.lamaisonsaintgobain.fr/guides-travaux/amenagement-interieur/prix-pose-lino)), fourni et posé. Un parquet massif dépasse le haut de la fourchette.
- **Meubles :** achat seul, sans livraison ni montage. Le prix bas suit les plafonds de la [grille de la CAF](https://www.caf.fr/sites/default/files/medias/351/Offre-de-service/logement/aide-equipement-premiere-necessite/RI-AFI_grille-tarifaire-equipement-premiere-necessite.pdf) (juillet 2025) pour de l'entrée de gamme. Le prix haut est une estimation du projet pour du milieu de gamme : aucune source publique ne donne de prix moyen par type de meuble.

## Comment ça marche

**Surface repeinte.** Le masque de la sélection (étape 7) dit quels points du panorama changent. Chaque point du panorama est une direction de regard depuis l'objectif. La pièce mesurée (étape 10) dit où ce regard rencontre un mur, le sol ou le plafond, et à quelle distance.

Un point du panorama couvre une surface réelle d'autant plus grande que le mur est loin : au double de la distance, la surface est multipliée par quatre. Elle grandit encore quand on voit le mur de biais. L'outil additionne ces petites surfaces sur toute la sélection, et obtient les m² repeints mur par mur, au sol et au plafond.

Une porte ou une fenêtre laissée hors de la sélection n'est donc pas comptée. Une sélection qui déborde de 0,1 m² au plus sur le sol ou le plafond ne compte que pour le mur.

**Objet remplacé.** Le prix d'un meuble ne dépend pas de sa surface : c'est un forfait par type d'objet.

**Prix.** La fourchette d'un mur est sa surface × le prix bas, et sa surface × le prix haut.

## Précision

Calculée sur des pièces de synthèse (tests automatiques) :

- la surface d'une zone peinte sur un mur sort à 2 % près ; un mur entier ou le sol, à 1 à 3 % près ;
- à cela s'ajoute l'erreur de la mesure de la pièce : un horizon penché d'un degré fausse la surface d'un mur d'environ 8 % ([dimensions.md](dimensions.md)) ;
- et celle du contour de la sélection : s'il déborde sur une porte, la porte est comptée.

L'écart entre le prix bas et le prix haut, souvent du simple au double, reste bien plus grand que ces erreurs.

## Mauvais résultats et leur cause

- **« Pièce pas encore mesurée »** : mesurer la pièce à l'adresse `/agent`.
- **Surface nettement trop grande ou trop petite sur tous les murs** : la mesure de la pièce est fausse (contour tracé trop grand ou trop petit à l'étape 10, voir [dimensions.md](dimensions.md)).
- **Surface trop grande sur un seul mur** : la sélection déborde, sur une porte, une fenêtre ou le mur voisin. La voir avec **Sélections**, puis **Voir**.
- **Ligne « sol » ou « plafond » inattendue** : la sélection déborde de plus de 0,1 m² sur le sol ou le plafond.
- **« L'objectif est hors du contour de la pièce mesurée »** : les coins de l'étape 10 n'ont pas été cliqués tout autour de la pièce. Refaire la mesure.
- **« Panorama refait depuis la mesure »** : la pièce a été mesurée sur l'ancien panorama. Rouvrir la mesure et vérifier les coins.
- **Mauvais type d'objet** : le corriger dans la liste déroulante (adresse `/agent`), ou ajouter le mot manquant dans `tarifs.json`.

## Où sont rangées les données

- `visites/<visite>/tarifs.json` : la grille de prix de la visite, si l'agent l'a modifiée. Même format que la grille par défaut : `surfaces` (`mur`, `plafond`, `sol`, chacune avec `nom`, `bas`, `haut` en euros le m²) et `meubles` (liste de `id`, `nom`, `mots`, `bas`, `haut` en euros l'objet, avec obligatoirement une ligne `autre`).
- `<point>/modifications/chiffrage.json` : les types d'objet choisis par l'agent, par génération.
- `<point>/cache/chiffrage.json` : les surfaces déjà calculées. On peut l'effacer : il est refait à la demande.

Aucun panorama ni aucune photo n'est modifié (D9).
