"""WifiTest — webservice : file de jobs (workers) + UI pcap.zitoon.com.

- Workers (Anqa / RunPod) : endpoints token (/jobs/next, /jobs/{id}/result, ...).
- UI humaine (pcap.zitoon.com) : login mot de passe + cookie de session, upload pcap →
  hcxpcapngtool → hash 22000 → job(s) → affichage SSID + mot de passe (poll, asynchrone).

Déployé en conteneur Docker derrière Traefik sur Fez + Avignon.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from . import db

HERE = os.path.dirname(__file__)

PHONE_TOKEN = os.environ.get("WIFITEST_PHONE_TOKEN", "")
WORKER_TOKEN = os.environ.get("WIFITEST_WORKER_TOKEN", "")
UI_PASSWORD = os.environ.get("WIFITEST_UI_PASSWORD", "")
SESSION_SECRET = os.environ.get("WIFITEST_SESSION_SECRET", "") or secrets.token_hex(32)
MAX_UPLOAD = int(os.environ.get("WIFITEST_MAX_UPLOAD", str(60 * 1024 * 1024)))  # 60 Mo

SESSION_TTL = 12 * 3600
COOKIE = "wt_session"
MAX_FAILS = 6
LOCK_SECONDS = 300

_ser = URLSafeTimedSerializer(SESSION_SECRET, salt="wt-ui")
_fails: dict[str, tuple[int, float]] = {}  # ip -> (count, lock_until)

app = FastAPI(title="WifiTest", version="1.0")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    if DISPATCHER_ON:
        threading.Thread(target=_dispatcher_loop, daemon=True).start()


# ---- auth workers / téléphone (token) --------------------------------------

def _check(authorization: str | None, expected: str) -> None:
    if not expected:
        raise HTTPException(500, "Server token not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "Invalid or missing token")


def phone_auth(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, PHONE_TOKEN)


def worker_auth(authorization: str | None = Header(default=None)) -> None:
    _check(authorization, WORKER_TOKEN)


# ---- auth UI (mot de passe + session) --------------------------------------

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _lock_remaining(ip: str) -> int:
    count, until = _fails.get(ip, (0, 0.0))
    return max(0, int(until - time.time())) if count >= MAX_FAILS else 0


def _register_fail(ip: str) -> int:
    count, _ = _fails.get(ip, (0, 0.0))
    count += 1
    until = time.time() + LOCK_SECONDS if count >= MAX_FAILS else 0.0
    _fails[ip] = (count, until)
    return max(0, MAX_FAILS - count)


def _reset_fails(ip: str) -> None:
    _fails.pop(ip, None)


def _valid_session(cookie: str | None) -> bool:
    if not cookie:
        return False
    try:
        _ser.loads(cookie, max_age=SESSION_TTL)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_session(request: Request) -> None:
    if not _valid_session(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Session requise")


# ---- pages UI --------------------------------------------------------------

def _page(path: str) -> str:
    with open(os.path.join(HERE, "static", path), encoding="utf-8") as f:
        return f.read()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return HTMLResponse(_page("app.html" if _valid_session(request.cookies.get(COOKIE)) else "login.html"))


@app.post("/api/login")
async def login(request: Request):
    ip = _client_ip(request)
    locked = _lock_remaining(ip)
    if locked:
        return JSONResponse({"locked": locked}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        body = {}
    pw = (body or {}).get("password", "")
    if UI_PASSWORD and secrets.compare_digest(str(pw), UI_PASSWORD):
        _reset_fails(ip)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, _ser.dumps({"ok": True}), httponly=True, secure=True,
                        samesite="lax", max_age=SESSION_TTL, path="/")
        return resp
    reste = _register_fail(ip)
    locked = _lock_remaining(ip)
    if locked:
        return JSONResponse({"locked": locked}, status_code=429)
    return JSONResponse({"reste": reste}, status_code=401)


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


def _budget_seconds(budget_min: int | None) -> int | None:
    """Convertit un budget en minutes (input UI) en secondes, borné 1 min .. 12 h."""
    if not budget_min:
        return None
    return max(60, min(int(budget_min), 720) * 60)


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...),
                 budget_min: int | None = Form(None)):
    require_session(request)
    budget = _budget_seconds(budget_min)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"Fichier trop gros (max {MAX_UPLOAD // (1024*1024)} Mo)")
    if not data:
        raise HTTPException(422, "Fichier vide")

    with tempfile.TemporaryDirectory() as td:
        pcap = os.path.join(td, "in.pcap")
        out = os.path.join(td, "out.22000")
        with open(pcap, "wb") as f:
            f.write(data)
        try:
            subprocess.run(["hcxpcapngtool", "-o", out, pcap],
                           capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise HTTPException(500, "hcxpcapngtool absent du serveur")
        except subprocess.TimeoutExpired:
            raise HTTPException(500, "Conversion trop longue (timeout)")

        lines = []
        if os.path.exists(out):
            with open(out, encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f if ln.strip().startswith("WPA*")]

    seen: set[str] = set()
    uniq = [ln for ln in lines if not (ln in seen or seen.add(ln))]
    if not uniq:
        return JSONResponse({"created": [], "message":
            "Aucun hash exploitable dans ce pcap (pas de handshake complet M1/M2 ni de PMKID)."})

    # sauvegarder le pcap source pour pouvoir le supprimer via la poubelle
    os.makedirs(PCAP_DIR, exist_ok=True)
    pcap_name: str | None = uuid.uuid4().hex + ".pcap"
    try:
        with open(os.path.join(PCAP_DIR, pcap_name), "wb") as f:
            f.write(data)
    except Exception:
        pcap_name = None

    created = []
    for line in uniq:
        parts = line.split("*")
        ssid = ""
        if len(parts) > 5:
            try:
                ssid = bytes.fromhex(parts[5]).decode("utf-8", errors="replace")
            except ValueError:
                ssid = parts[5]
        jid = db.create_job(line, ssid or None, None, None, pcap=pcap_name,
                            max_runtime=budget)
        created.append({"job_id": jid, "ssid": ssid})
    return {"created": created, "message": f"{len(created)} réseau(x) → mis en file pour crack."}


@app.get("/api/jobs")
def api_jobs(request: Request):
    require_session(request)
    out = []
    for j in db.list_jobs(200):
        out.append({
            "job_id": j["id"], "ssid": j["ssid"], "status": j["status"],
            "password": j["password"], "error": j["error"],
            "progress": j["progress"], "created_at": j["created_at"],
            "worker_id": j["worker_id"], "started_at": j["started_at"],
            "phase": j["phase"], "max_runtime": j["max_runtime"],
        })
    return {"jobs": out, "now": time.time()}


@app.post("/api/jobs/{job_id}/stop")
def api_stop(request: Request, job_id: str):
    require_session(request)
    action = db.request_cancel(job_id)
    if action is None:
        raise HTTPException(404, "Unknown job")
    return {"ok": True, "action": action}


@app.delete("/api/jobs/{job_id}")
def api_delete(request: Request, job_id: str):
    require_session(request)
    job = db.delete_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    pcap = job.get("pcap")
    if pcap and db.count_pcap_refs(pcap) == 0:
        try:
            os.remove(os.path.join(PCAP_DIR, os.path.basename(pcap)))
        except OSError:
            pass
    return {"ok": True}


class RerunReq(BaseModel):
    budget_min: int | None = None


@app.post("/api/jobs/{job_id}/rerun")
def api_rerun(request: Request, job_id: str, r: RerunReq | None = None):
    """Bouton Play : relance un crack terminé (stopped/not_found/error/found)."""
    require_session(request)
    budget = _budget_seconds(r.budget_min if r else None)
    if not db.requeue_job(job_id, budget):
        raise HTTPException(409, "Job introuvable ou déjà en file/en cours")
    return {"ok": True}


# ---- infra : Anqa (WOL) / RunPod (crédit) / mode de dispatch ---------------

POWER_URL = os.environ.get("WIFITEST_POWER_URL", "http://192.168.0.250:8533").rstrip("/")
POWER_TOKEN = os.environ.get("POWER_TOKEN", "")
ANQA_ENDPOINTS = [("192.168.0.133", 22), ("192.168.0.112", 22)]
SETTINGS_FILE = os.environ.get("WIFITEST_SETTINGS", "/data/settings.json")
PCAP_DIR = os.environ.get("WIFITEST_PCAP_DIR", "/data/pcaps")
DEFAULT_MODE = "auto"  # anqa | pod | auto (pod si Anqa indisponible)


def _settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(s: dict) -> None:
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, SETTINGS_FILE)


def get_mode() -> str:
    m = _settings().get("mode", DEFAULT_MODE)
    return m if m in ("anqa", "pod", "auto") else DEFAULT_MODE


def anqa_reachable() -> bool:
    for host, port in ANQA_ENDPOINTS:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            continue
    return False


def _runpod_gql(query: str, key: str) -> dict:
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        "https://api.runpod.io/graphql?api_key=" + key, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _runpod_balance(key: str) -> dict | None:
    try:
        d = _runpod_gql("query{myself{clientBalance currentSpendPerHr spendLimit}}", key)
        m = (d.get("data") or {}).get("myself") or {}
        return {"balance": m.get("clientBalance"), "spend_hr": m.get("currentSpendPerHr"),
                "limit": m.get("spendLimit")}
    except Exception:
        return None


def runpod_accounts() -> list[dict]:
    keys = []
    k1 = os.environ.get("RUNPOD_API_KEY", "").strip()
    if k1:
        keys.append(("Compte 1", k1))
    i = 2
    while True:
        k = os.environ.get(f"RUNPOD_API_KEY_{i}", "").strip()
        if not k:
            break
        keys.append((f"Compte {i}", k))
        i += 1
    out = []
    for label, key in keys:
        b = _runpod_balance(key)
        out.append({"label": label, "balance": (b or {}).get("balance"),
                    "spend_hr": (b or {}).get("spend_hr"), "ok": b is not None})
    return out


def _power(path: str) -> dict:
    req = urllib.request.Request(POWER_URL + path, data=b"", method="POST",
                                 headers={"X-Power-Token": POWER_TOKEN})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


@app.get("/api/status")
def api_status(request: Request):
    require_session(request)
    return {"anqa": anqa_reachable(), "mode": get_mode(), "runpod": runpod_accounts()}


@app.post("/api/anqa/wake")
def api_wake(request: Request):
    require_session(request)
    try:
        return {"ok": True, "resp": _power("/anqa/on")}
    except Exception as exc:
        raise HTTPException(502, f"gqqfm-power injoignable: {exc}")


class ModeReq(BaseModel):
    mode: str


@app.post("/api/mode")
def api_set_mode(request: Request, m: ModeReq):
    require_session(request)
    if m.mode not in ("anqa", "pod", "auto"):
        raise HTTPException(422, "mode invalide")
    s = _settings()
    s["mode"] = m.mode
    _save_settings(s)
    return {"ok": True, "mode": m.mode}


# ---- RunPod pod (fallback GPU) : create / terminate / dispatcher -----------

RUNPOD_POD_KEY = os.environ.get("RUNPOD_API_KEY_2", "") or os.environ.get("RUNPOD_API_KEY", "")
POD_IMAGE = os.environ.get("WIFITEST_POD_IMAGE", "dizcza/docker-hashcat:cuda")
POD_GPU = os.environ.get("WIFITEST_POD_GPU", "NVIDIA GeForce RTX 4090")
POD_NAME = "wifitest-crack"
MAX_POD_LIFE = int(os.environ.get("WIFITEST_MAX_POD_LIFE", "1800"))  # garde-fou 30 min
PUBLIC_URL = os.environ.get("WIFITEST_PUBLIC_URL", "https://wifitest.zitoon.com").rstrip("/")
DISPATCHER_ON = os.environ.get("WIFITEST_DISPATCHER", "0") == "1"


def _pod_gql(query: str) -> dict:
    if not RUNPOD_POD_KEY:
        raise RuntimeError("Clé RunPod manquante")
    return _runpod_gql(query, RUNPOD_POD_KEY)


def _pod_create() -> str | None:
    # L'image de base CUDA n'a pas curl → l'installer avant de récupérer le bootstrap.
    boot = ("bash -c 'apt-get update -qq && apt-get install -y -qq curl ca-certificates && "
            f"curl -fsSL {PUBLIC_URL}/static/bootstrap.sh | bash'")
    envs = [("WIFITEST_SERVER", PUBLIC_URL), ("WIFITEST_WORKER_TOKEN", WORKER_TOKEN),
            ("RUNPOD_API_KEY", RUNPOD_POD_KEY), ("WIFITEST_IDLE_EXIT", "180")]
    envg = ",".join('{key:"%s",value:"%s"}' % (k, v) for k, v in envs)
    q = ('mutation{podFindAndDeployOnDemand(input:{cloudType:ALL,gpuCount:1,gpuTypeId:"%s",'
         'name:"%s",imageName:"%s",containerDiskInGb:20,volumeInGb:0,dockerArgs:"%s",env:[%s]}){id}}'
         % (POD_GPU, POD_NAME, POD_IMAGE, boot, envg))
    d = _pod_gql(q)
    return (((d.get("data") or {}).get("podFindAndDeployOnDemand")) or {}).get("id")


def _pod_terminate(pid: str) -> None:
    try:
        _pod_gql('mutation{podTerminate(input:{podId:"%s"})}' % pid)
    except Exception:
        pass


def _pods_wifitest() -> list[dict]:
    try:
        d = _pod_gql("query{myself{pods{id name desiredStatus}}}")
        pods = ((d.get("data") or {}).get("myself") or {}).get("pods") or []
        return [p for p in pods if (p.get("name") or "").startswith(POD_NAME)]
    except Exception:
        return []


def _dispatch_tick() -> None:
    s = _settings()
    pid = s.get("pod_id")
    started = s.get("pod_started", 0)
    jobs = db.list_jobs(300)
    active = [j for j in jobs if j["status"] in ("queued", "running")]
    queued = [j for j in jobs if j["status"] == "queued"]

    if pid and (time.time() - started > MAX_POD_LIFE or not active):
        _pod_terminate(pid)
        s.pop("pod_id", None); s.pop("pod_started", None); _save_settings(s)
        return

    mode = get_mode()
    want_pod = mode in ("pod", "auto") and queued and (mode == "pod" or not anqa_reachable())
    if want_pod and not pid:
        new = _pod_create()
        if new:
            s["pod_id"] = new; s["pod_started"] = time.time(); _save_settings(s)


def _dispatcher_loop() -> None:
    for p in _pods_wifitest():       # nettoyage au démarrage
        _pod_terminate(p["id"])
    s = _settings(); s.pop("pod_id", None); s.pop("pod_started", None); _save_settings(s)
    while True:
        try:
            _dispatch_tick()
        except Exception:
            pass
        time.sleep(15)


# ---- endpoints file de jobs (téléphone / workers) --------------------------

class CreateJob(BaseModel):
    hash_22000: str = Field(...)
    ssid: str | None = None
    bssid: str | None = None
    attack_plan: dict | None = None
    max_runtime: int | None = None


class Progress(BaseModel):
    progress: float = 0
    tried: int = 0
    phase: str | None = None


class Result(BaseModel):
    status: str
    password: str | None = None
    error: str | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/jobs", dependencies=[Depends(phone_auth)])
def submit_job(req: CreateJob) -> dict:
    if not req.hash_22000.startswith("WPA*"):
        raise HTTPException(422, "hash_22000 doit être une ligne mode 22000 (WPA*...)")
    job_id = db.create_job(req.hash_22000.strip(), req.ssid, req.bssid, req.attack_plan,
                           max_runtime=req.max_runtime)
    return {"job_id": job_id}


# ⚠️ Route STATIQUE avant la route dynamique /jobs/{job_id}.
@app.get("/jobs/next", dependencies=[Depends(worker_auth)])
def claim_job(worker_id: str = "worker") -> dict:
    job = db.claim_next_job(worker_id)
    if job is None:
        return {"job": None}
    return {"job": {
        "job_id": job["id"], "hash_22000": job["hash_22000"], "ssid": job["ssid"],
        "bssid": job["bssid"], "attack_plan": job["attack_plan"],
        "max_runtime": job.get("max_runtime"),
    }}


@app.get("/jobs/{job_id}", dependencies=[Depends(phone_auth)])
def job_status(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return {"job_id": job["id"], "status": job["status"], "progress": job["progress"],
            "tried": job["tried"], "password": job["password"], "error": job["error"],
            "ssid": job["ssid"]}


@app.post("/jobs/{job_id}/progress", dependencies=[Depends(worker_auth)])
def post_progress(job_id: str, p: Progress) -> dict:
    if not db.update_progress(job_id, p.progress, p.tried, p.phase):
        raise HTTPException(404, "Unknown or non-running job")
    return {"ok": True}


@app.post("/jobs/{job_id}/result", dependencies=[Depends(worker_auth)])
def post_result(job_id: str, r: Result) -> dict:
    if r.status not in ("found", "not_found", "error", "stopped"):
        raise HTTPException(422, "status invalide")
    if not db.finish_job(job_id, r.status, r.password, r.error):
        raise HTTPException(404, "Unknown job")
    return {"ok": True}


@app.get("/jobs/{job_id}/cancel", dependencies=[Depends(worker_auth)])
def job_cancel(job_id: str) -> dict:
    return {"cancel": db.is_canceled(job_id)}
