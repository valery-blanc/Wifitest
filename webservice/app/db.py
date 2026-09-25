"""Stockage des jobs de crack — SQLite, une connexion protégée par verrou.

Un job traverse : queued -> running -> (found | not_found | error).
Le claim (`claim_next_job`) est atomique : le verrou sérialise les workers.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

DB_PATH = os.environ.get("WIFITEST_DB", "jobs.db")

# Un job "running" dont le worker n'a plus donné signe depuis ce délai est requeue.
STALE_RUNNING_SECONDS = int(os.environ.get("WIFITEST_STALE_SECONDS", "900"))

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    hash_22000  TEXT NOT NULL,
    ssid        TEXT,
    bssid       TEXT,
    attack_plan TEXT,               -- JSON, optionnel (tiers d'attaque, M3)
    status      TEXT NOT NULL,       -- queued|running|found|not_found|error
    worker_id   TEXT,
    progress    REAL DEFAULT 0,      -- 0..100
    tried       INTEGER DEFAULT 0,
    password    TEXT,
    error       TEXT,
    cancel      INTEGER DEFAULT 0,   -- demande d'annulation (le worker interrompt hashcat)
    pcap        TEXT,                -- nom du fichier pcap source (dans /data/pcaps)
    phase       TEXT,                -- passe de la cascade en cours (ex. "rockyou+best64 (3/7)")
    max_runtime INTEGER,             -- budget temps en secondes (None = défaut du worker)
    created_at  REAL NOT NULL,
    started_at  REAL,
    updated_at  REAL NOT NULL
);
"""


def init_db() -> None:
    global _conn
    with _lock:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(_SCHEMA)
        # migrations idempotentes (bases existantes)
        for col, ddl in (("cancel", "INTEGER DEFAULT 0"), ("pcap", "TEXT"),
                         ("phase", "TEXT"), ("max_runtime", "INTEGER")):
            try:
                _conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS job_slices ("
            " job_id TEXT NOT NULL, slice INTEGER NOT NULL, worker_id TEXT,"
            " state TEXT NOT NULL, updated_at REAL NOT NULL,"
            " PRIMARY KEY (job_id, slice))"
        )
        _conn.commit()


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["attack_plan"] = json.loads(job["attack_plan"]) if job["attack_plan"] else None
    return job


def create_job(hash_22000: str, ssid: str | None, bssid: str | None,
               attack_plan: dict | None, pcap: str | None = None,
               max_runtime: int | None = None) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, hash_22000, ssid, bssid, attack_plan, status,"
            " pcap, max_runtime, created_at, updated_at) VALUES (?,?,?,?,?, 'queued', ?, ?, ?, ?)",
            (job_id, hash_22000, ssid, bssid,
             json.dumps(attack_plan) if attack_plan else None, pcap, max_runtime, now, now),
        )
        _conn.commit()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 100) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def _requeue_stale(now: float) -> None:
    """Remet en file les jobs 'running' dont plus aucun worker ne donne signe (sous _lock)."""
    stale = _conn.execute(
        "SELECT id FROM jobs WHERE status='running' AND updated_at < ?",
        (now - STALE_RUNNING_SECONDS,),
    ).fetchall()
    for row in stale:
        _conn.execute("DELETE FROM job_slices WHERE job_id=?", (row["id"],))
    _conn.execute(
        "UPDATE jobs SET status='queued', worker_id=NULL, started_at=NULL,"
        " updated_at=? WHERE status='running' AND updated_at < ?",
        (now, now - STALE_RUNNING_SECONDS),
    )


def _drop_stale_slices(now: float) -> None:
    """Libère une part dont le pod ne donne plus signe, sans toucher aux autres."""
    _conn.execute(
        "DELETE FROM job_slices WHERE state='running' AND updated_at < ?",
        (now - STALE_RUNNING_SECONDS,),
    )


