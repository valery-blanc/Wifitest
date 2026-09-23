# FEAT-003 — Suivi d'avancement, bouton Play, budget par job, worker sans fenêtre

**Statut** : IN PROGRESS (2026-09-23)

## Contexte / besoin (Val, 2026-09-23)

1. **Suivi d'avancement** : afficher la passe en cours (laquelle), depuis combien de temps,
   sur quel worker + une **barre de progression**.
2. **Bouton Play** : relancer un crack **arrêté** (statut `stopped`) mais pas mis à la corbeille.
3. **Budget temps** : une input (en **minutes**) pour choisir le budget max d'un crack.
4. **Worker Anqa sans fenêtre** : le process ouvre une fenêtre `cmd` avec les logs → si
   possible, ne pas l'ouvrir.

⚠️ Contrainte : un scan tourne au moment de la demande → **ne pas l'interrompre**. Les
changements worker (passe affichée, budget par job, fenêtre masquée) s'appliquent au
**prochain cycle** du worker.

## Spécification

### Suivi (passe / durée / worker / barre)
- Nouveau champ job `phase` (texte, ex. `rockyou+best64.rule (3/7)`), posté par le worker via
  `POST /jobs/{id}/progress` (le body accepte désormais `phase`).
- `progress` = pourcentage **temps écoulé / budget** (0-100) pour une barre lisible.
- `GET /api/jobs` renvoie aussi `started_at`, `phase`, `max_runtime` et un `now` serveur ;
  l'UI calcule la durée écoulée (`now - started_at`) et la fait défiler entre deux polls.
- L'UI affiche, pour un job `running` : badge + **barre** + `phase` + `écoulé / budget`.
  Le worker est déjà dans la colonne Worker.

### Bouton Play (relance)
- `POST /api/jobs/{id}/rerun` (session) → `db.requeue_job` : remet un job terminé
  (`stopped|not_found|error|found`) en `queued` (reset worker_id/started_at/cancel/password/
  error/progress/phase), en réutilisant hash/ssid/pcap. Accepte un `budget_min` optionnel.
- UI : bouton ▶ affiché pour les statuts terminés (hors `queued`/`running`).

### Budget par job (minutes)
- Nouveau champ job `max_runtime` (secondes). Défini à l'upload (input minutes) et à la
  relance. Le worker lit `job.max_runtime` s'il est présent, sinon `WIFITEST_MAX_RUNTIME`.
- `GET /jobs/next` renvoie `max_runtime` au worker.
- UI : input « Budget (min) » dans la barre de contrôles (défaut 60), envoyé à l'upload et au Play.

### Worker Anqa sans fenêtre
- Lancement via un wrapper **VBS caché** (`launch_hidden.vbs`, `Run …, 0`), tâche planifiée
  `WifiTestWorker` pointée dessus ; `run_worker.bat` redirige les logs vers
  `C:\Tools\wifitest\worker.log`. → aucune fenêtre au prochain lancement.
- Fenêtre courante masquée à chaud (ShowWindow SW_HIDE, best-effort) sans tuer le process.

## Impact fichiers
- `webservice/app/db.py` : colonnes `phase`, `max_runtime` ; `create_job`, `update_progress`,
  `requeue_job`.
- `webservice/app/main.py` : modèles + `/api/jobs` (started_at/phase/max_runtime/now),
  `/jobs/next` (max_runtime), `/jobs/{id}/progress` (phase), `/api/upload` (budget_min),
  `POST /api/jobs/{id}/rerun`.
- `webservice/app/static/app.html` + `style.css` : barre, phase, durée, bouton Play, input budget.
- `worker/worker.py` (+ copie `static/worker.py`) : budget par job + `phase` posté.
- Anqa : `launch_hidden.vbs`, `run_worker.bat` (log), tâche `WifiTestWorker` (appliqué au
  prochain cycle, scan en cours non interrompu).

## Cadre
⚖️ Réseaux possédés / autorisés uniquement.
