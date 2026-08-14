import os
import sqlite3
import time

DB_PATH = os.environ.get("DB_PATH", "/data/control_plane.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS policies (
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            cap_per_min REAL,
            notify_enabled INTEGER NOT NULL DEFAULT 0,
            auto_block_enabled INTEGER NOT NULL DEFAULT 0,
            notify_target TEXT,
            blocked INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (service, environment)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            service TEXT,
            environment TEXT,
            action TEXT NOT NULL,
            detail TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_policy_row(service: str, environment: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO policies (service, environment) VALUES (?, ?)",
        (service, environment),
    )
    conn.commit()
    conn.close()


def upsert_policy(
    service: str,
    environment: str,
    cap_per_min: float | None,
    notify_enabled: bool,
    auto_block_enabled: bool,
    notify_target: str,
) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO policies (service, environment, cap_per_min, notify_enabled, auto_block_enabled, notify_target)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(service, environment) DO UPDATE SET
            cap_per_min=excluded.cap_per_min,
            notify_enabled=excluded.notify_enabled,
            auto_block_enabled=excluded.auto_block_enabled,
            notify_target=excluded.notify_target
        """,
        (service, environment, cap_per_min, int(notify_enabled), int(auto_block_enabled), notify_target),
    )
    conn.commit()
    conn.close()


def set_blocked(service: str, environment: str, blocked: bool) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE policies SET blocked=? WHERE service=? AND environment=?",
        (int(blocked), service, environment),
    )
    conn.commit()
    conn.close()


def all_policies() -> list[sqlite3.Row]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM policies ORDER BY service, environment").fetchall()
    conn.close()
    return rows


def blocked_pairs() -> list[tuple[str, str]]:
    conn = get_conn()
    rows = conn.execute("SELECT service, environment FROM policies WHERE blocked=1").fetchall()
    conn.close()
    return [(r["service"], r["environment"]) for r in rows]


def add_audit(service: str, environment: str, action: str, detail: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (ts, service, environment, action, detail) VALUES (?, ?, ?, ?, ?)",
        (time.time(), service, environment, action, detail),
    )
    conn.commit()
    conn.close()


def recent_audit(limit: int = 50) -> list[sqlite3.Row]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
