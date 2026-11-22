"""
Che do mang cua Pi, dung chung giua REST API (doi che do tu dashboard) va netwatch.py (thuc hien).

- Che do mac dinh: NETWORK_MODE trong gateway/.env.
- Dashboard doi che do -> API ghi file `network_mode` (ben canh database). netwatch doc lai moi vong
  kiem tra (15 s) nen khong can khoi dong lai dich vu. Xoa file = quay ve mac dinh trong .env.
- netwatch ghi `network_status.json` moi vong: che do dang chay, trang thai Wi-Fi, mang dang dung.
  API doc file nay de dashboard hien thi; file cu qua STATUS_STALE_S = netwatch khong chay.

Xem docs/adr/0006-field-network-and-device-pairing.md.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

AUTO, STANDALONE, HOME_ONLY = "auto", "standalone", "home"
MODES = (AUTO, STANDALONE, HOME_ONLY)
STATUS_STALE_S = 60.0

_DIR = Path(__file__).resolve().parent
MODE_FILE = _DIR / "network_mode"
STATUS_FILE = _DIR / "network_status.json"


def normalize(mode: str | None) -> str | None:
    mode = (mode or "").strip().lower()
    return mode if mode in MODES else None


def default_mode() -> str:
    """Che do trong .env (hoac bien moi truong). Gia tri la -> auto."""
    import settings  # doc gateway/.env
    return normalize(os.getenv("NETWORK_MODE", settings.NETWORK_MODE)) or AUTO


def chosen_mode(path: Path | None = None) -> str | None:
    """Che do nguoi dung chon tren dashboard, None neu chua chon (hoac file hong)."""
    try:
        return normalize((path or MODE_FILE).read_text(encoding="utf-8"))
    except OSError:
        return None


def effective_mode(path: Path | None = None) -> str:
    return chosen_mode(path) or default_mode()


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)          # netwatch (root) va API (nguoi dung thuong) deu doc duoc
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def choose_mode(mode: str, path: Path | None = None) -> None:
    mode = normalize(mode)
    if mode is None:
        raise ValueError(f"che do mang khong hop le, phai la mot trong {MODES}")
    _write_atomic(path or MODE_FILE, mode + "\n")


def write_status(status: dict, path: Path | None = None) -> None:
    _write_atomic(path or STATUS_FILE, json.dumps(status))


def read_status(now: float, path: Path | None = None) -> dict | None:
    """Trang thai netwatch ghi gan nhat, kem `running` (netwatch con chay khong)."""
    try:
        data = json.loads((path or STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["running"] = isinstance(data.get("ts"), (int, float)) and 0 <= now - data["ts"] <= STATUS_STALE_S
    return data
