"""Giao thuc IR cua dieu hoa: luu theo phong, goi y theo hang (v0.11.0, ADR 0009).

Node la noi quyet dinh cuoi cung: no kiem tra ten giao thuc bang IRac::isProtocolSupported()
cua IRremoteESP8266 2.9.0. Danh sach o day chi de goi y tren giao dien, khong phai danh sach day du.
"""
from __future__ import annotations

import json
import re
import sqlite3

NAME_RE = re.compile(r"^[A-Z0-9_]{2,32}$")

# Hang pho bien o Viet Nam -> cac giao thuc IRremoteESP8266 nen thu, theo thu tu.
# Nguon: README "Supported Protocols" cua IRremoteESP8266. Hang noi dia (Casper, Nagakawa, Funiki...)
# thuong mua lai dong may cua hang khac nen khong biet truoc: hay dung "Nhan dien remote".
BRANDS: dict[str, list[str]] = {
    "Daikin": ["DAIKIN", "DAIKIN2", "DAIKIN216", "DAIKIN160", "DAIKIN176", "DAIKIN128", "DAIKIN152",
               "DAIKIN64", "DAIKIN200", "DAIKIN312"],
    "Panasonic": ["PANASONIC_AC", "PANASONIC_AC32"],
    "LG": ["LG", "LG2"],
    "Samsung": ["SAMSUNG_AC"],
    "Mitsubishi Electric": ["MITSUBISHI_AC", "MITSUBISHI136", "MITSUBISHI112"],
    "Mitsubishi Heavy": ["MITSUBISHI_HEAVY_88", "MITSUBISHI_HEAVY_152"],
    "Toshiba": ["TOSHIBA_AC"],
    "Sharp": ["SHARP_AC"],
    "Gree": ["GREE"],
    "Midea / Comfee": ["MIDEA", "COOLIX"],
    "Hitachi": ["HITACHI_AC", "HITACHI_AC1", "HITACHI_AC264", "HITACHI_AC344", "HITACHI_AC424"],
    "Fujitsu": ["FUJITSU_AC"],
    "Haier / Aqua": ["HAIER_AC", "HAIER_AC_YRW02", "HAIER_AC176", "HAIER_AC160"],
    "Electrolux / Electra": ["ELECTRA_AC"],
    "Carrier": ["CARRIER_AC64", "CARRIER_AC128"],
    "TCL": ["TCL112AC", "TCL96AC"],
    "Kelon / Hisense": ["KELON", "KELON168"],
    "Whirlpool": ["WHIRLPOOL_AC"],
    "Sanyo": ["SANYO_AC", "SANYO_AC88"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS room_ir (
    room         TEXT PRIMARY KEY,
    protocol     TEXT NOT NULL,
    model        INTEGER NOT NULL DEFAULT -1,
    reported_ts  REAL,             -- node bao gan nhat (telemetry)
    changed_ts   REAL,             -- lan doi giao thuc gan nhat
    confirmed    INTEGER NOT NULL DEFAULT 0,   -- nguoi dung xac nhan dieu hoa phan ung
    confirmed_ts REAL,
    confirmed_by TEXT
);
"""


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def get(conn: sqlite3.Connection, room: str) -> dict | None:
    row = conn.execute(
        "SELECT protocol, model, reported_ts, confirmed, confirmed_ts, confirmed_by FROM room_ir WHERE room=?",
        (room,)).fetchone()
    if row is None:
        return None
    keys = ("protocol", "model", "reported_ts", "confirmed", "confirmed_ts", "confirmed_by")
    out = dict(zip(keys, row, strict=True))
    out["confirmed"] = bool(out["confirmed"])
    return out


STALE_REPORT_S = 15   # telemetry gui truoc luc doi giao thuc co the toi sau ket qua doi


def report(conn: sqlite3.Connection, room: str, protocol: str, model: int, ts: float,
           from_telemetry: bool = True) -> bool:
    """Node bao giao thuc dang dung. Doi giao thuc thi bo xac nhan cu. Tra ve True neu giao thuc doi."""
    cur = get(conn, room)
    changed = cur is None or cur["protocol"] != protocol or cur["model"] != model
    if changed and cur is not None and from_telemetry:
        last = conn.execute("SELECT changed_ts FROM room_ir WHERE room=?", (room,)).fetchone()[0]
        if last is not None and 0 <= ts - last < STALE_REPORT_S:
            return False   # ban telemetry cu (truoc khi doi), bo qua
    if cur is None:
        conn.execute("INSERT INTO room_ir(room, protocol, model, reported_ts, changed_ts) VALUES (?,?,?,?,?)",
                     (room, protocol, model, ts, None if from_telemetry else ts))
    elif changed:
        conn.execute("UPDATE room_ir SET protocol=?, model=?, reported_ts=?, changed_ts=?, confirmed=0,"
                     " confirmed_ts=NULL, confirmed_by=NULL WHERE room=?", (protocol, model, ts, ts, room))
    else:
        conn.execute("UPDATE room_ir SET reported_ts=? WHERE room=?", (ts, room))
    conn.commit()
    return changed


def confirm(conn: sqlite3.Connection, room: str, works: bool, by: str, ts: float) -> None:
    conn.execute("UPDATE room_ir SET confirmed=?, confirmed_ts=?, confirmed_by=? WHERE room=?",
                 (int(works), ts if works else None, by if works else None, room))
    conn.commit()


def expected_protocol(conn: sqlite3.Connection, room: str, fallback: str = "") -> str:
    """Giao thuc ma remote cua phong nay phai co thi moi dong bo trang thai."""
    cur = get(conn, room)
    return cur["protocol"] if cur else fallback


def detections(conn: sqlite3.Connection, room: str, since: float, limit: int = 20) -> list[dict]:
    """Tin hieu node nghe duoc tu luc bat nhan dien, moi nhat truoc."""
    rows = conn.execute(
        "SELECT ts, protocol, power, mode, temp, fan, raw FROM ir_events WHERE room=? AND ts>=?"
        " ORDER BY id DESC LIMIT ?", (room, since, limit)).fetchall()
    out = []
    for ts, protocol, power, mode, temp, fan, raw in rows:
        try:
            extra = json.loads(raw or "{}")
        except ValueError:
            extra = {}
        out.append({"ts": ts, "protocol": protocol, "ac": extra.get("ac", True), "model": extra.get("model"),
                    "bits": extra.get("bits"), "power": power, "mode": mode, "temp": temp, "fan": fan})
    return out


def candidates(found: list[dict]) -> list[dict]:
    """Gom cac lan bam remote theo giao thuc: giao thuc dieu hoa giai ma duoc len truoc."""
    groups: dict[str, dict] = {}
    for d in found:
        g = groups.setdefault(d["protocol"], {"protocol": d["protocol"], "ac": d["ac"], "count": 0,
                                               "model": d.get("model"), "last": d})
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: (not g["ac"], -g["count"]))
