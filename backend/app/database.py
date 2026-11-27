from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import STORAGE_ROOT


DATABASE_PATH = STORAGE_ROOT / "timetable_analyzer.sqlite3"
MIGRATIONS_PATH = Path(__file__).resolve().parents[1] / "migrations"
_initialized = False


def initialize_database() -> None:
    """Apply each numbered SQL migration once for the local application store."""
    global _initialized
    if _initialized:
        return
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH, timeout=30) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for migration in sorted(MIGRATIONS_PATH.glob("*.sql")):
            if migration.name in applied:
                continue
            sql = migration.read_text(encoding="utf-8")
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT INTO schema_migrations(version) VALUES ({migration.name!r});\nCOMMIT;"
            )
    _initialized = True


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    initialize_database()
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
