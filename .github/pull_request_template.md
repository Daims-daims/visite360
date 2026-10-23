## Étape

<!-- Numéro et nom de l'étape de PLAN.md -->

## Ce qui a été fait

<!-- En quelques points, ce que cette pull request ajoute ou change -->

## Comment ça marche, en clair

<!--
Pour le propriétaire du dépôt, qui n'est pas spécialiste de vision par ordinateur ni d'IA générative. Sans jargon, 5 à 15 lignes :
- le principe de ce que fait l'étape, avec une image ou une analogie si elle aide ;
- ses limites connues ;
- à quoi ressemble un mauvais résultat, et sa cause probable : prise de vue, réglage ou code ;
- pour creuser, une ressource de docs/ressources.md si l'une d'elles s'y prête.
Tout mot technique est expliqué à sa première apparition.
-->

## Comment le tester

<!-- Commandes exactes à lancer sur le Mac ou le téléphone, et ce qu'on doit observer -->

## Ce qui n'a pas été testé

<!-- Tout ce qui n'a pas pu être vérifié, notamment ce qui demande de vraies photos ou un téléphone -->

## Questions ouvertes

<!-- Décisions à prendre, idées hors périmètre, doutes -->

## Vérifications

- [ ] `pytest`, `ruff check .` et `ruff format --check .` passent
- [ ] La rubrique « Comment ça marche, en clair » est remplie, sans mot technique laissé sans explication
- [ ] `PLAN.md` est à jour (statut de l'étape)
- [ ] Toute nouvelle dépendance est dans `docs/licences.md`, licence vérifiée à la source
- [ ] Tout nouveau choix structurant est dans `docs/decisions.md`
- [ ] Aucune photo, aucun panorama ni poids de modèle dans les fichiers ajoutés
