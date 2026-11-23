"""Cau hinh chung cho Gateway. Gia tri lay tu bien moi truong (file .env), co gia tri mac dinh."""
import os
from pathlib import Path

from safety import Policy

BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    """Doc file .env dang KEY=VALUE (khong ghi de bien moi truong da co)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "gateway")
MQTT_PASS = os.getenv("MQTT_PASS", "")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "pbl5.db"))

# Mang cua Pi (netwatch.py): auto | standalone | home. Xem docs/adr/0006-field-network-and-device-pairing.md
NETWORK_MODE = os.getenv("NETWORK_MODE", "auto")

# Giao thuc IR mac dinh khi node chua bao giao thuc dang dung (firmware < 0.11.0). Tu 0.11.0 node bao qua
# telemetry va doi duoc tren dashboard / app (irproto.py). De trong = chap nhan moi remote dieu hoa.
IR_PROTOCOL = os.getenv("IR_PROTOCOL", "")

# --- REST API ---
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
# Khoa cho app/dashboard (lenh cua nguoi dung) va khoa rieng cho dich vu tu dong (luat, AI).
# Nguon lenh duoc suy ra tu KHOA, khong tin vao noi dung request -> AI khong the gia lam nguoi dung.
API_KEY = os.getenv("API_KEY", "")
API_KEY_AUTOMATION = os.getenv("API_KEY_AUTOMATION", "")
# Dia chi truy cap tu xa qua Cloudflare Tunnel (vd. https://ac.ductruc.site). De trong = chi dung trong mang nha.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
COMMAND_TIMEOUT_S = float(os.getenv("COMMAND_TIMEOUT_S", "5"))

# --- Goi y (M6) ---
# 1 = tu dong ap dung goi y (nguon "ai", van qua Safety Layer). Mac dinh TAT: chi goi y tren dashboard.
ADVISOR_AUTO = os.getenv("ADVISOR_AUTO", "0") == "1"
ADVISOR_INTERVAL_S = float(os.getenv("ADVISOR_INTERVAL_S", "60"))


def _policy_from_env() -> Policy:
    """Cho phep ghi de tung tham so Safety Layer bang bien moi truong SAFETY_<TEN_IN_HOA>."""
    base = Policy()
    overrides = {}
    for name, default in vars(base).items():
        raw = os.getenv("SAFETY_" + name.upper())
        if raw is not None:
            overrides[name] = type(default)(raw)
    return Policy(**overrides)


POLICY = _policy_from_env()
