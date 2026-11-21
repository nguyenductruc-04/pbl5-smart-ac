"""Doc phieu cam nhan tu database cua gateway (pure Python, dung chung cho danh gia va mo phong)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from comfort import VOTE_TO_CLASS, Vote  # noqa: E402

META_SQL = "CREATE TABLE IF NOT EXISTS ml_meta (key TEXT PRIMARY KEY, value TEXT)"


def load_votes(db_path: str, room: str) -> list[Vote]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT ts, vote, temp, hum FROM comfort_votes WHERE room=? AND temp IS NOT NULL"
            " AND hum IS NOT NULL ORDER BY ts", (room,)).fetchall()
    finally:
        conn.close()
    return [Vote(ts, VOTE_TO_CLASS[v], t, h) for ts, v, t, h in rows]


def synthetic_info(db_path: str) -> dict | None:
    """Thong tin mo phong neu database nay do ml/simulate_votes.py tao ra."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ml_meta'").fetchone():
            return None
        return dict(conn.execute("SELECT key, value FROM ml_meta").fetchall()) or None
    finally:
        conn.close()
