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
        _conn.commit()


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["attack_plan"] = json.loads(job["attack_plan"]) if job["attack_plan"] else None
    return job


def create_job(hash_22000: str, ssid: str | None, bssid: str | None,
               attack_plan: dict | None) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, hash_22000, ssid, bssid, attack_plan, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?, 'queued', ?, ?)",
            (job_id, hash_22000, ssid, bssid,
             json.dumps(attack_plan) if attack_plan else None, now, now),
        )
        _conn.commit()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def _requeue_stale(now: float) -> None:
    """Remet en file les jobs 'running' dont le worker s'est tu (appelé sous _lock)."""
    _conn.execute(
        "UPDATE jobs SET status='queued', worker_id=NULL, started_at=NULL,"
        " updated_at=? WHERE status='running' AND updated_at < ?",
        (now, now - STALE_RUNNING_SECONDS),
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


def update_progress(job_id: str, progress: float, tried: int) -> bool:
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "UPDATE jobs SET progress=?, tried=?, updated_at=?"
            " WHERE id=? AND status='running'",
            (progress, tried, now, job_id),
        )
        _conn.commit()
        return cur.rowcount > 0


def finish_job(job_id: str, status: str, password: str | None = None,
               error: str | None = None) -> bool:
    assert status in ("found", "not_found", "error")
    now = time.time()
    with _lock:
        cur = _conn.execute(
            "UPDATE jobs SET status=?, password=?, error=?, progress=100, updated_at=?"
            " WHERE id=?",
            (status, password, error, now, job_id),
        )
        _conn.commit()
        return cur.rowcount > 0
