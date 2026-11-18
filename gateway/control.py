"""
Dich vu dieu khien: DUONG DUY NHAT de mot lenh di tu API xuong node.

    yeu cau -> ghep thanh trang thai dich day du -> Safety Layer -> ghi nhat ky quyet dinh
            -> publish MQTT -> cho command_result (co han) -> tra ket qua

Che do mat ket noi (xem ADR 0002):
- Node offline hoac mat broker: tu choi ngay, KHONG xep hang lenh.
- Het han cho ket qua: khong biet node da phat IR hay chua -> danh dau trang thai "khong chac chan".
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import safety
import settings
import store

log = logging.getLogger("control")

# Trang thai ket qua cua mot yeu cau
EXECUTED = "executed"            # node da phat IR
SKIPPED = "skipped"              # khong can gui (lenh tu dong trung trang thai hien tai)
REJECTED = "rejected"            # Safety Layer tu choi
UNAVAILABLE = "unavailable"      # dang mat ket noi toi broker MQTT
TIMEOUT = "timeout"              # node khong tra loi trong thoi han
NODE_ERROR = "node_error"        # node tra loi nhung khong thuc hien duoc


@dataclass(frozen=True)
class Outcome:
    status: str
    decision: safety.Decision
    target: safety.AcState
    cmd_id: str | None = None
    latency_ms: int | None = None
    node_error: str | None = None


class CommandService:
    def __init__(self, gateway, policy: safety.Policy | None = None,
                 clock: Callable[[], float] = time.time,
                 timeout_s: float | None = None,
                 connect: Callable[[], sqlite3.Connection] | None = None):
        self.gateway = gateway
        self.policy = policy or gateway.policy
        self.clock = clock
        self.timeout_s = settings.COMMAND_TIMEOUT_S if timeout_s is None else timeout_s
        self._connect = connect or (lambda: sqlite3.connect(settings.DB_PATH, timeout=5.0))
        # Moi phong mot khoa: hai lenh den cung luc duoc danh gia lan luot, khong lach duoc gioi han
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def _room_lock(self, room: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[room]

    def submit(self, room: str, source: str, *, power: str | None = None, mode: str | None = None,
               temp: int | None = None, fan: str | None = None) -> Outcome:
        with self._room_lock(room):
            conn = self._connect()
            try:
                return self._submit(conn, room, source, power, mode, temp, fan)
            finally:
                conn.close()

    def _submit(self, conn, room, source, power, mode, temp, fan) -> Outcome:
        now = self.clock()
        view = store.load_room_view(conn, room)
        target = safety.resolve_target(view.ac, self.policy, power=power, mode=mode, temp=temp, fan=fan)
        decision = safety.evaluate(source, target, view, now, self.policy)

        cmd_id = "c-" + uuid.uuid4().hex[:8] if decision.allowed else None
        store.log_decision(conn, now, room, source, cmd_id, decision.verdict, decision.code,
                           decision.message, target.as_dict())
        if decision.verdict == safety.SKIP:
            return Outcome(SKIPPED, decision, target)
        if not decision.allowed:
            log.info("[%s] TU CHOI lenh %s tu '%s': %s", room, target.as_dict(), source, decision.code)
            return Outcome(REJECTED, decision, target)

        payload = json.dumps({"cmd_id": cmd_id, **target.as_dict(), "source": source, "ts": int(now)})
        conn.execute("INSERT INTO commands(cmd_id, room, ts_sent, source, payload) VALUES (?,?,?,?,?)",
                     (cmd_id, room, now, source, payload))
        conn.commit()

        waiter = self.gateway.expect_result(cmd_id)
        t0 = time.perf_counter()
        if not self.gateway.publish_command(room, payload):
            self.gateway.take_result(cmd_id)
            conn.execute("UPDATE commands SET ok=0, result=? WHERE cmd_id=?",
                         (json.dumps({"error": "broker_unavailable"}), cmd_id))
            conn.commit()
            return Outcome(UNAVAILABLE, decision, target, cmd_id)

        waiter.wait(self.timeout_s)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        result = self.gateway.take_result(cmd_id)

        if result is None:
            # Co the node da phat IR nhung ket qua bi mat -> khong con chac trang thai dieu hoa
            store.mark_uncertain(conn, room)
            log.warning("[%s] lenh %s het han sau %.1f s", room, cmd_id, self.timeout_s)
            return Outcome(TIMEOUT, decision, target, cmd_id, latency_ms)
        if not result.get("ok"):
            return Outcome(NODE_ERROR, decision, target, cmd_id, latency_ms,
                           str(result.get("error") or "unknown"))
        return Outcome(EXECUTED, decision, target, cmd_id, latency_ms)
