"""
Mo hinh tien nghi nhiet (M6): du doan nguoi dung muon "am hon / giu nguyen / mat hon".

Xem docs/adr/0004-comfort-model.md.

- Hoi quy logistic THU BAC (proportional odds): mot bien an z tang theo nhiet do (va do am),
  hai nguong theta0 < theta1 chia z thanh 3 lop theo thu tu: am hon < giu nguyen < mat hon.
- Tham so chung (w_t, w_h, theta0, theta1) hoc OFFLINE tu ASHRAE Global Thermal Comfort Database II
  (ml/train_prior.py) -> gateway/comfort_prior.json.
- Ca nhan hoa: hoc HAI tham so tu phieu cua nguoi dung:
    shift (do C)  lech nhiet do ua thich so voi nguoi trung binh (duong = thich am hon)
    scale         do nhay: mot nguoi cu the tra loi nhat quan hon ca dam dong (scale > 1)
  Uoc luong MAP voi prior quanh mo hinh chung: it phieu thi gan mo hinh chung, nhieu phieu thi tien dan
  ve so thich that. Phieu cu duoc giam trong so (half-life).

File nay KHONG dung numpy: chay tren Pi ma khong can thu vien them.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

CLASSES = ("warmer", "comfortable", "cooler")       # thu tu tang theo nhiet do
VOTE_TO_CLASS = {1: 0, 0: 1, -1: 2}                 # ma luu trong DB (warmer=+1, cooler=-1)
PRIOR_PATH = Path(__file__).resolve().parent / "comfort_prior.json"

SHIFT_PRIOR_SD_C = 2.0        # truoc khi co phieu: nguoi dung lech nguoi trung binh khoang +-2 do C
SHIFT_LIMIT_C = 8.0
LOG_SCALE_PRIOR_MEAN = 0.0    # prior cho ln(scale): mac dinh nhay nhu dam dong...
LOG_SCALE_PRIOR_SD = 0.7      # ...nhung cho phep nhay hon toi vai lan
LOG_SCALE_GRID = [-0.7 + 0.15 * i for i in range(15)]    # scale tu ~0.5 den ~4
HALF_LIFE_DAYS = 30.0         # so thich thay doi theo mua -> phieu 30 ngay truoc chi tinh mot nua
BAND_P = 0.3                  # vung de chiu: kha nang muon doi (moi huong) duoi 30 %


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass(frozen=True)
class ComfortModel:
    w_t: float                 # do doc theo nhiet do (moi do C), > 0
    w_h: float                 # theo do am (moi 10 %RH)
    theta0: float              # nguong "am hon" | "giu nguyen"
    theta1: float              # nguong "giu nguyen" | "mat hon"
    t_ref: float = 26.0
    h_ref: float = 60.0
    shift: float = 0.0         # lech ca nhan (do C)
    scale: float = 1.0         # do nhay ca nhan, keo gian quanh diem trung tinh

    @property
    def _center(self) -> float:
        return (self.theta0 + self.theta1) / 2.0

    def _raw(self, ta: float, rh: float) -> float:
        return self.w_t * (ta - self.t_ref - self.shift) + self.w_h * (rh - self.h_ref) / 10.0

    def z(self, ta: float, rh: float) -> float:
        # Keo gian quanh diem trung tinh: doi scale khong lam doi nhiet do trung tinh
        return self._center + self.scale * (self._raw(ta, rh) - self._center)

    def proba(self, ta: float, rh: float) -> tuple[float, float, float]:
        """Xac suat (am hon, giu nguyen, mat hon)."""
        z = self.z(ta, rh)
        c0 = _sigmoid(self.theta0 - z)
        c1 = _sigmoid(self.theta1 - z)
        return c0, max(0.0, c1 - c0), 1.0 - c1

    def _temp_at(self, z_target: float, rh: float) -> float:
        raw = self._center + (z_target - self._center) / self.scale
        return self.t_ref + self.shift + (raw - self.w_h * (rh - self.h_ref) / 10.0) / self.w_t

    def neutral_temp(self, rh: float) -> float:
        """Nhiet do ma 'muon am hon' va 'muon mat hon' can bang: muc nhiet nguoi nay thich nhat."""
        return self._temp_at((self.theta0 + self.theta1) / 2.0, rh)

    def comfort_band(self, rh: float, p: float = BAND_P) -> tuple[float, float]:
        """Khoang nhiet do ma xac suat 'muon am hon' va 'muon mat hon' deu khong qua `p`."""
        k = math.log((1 - p) / p)
        return self._temp_at(self.theta0 + k, rh), self._temp_at(self.theta1 - k, rh)

    def setpoint(self, rh: float, lo: int, hi: int) -> int:
        """Nhiet do dat goi y: muc AM NHAT ma van trong vung de chiu (tiet kiem dien), trong [lo, hi]."""
        return int(min(hi, max(lo, math.floor(self.comfort_band(rh)[1] + 1e-9))))

    def log_lik(self, ta: float, rh: float, cls: int) -> float:
        return math.log(max(self.proba(ta, rh)[cls], 1e-12))

    def as_dict(self) -> dict:
        return {"w_t": self.w_t, "w_h": self.w_h, "theta0": self.theta0, "theta1": self.theta1,
                "t_ref": self.t_ref, "h_ref": self.h_ref, "shift": self.shift, "scale": self.scale}


def load_prior(path: Path = PRIOR_PATH) -> tuple[ComfortModel, dict]:
    """Doc mo hinh chung da hoc tu ASHRAE. Tra ve (mo hinh, thong tin nguon goc)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    p = data["params"]
    model = ComfortModel(p["w_t"], p["w_h"], p["theta0"], p["theta1"], p["t_ref"], p["h_ref"])
    return model, {k: v for k, v in data.items() if k != "params"}


