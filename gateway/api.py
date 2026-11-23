"""
REST API cua Gateway (FastAPI). Chay:  python api.py
Tai lieu tu sinh: http://<pi>:8000/docs      Mo ta: docs/API.md

Mot tien trinh chay ca hai viec: thu thap du lieu MQTT (lop Gateway) va phuc vu HTTP.
Moi lenh dieu khien deu di qua control.CommandService -> Safety Layer.
"""
import hmac
import ipaddress
import logging
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path as FsPath
from typing import Annotated, Literal

import segno
import uvicorn
from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

import accounts
import advisor as advisor_mod
import control
import netmode
import safety
import settings
import store
from gateway import Gateway

__version__ = "0.10.0"
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
    def __init__(self, status: int, code: str, message: str, retry_after_s: int | None = None,
                 extra: dict | None = None):
        self.status, self.code, self.message, self.retry_after_s = status, code, message, retry_after_s
        self.extra = extra or {}


class CommandIn(BaseModel):
    """Lenh dieu khien. Truong nao bo trong thi giu nguyen gia tri hien tai."""
    model_config = ConfigDict(extra="forbid")

    power: Literal["on", "off"] | None = None
    mode: Literal["cool", "dry", "fan", "auto", "heat"] | None = None
    temp: int | None = Field(default=None, ge=0, le=50, description="Do C")
    fan: Literal["auto", "low", "mid", "high"] | None = None
    source: Literal["app", "rule", "ai"] | None = Field(
        default=None, description="Chi dich vu tu dong moi can gui: 'rule' hoac 'ai'")
    confirm: bool = Field(
        default=False, description="Nguoi dung xac nhan bat lai som khi may nen vua tat (chi khoa app)")

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.power is None and self.mode is None and self.temp is None and self.fan is None:
            raise ValueError("can it nhat mot trong cac truong: power, mode, temp, fan")
        return self


class AcSyncIn(BaseModel):
    """Trang thai THAT cua dieu hoa do nguoi dung bao. Truong nao bo trong thi giu nguyen."""
    model_config = ConfigDict(extra="forbid")

    power: Literal["on", "off"] | None = None
    mode: Literal["cool", "dry", "fan", "auto", "heat"] | None = None
    temp: int | None = Field(default=None, ge=0, le=50)
    fan: Literal["auto", "low", "mid", "high"] | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.power is None and self.mode is None and self.temp is None and self.fan is None:
            raise ValueError("can it nhat mot trong cac truong: power, mode, temp, fan")
        return self


class ComfortIn(BaseModel):
    """Phieu cam nhan: nguoi dung muon phong mat hon, giu nhu hien tai, hay am hon."""
    model_config = ConfigDict(extra="forbid")

    vote: Literal["cooler", "comfortable", "warmer"]


class NetworkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "standalone", "home"]


AP_SSID = "SmartAC-Backup"
AP_ADDRESS = "10.42.0.1"     # dia chi cua Pi tren mang du phong (NetworkManager, ADR 0001)


class SetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=40, description="Ma thiet lap in tren tem dan Pi")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=40)
    device: str | None = Field(default=None, max_length=60, description="Ten thiet bi, de quan ly phien")


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=40)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    device: str | None = Field(default=None, max_length=60)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class RoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "member", "guest"]


@dataclass(frozen=True)
class Who:
    """Ai dang goi API: mot tai khoan (qua phien dang nhap) hoac mot khoa API."""
    kind: str                     # "user" | "key"
    role: str                     # admin | member | guest | automation
    user_id: int | None = None
    username: str | None = None
    token: str | None = None

    @property
    def can_control(self) -> bool:
        return self.role in (accounts.ADMIN, accounts.MEMBER)

    @property
    def is_admin(self) -> bool:
        return self.role == accounts.ADMIN


LOGIN_MAX_FAILS = 5          # sai mat khau bay nhieu lan trong LOGIN_WINDOW_S thi khoa ten do tam thoi
LOGIN_WINDOW_S = 300
SETUP_MAX_FAILS_PER_MIN = 5
REGISTER_MAX_PER_MIN = 10
MAX_PENDING = 20             # chan spam dang ky tu mang Wi-Fi du phong


class PairClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=64)


PAIR_TTL_S = 300             # ma ghep thiet bi het han sau 5 phut
PAIR_MAX_TTL_S = 900         # ma kem theo khi doi mang (con phai doi Wi-Fi tren dien thoai)
PAIR_MAX_FAILS_PER_MIN = 10  # chong do ma