def claim_next_job(worker_id: str) -> dict | None:
    """Prend le plus ancien job 'queued' et le passe 'running'. Atomique via _lock."""
    now = time.time()
    with _lock:
        _requeue_stale(now)
        row = _conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            _conn.commit()
            return None
        _conn.execute(
            "UPDATE jobs SET status='running', worker_id=?, started_at=?, updated_at=?"
            " WHERE id=?",
            (worker_id, now, now, row["id"]),
        )
        _conn.commit()
        row = _conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
    return _row_to_job(row)


def claim_slice(worker_id: str, n: int) -> dict | None:
    """Donne à un pod la prochaine part libre (0..n-1) du plus ancien job actif.
    Le job passe 'running' à la première part. None si toutes les parts sont prises."""
    now = time.time()
    n = max(1, int(n))
    with _lock:
        _requeue_stale(now)
        _drop_stale_slices(now)
        rows = _conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
        ).fetchall()
        for row in rows:
            taken = {
                r["slice"] for r in _conn.execute(
                    "SELECT slice FROM job_slices WHERE job_id=? AND state='running'",
                    (row["id"],),
                )
            }
            free = [i for i in range(n) if i not in taken]
            if not free:
                continue
            sl = free[0]
            _conn.execute(
                "INSERT OR REPLACE INTO job_slices (job_id, slice, worker_id, state, updated_at)"
                " VALUES (?,?,?,'running',?)",
                (row["id"], sl, worker_id, now),
            )
            if row["status"] == "queued":
                _conn.execute(
                    "UPDATE jobs SET status='running', worker_id=?, started_at=?, updated_at=?"
                    " WHERE id=?",
                    (worker_id, now, now, row["id"]),
                )
            else:
                _conn.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, row["id"]))
            _conn.commit()
            job = _row_to_job(_conn.execute(
                "SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
            job["slice"] = sl
            job["slice_count"] = n
            return job
        _conn.commit()
    return None


def touch_slice(job_id: str, slice_index: int | None) -> None:
    if slice_index is None:
        return
    now = time.time()
    with _lock:
        _conn.execute(
            "UPDATE job_slices SET updated_at=? WHERE job_id=? AND slice=? AND state='running'",
            (now, job_id, slice_index),
        )
        _conn.commit()


def pod_target(n: int) -> int:
    """Combien de pods garder pour le plus ancien job actif. 0 s'il n'y a rien à faire.
    Une part déjà terminée ne justifie plus une machine."""
    now = time.time()
    n = max(1, int(n))
    with _lock:
        _drop_stale_slices(now)
        row = _conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            _conn.commit()
            return 0
        done = _conn.execute(
            "SELECT COUNT(*) AS c FROM job_slices WHERE job_id=? AND state!='running'",
            (row["id"],),
        ).fetchone()["c"]
        _conn.commit()
    return max(0, n - int(done))


def finish_slice(job_id: str, slice_index: int, status: str,
                 password: str | None = None, error: str | None = None) -> bool:
    """Clôt une part. Un 'found' gagne et annule les autres. Un 'not_found' de part
    ne clôt le job que quand plus aucune part ne tourne."""
    assert status in ("found", "not_found", "error", "stopped")
    now = time.time()
    with _lock:
        job = _conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            return False
        if job["status"] == "found":
            _conn.execute(
                "UPDATE job_slices SET state='done', updated_at=? WHERE job_id=? AND slice=?",
                (now, job_id, slice_index),
            )
            _conn.commit()
            return True
        if status == "found":
            _conn.execute(
                "UPDATE jobs SET status='found', password=?, error=NULL, progress=100,"
                " cancel=1, updated_at=? WHERE id=?",
                (password, now, job_id),
            )
            _conn.execute(
                "UPDATE job_slices SET state='done', updated_at=? WHERE job_id=?",
                (now, job_id),
            )
            _conn.commit()
            return True
        _conn.execute(
            "UPDATE job_slices SET state=?, updated_at=? WHERE job_id=? AND slice=?",
            ("error" if status == "error" else "done", now, job_id, slice_index),
        )
        running = _conn.execute(
            "SELECT COUNT(*) AS c FROM job_slices WHERE job_id=? AND state='running'",
            (job_id,),
        ).fetchone()["c"]
        if running == 0 and job["status"] == "running":
            done = _conn.execute(
                "SELECT COUNT(*) AS c FROM job_slices WHERE job_id=? AND state='done'",
                (job_id,),
            ).fetchone()["c"]
            if status == "stopped":
                final, err = "stopped", None
            else:
                final, err = ("not_found", None) if done else ("error", error)
            _conn.execute(
                "UPDATE jobs SET status=?, error=?, progress=100, updated_at=?"
                " WHERE id=? AND status='running'",
                (final, err, now, job_id),
            )
        else:
            _conn.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, job_id))
        _conn.commit()
    return True


