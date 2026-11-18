"""
Luu va doc trang thai phuc vu Safety Layer va REST API (SQLite).

- `ac_state`: trang thai DU KIEN cua dieu hoa moi phong + cac moc thoi gian cho Safety Layer.
  Chi mot noi ghi: tien trinh gateway (khi node bao lenh thanh cong, hoac khi nghe duoc remote).
  Luu trong database nen khoi dong lai Pi khong lam mat dong ho bao ve may nen.
- `decisions`: nhat ky MOI quyet dinh cua Safety Layer (cho phep / tu choi / bo qua, kem ly do).
"""
from __future__ import annotations

import json
import sqlite3

from safety import AcState, Policy, RoomView

SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_state (
    room        TEXT PRIMARY KEY,
    power       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    temp        INTEGER NOT NULL,
    fan         TEXT NOT NULL,
    ts          REAL NOT NULL,             -- lan thay doi gan nhat
    source      TEXT NOT NULL,             -- nguon cua lan thay doi do
    uncertain   INTEGER NOT NULL DEFAULT 0,
    last_on_ts  REAL,
    last_off_ts REAL,
    hold_until  REAL,
    hold_source TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    room      TEXT NOT NULL,
    source    TEXT NOT NULL,
    cmd_id    TEXT,
    verdict   TEXT NOT NULL,               -- allow / reject / skip
    code      TEXT NOT NULL,
    message   TEXT,
    requested TEXT                         -- trang thai dich (JSON)
);
CREATE INDEX IF NOT EXISTS idx_decisions_room_ts ON decisions(room, ts);
"""

AUTO_SOURCES_SQL = "('rule','ai')"


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ------------------------------------------------------------------ ghi
def apply_state_change(conn: sqlite3.Connection, room: str, ts: float, source: str,
                       state: AcState, policy: Policy) -> None:
    """Ghi nhan dieu hoa da chuyen sang `state` (lenh thanh cong hoac nghe duoc remote)."""
    row = conn.execute("SELECT power, last_on_ts, last_off_ts, hold_until, hold_source"
                       " FROM ac_state WHERE room=?", (room,)).fetchone()
    prev_power, last_on, last_off, hold_until, hold_source = row or (None, None, None, None, None)

    if state.power == "on" and prev_power != "on":
        last_on = ts
    if state.power == "off" and prev_power != "off":
        # Chua biet trang thai truoc do -> coi nhu vua tat (than trong cho may nen)
        last_off = ts

    hold = policy.hold_for(source)
    if hold > 0:
        hold_until, hold_source = ts + hold, source

    conn.execute(
        "INSERT INTO ac_state(room, power, mode, temp, fan, ts, source, uncertain,"
        " last_on_ts, last_off_ts, hold_until, hold_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(room) DO UPDATE SET power=excluded.power, mode=excluded.mode,"
        " temp=excluded.temp, fan=excluded.fan, ts=excluded.ts, source=excluded.source,"
        " uncertain=excluded.uncertain, last_on_ts=excluded.last_on_ts,"
        " last_off_ts=excluded.last_off_ts, hold_until=excluded.hold_until,"
        " hold_source=excluded.hold_source",
        # Lenh cua nguoi dung dong bo lai trang thai; lenh tu dong chi chay khi da chac chan
        (room, state.power, state.mode, state.temp, state.fan, ts, source, 0,
         last_on, last_off, hold_until, hold_source),
    )
    conn.commit()


def mark_uncertain(conn: sqlite3.Connection, room: str | None = None) -> None:
    """Danh dau trang thai co the da lech (node offline, lenh het han, gateway vua khoi dong)."""
    if room is None:
        conn.execute("UPDATE ac_state SET uncertain=1")
    else:
        conn.execute("UPDATE ac_state SET uncertain=1 WHERE room=?", (room,))
    conn.commit()


def heal_clock(conn: sqlite3.Connection, now: float, policy: Policy) -> int:
    """Keo cac moc thoi gian "o tuong lai" ve hien tai. Tra ve so phong da sua.

    Pi khong co pin RTC: khoi dong lai khi mat Internet thi dong ho bi LUI. Neu khong sua, cac moc
    da luu nam o tuong lai va bao ve may nen / manual hold se khoa lenh trong nhieu gio.
    Sau khi sua, thoi gian cho toi da dung bang gia tri trong Policy.
    """
    max_hold = max(policy.hold_remote_s, policy.hold_app_s)
    cur = conn.execute(
        "UPDATE ac_state SET"
        " ts = MIN(ts, :now),"
        " last_on_ts = MIN(last_on_ts, :now),"
        " last_off_ts = MIN(last_off_ts, :now),"
        " hold_until = MIN(hold_until, :now + :max_hold)"
        " WHERE ts > :now OR last_on_ts > :now OR last_off_ts > :now"
        " OR hold_until > :now + :max_hold",
        {"now": now, "max_hold": max_hold})
    conn.commit()
    return cur.rowcount


def clear_hold(conn: sqlite3.Connection, room: str) -> None:
    conn.execute("UPDATE ac_state SET hold_until=NULL, hold_source=NULL WHERE room=?", (room,))
    conn.commit()


def log_decision(conn: sqlite3.Connection, ts: float, room: str, source: str, cmd_id: str | None,
                 verdict: str, code: str, message: str, requested: dict) -> None:
    conn.execute(
        "INSERT INTO decisions(ts, room, source, cmd_id, verdict, code, message, requested)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (ts, room, source, cmd_id, verdict, code, message, json.dumps(requested)),
    )
    conn.commit()


# ------------------------------------------------------------------ doc
def room_exists(conn: sqlite3.Connection, room: str) -> bool:
    return conn.execute("SELECT 1 FROM node_status WHERE room=?", (room,)).fetchone() is not None


def list_rooms(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT room, status, ts FROM node_status ORDER BY room").fetchall()
    return [{"room": r, "status": s, "since": ts} for r, s, ts in rows]


def node_status(conn: sqlite3.Connection, room: str) -> tuple[str, float] | None:
    return conn.execute("SELECT status, ts FROM node_status WHERE room=?", (room,)).fetchone()


def latest_telemetry(conn: sqlite3.Connection, room: str) -> dict | None:
    row = conn.execute(
        "SELECT ts, temp, hum, presence, simulated, rssi FROM telemetry"
        " WHERE room=? ORDER BY id DESC LIMIT 1", (room,)).fetchone()
    if row is None:
        return None
    ts, temp, hum, presence, simulated, rssi = row
    return {"ts": ts, "temp": temp, "hum": hum,
            "presence": None if presence is None else bool(presence),
            "simulated": bool(simulated), "rssi": rssi}


def ac_row(conn: sqlite3.Connection, room: str) -> dict | None:
    row = conn.execute(
        "SELECT power, mode, temp, fan, ts, source, uncertain, last_on_ts, last_off_ts,"
        " hold_until, hold_source FROM ac_state WHERE room=?", (room,)).fetchone()
    if row is None:
        return None
    keys = ("power", "mode", "temp", "fan", "ts", "source", "uncertain", "last_on_ts",
            "last_off_ts", "hold_until", "hold_source")
    out = dict(zip(keys, row, strict=True))
    out["uncertain"] = bool(out["uncertain"])
    return out


def load_room_view(conn: sqlite3.Connection, room: str) -> RoomView:
    """Gom moi thu Safety Layer can de danh gia mot lenh."""
    status = node_status(conn, room)
    ac = ac_row(conn, room)
    tel = latest_telemetry(conn, room)
    last_cmd = conn.execute("SELECT MAX(ts_sent) FROM commands WHERE room=?", (room,)).fetchone()[0]
    last_auto = conn.execute(
        f"SELECT MAX(ts_sent) FROM commands WHERE room=? AND source IN {AUTO_SOURCES_SQL}",
        (room,)).fetchone()[0]
    return RoomView(
        node_online=bool(status and status[0] == "online"),
        ac=AcState(ac["power"], ac["mode"], ac["temp"], ac["fan"]) if ac else None,
        uncertain=ac["uncertain"] if ac else True,
        last_on_ts=ac["last_on_ts"] if ac else None,
        last_off_ts=ac["last_off_ts"] if ac else None,
        last_cmd_ts=last_cmd,
        last_auto_ts=last_auto,
        hold_until=ac["hold_until"] if ac else None,
        telemetry_ts=tel["ts"] if tel else None,
        presence=tel["presence"] if tel else None,
    )


def _rows(conn: sqlite3.Connection, sql: str, params: tuple, keys: tuple[str, ...]) -> list[dict]:
    return [dict(zip(keys, r, strict=True)) for r in conn.execute(sql, params).fetchall()]


def telemetry_history(conn, room: str, limit: int, since: float | None, until: float | None) -> list[dict]:
    sql = "SELECT ts, temp, hum, presence, simulated, rssi FROM telemetry WHERE room=?"
    params: list = [room]
    if since is not None:
        sql += " AND ts>=?"
        params.append(since)
    if until is not None:
        sql += " AND ts<=?"
        params.append(until)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = _rows(conn, sql, tuple(params), ("ts", "temp", "hum", "presence", "simulated", "rssi"))
    for r in rows:
        r["presence"] = None if r["presence"] is None else bool(r["presence"])
        r["simulated"] = bool(r["simulated"])
    return rows


def command_history(conn, room: str, limit: int) -> list[dict]:
    rows = _rows(
        conn,
        "SELECT cmd_id, ts_sent, source, payload, ts_result, ok FROM commands WHERE room=?"
        " ORDER BY COALESCE(ts_sent, ts_result) DESC LIMIT ?", (room, limit),
        ("cmd_id", "ts_sent", "source", "payload", "ts_result", "ok"))
    for r in rows:
        r["requested"] = extract_state_fields(r.pop("payload"))
        r["ok"] = None if r["ok"] is None else bool(r["ok"])
        r["latency_ms"] = (round((r["ts_result"] - r["ts_sent"]) * 1000)
                           if r["ts_sent"] and r["ts_result"] else None)
    return rows


def decision_history(conn, room: str, limit: int) -> list[dict]:
    rows = _rows(
        conn,
        "SELECT ts, source, cmd_id, verdict, code, message, requested FROM decisions WHERE room=?"
        " ORDER BY id DESC LIMIT ?", (room, limit),
        ("ts", "source", "cmd_id", "verdict", "code", "message", "requested"))
    for r in rows:
        r["requested"] = json.loads(r["requested"]) if r["requested"] else None
    return rows


def ir_event_history(conn, room: str, limit: int) -> list[dict]:
    return _rows(
        conn,
        "SELECT ts, protocol, power, mode, temp, fan FROM ir_events WHERE room=?"
        " ORDER BY id DESC LIMIT ?", (room, limit),
        ("ts", "protocol", "power", "mode", "temp", "fan"))


def extract_state_fields(payload: str | None) -> dict | None:
    """Lay power/mode/temp/fan tu payload lenh da luu (JSON)."""
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {k: data.get(k) for k in ("power", "mode", "temp", "fan")}
