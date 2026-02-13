from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILENAME = "astra.db"


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def get_db_path(base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / DB_FILENAME


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {row["name"] for row in rows}


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    _ensure_migrations_table(conn)
    applied = _applied_migrations(conn)

    migration_files = sorted(p for p in migrations_dir.glob("*.sql"))
    for path in migration_files:
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            (path.name, now_iso()),
        )
        conn.commit()


def ensure_db(base_dir: Path, migrations_dir: Path) -> sqlite3.Connection:
    db_path = get_db_path(base_dir)
    conn = connect(db_path)
    apply_migrations(conn, migrations_dir)
    return conn