def update_progress(job_id: str, progress: float, tried: int,
                    phase: str | None = None) -> bool:
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "UPDATE jobs SET progress=?, tried=?, phase=COALESCE(?, phase), updated_at=?"
            " WHERE id=? AND status='running'",
            (progress, tried, phase, now, job_id),
        )
        _conn.commit()
        return cur.rowcount > 0


def finish_job(job_id: str, status: str, password: str | None = None,
               error: str | None = None) -> bool:
    assert status in ("found", "not_found", "error", "stopped")
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "UPDATE jobs SET status=?, password=?, error=?, progress=100, updated_at=?"
            " WHERE id=?",
            (status, password, error, now, job_id),
        )
        _conn.commit()
        return cur.rowcount > 0


def request_cancel(job_id: str) -> str | None:
    """Demande l'arrêt d'un job. queued -> 'stopped' direct ; running -> flag cancel
    (le worker interrompt hashcat et poste 'stopped'). Retourne l'action, ou None si absent."""
    now = time.time()
    with _lock:
        row = _conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        st = row["status"]
        if st == "queued":
            _conn.execute("UPDATE jobs SET status='stopped', progress=100, updated_at=? WHERE id=?",
                          (now, job_id))
            _conn.commit()
            return "stopped"
        if st == "running":
            _conn.execute("UPDATE jobs SET cancel=1, updated_at=? WHERE id=?", (now, job_id))
            _conn.commit()
            return "canceling"
        return "noop"


def is_canceled(job_id: str) -> bool:
    with _lock:
        row = _conn.execute("SELECT cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel"])


def delete_job(job_id: str) -> dict | None:
    """Supprime le job et retourne sa ligne (pour nettoyer les fichiers associés)."""
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        _conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        _conn.commit()
    return _row_to_job(row)


def count_pcap_refs(pcap: str) -> int:
    with _lock:
        row = _conn.execute("SELECT COUNT(*) FROM jobs WHERE pcap=?", (pcap,)).fetchone()
    return int(row[0] if row else 0)


def requeue_job(job_id: str, max_runtime: int | None = None) -> bool:
    """Relance (bouton Play) un job terminé : le repasse en 'queued' et réinitialise l'état
    d'exécution, en gardant hash/ssid/pcap. `max_runtime` non nul écrase le budget.
    Sans effet sur un job déjà queued/running. Retourne True si relancé."""
    now = time.time()
    with _lock:
        row = _conn.execute("SELECT status, max_runtime FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["status"] in ("queued", "running"):
            return False
        budget = max_runtime if max_runtime else row["max_runtime"]
        _conn.execute(
            "UPDATE jobs SET status='queued', worker_id=NULL, started_at=NULL, cancel=0,"
            " password=NULL, error=NULL, progress=0, tried=0, phase=NULL,"
            " max_runtime=?, updated_at=? WHERE id=?",
            (budget, now, job_id),
        )
        _conn.commit()
    return True
