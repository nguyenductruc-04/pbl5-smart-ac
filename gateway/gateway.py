"""
PBL5 Gateway
- Subscribe telemetry / status / command_result / ir_event cua tat ca cac phong
- Kiem tra lai du lieu, luu vao SQLite
- Theo doi trang thai DU KIEN cua dieu hoa (bang ac_state) cho Safety Layer

Chay day du (co REST API):  python api.py
Chi thu thap du lieu:       python gateway.py   (KHONG chay cung luc voi api.py: trung client_id)
"""
import json
import logging
import sqlite3
import threading
import time

import paho.mqtt.client as mqtt

import irproto
import safety
import settings
import store

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

CREATE TABLE IF NOT EXISTS ir_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    room     TEXT NOT NULL,
    ts       REAL NOT NULL,
    protocol TEXT,
    power    TEXT,
    mode     TEXT,
    temp     INTEGER,
    fan      TEXT,
    raw      TEXT
);
CREATE INDEX IF NOT EXISTS idx_ir_events_room_ts ON ir_events(room, ts);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
    # WAL: tien trinh/luong khac doc duoc trong khi gateway dang ghi
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    store.init(conn)
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


def state_from_fields(data: dict) -> safety.AcState | None:
    """Tao AcState tu dict power/mode/temp/fan. Tra ve None neu thieu hoac sai gia tri."""
    power, mode, temp, fan = data.get("power"), data.get("mode"), data.get("temp"), data.get("fan")
    if power not in ("on", "off") or mode not in safety.MODES or fan not in safety.FANS:
        return None
    if isinstance(temp, bool) or not isinstance(temp, int):
        return None
    return safety.AcState(power, mode, temp, fan)


