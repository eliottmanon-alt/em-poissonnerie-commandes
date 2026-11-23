# EM Poissonnerie — V10.6, test Render

Source : `EM_Poissonnerie_Site_V10_6_ADMIN_TOUTES_PAGES(1).zip`.
Les quatre pages, photos, CSS et le mode admin d'origine sont conservés.
Le clic de confirmation envoie désormais la commande au serveur. Le succès
est affiché seulement après sauvegarde et un nouvel essai ne crée pas de doublon.

## Déploiement

- Python, `python prepare_assets.py && pip install -r requirements.txt`.
- Les images originales sont encodées dans `deploy_assets/`; `prepare_assets.py` les restaure sans modification.
- Démarrage : `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`.
- `DATABASE_URL` : URL PostgreSQL interne, configurée uniquement dans Render.
- `EM_SITE_API_KEY` : clé de synchronisation avec le logiciel, uniquement dans Render.
- Aucun secret ni aucune commande client ne doit être ajouté à ce dépôt public.

La base PostgreSQL gratuite créée pour ce test expire le **13 novembre 2026**.
Avant cette date, exporter les données ou migrer vers un stockage durable.
Le site est destiné aux essais, pas aux vraies commandes clients.
Les courriels ne sont pas encore configurés. L'API ne prétend pas les envoyer.
Sans DATABASE_URL sur Render, la vitrine fonctionne et l'enregistrement des
commandes est explicitement bloqué pour éviter toute fausse confirmation.

## API compatible avec le logiciel

`GET /api/health`, `POST /api/orders`, `GET /api/catalog`.
Routes protégées par `X-EM-API-Key` : `GET /api/sync/ping`,
`GET /api/sync/orders?since=...`, `PUT /api/sync/catalog`,
`POST /api/sync/orders/<id>/status`.
L'export `/api/sync/orders` conserve les coordonnées, le détail des articles,
les pièces spéciales et l'historique des statuts. Les prix sont recalculés à
partir du catalogue V10.6. La publication du catalogue depuis le logiciel
est stockée, mais son affichage dans le panier reste à intégrer.

Le mode admin original reste local au navigateur (localStorage / IndexedDB).
Il ne publie pas encore ses changements pour tous les visiteurs.

## Local

`python app.py` démarre sur http://127.0.0.1:8765.
Sans DATABASE_URL en local, SQLite est utilisé dans `data/orders.sqlite3`.
Les tests s'exécutent avec `python -m unittest discover -s tests`.

## Contact et édition Admin — 21 octobre 2026

Modification fondée sur le commit actif Render `3153b20eaf710d09e81c5a9dc48d8049f28b31f2`.
Le formulaire `/api/contact` utilise Resend côté serveur, indépendamment des commandes.
Variables Render : `EM_CONTACT_RESEND_KEY` (clé limitée à l’envoi sur le domaine),
`EM_CONTACT_FROM` (expéditeur vérifié), `EM_CONTACT_TO` (destinataire professionnel).
Changer le destinataire dans Render, puis redéployer. Ne jamais placer la clé dans les fichiers du site.
Une réussite est affichée uniquement après acceptation par Resend. Les reprises utilisent
la même clé d’idempotence ; validation, piège anti-robot et limitation des tentatives sont intégrés.
La limitation est en mémoire pour le service actuel à un worker ; une mise à l’échelle
nécessiterait un compteur partagé. Les commandes ne déclenchent toujours aucun e-mail.

Les liens du site sont accessibles depuis les trois étapes de commande.
La carte fidélité complète est déplaçable et redimensionnable dans l’Admin ; ses réglages
restent dans le stockage Admin existant et dans les exports/imports. La position de la
palette est mémorisée séparément dans ce navigateur et reste bornée à l’écran.
Les modifications Admin restent locales au navigateur, comme auparavant.

Tests : `python -m unittest discover -s tests`.

## Réglages visuels Admin durables

La référence officielle est **https://commandes.empoissonnerie.com/**, déploiement Render du commit `691f32cfa291f3e411d529e406acc149a3ce040b`. Les pages HTML, les photos et le parcours de commande restent ceux de ce déploiement.

Les réglages de l'éditeur visuel sont maintenant indépendants du dépôt Git :

