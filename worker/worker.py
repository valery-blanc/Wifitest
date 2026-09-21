"""WifiTest — worker de crack portable (Anqa, RunPod, ou local).

Boucle : tire un job du webservice (sortie HTTPS), lance `hashcat -m 22000`, poste le
résultat. Le hash 22000 étant portable, le même worker tourne partout où hashcat + un GPU
sont présents.

Config par variables d'environnement :
  WIFITEST_SERVER        URL du webservice (ex: https://wifitest.zitoon.com)
  WIFITEST_WORKER_TOKEN  bearer token worker
  WIFITEST_HASHCAT       chemin de hashcat (défaut: "hashcat")
  WIFITEST_WORDLIST      chemin de la wordlist (attaque -a 0)   [M0]
  WIFITEST_HASHCAT_EXTRA args hashcat supplémentaires (ex: "--force -O")
  WIFITEST_WORKER_ID     identifiant du worker (défaut: hostname)
  WIFITEST_POLL_SECONDS  intervalle de poll quand la file est vide (défaut: 10)

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
WORDLIST = os.environ.get("WIFITEST_WORDLIST", "")
HASHCAT_EXTRA = os.environ.get("WIFITEST_HASHCAT_EXTRA", "").split()
WORKER_ID = os.environ.get("WIFITEST_WORKER_ID", socket.gethostname())
POLL_SECONDS = int(os.environ.get("WIFITEST_POLL_SECONDS", "10"))

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def claim() -> dict | None:
    r = requests.get(f"{SERVER}/jobs/next", headers=HEADERS,
                     params={"worker_id": WORKER_ID}, timeout=30)
    r.raise_for_status()
    return r.json().get("job")


def post_result(job_id: str, status: str, password: str | None = None,
                error: str | None = None) -> None:
    r = requests.post(f"{SERVER}/jobs/{job_id}/result", headers=HEADERS,
                      json={"status": status, "password": password, "error": error},
                      timeout=30)
    r.raise_for_status()


def crack(job: dict) -> tuple[str, str | None, str | None]:
    """Retourne (status, password, error). status ∈ found|not_found|error."""
    if not WORDLIST or not os.path.exists(WORDLIST):
        return "error", None, f"WIFITEST_WORDLIST introuvable: {WORDLIST!r}"

    with tempfile.TemporaryDirectory() as tmp:
        hash_file = os.path.join(tmp, "hash.22000")
        out_file = os.path.join(tmp, "cracked.txt")
        with open(hash_file, "w", encoding="ascii") as f:
            f.write(job["hash_22000"].strip() + "\n")

        cmd = [HASHCAT, "-m", "22000", "-a", "0",
               "--quiet", "--potfile-disable",
               "--outfile", out_file, "--outfile-format", "2",
               *HASHCAT_EXTRA, hash_file, WORDLIST]
        print(f"[{job['job_id']}] $ {' '.join(cmd)}", flush=True)
        # hashcat cherche son dossier OpenCL/ de kernels dans le CWD → se placer dans son
        # répertoire (utile pour le hashcat portable ; inoffensif pour un hashcat du PATH).
        hashcat_dir = os.path.dirname(HASHCAT)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=hashcat_dir or None)

        # La présence d'un mot de passe dans l'outfile fait foi (plus fiable que le rc).
        password = None
        if os.path.exists(out_file):
            content = open(out_file, encoding="utf-8", errors="replace").read().strip()
            if content:
                password = content.splitlines()[0]

        if password:
            return "found", password, None
        if proc.returncode in (0, 1):   # 1 = keyspace épuisé sans hit
            return "not_found", None, None
        return "error", None, (proc.stderr or proc.stdout or f"rc={proc.returncode}").strip()[:2000]


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
    post_result(jid, status, password, error)
    print(f"[{jid}] -> {status}" + (f" ({password})" if password else ""), flush=True)
    return True


def main() -> None:
    once = "--once" in sys.argv[1:]
    if not TOKEN:
        sys.exit("WIFITEST_WORKER_TOKEN manquant")
    print(f"worker {WORKER_ID} -> {SERVER} (once={once})", flush=True)
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
        if once and worked:
            return
        if not worked:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