class Gateway:
    def __init__(self, policy: safety.Policy | None = None):
        self.policy = policy or settings.POLICY
        self.db = open_db(settings.DB_PATH)
        # Gateway vua khoi dong: co the da bo lo lan bam remote -> trang thai chua chac chan
        store.mark_uncertain(self.db)
        if store.heal_clock(self.db, time.time(), self.policy):
            log.warning("Dong ho he thong da bi lui: da chinh lai cac moc thoi gian cua Safety Layer")
        self._waiters: dict[str, tuple[threading.Event, dict]] = {}
        self._waiters_lock = threading.Lock()
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
            ("home/+/ir_event", 1),
            ("home/+/config_result", 1),
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
            elif kind == "ir_event":
                self.handle_ir_event(room, now, text)
            elif kind == "config_result":
                self.handle_config_result(room, now, text)
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
        proto = data.get("ir_protocol")
        if isinstance(proto, str) and irproto.valid_name(proto):
            model = data.get("ir_model")
            irproto.report(self.db, room, proto, model if isinstance(model, int) else -1, now)
        presence_txt = {None: "?", 0: "khong", 1: "CO"}[None if presence is None else int(bool(presence))]
        log.info("[%s] temp=%.2f hum=%.1f nguoi=%s%s", room, data["temp"], data["hum"], presence_txt,
                 " (gia lap)" if data.get("sim") else "")

    def handle_status(self, room, now, text):
        status = text.strip()
        self.db.execute(
            "INSERT INTO node_status(room, status, ts) VALUES (?,?,?)"
            " ON CONFLICT(room) DO UPDATE SET status=excluded.status, ts=excluded.ts",
            (room, status, now),
        )
        self.db.commit()
        if status != "online":
            # Trong luc node offline, nguoi dung co the bam remote ma Pi khong biet
            store.mark_uncertain(self.db, room)
        log.info("[%s] node %s", room, status.upper())

    def handle_result(self, room, now, text):
        data = json.loads(text)
        cmd_id = data.get("cmd_id")
        before = self.db.execute(
            "SELECT source, payload, ts_result FROM commands WHERE cmd_id=? AND room=?",
            (cmd_id, room)).fetchone()
        self.db.execute(
            "INSERT INTO commands(cmd_id, room, ts_result, ok, result) VALUES (?,?,?,?,?)"
            " ON CONFLICT(cmd_id) DO UPDATE SET ts_result=excluded.ts_result,"
            " ok=excluded.ok, result=excluded.result",
            (cmd_id or f"unknown-{now}", room, now, int(bool(data.get("ok"))), text),
        )
        self.db.commit()
        # Lenh thanh cong lan dau -> cap nhat trang thai du kien cua dieu hoa
        if data.get("ok") and before and before[2] is None:
            state = state_from_fields(store.extract_state_fields(before[1]) or {})
            if state is not None:
                store.apply_state_change(self.db, room, now, before[0] or "cli", state, self.policy)
        log.info("[%s] ket qua lenh %s: %s", room, cmd_id, "OK" if data.get("ok") else "LOI")
        self._notify(cmd_id, data)

    def handle_ir_event(self, room, now, text):
        """Nguoi dung bam remote goc (node nghe len). Day la thay doi uu tien cao nhat."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._reject(room, now, "ir_event json loi", text)
            return
        temp = data.get("temp")
        if data.get("ac") is False:
            # Che do nhan dien: tin hieu khong phai remote dieu hoa (hoac giao thuc chua ho tro).
            # Chi ghi lai de giao dien hien "node co nghe thay", khong dung toi trang thai dieu hoa.
            self.db.execute("INSERT INTO ir_events(room, ts, protocol, raw) VALUES (?,?,?,?)",
                            (room, now, data.get("protocol"), text))
            self.db.commit()
            log.info("[%s] IR khong phai dieu hoa: %s (%s bit)", room, data.get("protocol"), data.get("bits"))
            return
        self.db.execute(
            "INSERT INTO ir_events(room, ts, protocol, power, mode, temp, fan, raw)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (room, now, data.get("protocol"), data.get("power"), data.get("mode"),
             temp if isinstance(temp, int) else None, data.get("fan"), text),
        )
        self.db.commit()
        # Nguoi dung bam remote: dong bo trang thai va chan lenh tu dong mot thoi gian
        expected = irproto.expected_protocol(self.db, room, settings.IR_PROTOCOL)
        if expected and data.get("protocol") != expected:
            log.info("[%s] remote giao thuc %s khac %s -> khong doi trang thai", room,
                     data.get("protocol"), expected)
        else:
            state = state_from_fields(data)
            if state is not None:
                store.apply_state_change(self.db, room, now, "remote", state, self.policy)
            else:
                store.mark_uncertain(self.db, room)
        log.info("[%s] REMOTE %s: power=%s mode=%s temp=%s fan=%s", room, data.get("protocol"),
                 data.get("power"), data.get("mode"), temp, data.get("fan"))

    def handle_config_result(self, room, now, text):
        """Node tra loi ban tin cau hinh (doi giao thuc IR; Wi-Fi do push_wifi.py tu theo doi)."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        ir = data.get("ir")
        if data.get("ok") and isinstance(ir, dict) and irproto.valid_name(ir.get("protocol", "")):
            model = ir.get("model")
            if irproto.report(self.db, room, ir["protocol"], model if isinstance(model, int) else -1, now,
                              from_telemetry=False):
                store.mark_uncertain(self.db, room)   # giao thuc moi: chua biet dieu hoa dang o trang thai nao
            log.warning("[%s] doi giao thuc IR -> %s (model %s)", room, ir["protocol"], ir.get("model"))
        if data.get("cfg_id"):
            self._notify(data["cfg_id"], data)

    def _reject(self, room, now, reason, raw):
        self.db.execute("INSERT INTO rejected(room, ts, reason, raw) VALUES (?,?,?,?)",
                        (room, now, reason, raw))
        self.db.commit()
        log.warning("[%s] loai bo telemetry: %s", room, reason)

    # --------------------------------------------------------------- cho ket qua lenh
    def expect_result(self, cmd_id: str) -> threading.Event:
        """Dang ky cho command_result cua `cmd_id`. Goi TRUOC khi publish lenh."""
        event = threading.Event()
        with self._waiters_lock:
            self._waiters[cmd_id] = (event, {})
        return event

    def take_result(self, cmd_id: str) -> dict | None:
        """Lay ket qua (None neu chua co) va huy dang ky."""
        with self._waiters_lock:
            _, box = self._waiters.pop(cmd_id, (None, {}))
        return box.get("data")

    def _notify(self, cmd_id, data: dict) -> None:
        with self._waiters_lock:
            waiter = self._waiters.get(cmd_id)
            if waiter:
                waiter[1]["data"] = data
                waiter[0].set()

    # --------------------------------------------------------------- gui lenh
    def is_connected(self) -> bool:
        return self.client.is_connected()

    def publish_command(self, room: str, payload: str) -> bool:
        """Gui lenh xuong node. Tra ve False neu dang mat broker.

        Khong publish khi mat ket noi: paho se giu lenh QoS 1 va gui bu khi noi lai (lenh den tre).
        """
        if not self.client.is_connected():
            return False
        self.client.publish(f"home/{room}/command", payload, qos=1)
        return True

    def publish_config(self, room: str, payload: dict) -> bool:
        """Ban tin cau hinh KHONG retained toi node (doi / nhan dien giao thuc IR)."""
        if not self.client.is_connected():
            return False
        self.client.publish(f"home/{room}/config", json.dumps(payload), qos=1)
        return True

    def publish_net_hint(self, room: str, net: str) -> bool:
        """Bao truoc cho node Pi sap doi mang (v0.9.0): net = "backup" (sap phat mang rieng) hoac
        "home" (sap ve Wi-Fi nha). KHONG retained: chi co y nghia ngay luc nay. ADR 0006."""
        if not self.client.is_connected():
            return False
        self.client.publish(f"home/{room}/config", json.dumps({"net": net}), qos=1)
        return True

    # ---------------------------------------------------------------
    def connect(self):
        log.info("Database: %s", settings.DB_PATH)
        self.client.connect_async(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)

    def start(self):
        """Chay vong lap MQTT o luong nen (dung khi nhung vao REST API)."""
        self.connect()
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def run(self):
        self.connect()
        self.client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    try:
        Gateway().run()
    except KeyboardInterrupt:
        log.info("Dung gateway")
