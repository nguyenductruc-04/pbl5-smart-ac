"""
REST API cua Gateway (FastAPI). Chay:  python api.py
Tai lieu tu sinh: http://<pi>:8000/docs      Mo ta: docs/API.md

Mot tien trinh chay ca hai viec: thu thap du lieu MQTT (lop Gateway) va phuc vu HTTP.
Moi lenh dieu khien deu di qua control.CommandService -> Safety Layer.
"""
import hmac
import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path as FsPath
from typing import Annotated, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

import advisor as advisor_mod
import control
import safety
import settings
import store
from gateway import Gateway

__version__ = "0.8.0"
log = logging.getLogger("api")

WEB_DIR = FsPath(__file__).resolve().parent / "web"
# Dashboard chi duoc tai tai nguyen tu chinh Pi: khong CDN (chay duoc khi mat Internet) va
# khong script noi tuyen (khoa API nam trong trinh duyet, nen phai chan chen ma la).
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
# Trang tai lieu tu sinh cua FastAPI can CDN va script noi tuyen -> khong ap CSP len chung
CSP_EXEMPT = ("/docs", "/redoc", "/openapi.json")

Room = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,32}$", description="Ma phong, vd. room01")]
Limit = Annotated[int, Query(ge=1, le=1000)]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after_s: int | None = None):
        self.status, self.code, self.message, self.retry_after_s = status, code, message, retry_after_s


class CommandIn(BaseModel):
    """Lenh dieu khien. Truong nao bo trong thi giu nguyen gia tri hien tai."""
    model_config = ConfigDict(extra="forbid")

    power: Literal["on", "off"] | None = None
    mode: Literal["cool", "dry", "fan", "auto", "heat"] | None = None
    temp: int | None = Field(default=None, ge=0, le=50, description="Do C")
    fan: Literal["auto", "low", "mid", "high"] | None = None
    source: Literal["app", "rule", "ai"] | None = Field(
        default=None, description="Chi dich vu tu dong moi can gui: 'rule' hoac 'ai'")

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.power is None and self.mode is None and self.temp is None and self.fan is None:
            raise ValueError("can it nhat mot trong cac truong: power, mode, temp, fan")
        return self


class ComfortIn(BaseModel):
    """Phieu cam nhan: nguoi dung muon phong mat hon, giu nhu hien tai, hay am hon."""
    model_config = ConfigDict(extra="forbid")

    vote: Literal["cooler", "comfortable", "warmer"]


VOTE_MIN_INTERVAL_S = 5      # chong bam dup
VOTE_UNDO_WINDOW_S = 120     # duoc hoan tac phieu trong bao lau

# HTTP status cho tung ma tu choi cua Safety Layer (mac dinh 409)
REJECT_STATUS = {
    safety.NODE_OFFLINE: 503,
    safety.RATE_LIMIT: 429,
    safety.TEMP_OUT_OF_RANGE: 422,
}


