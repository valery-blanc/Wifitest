"""WifiTest — worker de crack portable (Anqa, RunPod, ou local).

Boucle : tire un job du webservice (sortie HTTPS), lance une **cascade** d'attaques
`hashcat -m 22000` (du plus probable au plus large, arrêt au 1er hit, bornée par un budget
temps), poste le résultat. Le hash 22000 étant portable, le même worker tourne partout où
hashcat + un GPU sont présents.

Config par variables d'environnement :
  WIFITEST_SERVER        URL du webservice (ex: https://wifitest.zitoon.com)
  WIFITEST_WORKER_TOKEN  bearer token worker
  WIFITEST_HASHCAT       chemin de hashcat (défaut: "hashcat")
  WIFITEST_HASHCAT_EXTRA args hashcat supplémentaires communs (ex: "-d 1")
  WIFITEST_WORKER_ID     identifiant du worker (défaut: hostname)
  WIFITEST_POLL_SECONDS  intervalle de poll quand la file est vide (défaut: 10)
  WIFITEST_IDLE_EXIT     sortie auto après N s sans job (0 = désactivé ; utile sur pod)

  --- cascade (FEAT-002) ---
  WIFITEST_WORDLIST      wordlist ciblée (passe 1, mots de passe connus)
  WIFITEST_ROCKYOU       rockyou.txt (passes rockyou / rockyou+règles / suffixe chiffres)
  WIFITEST_RULES         règles custom (`;`-séparées) remplaçant best64/OneRule auto
  WIFITEST_MASKS         masques -a 3 (`;`-séparés) remplaçant 8/10 chiffres auto
  WIFITEST_MAX_RUNTIME   budget temps total en secondes (défaut: 3600 = 1 h)

Usage : python worker.py [--once]
  --once : traite un seul job puis quitte (utile pour les tests).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time

import requests

SERVER = os.environ.get("WIFITEST_SERVER", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("WIFITEST_WORKER_TOKEN", "")
HASHCAT = os.environ.get("WIFITEST_HASHCAT", "hashcat")
HASHCAT_EXTRA = os.environ.get("WIFITEST_HASHCAT_EXTRA", "").split()
WORKER_ID = os.environ.get("WIFITEST_WORKER_ID", socket.gethostname())
POLL_SECONDS = int(os.environ.get("WIFITEST_POLL_SECONDS", "10"))
# Sortie automatique après N s sans job (0 = désactivé). Sur un pod RunPod, le script
# appelant enchaîne alors sur podTerminate → le pod ne facture plus.
IDLE_EXIT = int(os.environ.get("WIFITEST_IDLE_EXIT", "0"))

# --- cascade (FEAT-002) ---
WORDLIST = os.environ.get("WIFITEST_WORDLIST", "")
ROCKYOU = os.environ.get("WIFITEST_ROCKYOU", "")
RULES = [r for r in os.environ.get("WIFITEST_RULES", "").split(";") if r.strip()]
MASKS = [m for m in os.environ.get("WIFITEST_MASKS", "").split(";") if m.strip()]
MAX_RUNTIME = int(os.environ.get("WIFITEST_MAX_RUNTIME", "3600"))
# Intervalle de remontée de progression pendant une passe longue (anti-requeue « stale »).
PROGRESS_EVERY = 30
# Codes de sortie hashcat considérés comme « passe terminée sans erreur » :
# 0=cracked 1=exhausted 2=abort 3=abort-checkpoint 4=abort-runtime 5=abort-finish
HC_OK_CODES = {0, 1, 2, 3, 4, 5}

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def claim() -> dict | None:
    r = requests.get(f"{SERVER}/jobs/next", headers=HEADERS,
                     params={"worker_id": WORKER_ID}, timeout=30)
    r.raise_for_status()
    return r.json().get("job")


def post_result(job_id: str, status: str, password: str | None = None,
                error: str | None = None, slice_index: int | None = None) -> None:
    body: dict = {"status": status, "password": password, "error": error}
    if slice_index is not None:
        body["slice"] = slice_index
    r = requests.post(f"{SERVER}/jobs/{job_id}/result", headers=HEADERS,
                      json=body, timeout=30)
    r.raise_for_status()


def post_progress(job_id: str, progress: float, tried: int = 0,
                  phase: str | None = None, slice_index: int | None = None) -> None:
    body: dict = {"progress": progress, "tried": tried, "phase": phase}
    if slice_index is not None:
        body["slice"] = slice_index
    try:
        requests.post(f"{SERVER}/jobs/{job_id}/progress", headers=HEADERS,
                      json=body, timeout=10)
    except requests.RequestException:
        pass


def check_cancel(job_id: str) -> bool:
    try:
        r = requests.get(f"{SERVER}/jobs/{job_id}/cancel", headers=HEADERS, timeout=10)
        return bool(r.ok and r.json().get("cancel"))
    except requests.RequestException:
        return False


def build_cascade(hashcat_dir: str, hash_file: str) -> list[tuple[str, list[str]]]:
    """Construit la liste ordonnée des passes (label, args d'attaque après le préfixe commun).
    Ressource absente → passe omise. Ordre = du plus probable/rapide au plus large."""
    rockyou = ROCKYOU if (ROCKYOU and os.path.exists(ROCKYOU)) else None

    # Règles : celles fournies par l'utilisateur, sinon best64 (tôt) + OneRule (tard, lourd).
    early_rules: list[str] = []
    heavy_rules: list[str] = []
    if RULES:
        early_rules = [r for r in RULES if os.path.exists(r)]
    else:
        best64 = os.path.join(hashcat_dir, "rules", "best64.rule")
        if os.path.exists(best64):
            early_rules.append(best64)
        if rockyou:
            one = os.path.join(os.path.dirname(rockyou), "OneRuleToRuleThemAll.rule")
            if os.path.exists(one):
                heavy_rules.append(one)

    # Masques : ceux fournis, sinon 8 chiffres (tôt) puis 10 chiffres (tard).
    if MASKS:
        masks_small, masks_big = MASKS, []
    else:
        masks_small = ["?d?d?d?d?d?d?d?d"]          # 8 chiffres (dates) — 10^8
        masks_big = ["?d?d?d?d?d?d?d?d?d?d"]         # 10 chiffres (tél)  — 10^10

    steps: list[tuple[str, list[str]]] = []
    if WORDLIST and os.path.exists(WORDLIST):
        steps.append(("wordlist ciblée", ["-a", "0", hash_file, WORDLIST]))
    if rockyou:
        steps.append(("rockyou", ["-a", "0", hash_file, rockyou]))
        for r in early_rules:
            steps.append((f"rockyou+{os.path.basename(r)}",
                          ["-a", "0", hash_file, rockyou, "-r", r]))
    for m in masks_small:
        steps.append((f"masque {m}", ["-a", "3", hash_file, m]))
    if rockyou:
        steps.append(("rockyou+2chiffres", ["-a", "6", hash_file, rockyou, "?d?d"]))
        for r in heavy_rules:
            steps.append((f"rockyou+{os.path.basename(r)}",
                          ["-a", "0", hash_file, rockyou, "-r", r]))
    for m in masks_big:
        steps.append((f"masque {m}", ["-a", "3", hash_file, m]))
    return steps


def _read_password(out_file: str) -> str | None:
    if os.path.exists(out_file):
        content = open(out_file, encoding="utf-8", errors="replace").read().strip()
        if content:
            return content.splitlines()[0]
    return None


def _keyspace(hashcat_dir: str, attack: list[str]) -> int | None:
    """Taille de la passe. None si hashcat ne sait pas la dire : la part 0 fera toute la passe."""
    try:
        r = subprocess.run([HASHCAT, "--keyspace", *attack], cwd=hashcat_dir or None,
                           capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    for line in reversed((r.stdout or "").splitlines()):
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def _bounds(keyspace: int, index: int, count: int) -> tuple[int, int]:
    base, extra = divmod(keyspace, count)
    skip = index * base + min(index, extra)
    limit = base + (1 if index < extra else 0)
    return skip, limit


def _run_step(cmd: list[str], err_file: str, cwd: str | None, job_id: str,
              start: float, budget: int, phase: str,
              slice_index: int | None = None) -> tuple[bool, int | None]:
    """Lance une passe hashcat en process suivable. Sonde l'annulation (kill si Stop) et
    remonte la progression (temps écoulé / budget) + la passe en cours. Retourne
    (canceled, returncode)."""
    with open(err_file, "a", encoding="utf-8", errors="replace") as ef:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=ef,
                                 text=True, cwd=cwd or None)
        last_prog = 0.0
        while proc.poll() is None:
            if check_cancel(job_id):
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return True, None
            now = time.time()
            if now - last_prog > PROGRESS_EVERY:
                pct = min(99.0, (now - start) / budget * 100.0)
                post_progress(job_id, round(pct, 1), phase=phase, slice_index=slice_index)
                last_prog = now
            time.sleep(3)
    return False, proc.returncode


def crack(job: dict) -> tuple[str, str | None, str | None]:
    """Retourne (status, password, error). status ∈ found|not_found|error|stopped.
    Cascade d'attaques bornée par MAX_RUNTIME, arrêt au 1er hit, interruptible."""
    job_id = job["job_id"]
    with tempfile.TemporaryDirectory() as tmp:
        hash_file = os.path.join(tmp, "hash.22000")
        out_file = os.path.join(tmp, "cracked.txt")
        err_file = os.path.join(tmp, "err.txt")
        with open(hash_file, "w", encoding="ascii") as f:
            f.write(job["hash_22000"].strip() + "\n")

        hashcat_dir = os.path.dirname(HASHCAT)  # hashcat cherche son OpenCL/ dans le CWD
        steps = build_cascade(hashcat_dir, hash_file)
        if not steps:
            return "error", None, ("aucune ressource de crack : définir WIFITEST_WORDLIST "
                                   "et/ou WIFITEST_ROCKYOU")

        slice_i = int(job.get("slice") or 0)
        slice_n = max(1, int(job.get("slice_count") or 1))
        common = [HASHCAT, "-m", "22000", "--quiet", "--potfile-disable",
                  "--outfile", out_file, "--outfile-format", "2", *HASHCAT_EXTRA]
        # Budget : celui du job (choisi dans l'UI) sinon le défaut du worker.
        budget = int(job.get("max_runtime") or MAX_RUNTIME)
        start = time.time()
        clean_ran = False
        ran_any = False
        last_err = ""

        for i, (label, attack) in enumerate(steps):
            remaining = int(budget - (time.time() - start))
            if remaining < 5:
                print(f"[{job_id}] budget épuisé, arrêt de la cascade", flush=True)
                break
            part = ""
            step = list(attack)
            if slice_n > 1:
                ks = _keyspace(hashcat_dir, attack)
                if ks is None:
                    if slice_i != 0:
                        continue
                else:
                    skip, limit = _bounds(ks, slice_i, slice_n)
                    if limit <= 0:
                        continue
                    step += ["--skip", str(skip), "--limit", str(limit)]
                part = f" partie {slice_i + 1}/{slice_n}"
            phase = f"{label} ({i + 1}/{len(steps)}){part}"
            post_progress(job_id, round((time.time() - start) / budget * 100.0, 1),
                          phase=phase, slice_index=slice_i if slice_n > 1 else None)
            cmd = common + ["--runtime", str(remaining)] + step
            ran_any = True
            print(f"[{job_id}] passe {i + 1}/{len(steps)} : {label}{part} "
                  f"(reste {remaining}s)", flush=True)
            canceled, rc = _run_step(cmd, err_file, hashcat_dir, job_id, start,
                                     budget, phase,
                                     slice_i if slice_n > 1 else None)
            if canceled:
                print(f"[{job_id}] annulé (Stop)", flush=True)
                return "stopped", None, None
            pw = _read_password(out_file)
            if pw:
                return "found", pw, None
            if rc in HC_OK_CODES:
                clean_ran = True
            else:
                last_err = (open(err_file, encoding="utf-8", errors="replace").read()
                            if os.path.exists(err_file) else f"rc={rc}")

        pw = _read_password(out_file)
        if pw:
            return "found", pw, None
        if clean_ran or not ran_any:
            return "not_found", None, None
        return "error", None, (last_err or "échec hashcat").strip()[:2000]


def handle_one() -> bool:
    """Traite un job si disponible. Retourne True si un job a été traité."""
    job = claim()
    if not job:
        return False
    jid = job["job_id"]
    print(f"[{jid}] claimé (ssid={job.get('ssid')})", flush=True)
    try:
        status, password, error = crack(job)
    except Exception as exc:  # noqa: BLE001 — on remonte toute erreur au serveur
        status, password, error = "error", None, f"{type(exc).__name__}: {exc}"
    slice_n = int(job.get("slice_count") or 1)
    post_result(jid, status, password, error,
                slice_index=int(job.get("slice") or 0) if slice_n > 1 else None)
    print(f"[{jid}] -> {status}" + (f" ({password})" if password else ""), flush=True)
    return True


def main() -> None:
    once = "--once" in sys.argv[1:]
    if not TOKEN:
        sys.exit("WIFITEST_WORKER_TOKEN manquant")
    print(f"worker {WORKER_ID} -> {SERVER} (once={once}, idle_exit={IDLE_EXIT}, "
          f"budget={MAX_RUNTIME}s)", flush=True)
    last_activity = time.time()
    while True:
        try:
            worked = handle_one()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code in (401, 403):
                sys.exit(f"Auth refusée par le serveur ({code}) — vérifier WIFITEST_WORKER_TOKEN")
            print(f"[http {code}] {exc}", flush=True)
            worked = False
        except requests.RequestException as exc:
            print(f"[net] {exc}", flush=True)
            worked = False
        if worked:
            last_activity = time.time()
        if once and worked:
            return
        if not worked:
            if IDLE_EXIT and time.time() - last_activity > IDLE_EXIT:
                print(f"[idle] aucun job depuis {IDLE_EXIT}s → sortie", flush=True)
                return
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