- `em_admin_document` : état partagé des quatre pages, position globale du panneau et numéro de révision. Toutes les modifications enregistrées sont immédiatement visibles aux nouvelles visites.
- `em_admin_media` : images optimisées, identifiées par SHA-256, stockées dans PostgreSQL. Une nouvelle photo ne remplace pas les octets d'une ancienne image.
- `em_admin_versions` : instantanés des quatre pages, avec leurs références d'images. Le bouton **Publier / figer cette version** ajoute un instantané. **Restaurer la dernière version figée** recharge le dernier instantané publié et conserve une copie de sécurité de l'état remplacé.
- `em_admin_private` : empreinte du mot de passe, clé de signature de session, jeton temporaire d'activation et limitation des tentatives. Rien de cette table n'est exposé à l'API publique ou inclus dans les sauvegardes visuelles.

Ces tables ne sont jamais réinitialisées au déploiement. Les tables commandes, mails et catalogue, les routes `/api/sync/*`, leur clé et le fonctionnement de Stripe ne changent pas. SQLite est réservé aux tests locaux ; sur Render, `DATABASE_URL` reste obligatoire.

### Première connexion et récupération des anciens réglages

Dans la console Shell authentifiée du service Render, exécuter une fois :

```python
python -c "from app import admin_store; admin_store.init(); print(admin_store.bootstrap())"
```

Le résultat est un jeton d'activation secret, à usage unique, valable 30 minutes. Ouvrir `/admin#setup=JETON` sur l'adresse du service, choisir et confirmer un mot de passe d'au moins 12 caractères. Le jeton est retiré immédiatement de l'adresse et aucun mot de passe n'est écrit dans le JavaScript, GitHub ou le stockage navigateur. La connexion utilise un cookie signé HttpOnly, Secure en production, SameSite Strict, valable huit heures, et les écritures exigent un jeton CSRF.

Depuis le navigateur et l'adresse où les anciennes modifications ont été faites : ouvrir **ADMIN**, se connecter, puis **Récupérer les anciens réglages**. Cette action propose le transfert des clés `em-poissonnerie-v10-admin:*` des quatre pages, de `em-poissonnerie-admin-panel-position`, et des images IndexedDB `em-poissonnerie-v10-images`. Elle crée un instantané serveur de sécurité avant de transférer. Si une image locale manque, le transfert est interrompu avant de remplacer les réglages. Les anciennes clés et blobs restent présents.

Un navigateur ne peut pas lire les données privées d'un autre navigateur ou d'une autre origine. Pour transférer des réglages provenant d'une autre adresse, exporter depuis l'ancien éditeur puis importer le fichier sur la page correspondante du nouvel Admin. Ne pas effacer les données de l'ancien navigateur avant récupération.

### Sauvegarder et restaurer

- **Exporter / Importer** : fichier JSON autonome de la page avec les images remplacées.
- **Sauvegarde complète du site** : téléchargement authentifié d'un JSON contenant les quatre pages, les images et les instantanés. Le bouton **Importer**, depuis n'importe quelle page, reconnaît ce fichier et restaure les quatre pages courantes ; les instantanés précédents sont également présents dans le fichier pour archivage.
- **Publier / figer** puis **Restaurer la dernière version figée** : retour rapide sans fichier. Les instantanés et les anciennes images sont conservés.
- Une modification non envoyée est conservée séparément dans `em-admin-pending:PAGE`. L'indicateur ne confirme l'enregistrement qu'après réponse du serveur. En cas de réseau indisponible, reprise automatique toutes les dix secondes et au retour réseau. **Récupérer une sauvegarde non envoyée** permet de récupérer cette copie après une reconnexion.
- Les écritures utilisent une révision et une transaction verrouillée. Une session obsolète reçoit un conflit, au lieu d'écraser les modifications d'une autre session. Exporter la page locale avant rechargement si nécessaire.

Le fichier de sauvegarde visuelle n'est pas une sauvegarde des commandes. La sauvegarde PostgreSQL Render couvre la base dans son ensemble. Le stockage des images partage le quota existant de la base ; aucun abonnement de stockage supplémentaire n'est créé.

Validation locale : `python -m unittest discover -s tests -v` et `node --check site/assets/admin/admin.js`. Les tests d'e-mail utilisent un fournisseur simulé, sans envoi externe.
