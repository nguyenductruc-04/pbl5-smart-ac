"""
Dich vu goi y (M6): ghep mo hinh tien nghi ca nhan hoa voi tinh trang phong de dua ra goi y.

- `Advisor.suggest()` chi DOC database va tra ve goi y; khong gui lenh.
- Neu bat ADVISOR_AUTO, `run_auto_loop()` dinh ky ap dung goi y voi nguon "ai". Lenh van di qua
  CommandService -> Safety Layer nhu moi lenh khac: bi chan khi nguoi dung vua dieu chinh, khi trang thai
  khong chac chan, khi doi qua 1 do, khi lenh tu dong qua day...
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass

import comfort
import safety
import store
from comfort import ComfortModel, Personalization, Situation, Vote

log = logging.getLogger("advisor")

MIN_PERSONAL_VOTES = 10      # duoi muc nay giao dien noi ro "dang dung mo hinh chung"
CACHE_S = 600                # hoc lai toi da moi 10 phut (hoac ngay khi co phieu moi)


@dataclass
class _Cached:
    key: tuple
    at: float
    result: Personalization


class Advisor:
    def __init__(self, policy: safety.Policy, prior: ComfortModel | None = None, prior_info: dict | None = None):
        self.policy = policy
        if prior is None:
            prior, prior_info = comfort.load_prior()
        self.prior = prior
        self.prior_info = prior_info or {}
        self._cache: dict[str, _Cached] = {}
        self._lock = threading.Lock()

    def personalization(self, conn: sqlite3.Connection, room: str, now: float) -> Personalization:
        rows = store.vote_samples(conn, room)
        key = (len(rows), rows[-1][0] if rows else None)
        with self._lock:
            hit = self._cache.get(room)
            if hit and hit.key == key and now - hit.at < CACHE_S:
                return hit.result
        votes = [Vote(ts, comfort.VOTE_TO_CLASS[v], t, h) for ts, v, t, h in rows]
        result = comfort.personalize(self.prior, votes, now)
        with self._lock:
            self._cache[room] = _Cached(key, now, result)
        return result

    def situation(self, conn: sqlite3.Connection, room: str, now: float) -> Situation:
        status = store.node_status(conn, room)
        tel = store.latest_telemetry(conn, room)
        ac = store.ac_row(conn, room)
        fresh = tel is not None and now - tel["ts"] <= self.policy.telemetry_stale_s
        return Situation(
            node_online=bool(status and status[0] == "online"),
            telemetry_fresh=fresh,
            ta=tel["temp"] if tel else None,
            rh=tel["hum"] if tel else None,
            presence=tel["presence"] if tel else None,
            empty_for_s=store.empty_for_s(conn, room, now),
            ac_power=ac["power"] if ac else None,
            ac_mode=ac["mode"] if ac else None,
            ac_temp=ac["temp"] if ac else None,
            ac_fan=ac["fan"] if ac else None,
        )

    def suggest(self, conn: sqlite3.Connection, room: str, now: float) -> dict:
        pers = self.personalization(conn, room, now)
        s = self.situation(conn, room, now)
        p = self.policy
        advice = comfort.advise(pers.model, s, p.auto_temp_min, p.auto_temp_max)
        rh = s.rh if s.rh is not None else pers.model.h_ref
        lo, hi = pers.model.comfort_band(rh)
        out = {
            "action": advice.action,
            "reason": advice.reason,
            "target": advice.target,
            "room_temp": s.ta,
            "comfort": None,
            "neutral_temp": round(pers.model.neutral_temp(rh), 1),
            "comfort_band": [round(lo, 1), round(hi, 1)],
            "setpoint": pers.model.setpoint(rh, p.auto_temp_min, p.auto_temp_max),
            "model": {
                "votes": pers.n_votes,
                "personal": pers.n_votes >= MIN_PERSONAL_VOTES,
                "shift_c": round(pers.shift, 2),
                "shift_sd_c": round(pers.shift_sd, 2),
                "scale": round(pers.scale, 2),
                "prior": self.prior_info.get("dataset"),
            },
        }
        if s.ta is not None and s.rh is not None:
            pw, pc, pk = pers.model.proba(s.ta, s.rh)
            out["comfort"] = {"warmer": round(pw, 3), "comfortable": round(pc, 3), "cooler": round(pk, 3)}
        return out


def auto_step(advisor: Advisor, service, conn: sqlite3.Connection, now: float) -> list[tuple]:
    """Mot vong tu dong: voi moi phong, ap dung goi y neu Safety Layer cho phep. Tra ve [(phong, ket qua)]."""
    done = []
    for room in [r["room"] for r in store.list_rooms(conn)]:
        sug = advisor.suggest(conn, room, now)
        if sug["action"] == comfort.NONE or not sug["target"]:
            continue
        decision = service.preview(room, "ai", **sug["target"])
        if not decision.allowed:
            log.debug("[%s] bo qua goi y %s: %s", room, sug["action"], decision.code)
            continue
        out = service.submit(room, "ai", **sug["target"])
        log.info("[%s] tu dong %s %s -> %s", room, sug["action"], sug["target"], out.status)
        done.append((room, out))
    return done


def run_auto_loop(advisor: Advisor, service, connect, stop: threading.Event, interval_s: float,
                  clock=time.time) -> None:
    """Chay auto_step() dinh ky cho toi khi `stop` duoc bat."""
    log.info("Che do tu dong BAT: ap dung goi y moi %.0f s (van qua Safety Layer)", interval_s)
    while not stop.wait(interval_s):
        conn = connect()
        try:
            auto_step(advisor, service, conn, clock())
        except Exception:                                     # khong de loi lam chet vong lap
            log.exception("Loi trong vong lap tu dong")
        finally:
            conn.close()