@dataclass(frozen=True)
class Vote:
    ts: float
    cls: int        # chi so trong CLASSES
    ta: float
    rh: float


def vote_weight(vote_ts: float, now: float, half_life_days: float = HALF_LIFE_DAYS) -> float:
    age_days = max(0.0, now - vote_ts) / 86400.0
    return 0.5 ** (age_days / half_life_days)


def _objective(prior: ComfortModel, votes: list[Vote], weights: list[float], shift: float,
               log_scale: float, prior_sd: float) -> float:
    m = replace(prior, shift=shift, scale=math.exp(log_scale))
    ll = sum(w * m.log_lik(v.ta, v.rh, v.cls) for v, w in zip(votes, weights, strict=True))
    return (ll - 0.5 * (shift / prior_sd) ** 2
            - 0.5 * ((log_scale - LOG_SCALE_PRIOR_MEAN) / LOG_SCALE_PRIOR_SD) ** 2)


def _golden_max(f, lo: float, hi: float, iters: int = 60) -> float:
    g = (math.sqrt(5) - 1) / 2
    a, b = hi - g * (hi - lo), lo + g * (hi - lo)
    fa, fb = f(a), f(b)
    for _ in range(iters):
        if fa < fb:
            lo, a, fa = a, b, fb
            b = lo + g * (hi - lo)
            fb = f(b)
        else:
            hi, b, fb = b, a, fa
            a = hi - g * (hi - lo)
            fa = f(a)
    return (lo + hi) / 2


@dataclass(frozen=True)
class Personalization:
    model: ComfortModel
    shift: float            # do C
    shift_sd: float         # do khong chac chan (do lech chuan, xap xi Laplace)
    scale: float
    n_votes: int
    effective_votes: float  # tong trong so sau khi giam theo tuoi


