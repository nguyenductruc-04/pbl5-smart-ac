"""
PBL5 Gateway - Milestone 1
- Subscribe telemetry / status / command_result cua tat ca cac phong
- Kiem tra lai du lieu, luu vao SQLite
Chay:  python gateway.py
"""
import json
import logging
import sqlite3
import time

import paho.mqtt.client as mqtt

import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    room      TEXT    NOT NULL,
    ts        REAL    NOT NULL,          -- thoi diem Gateway nhan (unix time)
    temp      REAL,
    hum       REAL,
    presence  INTEGER,                   -- NULL khi chua co cam bien
    simulated INTEGER NOT NULL DEFAULT 0,
    rssi      INTEGER,
    seq       INTEGER,
    raw       TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_room_ts ON telemetry(room, ts);

CREATE TABLE IF NOT EXISTS node_status (
    room   TEXT PRIMARY KEY,
    status TEXT NOT NULL,                -- online / offline
    ts     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    cmd_id   TEXT PRIMARY KEY,
    room     TEXT NOT NULL,
    ts_sent  REAL,
    source   TEXT,
    payload  TEXT,
    ts_result REAL,
    ok       INTEGER,
    result   TEXT
);

CREATE TABLE IF NOT EXISTS rejected (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    room   TEXT,
    ts     REAL,
    reason TEXT,
    raw    TEXT
);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def validate_telemetry(data: dict):
    """Tra ve (True, None) neu hop le, nguoc lai (False, ly_do)."""
    t, h = data.get("temp"), data.get("hum")
    if not isinstance(t, (int, float)) or not isinstance(h, (int, float)):
        return False, "thieu temp/hum"
    if not -10 <= t <= 60:
        return False, f"temp ngoai mien: {t}"
    if not 0 <= h <= 100:
        return False, f"hum ngoai mien: {h}"
    return True, None


class Gateway:
    def __init__(self):
        self.db = open_db(settings.DB_PATH)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pbl5-gateway")
        self.client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    # ---------------------------------------------------------------
    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Ket noi broker that bai: %s", reason_code)
            return
        log.info("Da ket noi broker %s:%s", settings.MQTT_HOST, settings.MQTT_PORT)
        client.subscribe([
            ("home/+/telemetry", 0),
            ("home/+/status", 1),
            ("home/+/command_result", 1),
        ])

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("Mat ket noi broker (%s), dang thu lai...", reason_code)

    # ---------------------------------------------------------------
    def on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[0] != "home":
            return
        _, room, kind = parts
        now = time.time()
        text = msg.payload.decode("utf-8", errors="replace")
        try:
            if kind == "telemetry":
                self.handle_telemetry(room, now, text)
            elif kind == "status":
                self.handle_status(room, now, text)
            elif kind == "command_result":
                self.handle_result(room, now, text)
        except Exception:
            log.exception("Loi xu ly ban tin %s", msg.topic)

    def handle_telemetry(self, room, now, text):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._reject(room, now, "json loi", text)
            return
        ok, reason = validate_telemetry(data)
        if not ok:
            self._reject(room, now, reason, text)
            return
        presence = data.get("presence")
        self.db.execute(
            "INSERT INTO telemetry(room, ts, temp, hum, presence, simulated, rssi, seq, raw)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (room, now, data["temp"], data["hum"],
             None if presence is None else int(bool(presence)),
             int(bool(data.get("sim"))), data.get("rssi"), data.get("seq"), text),
        )
        self.db.commit()
        log.info("[%s] temp=%.2f hum=%.1f%s", room, data["temp"], data["hum"],
                 " (gia lap)" if data.get("sim") else "")

    def handle_status(self, room, now, text):
        status = text.strip()
        self.db.execute(
            "INSERT INTO node_status(room, status, ts) VALUES (?,?,?)"
            " ON CONFLICT(room) DO UPDATE SET status=excluded.status, ts=excluded.ts",
            (room, status, now),
        )
        self.db.commit()
        log.info("[%s] node %s", room, status.upper())

    def handle_result(self, room, now, text):
        data = json.loads(text)
        cmd_id = data.get("cmd_id")
        self.db.execute(
            "INSERT INTO commands(cmd_id, room, ts_result, ok, result) VALUES (?,?,?,?,?)"
            " ON CONFLICT(cmd_id) DO UPDATE SET ts_result=excluded.ts_result,"
            " ok=excluded.ok, result=excluded.result",
            (cmd_id or f"unknown-{now}", room, now, int(bool(data.get("ok"))), text),
        )
        self.db.commit()
        log.info("[%s] ket qua lenh %s: %s", room, cmd_id, "OK" if data.get("ok") else "LOI")

    def _reject(self, room, now, reason, raw):
        self.db.execute("INSERT INTO rejected(room, ts, reason, raw) VALUES (?,?,?,?)",
                        (room, now, reason, raw))
        self.db.commit()
        log.warning("[%s] loai bo telemetry: %s", room, reason)

    # ---------------------------------------------------------------
    def run(self):
        log.info("Database: %s", settings.DB_PATH)
        self.client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
        self.client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    try:
        Gateway().run()
    except KeyboardInterrupt:
        log.info("Dung gateway")
