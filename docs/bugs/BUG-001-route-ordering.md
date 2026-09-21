# BUG-001 — `/jobs/next` capté par `/jobs/{job_id}` (auth inversée)

**Statut** : FIXED (2026-09-21, découvert au test M0)
**Composant** : `webservice/app/main.py`

## Symptôme
Le worker recevait **401** sur `GET /jobs/next` (token worker pourtant correct). Le token
**téléphone** sur la même route donnait **404**. Le worker bouclait sans jamais claimer.

## Reproduction
```
GET /jobs/next  -H "Authorization: Bearer <worker>"  -> 401
GET /jobs/next  -H "Authorization: Bearer <phone>"   -> 404
```

## Cause racine
FastAPI matche les routes **dans l'ordre de déclaration**. `/jobs/{job_id}` (auth
téléphone) était déclarée **avant** `/jobs/next` (auth worker) → `/jobs/next` était capté
par `{job_id}="next"`, donc soumis à l'auth téléphone et à `get_job("next")` (→ 404), et le
token worker y était rejeté (→ 401).

## Fix
Déclarer la route **statique** `/jobs/next` **avant** la route dynamique `/jobs/{job_id}`.

## Règle à retenir (→ spec §5)
Toujours déclarer les routes statiques avant les routes paramétrées qui partagent le même
préfixe. `hash_22000` de test : `WPA*01*...` (mdp `hashcat!`), voir `tests/`.