def personalize(prior: ComfortModel, votes: list[Vote], now: float,
                prior_sd: float = SHIFT_PRIOR_SD_C,
                half_life_days: float = HALF_LIFE_DAYS) -> Personalization:
    """Uoc luong MAP cho (shift, scale).

    Voi moi scale tren luoi, ham muc tieu lom theo shift -> tim lat cat vang; chon cap tot nhat.
    """
    weights = [vote_weight(v.ts, now, half_life_days) for v in votes]
    if not votes:
        return Personalization(prior, 0.0, prior_sd, 1.0, 0, 0.0)

    best = None
    for ls in LOG_SCALE_GRID:
        sh = _golden_max(lambda x, ls=ls: _objective(prior, votes, weights, x, ls, prior_sd),
                         -SHIFT_LIMIT_C, SHIFT_LIMIT_C)
        val = _objective(prior, votes, weights, sh, ls, prior_sd)
        if best is None or val > best[0]:
            best = (val, sh, ls)
    _, shift, ls = best

    def f(x: float) -> float:
        return _objective(prior, votes, weights, x, ls, prior_sd)

    h = 1e-3
    curv = (f(shift + h) - 2 * f(shift) + f(shift - h)) / (h * h)
    sd = math.sqrt(-1.0 / curv) if curv < 0 else prior_sd
    model = replace(prior, shift=shift, scale=math.exp(ls))
    return Personalization(model, shift, sd, math.exp(ls), len(votes), sum(weights))


# ------------------------------------------------------------------ goi y hanh dong
NONE, TURN_ON, SET_TEMP, TURN_OFF = "none", "turn_on", "set_temp", "turn_off"

TURN_ON_P_COOLER = 0.6          # chi goi y bat khi kha chac nguoi dung muon mat hon
EMPTY_BEFORE_OFF_S = 15 * 60    # phong trong lien tuc bao lau thi moi goi y tat


@dataclass(frozen=True)
class Situation:
    node_online: bool
    telemetry_fresh: bool
    ta: float | None
    rh: float | None
    presence: bool | None
    empty_for_s: float | None   # phong trong lien tuc bao lau (None = khong biet / dang co nguoi)
    ac_power: str | None        # "on" / "off" / None = chua biet
    ac_mode: str | None
    ac_temp: int | None
    ac_fan: str | None


@dataclass(frozen=True)
class Advice:
    action: str
    reason: str
    target: dict | None = None  # power/mode/temp/fan neu co hanh dong


def advise(model: ComfortModel, s: Situation, auto_min: int, auto_max: int) -> Advice:
    """Quy tac chon hanh dong tu du doan. Moi hanh dong van phai qua Safety Layer khi thuc hien."""
    if not s.node_online or not s.telemetry_fresh or s.ta is None or s.rh is None:
        return Advice(NONE, "NO_DATA")
    setpoint = model.setpoint(s.rh, auto_min, auto_max)
    fan = s.ac_fan or "auto"

    if s.presence is False:
        if s.ac_power == "on" and s.empty_for_s is not None and s.empty_for_s >= EMPTY_BEFORE_OFF_S:
            return Advice(TURN_OFF, "ROOM_EMPTY_LONG",
                          {"power": "off", "mode": s.ac_mode or "cool", "temp": s.ac_temp or setpoint,
                           "fan": fan})
        return Advice(NONE, "ROOM_EMPTY")

    p_warmer, _, p_cooler = model.proba(s.ta, s.rh)
    if s.ac_power != "on":
        if p_cooler >= TURN_ON_P_COOLER:
            return Advice(TURN_ON, "TOO_WARM", {"power": "on", "mode": "cool", "temp": setpoint, "fan": fan})
        return Advice(NONE, "COMFORTABLE" if p_warmer < 0.5 else "TOO_COOL_AC_OFF")

    if s.ac_mode not in ("cool", "dry", "auto") or s.ac_temp is None:
        return Advice(NONE, "MODE_NOT_SUPPORTED")
    if setpoint == s.ac_temp:
        return Advice(NONE, "SETPOINT_OK")
    step = 1 if setpoint > s.ac_temp else -1          # Safety Layer: tu dong chi doi 1 do moi lan
    return Advice(SET_TEMP, "WARMER_SETPOINT" if step > 0 else "COOLER_SETPOINT",
                  {"power": "on", "mode": s.ac_mode, "temp": s.ac_temp + step, "fan": fan})
