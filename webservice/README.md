# webservice — plan de contrôle WifiTest

API + file de jobs. Le téléphone soumet un hash `22000` et poll le résultat ; les workers
GPU (Anqa / RunPod) **tirent** les jobs en sortie HTTPS. Déployé sur **Fez** derrière
Traefik (`wifitest.zitoon.com`).

## Endpoints
| Méthode | Route | Auth | Rôle |
|---|---|---|---|
| GET | `/health` | — | liveness |
| POST | `/jobs` | téléphone | soumettre `{hash_22000, ssid?, bssid?, attack_plan?}` → `{job_id}` |
| GET | `/jobs/{id}` | téléphone | statut/progression/résultat |
| GET | `/jobs/next` | worker | claim atomique du prochain job (⚠️ déclarée **avant** `/jobs/{id}`) |
| POST | `/jobs/{id}/progress` | worker | progression |
| POST | `/jobs/{id}/result` | worker | `{status: found\|not_found\|error, password?, error?}` |

Auth : `Authorization: Bearer <token>`, deux tokens distincts (téléphone / worker).

## Variables d'environnement
- `WIFITEST_PHONE_TOKEN`  token téléphone (obligatoire)
- `WIFITEST_WORKER_TOKEN` token worker (obligatoire)
- `WIFITEST_DB`           chemin SQLite (défaut `jobs.db`)
- `WIFITEST_STALE_SECONDS` requeue d'un job `running` muet depuis N s (défaut 900)

## Lancer en local
```bash
python -m venv .venv && . .venv/Scripts/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
WIFITEST_PHONE_TOKEN=xxx WIFITEST_WORKER_TOKEN=yyy \
  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Déploiement Fez
Conteneur Docker isolé (ne pas toucher GQQFM) + route Traefik `wifitest.zitoon.com`,
via `/vb-deployFez`. Tokens injectés par `environment:` (jamais commités). Voir `Dockerfile`.
