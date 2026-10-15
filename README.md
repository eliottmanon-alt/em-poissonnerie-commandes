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
