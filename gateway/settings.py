"""Cau hinh chung cho Gateway. Gia tri lay tu bien moi truong (file .env), co gia tri mac dinh."""
import os
from pathlib import Path

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