def create_app(gateway: Gateway | None = None, service: control.CommandService | None = None,
               *, api_key: str | None = None, automation_key: str | None = None,
               clock=time.time) -> FastAPI:
    api_key = settings.API_KEY if api_key is None else api_key
    automation_key = settings.API_KEY_AUTOMATION if automation_key is None else automation_key
    if len(api_key) < 16:
        raise SystemExit("Thieu API_KEY (>= 16 ky tu) trong gateway/.env. "
                         "Tao khoa: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    if automation_key and (len(automation_key) < 16 or automation_key == api_key):
        raise SystemExit("API_KEY_AUTOMATION phai >= 16 ky tu va KHAC API_KEY")

    own_gateway = gateway is None
    started = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if own_gateway:
            app.state.gateway = Gateway()
            app.state.gateway.start()
        else:
            app.state.gateway = gateway
        app.state.service = service or control.CommandService(app.state.gateway)
        app.state.advisor = advisor_mod.Advisor(app.state.gateway.policy)
        stop = threading.Event()
        if settings.ADVISOR_AUTO:
            threading.Thread(
                target=advisor_mod.run_auto_loop, daemon=True, name="advisor",
                args=(app.state.advisor, app.state.service,
                      lambda: sqlite3.connect(settings.DB_PATH, timeout=5.0), stop, settings.ADVISOR_INTERVAL_S),
            ).start()
        yield
        stop.set()
        if own_gateway:
            app.state.gateway.stop()

    app = FastAPI(title="PBL5 Smart AC Gateway", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith(CSP_EXEMPT):
            response.headers["Content-Security-Policy"] = CSP
        if not request.url.path.startswith("/api/"):
            # Trinh duyet luon hoi lai Pi (ETag) -> cap nhat dashboard xong la thay ngay
            response.headers.setdefault("Cache-Control", "no-cache")
        else:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        body = {"error": {"code": exc.code, "message": exc.message}}
        headers = {}
        if exc.retry_after_s is not None:
            body["error"]["retry_after_s"] = exc.retry_after_s
            headers["Retry-After"] = str(exc.retry_after_s)
        return JSONResponse(body, status_code=exc.status, headers=headers)

    # ------------------------------------------------------------ dependencies
    def get_db():
        # Moi request mot ket noi rieng. FastAPI co the mo va dong no o hai luong khac nhau
        # cua thread pool, nen phai tat kiem tra "cung luong" (van chi mot request dung no).
        conn = sqlite3.connect(settings.DB_PATH, timeout=5.0, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    Db = Annotated[sqlite3.Connection, Depends(get_db)]

    def get_role(x_api_key: Annotated[str | None, Header()] = None) -> str:
        """Tra ve 'app' hoac 'automation' theo khoa. So sanh thoi gian hang de tranh do khoa."""
        given = (x_api_key or "").encode()
        if hmac.compare_digest(given, api_key.encode()):
            return "app"
        if automation_key and hmac.compare_digest(given, automation_key.encode()):
            return "automation"
        raise ApiError(401, "UNAUTHORIZED", "Thieu hoac sai header X-API-Key")

    Role = Annotated[str, Depends(get_role)]

    def known_room(room: Room, db: Db, role: Role) -> str:
        if not store.room_exists(db, room):
            raise ApiError(404, "ROOM_NOT_FOUND", f"Chua tung thay node cua phong '{room}'")
        return room

    KnownRoom = Annotated[str, Depends(known_room)]

    def room_snapshot(db: sqlite3.Connection, room: str) -> dict:
        now = clock()
        policy = app.state.gateway.policy
        status = store.node_status(db, room)
        tel = store.latest_telemetry(db, room)
        ac = store.ac_row(db, room)
        if tel:
            tel["age_s"] = round(max(0.0, now - tel["ts"]))
        hold_left = compressor_wait = 0
        ac_out = None
        if ac:
            if ac["hold_until"] and ac["hold_until"] > now:
                hold_left = round(ac["hold_until"] - now)
            if ac["power"] == "off" and ac["last_off_ts"] is not None:
                compressor_wait = max(0, round(policy.min_off_s - max(0.0, now - ac["last_off_ts"])))
            ac_out = {k: ac[k] for k in ("power", "mode", "temp", "fan", "source", "uncertain")}
            ac_out["since"] = ac["ts"]
        return {
            "room": room,
            "node": {"status": status[0], "since": status[1]},
            "telemetry": tel,
            # Trang thai DU KIEN: IR la mot chieu, dieu hoa khong xac nhan lai
            "ac": ac_out,
            "safety": {
                "auto_hold_remaining_s": hold_left,
                "auto_hold_source": ac["hold_source"] if ac and hold_left else None,
                "compressor_ready_in_s": compressor_wait,
                # Dashboard chi nhac ve "tam dung tu dong" khi co dich vu tu dong duoc cau hinh
                "automation_enabled": bool(automation_key),
            },
        }

    # ------------------------------------------------------------ endpoints
    @app.get("/api/v1/health", tags=["he thong"])
    def health():
        """Khong can khoa. 503 khi gateway mat ket noi toi broker MQTT."""
        connected = app.state.gateway.is_connected()
        body = {"status": "ok" if connected else "degraded", "mqtt_connected": connected,
                "version": __version__, "uptime_s": round(time.monotonic() - started)}
        return JSONResponse(body, status_code=200 if connected else 503)

    @app.get("/api/v1/policy", tags=["he thong"])
    def get_policy(role: Role):
        """Cac nguong Safety Layer dang ap dung."""
        return vars(app.state.gateway.policy)

    @app.get("/api/v1/rooms", tags=["phong"])
    def rooms(db: Db, role: Role):
        return {"rooms": store.list_rooms(db)}

    @app.get("/api/v1/rooms/{room}", tags=["phong"])
    def room_state(room: KnownRoom, db: Db):
        """Trang thai hien tai: node, cam bien, dieu hoa (du kien), cac dong ho Safety Layer."""
        return room_snapshot(db, room)

    @app.get("/api/v1/rooms/{room}/telemetry", tags=["lich su"])
    def telemetry(room: KnownRoom, db: Db, limit: Limit = 100,
                  since: Annotated[float | None, Query(description="unix time")] = None,
                  until: Annotated[float | None, Query(description="unix time")] = None):
        return {"items": store.telemetry_history(db, room, limit, since, until)}

    @app.get("/api/v1/rooms/{room}/telemetry/series", tags=["lich su"])
    def telemetry_series(room: KnownRoom, db: Db,
                         hours: Annotated[float, Query(gt=0, le=24 * 31)] = 24,
                         points: Annotated[int, Query(ge=10, le=500)] = 240):
        """Nhiet do / do am trung binh theo tung khoang, cu nhat truoc. Dung de ve bieu do."""
        now = clock()
        return store.telemetry_series(db, room, now - hours * 3600, now, points)

    @app.get("/api/v1/rooms/{room}/commands", tags=["lich su"])
    def commands(room: KnownRoom, db: Db, limit: Limit = 50):
        return {"items": store.command_history(db, room, limit)}

    @app.get("/api/v1/rooms/{room}/decisions", tags=["lich su"])
    def decisions(room: KnownRoom, db: Db, limit: Limit = 50):
        """Nhat ky Safety Layer: moi yeu cau, ket luan va ly do."""
        return {"items": store.decision_history(db, room, limit)}

    @app.get("/api/v1/rooms/{room}/ir-events", tags=["lich su"])
    def ir_events(room: KnownRoom, db: Db, limit: Limit = 50):
        """Nhung lan nguoi dung bam remote goc ma node nghe duoc."""
        return {"items": store.ir_event_history(db, room, limit)}

    @app.post("/api/v1/rooms/{room}/commands", tags=["dieu khien"])
    def send_command(room: KnownRoom, body: CommandIn, role: Role, db: Db):
        """Gui lenh. Tra ve sau khi node bao ket qua (hoac het han).

        Nguon lenh lay tu KHOA: khoa app -> `app`; khoa tu dong -> phai neu `source` la `rule`/`ai`.
        """
        if role == "app":
            if body.source not in (None, "app"):
                raise ApiError(403, "SOURCE_NOT_ALLOWED", "Khoa nay chi duoc gui lenh nguon 'app'")
            source = "app"
        else:
            if body.source not in ("rule", "ai"):
                raise ApiError(403, "SOURCE_NOT_ALLOWED", "Khoa tu dong phai gui source = 'rule' hoac 'ai'")
            source = body.source

        out = app.state.service.submit(room, source, power=body.power, mode=body.mode,
                                       temp=body.temp, fan=body.fan)
        d = out.decision
        if out.status == control.REJECTED:
            raise ApiError(REJECT_STATUS.get(d.code, 409), d.code, d.message, d.retry_after_s)
        if out.status == control.UNAVAILABLE:
            raise ApiError(503, "BROKER_UNAVAILABLE", "Gateway dang mat ket noi toi broker MQTT")
        if out.status == control.TIMEOUT:
            raise ApiError(504, "NODE_TIMEOUT", "Node khong tra loi; khong chac lenh da duoc thuc hien")
        if out.status == control.NODE_ERROR:
            raise ApiError(502, "NODE_ERROR", f"Node khong thuc hien duoc lenh: {out.node_error}")
        return {
            "status": out.status,                 # executed / skipped
            "cmd_id": out.cmd_id,
            "source": source,
            "code": d.code,
            "requested": out.target.as_dict(),
            "latency_ms": out.latency_ms,
            "room": room_snapshot(db, room),
        }

    @app.delete("/api/v1/rooms/{room}/auto-hold", tags=["dieu khien"])
    def clear_auto_hold(room: KnownRoom, role: Role, db: Db):
        """Nguoi dung cho phep che do tu dong chay lai ngay (bo manual hold)."""
        if role != "app":
            raise ApiError(403, "FORBIDDEN", "Chi nguoi dung (khoa app) moi duoc bo manual hold")
        store.clear_hold(db, room)
        return room_snapshot(db, room)

    # ------------------------------------------------------------ phieu cam nhan (nhan cho AI)
    def require_app(role: str) -> None:
        if role != "app":
            raise ApiError(403, "FORBIDDEN", "Chi nguoi dung (khoa app) moi duoc ghi phieu cam nhan")

    @app.post("/api/v1/rooms/{room}/comfort", tags=["cam nhan"], status_code=201)
    def add_comfort(room: KnownRoom, body: ComfortIn, role: Role, db: Db):
        """Ghi mot phieu cam nhan kem so do va trang thai dieu hoa luc bam.

        Tu choi khi khong co so do moi: phieu thieu boi canh thi khong dung duoc de huan luyen.
        """
        require_app(role)
        now = clock()
        last = store.last_vote_ts(db, room)
        if last is not None and 0 <= now - last < VOTE_MIN_INTERVAL_S:
            raise ApiError(429, "VOTE_TOO_FAST", "Vua ghi mot phieu, cho vai giay",
                           max(1, round(VOTE_MIN_INTERVAL_S - (now - last))))
        tel = store.latest_telemetry(db, room)
        if tel is None or now - tel["ts"] > app.state.gateway.policy.telemetry_stale_s:
            raise ApiError(409, "TELEMETRY_STALE",
                           "Chua co so do moi tu node nen phieu khong duoc ghi")
        return store.add_vote(db, room, now, body.vote)

    @app.get("/api/v1/rooms/{room}/suggestion", tags=["goi y"])
    def suggestion(room: KnownRoom, db: Db):
        """Goi y tu mo hinh tien nghi ca nhan hoa. Chi doc, khong gui lenh.

        `target` (neu co) la lenh co the gui bang POST /commands; nut "Ap dung" tren dashboard lam viec do.
        """
        out = app.state.advisor.suggest(db, room, clock())
        out["auto"] = settings.ADVISOR_AUTO
        return out

    @app.get("/api/v1/rooms/{room}/comfort", tags=["cam nhan"])
    def list_comfort(room: KnownRoom, db: Db, limit: Limit = 100,
                     since: Annotated[float | None, Query(description="unix time")] = None):
        """Cac phieu cam nhan, moi nhat truoc. Day la du lieu co nhan cho M6."""
        return {"items": store.vote_history(db, room, limit, since)}

    @app.delete("/api/v1/rooms/{room}/comfort/{vote_id}", tags=["cam nhan"])
    def undo_comfort(room: KnownRoom, vote_id: int, role: Role, db: Db):
        """Hoan tac phieu vua bam nham (chi trong VOTE_UNDO_WINDOW_S giay)."""
        require_app(role)
        vote = store.get_vote(db, room, vote_id)
        if vote is None:
            raise ApiError(404, "VOTE_NOT_FOUND", "Khong co phieu nay")
        if clock() - vote["ts"] > VOTE_UNDO_WINDOW_S:
            raise ApiError(409, "UNDO_EXPIRED", "Qua thoi gian hoan tac")
        store.delete_vote(db, room, vote_id)
        return {"deleted": vote_id}

    # Dashboard (cac file tinh). Gan SAU CUNG de khong che cac duong dan /api va /docs.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    else:
        log.warning("Khong thay thu muc dashboard %s", WEB_DIR)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=settings.API_HOST, port=settings.API_PORT, log_level="info")


if __name__ == "__main__":
    main()