VOTE_MIN_INTERVAL_S = 5      # chong bam dup
VOTE_UNDO_WINDOW_S = 120     # duoc hoan tac phieu trong bao lau

# HTTP status cho tung ma tu choi cua Safety Layer (mac dinh 409)
REJECT_STATUS = {
    control.NO_STATE: 409,
    safety.NODE_OFFLINE: 503,
    safety.RATE_LIMIT: 429,
    safety.TEMP_OUT_OF_RANGE: 422,
}


def create_app(gateway: Gateway | None = None, service: control.CommandService | None = None,
               *, api_key: str | None = None, automation_key: str | None = None,
               setup_code: str | None = None, device_id: str | None = None,
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
    # Ma thiet lap (in tren tem) va ma thiet bi: tao lan dau, giu mai (accounts.py)
    setup_code = setup_code or accounts.setup_code()
    device_id = device_id or accounts.device_id()
    login_fails: dict[str, list[float]] = {}   # ten dang nhap -> thoi diem cac lan sai
    setup_fails: list[float] = []
    registrations: list[float] = []
    auth_lock = threading.Lock()
    # Ma ghep thiet bi: chi nam trong RAM (khoi dong lai Pi la mat het), moi ma dung MOT lan
    pairing: dict[str, tuple[float, int | None]] = {}   # ma -> (het han, tai khoan tao ma)
    pair_fails: list[float] = []            # thoi diem cac lan nhap sai gan day
    pair_lock = threading.Lock()

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
        body = {"error": {"code": exc.code, "message": exc.message, **exc.extra}}
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

    def get_who(db: Db, authorization: Annotated[str | None, Header()] = None,
                x_api_key: Annotated[str | None, Header()] = None) -> Who:
        """Phien dang nhap (Authorization: Bearer ...) hoac khoa API (X-API-Key).

        Khoa app (API_KEY) giu quyen quan tri cho cong cu dong lenh tren Pi; khoa tu dong chi gui lenh
        nguon rule/ai. Nguoi dung dung tai khoan.
        """
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            user = accounts.session_user(db, token, clock()) if token else None
            if user is None:
                raise ApiError(401, "SESSION_INVALID", "Phien dang nhap het han hoac da bi thu hoi")
            if user["role"] == accounts.PENDING:
                raise ApiError(403, "ACCOUNT_PENDING", "Tai khoan dang cho quan tri vien duyet")
            return Who("user", user["role"], user["id"], user["username"], token)
        given = (x_api_key or "").encode()
        if given and hmac.compare_digest(given, api_key.encode()):
            return Who("key", accounts.ADMIN)
        if given and automation_key and hmac.compare_digest(given, automation_key.encode()):
            return Who("key", "automation")
        raise ApiError(401, "UNAUTHORIZED", "Can dang nhap (Authorization: Bearer) hoac khoa X-API-Key")

    WhoDep = Annotated[Who, Depends(get_who)]

    def require_control(who: Who) -> None:
        if not who.can_control:
            raise ApiError(403, "FORBIDDEN", "Tai khoan khach chi duoc xem" if who.role == accounts.GUEST
                           else "Khoa nay khong duoc lam viec nay")

    def require_admin(who: Who) -> None:
        if not who.is_admin:
            raise ApiError(403, "FORBIDDEN", "Chi quan tri vien moi duoc lam viec nay")

    def known_room(room: Room, db: Db, who: WhoDep) -> str:
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
                "version": __version__, "uptime_s": round(time.monotonic() - started),
                "time": round(clock(), 1)}   # dashboard so voi dong ho dien thoai: Pi khong co pin RTC
        return JSONResponse(body, status_code=200 if connected else 503)

    @app.get("/api/v1/policy", tags=["he thong"])
    def get_policy(who: WhoDep):
        """Cac nguong Safety Layer dang ap dung."""
        return vars(app.state.gateway.policy)

    @app.get("/api/v1/rooms", tags=["phong"])
    def rooms(db: Db, who: WhoDep):
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
    def send_command(room: KnownRoom, body: CommandIn, who: WhoDep, db: Db):
        """Gui lenh. Tra ve sau khi node bao ket qua (hoac het han).

        Nguon lenh lay tu NGUOI GOI: tai khoan / khoa app -> `app`; khoa tu dong -> phai neu `source`
        la `rule`/`ai`. Tai khoan khach khong duoc gui lenh.
        """
        if who.role == "automation":
            if body.source not in ("rule", "ai"):
                raise ApiError(403, "SOURCE_NOT_ALLOWED", "Khoa tu dong phai gui source = 'rule' hoac 'ai'")
            source = body.source
        else:
            require_control(who)
            if body.source not in (None, "app"):
                raise ApiError(403, "SOURCE_NOT_ALLOWED", "Nguoi dung chi duoc gui lenh nguon 'app'")
            source = "app"

        if body.confirm and source != "app":
            raise ApiError(403, "CONFIRM_NOT_ALLOWED", "Chi nguoi dung moi duoc xac nhan bat lai som")

        out = app.state.service.submit(room, source, power=body.power, mode=body.mode,
                                       temp=body.temp, fan=body.fan, confirmed=body.confirm)
        return command_response(out, source, db, room)

    def command_response(out: control.Outcome, source: str, db: sqlite3.Connection, room: str) -> dict:
        d = out.decision
        if out.status == control.REJECTED:
            # Lenh thu cong bi chan vi may nen vua tat: nguoi dung duoc phep xac nhan va gui lai
            extra = {"can_confirm": True} if d.code == safety.COMPRESSOR_MIN_OFF and source == "app" else None
            raise ApiError(REJECT_STATUS.get(d.code, 409), d.code, d.message, d.retry_after_s, extra)
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

    @app.post("/api/v1/rooms/{room}/commands/resend", tags=["dieu khien"])
    def resend_command(room: KnownRoom, who: WhoDep, db: Db):
        """Phat lai trang thai du kien hien tai, khi dieu hoa co ve da bo lo lenh truoc."""
        require_control(who)
        return command_response(app.state.service.resend(room, "app"), "app", db, room)

    @app.put("/api/v1/rooms/{room}/ac-state", tags=["dieu khien"])
    def sync_ac_state(room: KnownRoom, body: AcSyncIn, who: WhoDep, db: Db):
        """Bao trang thai THAT cua dieu hoa khi man hinh hien sai. Khong phat IR.

        Xoa danh dau "khong chac chan", tam dung che do tu dong nhu mot lenh cua nguoi dung,
        va khong dong toi dong ho bao ve may nen.
        """
        require_control(who)
        app.state.service.sync(room, power=body.power, mode=body.mode, temp=body.temp, fan=body.fan)
        return room_snapshot(db, room)

    @app.delete("/api/v1/rooms/{room}/auto-hold", tags=["dieu khien"])
    def clear_auto_hold(room: KnownRoom, who: WhoDep, db: Db):
        """Nguoi dung cho phep che do tu dong chay lai ngay (bo manual hold)."""
        require_control(who)
        store.clear_hold(db, room)
        return room_snapshot(db, room)

    # ------------------------------------------------------------ phieu cam nhan (nhan cho AI)
    @app.post("/api/v1/rooms/{room}/comfort", tags=["cam nhan"], status_code=201)
    def add_comfort(room: KnownRoom, body: ComfortIn, who: WhoDep, db: Db):
        """Ghi mot phieu cam nhan kem so do va trang thai dieu hoa luc bam.

        Tu choi khi khong co so do moi: phieu thieu boi canh thi khong dung duoc de huan luyen.
        """
        require_control(who)
        now = clock()
        last = store.last_vote_ts(db, room)
        if last is not None and 0 <= now - last < VOTE_MIN_INTERVAL_S:
            raise ApiError(429, "VOTE_TOO_FAST", "Vua ghi mot phieu, cho vai giay",
                           max(1, round(VOTE_MIN_INTERVAL_S - (now - last))))
        tel = store.latest_telemetry(db, room)
        if tel is None or now - tel["ts"] > app.state.gateway.policy.telemetry_stale_s:
            raise ApiError(409, "TELEMETRY_STALE",
                           "Chua co so do moi tu node nen phieu khong duoc ghi")
        return store.add_vote(db, room, now, body.vote, who.user_id, who.username)

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
    def undo_comfort(room: KnownRoom, vote_id: int, who: WhoDep, db: Db):
        """Hoan tac phieu vua bam nham (chi trong VOTE_UNDO_WINDOW_S giay). Chi phieu cua minh."""
        require_control(who)
        vote = store.get_vote(db, room, vote_id)
        if vote is None:
            raise ApiError(404, "VOTE_NOT_FOUND", "Khong co phieu nay")
        if vote["user_id"] is not None and vote["user_id"] != who.user_id and not who.is_admin:
            raise ApiError(403, "NOT_YOUR_VOTE", "Chi nguoi gui moi hoan tac duoc phieu nay")
        if clock() - vote["ts"] > VOTE_UNDO_WINDOW_S:
            raise ApiError(409, "UNDO_EXPIRED", "Qua thoi gian hoan tac")
        store.delete_vote(db, room, vote_id)
        return {"deleted": vote_id}

    # ------------------------------------------------------------ mang cua Pi
    def network_info() -> dict:
        port = f":{settings.API_PORT}" if settings.API_PORT != 80 else ""
        return {
            "mode": netmode.effective_mode(),     # che do netwatch se ap dung
            "chosen": netmode.chosen_mode(),      # chon tren dashboard (None = theo .env)
            "default": netmode.default_mode(),    # NETWORK_MODE trong .env
            "status": netmode.read_status(clock()),
            "ap_ssid": AP_SSID,
            "ap_url": f"http://{AP_ADDRESS}{port}/",
            "home_url": f"http://gateway.local{port}/",
        }

    @app.get("/api/v1/system/network", tags=["he thong"])
    def get_network(who: WhoDep):
        """Che do mang cua Pi va trang thai Wi-Fi do netwatch bao (`status.running` = netwatch con chay)."""
        return network_info()

    @app.put("/api/v1/system/network", tags=["he thong"])
    def set_network(body: NetworkIn, who: WhoDep, db: Db):
        """Doi che do mang (chi quan tri vien). netwatch ap dung trong khoang 15 s."""
        require_admin(who)
        try:
            netmode.choose_mode(body.mode)
        except OSError as e:
            raise ApiError(500, "NETWORK_MODE_WRITE_FAILED", f"Khong ghi duoc lua chon: {e}") from e
        log.warning("Doi che do mang -> %s", body.mode)
        # Bao truoc cho cac node (Pi con o mang cu thi moi gui toi duoc): node chuyen theo trong
        # ~20 s thay vi cho mat broker 120 s. Node cu (firmware < 0.10.0) bo qua ban tin nay.
        status = netmode.read_status(clock()) or {}
        hint = ("backup" if body.mode == netmode.STANDALONE and status.get("state") != "ap" else
                "home" if body.mode != netmode.STANDALONE and status.get("state") == "ap" else None)
        if hint:
            for room in [r["room"] for r in store.list_rooms(db)]:
                app.state.gateway.publish_net_hint(room, hint)
        return network_info()

    # ------------------------------------------------------------ ghep thiet bi (QR)
    def lan_host(request: Request) -> str:
        """Dia chi de dien thoai mo dashboard. Ten .local (mDNS) thuong khong chay tren Android,
        nen doi sang IP cua Pi tren dung mang ma trinh duyet dang dung."""
        host = request.url.hostname or "localhost"
        if not host.endswith(".local") and host not in ("localhost", "127.0.0.1"):
            return host
        client = request.client.host if request.client else ""
        try:
            if ipaddress.ip_address(client).is_loopback:
                return host
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((client, 9))          # UDP: khong gui goi tin nao, chi de he dieu hanh chon card mang
                return s.getsockname()[0]
        except (ValueError, OSError):
            return host

    @app.post("/api/v1/pairing", tags=["ghep thiet bi"], status_code=201)
    def create_pairing(request: Request, who: WhoDep,
                       ttl_s: Annotated[int, Query(ge=60, le=PAIR_MAX_TTL_S)] = PAIR_TTL_S):
        """Tao ma ghep dung mot lan (mac dinh 5 phut) kem ma QR. Thiet bi moi quet la dang nhap.

        Dashboard cung tao mot ma (toi da 15 phut) ngay truoc khi doi mang cua Pi: trinh duyet luu khoa
        theo TUNG DIA CHI, nen http://10.42.0.1:8000 la "trang moi" va se hoi khoa lai neu khong co ma.
        """
        require_control(who)
        now = clock()
        code = secrets.token_urlsafe(12)
        with pair_lock:
            for c, (exp, _) in list(pairing.items()):
                if exp <= now:
                    del pairing[c]
            pairing[code] = (now + ttl_s, who.user_id)
        port = request.url.port
        base = f"{request.url.scheme}://{lan_host(request)}{f':{port}' if port else ''}/"
        url = f"{base}#pair={code}"              # sau dau # : trinh duyet KHONG gui len may chu, khong vao log
        qr = segno.make(url, error="m")
        return {"code": code, "url": url, "expires_in_s": ttl_s,
                "qr": qr.svg_data_uri(scale=6, border=2, dark="#12232D", light="#FFFFFF")}

    @app.post("/api/v1/pairing/claim", tags=["ghep thiet bi"])
    def claim_pairing(body: PairClaimIn, db: Db):
        """Doi ma ghep lay phien dang nhap cua nguoi tao ma (hoac khoa app, neu ma tao bang khoa).

        KHONG can dang nhap. Ma dung xong hoac het han la vo hieu.
        """
        now = clock()
        with pair_lock:
            pair_fails[:] = [t for t in pair_fails if now - t < 60]
            if len(pair_fails) >= PAIR_MAX_FAILS_PER_MIN:
                raise ApiError(429, "PAIR_TOO_MANY", "Nhap sai qua nhieu lan, cho mot phut", 60)
            exp, user_id = pairing.pop(body.code, (0.0, None))
            if exp <= now:
                pair_fails.append(now)
                raise ApiError(410, "PAIR_INVALID", "Ma ghep khong dung, da dung roi hoac da het han")
        log.info("Them mot thiet bi bang ma ghep")
        if user_id is None:
            return {"api_key": api_key}
        if db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise ApiError(410, "PAIR_INVALID", "Tai khoan tao ma khong con nua")
        return {"token": accounts.new_session(db, user_id, now, "Ghep bang ma QR")}

    # ------------------------------------------------------------ thiet lap lan dau, tai khoan
    def user_out(u: dict) -> dict:
        return {"username": u["username"], "display_name": u["display_name"], "role": u["role"],
                "created_ts": u["created_ts"], "approved_ts": u["approved_ts"], "approved_by": u["approved_by"]}

    def account_error(e: accounts.AccountError) -> ApiError:
        status = {"USERNAME_TAKEN": 409, "USER_NOT_FOUND": 404, "LAST_ADMIN": 409}.get(e.code, 422)
        return ApiError(status, e.code, e.message)

    @app.get("/api/v1/setup/status", tags=["tai khoan"])
    def setup_status(db: Db):
        """Khong can dang nhap. `claimed` = da co quan tri vien; `device_id` de app nhan dung Pi."""
        return {"claimed": accounts.has_admin(db), "device_id": device_id, "version": __version__}

    @app.post("/api/v1/setup", tags=["tai khoan"], status_code=201)
    def first_setup(body: SetupIn, db: Db):
        """Tao tai khoan quan tri dau tien bang ma thiet lap tren tem. Chi dung duoc khi chua co chu."""
        now = clock()
        with auth_lock:
            setup_fails[:] = [t for t in setup_fails if now - t < 60]
            if len(setup_fails) >= SETUP_MAX_FAILS_PER_MIN:
                raise ApiError(429, "SETUP_TOO_MANY", "Nhap sai ma qua nhieu lan, cho mot phut", 60)
            if accounts.has_admin(db):
                raise ApiError(409, "ALREADY_CLAIMED",
                               "Pi da co quan tri vien. Giu nut reset tren Pi 10 giay de thiet lap lai")
            if not accounts.setup_code_matches(body.code, setup_code):
                setup_fails.append(now)
                raise ApiError(403, "SETUP_CODE_INVALID", "Ma thiet lap khong dung (xem tem dan tren Pi)")
            try:
                user = accounts.create_user(db, body.username, body.password, accounts.ADMIN, now,
                                            body.display_name, approved_by="ma thiet lap")
            except accounts.AccountError as e:
                raise account_error(e) from e
        log.warning("Thiet lap lan dau: quan tri vien '%s'", user["username"])
        return {"token": accounts.new_session(db, user["id"], now, body.device), "user": user_out(user)}

    @app.post("/api/v1/auth/register", tags=["tai khoan"], status_code=201)
    def register(body: RegisterIn, db: Db):
        """Tu dang ky. Tai khoan o trang thai cho duyet cho toi khi quan tri vien cap quyen."""
        now = clock()
        with auth_lock:
            registrations[:] = [t for t in registrations if now - t < 60]
            if len(registrations) >= REGISTER_MAX_PER_MIN:
                raise ApiError(429, "REGISTER_TOO_MANY", "Qua nhieu dang ky, cho mot phut", 60)
            if not accounts.has_admin(db):
                raise ApiError(409, "NOT_CLAIMED", "Pi chua duoc thiet lap: tao tai khoan quan tri bang ma tren tem")
            pending = db.execute("SELECT COUNT(*) FROM users WHERE role=?", (accounts.PENDING,)).fetchone()[0]
            if pending >= MAX_PENDING:
                raise ApiError(429, "TOO_MANY_PENDING", "Qua nhieu tai khoan cho duyet; nho quan tri vien duyet truoc")
            registrations.append(now)
        try:
            user = accounts.create_user(db, body.username, body.password, accounts.PENDING, now, body.display_name)
        except accounts.AccountError as e:
            raise account_error(e) from e
        log.info("Dang ky moi, cho duyet: '%s'", user["username"])
        return {"status": "pending", "user": user_out(user)}

    @app.post("/api/v1/auth/login", tags=["tai khoan"])
    def login(body: LoginIn, db: Db):
        """Dang nhap, tra ve phien (`token`) dung cho header Authorization: Bearer."""
        now = clock()
        name = accounts.normalize_username(body.username)
        with auth_lock:
            fails = login_fails.setdefault(name, [])
            fails[:] = [t for t in fails if now - t < LOGIN_WINDOW_S]
            if len(fails) >= LOGIN_MAX_FAILS:
                wait = round(LOGIN_WINDOW_S - (now - fails[0]))
                raise ApiError(429, "LOGIN_LOCKED", "Sai mat khau qua nhieu lan, thu lai sau", max(1, wait))
        user = accounts.authenticate(db, name, body.password)
        if user is None:
            with auth_lock:
                login_fails.setdefault(name, []).append(now)
            raise ApiError(401, "LOGIN_FAILED", "Sai ten dang nhap hoac mat khau")
        with auth_lock:
            login_fails.pop(name, None)
        if user["role"] == accounts.PENDING:
            raise ApiError(403, "ACCOUNT_PENDING", "Tai khoan dang cho quan tri vien duyet")
        return {"token": accounts.new_session(db, user["id"], now, body.device), "user": user_out(user)}

    @app.post("/api/v1/auth/logout", tags=["tai khoan"], status_code=204)
    def logout(who: WhoDep, db: Db):
        if who.token:
            accounts.end_session(db, who.token)

    @app.get("/api/v1/auth/me", tags=["tai khoan"])
    def me(who: WhoDep, db: Db):
        if who.kind == "key":
            return {"username": None, "display_name": "Khoa API", "role": who.role, "kind": "key"}
        out = user_out(accounts.get_user(db, who.username))
        out["kind"] = "user"
        out["sessions"] = accounts.list_sessions(db, who.user_id)
        return out

    @app.put("/api/v1/auth/password", tags=["tai khoan"])
    def change_password(body: PasswordIn, who: WhoDep, db: Db):
        """Doi mat khau; dang xuat moi thiet bi khac."""
        if who.kind != "user":
            raise ApiError(403, "FORBIDDEN", "Khoa API khong co mat khau")
        if accounts.authenticate(db, who.username, body.old_password) is None:
            raise ApiError(403, "WRONG_PASSWORD", "Mat khau hien tai khong dung")
        try:
            accounts.change_password(db, who.user_id, body.new_password, who.token)
        except accounts.AccountError as e:
            raise account_error(e) from e
        return {"changed": True}

    @app.get("/api/v1/users", tags=["tai khoan"])
    def users(who: WhoDep, db: Db):
        """Moi tai khoan, cho duyet len dau (chi quan tri vien)."""
        require_admin(who)
        return {"items": [user_out(u) for u in accounts.list_users(db)]}

    @app.put("/api/v1/users/{username}", tags=["tai khoan"])
    def set_user_role(username: str, body: RoleIn, who: WhoDep, db: Db):
        """Cap quyen (duyet tai khoan cho duyet) hoac doi quyen."""
        require_admin(who)
        try:
            user = accounts.set_role(db, username, body.role, who.username or "khoa API", clock())
        except accounts.AccountError as e:
            raise account_error(e) from e
        log.warning("'%s' cap quyen %s cho '%s'", who.username, body.role, user["username"])
        return user_out(user)

    @app.delete("/api/v1/users/{username}", tags=["tai khoan"])
    def remove_user(username: str, who: WhoDep, db: Db):
        """Xoa tai khoan va moi phien cua no."""
        require_admin(who)
        try:
            accounts.delete_user(db, username)
        except accounts.AccountError as e:
            raise account_error(e) from e
        log.warning("'%s' xoa tai khoan '%s'", who.username, username)
        return {"deleted": accounts.normalize_username(username)}

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
