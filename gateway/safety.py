"""
Safety Layer: moi lenh dieu khien dieu hoa deu phai di qua ham `evaluate()` truoc khi duoc gui.

Thiet ke (xem docs/adr/0002-safety-layer-and-control-api.md):
- Ham THUAN: khong doc dong ho, khong goi MQTT, khong cham database. Tat ca du lieu can thiet
  duoc truyen vao (`RoomView`, `now`, `Policy`) -> unit test duoc tung luat.
- Hai lop nguon lenh:
    * thu cong  (remote, app, cli): con nguoi ra lenh. Nguoi cuoi cung ra lenh thang.
    * tu dong   (rule, ai): bi chan khi nguoi dung vua can thiep (manual hold), va chiu luat chat hon.
- Nguyen tac: con nguoi LUON tat duoc dieu hoa (khong bi gioi han tan suat chan).
- Bao ve may nen voi lenh THU CONG la "hoi lai", khong phai "cam": nguoi dung xac nhan (`confirmed`)
  thi van bat duoc. Ly do: IR mot chieu, dong ho bao ve co the dang tinh tu mot lan tat khong co that
  (dieu hoa bo lo lenh), va phan lon dieu hoa tu co tre khoi dong may nen. Lenh tu dong van bi chan cung.
- Moi quyet dinh co ma ly do (`code`) de ghi nhat ky va tra ve cho API.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

# --- Nguon lenh ---
MANUAL_SOURCES = frozenset({"remote", "app", "cli"})
AUTO_SOURCES = frozenset({"rule", "ai"})
ALL_SOURCES = MANUAL_SOURCES | AUTO_SOURCES

MODES = ("cool", "dry", "fan", "auto", "heat")
FANS = ("auto", "low", "mid", "high")
# Che do co chay may nen (fan chi quay quat dan lanh)
COMPRESSOR_MODES = frozenset({"cool", "dry", "auto", "heat"})

# --- Ket luan ---
ALLOW, REJECT, SKIP = "allow", "reject", "skip"

# --- Ma ly do ---
OK = "OK"
NO_CHANGE = "NO_CHANGE"                    # lenh tu dong trung trang thai hien tai -> bo qua
NODE_OFFLINE = "NODE_OFFLINE"
RATE_LIMIT = "RATE_LIMIT"
TEMP_OUT_OF_RANGE = "TEMP_OUT_OF_RANGE"
COMPRESSOR_MIN_OFF = "COMPRESSOR_MIN_OFF"  # vua tat, chua du thoi gian nghi may nen
COMPRESSOR_MIN_ON = "COMPRESSOR_MIN_ON"    # vua bat, lenh tu dong chua duoc tat
STATE_UNCERTAIN = "STATE_UNCERTAIN"        # khong chac trang thai dieu hoa -> khong tu dong
MANUAL_HOLD = "MANUAL_HOLD"                # nguoi dung vua can thiep
TELEMETRY_STALE = "TELEMETRY_STALE"
ROOM_EMPTY = "ROOM_EMPTY"
STEP_TOO_LARGE = "STEP_TOO_LARGE"
EARLY_START_CONFIRMED = "EARLY_START_CONFIRMED"  # nguoi dung xac nhan bat lai som (chi lenh thu cong)


@dataclass(frozen=True)
class AcState:
    power: str   # "on" / "off"
    mode: str    # mot trong MODES
    temp: int    # do C
    fan: str     # mot trong FANS

    def as_dict(self) -> dict:
        return {"power": self.power, "mode": self.mode, "temp": self.temp, "fan": self.fan}


@dataclass(frozen=True)
class Policy:
    # Gioi han nhiet do cho nguoi dung (trung voi IR_TEMP_MIN/MAX cua firmware)
    temp_min: int = 16
    temp_max: int = 30
    # Gioi han hep hon cho lenh tu dong: AI/luat khong duoc day ve hai dau cuc
    auto_temp_min: int = 24
    auto_temp_max: int = 29
    # Bao ve may nen
    min_off_s: float = 180.0        # tat xong phai nghi bao lau moi duoc bat lai
    min_on_s: float = 300.0         # lenh tu dong: bat xong phai chay bao lau moi duoc tat
    # Gioi han tan suat
    manual_min_interval_s: float = 2.0
    auto_min_interval_s: float = 600.0
    auto_max_step_c: int = 1        # lenh tu dong doi toi da bao nhieu do moi lan
    # Uu tien nguoi dung: sau khi nguoi dung ra lenh, lenh tu dong bi chan bao lau
    hold_remote_s: float = 3600.0
    hold_app_s: float = 1800.0
    # Lenh tu dong can du lieu cam bien con moi
    telemetry_stale_s: float = 120.0
    # Trang thai mac dinh khi chua biet dieu hoa dang o dau va lenh khong neu du truong
    default_mode: str = "cool"
    default_temp: int = 26
    default_fan: str = "auto"

    def hold_for(self, source: str) -> float:
        """Nguon nay ra lenh thi chan lenh tu dong bao lau (0 = khong chan)."""
        if source == "remote":
            return self.hold_remote_s
        if source in MANUAL_SOURCES:
            return self.hold_app_s
        return 0.0


@dataclass(frozen=True)
class RoomView:
    """Nhung gi Safety Layer can biet ve mot phong tai thoi diem danh gia."""
    node_online: bool
    ac: AcState | None = None            # trang thai DU KIEN (IR mot chieu, khong co xac nhan)
    uncertain: bool = True               # True = co the da lech voi may that
    last_on_ts: float | None = None      # lan cuoi chuyen off -> on
    last_off_ts: float | None = None     # lan cuoi chuyen on -> off
    last_cmd_ts: float | None = None     # lenh gan nhat da gui (moi nguon)
    last_auto_ts: float | None = None    # lenh tu dong gan nhat da gui
    hold_until: float | None = None      # lenh tu dong bi chan toi thoi diem nay
    telemetry_ts: float | None = None
    presence: bool | None = None         # None = chua co cam bien


@dataclass(frozen=True)
class Decision:
    verdict: str                 # ALLOW / REJECT / SKIP
    code: str
    message: str
    retry_after_s: int | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict == ALLOW


def resolve_target(current: AcState | None, policy: Policy, *, power: str | None = None,
                   mode: str | None = None, temp: int | None = None, fan: str | None = None) -> AcState:
    """Ghep lenh (co the thieu truong) voi trang thai du kien thanh trang thai dich DAY DU.

    Gateway luon gui lenh day du xuong node, de trang thai o Pi va o node khong lech nhau.
    """
    base = current or AcState("off", policy.default_mode, policy.default_temp, policy.default_fan)
    return replace(
        base,
        power=base.power if power is None else power,
        mode=base.mode if mode is None else mode,
        temp=base.temp if temp is None else temp,
        fan=base.fan if fan is None else fan,
    )


def _elapsed(now: float, ts: float | None) -> float | None:
    """Thoi gian da troi qua. Dong ho bi lui (ts o tuong lai) -> coi nhu vua xay ra (0), an toan."""
    if ts is None:
        return None
    return max(0.0, now - ts)


def _wait(required: float, elapsed: float) -> int:
    return max(1, math.ceil(required - elapsed))


def _reject(code: str, message: str, retry_after_s: int | None = None) -> Decision:
    return Decision(REJECT, code, message, retry_after_s)


def _compressor_rest(turning_on: bool, target: AcState, room: RoomView, now: float,
                     policy: Policy) -> Decision | None:
    """Luat chung cho moi nguon: may nen vua tat phai nghi du `min_off_s` moi duoc bat lai."""
    if turning_on and target.mode in COMPRESSOR_MODES:
        since_off = _elapsed(now, room.last_off_ts)
        if since_off is not None and since_off < policy.min_off_s:
            return _reject(COMPRESSOR_MIN_OFF, "May nen vua tat, can nghi truoc khi bat lai",
                           _wait(policy.min_off_s, since_off))
    return None


def evaluate(source: str, target: AcState, room: RoomView, now: float, policy: Policy,
             confirmed: bool = False) -> Decision:
    """Quyet dinh co cho gui `target` xuong node hay khong.

    `confirmed`: nguoi dung da xac nhan bat lai som du may nen vua tat. Chi co tac dung voi lenh thu cong.
    """
    if source not in ALL_SOURCES:
        raise ValueError(f"nguon lenh khong hop le: {source}")
    manual = source in MANUAL_SOURCES
    turning_on = target.power == "on" and (room.ac is None or room.ac.power == "off")
    turning_off = target.power == "off" and room.ac is not None and room.ac.power == "on"

    # 1. Node phai dang online. Khong xep hang lenh: lenh "bat" den tre mot gio la nguy hiem.
    if not room.node_online:
        return _reject(NODE_OFFLINE, "Node cua phong dang offline, lenh khong duoc xep hang cho")

    # ---------------- Luat rieng cho lenh TU DONG ----------------
    if not manual:
        if room.ac is None or room.uncertain:
            return _reject(STATE_UNCERTAIN,
                           "Khong chac trang thai dieu hoa; can mot lenh cua nguoi dung de dong bo lai")
        if room.hold_until is not None and now < room.hold_until:
            return _reject(MANUAL_HOLD, "Nguoi dung vua dieu chinh, lenh tu dong tam dung",
                           _wait(room.hold_until, now))
        if target == room.ac:
            return Decision(SKIP, NO_CHANGE, "Trang thai dich trung trang thai hien tai")
        age = _elapsed(now, room.telemetry_ts)
        if age is None or age > policy.telemetry_stale_s:
            return _reject(TELEMETRY_STALE, "Du lieu cam bien qua cu de ra quyet dinh tu dong")
        if turning_on and room.presence is False:
            return _reject(ROOM_EMPTY, "Phong khong co nguoi, khong tu dong bat dieu hoa")
        if target.power == "on" and target.mode != "fan":
            if not policy.auto_temp_min <= target.temp <= policy.auto_temp_max:
                return _reject(TEMP_OUT_OF_RANGE, f"Lenh tu dong chi duoc dat "
                               f"{policy.auto_temp_min}-{policy.auto_temp_max} do C")
            if room.ac.power == "on" and abs(target.temp - room.ac.temp) > policy.auto_max_step_c:
                return _reject(STEP_TOO_LARGE, f"Lenh tu dong chi duoc doi toi da "
                               f"{policy.auto_max_step_c} do C moi lan")
        since_auto = _elapsed(now, room.last_auto_ts)
        if since_auto is not None and since_auto < policy.auto_min_interval_s:
            return _reject(RATE_LIMIT, "Lenh tu dong qua day",
                           _wait(policy.auto_min_interval_s, since_auto))
        if turning_off and room.ac.mode in COMPRESSOR_MODES:
            since_on = _elapsed(now, room.last_on_ts)
            if since_on is not None and since_on < policy.min_on_s:
                return _reject(COMPRESSOR_MIN_ON, "May nen vua chay, chua duoc tu dong tat",
                               _wait(policy.min_on_s, since_on))
        if blocked := _compressor_rest(turning_on, target, room, now, policy):
            return blocked

    # ---------------- Luat rieng cho lenh THU CONG ----------------
    else:
        if target.power == "on" and target.mode != "fan":
            if not policy.temp_min <= target.temp <= policy.temp_max:
                return _reject(TEMP_OUT_OF_RANGE,
                               f"Nhiet do phai trong khoang {policy.temp_min}-{policy.temp_max} do C")
        # Bao ve may nen truoc gioi han tan suat: tra ve ly do co thoi gian cho dai hon
        blocked = _compressor_rest(turning_on, target, room, now, policy)
        if blocked and not confirmed:
            return blocked
        # Con nguoi luon tat duoc: lenh tat khong bi gioi han tan suat
        if target.power != "off":
            since_cmd = _elapsed(now, room.last_cmd_ts)
            if since_cmd is not None and since_cmd < policy.manual_min_interval_s:
                return _reject(RATE_LIMIT, "Gui lenh qua nhanh",
                               _wait(policy.manual_min_interval_s, since_cmd))
        if blocked:
            return Decision(ALLOW, EARLY_START_CONFIRMED,
                            "Nguoi dung xac nhan bat lai som; dieu hoa tu tre khoi dong may nen neu can")

    return Decision(ALLOW, OK, "Lenh duoc chap nhan")
