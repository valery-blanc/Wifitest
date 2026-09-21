"""WifiTest — webservice / file de jobs (plan de contrôle).

Le téléphone soumet un hash 22000 et poll le résultat ; les workers GPU (Anqa / RunPod)
tirent les jobs en sortie HTTPS. Deux tokens distincts (téléphone / worker).

Déploiement : conteneur Docker derrière Traefik sur Fez (`wifitest.zitoon.com`).
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import db

PHONE_TOKEN = os.environ.get("WIFITEST_PHONE_TOKEN", "")
WORKER_TOKEN = os.environ.get("WIFITEST_WORKER_TOKEN", "")

app = FastAPI(title="WifiTest webservice", version="0.1")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _check(authorization: str | None, expected: str) -> None:
    if not expected:
        raise HTTPException(500, "Server token not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "Invalid or missing token")


def phone_auth(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, PHONE_TOKEN)


def worker_auth(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, WORKER_TOKEN)


# ---- Modèles ---------------------------------------------------------------

class CreateJob(BaseModel):
    hash_22000: str = Field(..., description="Ligne hashcat mode 22000 (WPA*01*... ou WPA*02*...)")
    ssid: str | None = None
    bssid: str | None = None
    attack_plan: dict | None = None


class Progress(BaseModel):
    progress: float = 0
    tried: int = 0


class Result(BaseModel):
    status: str  # found | not_found | error
    password: str | None = None
    error: str | None = None


# ---- Endpoints téléphone ---------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/jobs", dependencies=[Depends(phone_auth)])
def submit_job(req: CreateJob) -> dict:
    if not req.hash_22000.startswith("WPA*"):
        raise HTTPException(422, "hash_22000 doit être une ligne mode 22000 (WPA*...)")
    job_id = db.create_job(req.hash_22000.strip(), req.ssid, req.bssid, req.attack_plan)
    return {"job_id": job_id}


# ⚠️ Route STATIQUE déclarée AVANT la route dynamique /jobs/{job_id} : sinon FastAPI
# capte /jobs/next comme {job_id}="next" (et l'auth téléphone au lieu de l'auth worker).
@app.get("/jobs/next", dependencies=[Depends(worker_auth)])
def claim_job(worker_id: str = "worker") -> dict:
    job = db.claim_next_job(worker_id)
    if job is None:
        return {"job": None}
    return {"job": {
        "job_id": job["id"],
        "hash_22000": job["hash_22000"],
        "ssid": job["ssid"],
        "bssid": job["bssid"],
        "attack_plan": job["attack_plan"],
    }}


@app.get("/jobs/{job_id}", dependencies=[Depends(phone_auth)])
def job_status(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    # On n'expose pas le hash au client qui poll (déjà connu de lui) — surface minimale.
    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "tried": job["tried"],
        "password": job["password"],
        "error": job["error"],
        "ssid": job["ssid"],
    }


# ---- Endpoints worker (pull) -----------------------------------------------

@app.post("/jobs/{job_id}/progress", dependencies=[Depends(worker_auth)])
def post_progress(job_id: str, p: Progress) -> dict:
    if not db.update_progress(job_id, p.progress, p.tried):
        raise HTTPException(404, "Unknown or non-running job")
    return {"ok": True}


@app.post("/jobs/{job_id}/result", dependencies=[Depends(worker_auth)])
def post_result(job_id: str, r: Result) -> dict:
    if r.status not in ("found", "not_found", "error"):
        raise HTTPException(422, "status invalide")
    if not db.finish_job(job_id, r.status, r.password, r.error):
        raise HTTPException(404, "Unknown job")
    return {"ok": True}
