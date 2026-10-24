# Envoyer une visite de l'iPhone au Mac

L'app envoie une visite entière au Mac par le Wi-Fi de la maison, sans câble, sans service en ligne et sans manipuler de fichiers (étape 6, D26).

## Mode d'emploi

1. **Sur le Mac**, dans le dossier du projet, environnement virtuel activé :

   ```bash
   visite360 receive
   ```

   La commande affiche un code à 6 chiffres et l'adresse du Mac, puis attend. Les visites reçues vont dans `visites/`. Pour un autre dossier : `visite360 receive <dossier>`.
   - Au premier lancement, macOS peut demander si Python peut accepter des connexions entrantes : répondre **Autoriser**.
2. **Sur l'iPhone**, connecté au même Wi-Fi : ouvrir la visite, puis **Envoyer au Mac (Wi-Fi)**.
   - Le Mac apparaît tout seul (« Visite360 sur … ») et il est choisi d'office s'il est seul.
   - S'il n'apparaît pas, recopier l'adresse affichée par le Mac (par exemple `192.168.1.20:8361`).
   - Au premier envoi, iOS demande l'accès au réseau local : répondre **Autoriser**. En cas de refus : Réglages > Confidentialité et sécurité > Réseau local, activer Visite360.
3. **Saisir le code** affiché par le Mac, puis **Envoyer**. Une barre montre l'avancement.
4. **À la fin**, l'app affiche la réponse du Mac, par exemple « Visite « Appartement » reçue dans visites/appartement : 5 point(s), 108 nouveau(x) fichier(s) ».
5. **Voir la visite sur le Mac :**

   ```bash
   visite360 serve visites/<nom de la visite>
   ```

   Les panoramas s'assemblent pendant que la page affiche l'avancement (étape 4).

`visite360 receive` peut rester ouvert pour plusieurs envois. Ctrl+C l'arrête.

## Ce qui est vérifié

- **Le code.** Sans le bon code, le Mac refuse tout. Après 10 codes faux, il refuse tout jusqu'à ce qu'on relance `visite360 receive`, qui affiche alors un nouveau code. N'importe quel appareil du Wi-Fi peut joindre le serveur, mais pas déposer de fichiers sans le code.
- **Chaque fichier.** L'app annonce la taille et l'empreinte de chaque fichier. Une empreinte (SHA-256) est un code de 64 caractères calculé à partir du contenu : un seul octet changé donne une empreinte complètement différente. Un fichier arrivé incomplet ou abîmé est refusé.
- **L'envoi complet.** Les fichiers arrivent d'abord dans un dossier caché (`visites/.reception-…`). Ils ne sont rangés dans `visites/<visite>/` que si rien ne manque et si `visite.json` et les `capture.json` sont valides. Sinon, rien n'est rangé et l'app affiche la raison.
- **Les photos déjà sur le Mac.** Elles ne sont jamais réécrites (D9). Si un point du même nom existe sur le Mac avec d'autres photos, l'envoi est refusé : renommer ou supprimer le point d'un côté, puis renvoyer.
- **`visite.json`** est remplacé par celui de l'app. L'ancien est gardé à côté, sous le nom `visite-avant-<date>.json`, au cas où il avait été corrigé à la main.

## Envoi interrompu, nouvel envoi

- Si le Wi-Fi coupe ou si l'app se ferme, renvoyer : seuls les fichiers qui manquent au Mac repartent.
- Après avoir ajouté un point à la visite, renvoyer : seul le nouveau point part, avec `visite.json`.
- Un dossier caché d'envoi interrompu est supprimé au prochain lancement ou à l'arrêt de `visite360 receive`. Les photos restent sur l'iPhone.

## Si ça ne marche pas

| Message ou symptôme | Cause probable |
|---|---|
| Le Mac n'apparaît pas dans l'app | iPhone sur un autre réseau (4G, Wi-Fi invité), accès au réseau local refusé sur l'iPhone, ou `visite360 receive` arrêté. Saisir l'adresse affichée par le Mac. |
| « Le Mac ne répond pas » | Pare-feu du Mac qui bloque Python (Réglages Système > Réseau > Pare-feu), ou adresse mal recopiée. |
| « Code faux » | Code mal recopié, ou `visite360 receive` relancé depuis (le code change à chaque lancement). |
| « … existe déjà sur le Mac avec une autre prise de vue » | Le point a été repris sur l'iPhone sous le même nom. Voir « Ce qui est vérifié ». |
| « Visite refusée : … » | `visite.json` ou un `capture.json` invalide. Le message dit lequel et pourquoi. |

En secours, l'app propose aussi **Envoyer par AirDrop** : le Mac reçoit `<visite>.zip` dans Téléchargements, à décompresser dans `visites/`.

## Format des échanges

Pour relire ou déboguer. Tout passe en HTTP, sans chiffrement, sur le port 8361. Chaque requête porte le code dans l'en-tête `X-Visite360-Code`. Les réponses sont en JSON. Une erreur a un code HTTP différent de 200 et un champ `message` en français.

1. `GET /info` : vérifie le code. Réponse `{"app": "visite360", "version": "…", "format": 1}`.
2. `POST /envois` avec la liste complète des fichiers de la visite :

   ```json
   {
     "format": 1,
     "visite": "appartement",
     "fichiers": [
       { "chemin": "visite.json", "taille": 812, "sha256": "…" },
       { "chemin": "salon/capture.json", "taille": 9120, "sha256": "…" },
       { "chemin": "salon/photos/IMG_0001.jpg", "taille": 2841022, "sha256": "…" }
     ]
   }
   ```

   Réponse : `{"envoi": "<identifiant>", "manquants": ["visite.json", "salon/photos/IMG_0001.jpg"]}`. Seuls `visite.json`, `<point>/capture.json` et `<point>/photos/<photo>.jpg|jpeg|heic|png` sont acceptés.
3. `PUT /envois/<identifiant>/<chemin>` pour chaque fichier manquant, avec le contenu du fichier.
4. `POST /envois/<identifiant>/fin` : vérification et rangement. Réponse `{"message": "…", "points": 5, "nouveaux": 108}`.

Le Mac s'annonce par Bonjour sous le type `_visite360._tcp`, avec le programme `dns-sd` fourni avec macOS.
