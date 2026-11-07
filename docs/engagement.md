# Liens clients et retours d'engagement

Étape 16. L'agent crée un lien par client pour une même visite. Le client y regarde la visite, essaie ses propres couleurs et remplacements d'objets, et, s'il l'accepte, l'agent voit ce qu'il a regardé. Décision D43.

## Comment ça marche, en clair

- **Un lien par client.** Dans l'espace web, chaque visite prête a un bloc « Liens clients ». On tape un libellé (par exemple « M. et Mme Martin »), puis « Créer un lien » : le lien est copié, prêt à envoyer. Il ressemble à `https://api.hesti-scan.fr/l/Xb3k…/`. La fin est un **jeton** tiré au hasard (128 bits) : impossible à deviner, mais quiconque a le lien ouvre la visite. Chaque client a le sien : supprimer un lien coupe ce client sans toucher aux autres.
- **La page du client est servie par le serveur du projet**, et non plus par le stockage de fichiers de l'étape 12, parce qu'elle doit maintenant envoyer des choses : les mesures et les modifications du client. Les panoramas, les images modifiées par l'agent et son chiffrage passent aussi par le serveur, qui les relit dans la visite publiée. Tout vient donc de la même adresse que la page : supprimer un lien coupe tout, images comprises.
- **La question à la première ouverture.** Avant toute mesure, la page demande « Aider votre agent ? », avec deux boutons de même taille, « Accepter » et « Refuser ». La visite marche pareil quelle que soit la réponse. La réponse est gardée sur le téléphone (seulement ce choix, rien d'autre), et un petit bouton « Mesure : activée / désactivée » en haut à gauche permet de changer d'avis.
- **Ce qui est mesuré, après accord seulement** : le temps passé dans chaque pièce (seulement quand la page est à l'écran, pas quand le téléphone est en veille ou sur une autre app), le nombre de bascules entre les modifications dans chaque pièce, et l'ouverture du chiffrage. La page l'envoie toutes les 15 secondes, puis une dernière fois quand on la quitte. Une **ouverture**, c'est une page chargée : recharger la page en fait une nouvelle.
- **Le serveur vérifie chaque mesure** : forme attendue, pièces qui existent, au plus une minute par envoi et jamais plus que le temps écoulé depuis l'envoi précédent, au plus un envoi toutes les 5 secondes et 20 ouvertures par heure et par lien. Une mesure refusée est simplement perdue, la visite continue.
- **Les modifications du client sont à part.** Il a les outils de l'agent réduits à deux : sélectionner une surface et changer sa couleur, et remplacer un objet (au plus **5 remplacements par jour et par lien**, car chacun coûte du temps de carte graphique, pris sur le plafond de 30 € par mois). Il n'a ni la mesure de la pièce ni la grille de prix. Ses modifications sont rangées dans le stockage privé sous `<visite>/liens/<lien>/` : ni l'agent, ni les autres clients, ni la visite publiée ne les voient.
- **La bascule à trois positions** : « propositions de l'agent » (ce que l'agent a publié avec « Mettre à jour le lien »), « mes idées » (les modifications du client, faites sur le panorama d'origine), puis « l'original ». Les deux séries de modifications ne se mélangent pas.
- **Le chiffrage du client** montre en fourchette les propositions de l'agent, puis ses propres idées, calculées avec la grille et la mesure de la pièce de l'agent, sans montrer la grille.
- **Ce que voit l'agent**, pour chaque lien : nombre d'ouvertures, durée totale, date de la dernière ; en ouvrant « Détail », le temps par pièce, les bascules, le nombre d'ouvertures où le chiffrage a été regardé, la liste des ouvertures (date, durée), et le nombre de modifications du client, avec « Voir » et « Effacer ses modifications ».
- **Effacement** : les mesures sont effacées 12 mois après la consultation ; les modifications d'un client, 12 mois après la dernière ouverture de son lien (le serveur note la date d'ouverture de la page pour ce seul usage, sans la montrer). C'est la tâche quotidienne de l'étape 13 qui s'en charge. Supprimer un lien efface tout de suite ses mesures et les modifications du client. Supprimer ou dépublier la visite coupe tous ses liens.

## Ce que montrent un bon et un mauvais résultat

| Ce qu'on voit | Ce que ça veut dire |
|---|---|
| L'agent voit les pièces et les durées d'un client qui a accepté | normal |
| Rien pour un client qui a refusé (« Aucune ouverture mesurée ») | normal : rien n'est envoyé après un refus |
| Durée beaucoup plus courte que la visite réelle | téléphone mis en veille ou autre app pendant la visite : ce temps-là n'est pas compté. Ou la page quittée moins de 6 secondes après un envoi : ces quelques secondes partent au suivant, il n'y en a pas |
| Deux ouvertures pour une seule visite | la page a été rechargée, ou rouverte depuis l'historique |
| « Ce lien ne mène plus à aucune visite » | lien supprimé, visite dépubliée ou supprimée, ou adresse mal recopiée |
| « Limite atteinte : 5 remplacements d'objets par jour » | le client a fait ses 5 remplacements du jour avec ce lien |
| Le client voit l'original au lieu des propositions de l'agent | l'agent n'a pas cliqué « Mettre à jour le lien » après ses modifications |
| La question revient à chaque ouverture | navigation privée, ou navigateur qui efface les données des sites : le choix ne peut pas être gardé |

## Comment tester

Avec le serveur local (`visite360 serveur --local`, voir `docs/serveur.md`), ou en ligne après déploiement :

1. Dans l'espace, sur une visite prête, créer deux liens, « Essai A » et « Essai B ».
2. Ouvrir « Essai A » sur un téléphone, **accepter** ; parcourir deux pièces une minute chacune, basculer les modifications, ouvrir le chiffrage, repeindre un mur ; fermer la page.
3. Ouvrir « Essai B » sur un autre téléphone, **refuser** ; parcourir la visite.
4. Dans l'espace, « Détail » de chaque lien : A montre les deux pièces avec environ une minute chacune, les bascules, le chiffrage ouvert et une couleur ; B montre « Aucune ouverture mesurée ».
5. Rouvrir A : la question n'est pas reposée ; le bouton en haut à gauche dit « Mesure : activée ». Le passer à « Refuser », naviguer : le détail ne bouge plus.
6. Supprimer le lien A : il affiche « Ce lien ne mène plus à aucune visite » ; B fonctionne toujours.

## Ce qui n'a pas été vérifié

- Rien n'a été essayé sur un vrai téléphone ni en ligne : seulement par les tests automatiques, avec un modèle de génération et une sélection simulés.
- Le dernier envoi à la fermeture de la page (`fetch` avec `keepalive`) dépend du navigateur ; Safari sur iPhone peut le perdre quand on passe d'une app à l'autre. Au pire, les 15 dernières secondes manquent.
- Le trafic des panoramas passe maintenant par le conteneur du serveur. Son coût et le temps d'ouverture en 4G restent à mesurer.
- Le texte de la question et la durée de conservation doivent être relus par une personne compétente en RGPD avant les premiers vrais clients (D43).
