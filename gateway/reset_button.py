"""Nut reset tren Raspberry Pi: giu 10 giay de xoa moi tai khoan, nhu nut reset cua san pham that.

Noi nut nhan giua GPIO 17 (chan 11) va GND (chan 9). Khong can dien tro: dung dien tro keo len ben trong.
Sau khi reset:
- moi tai khoan va phien dang nhap bi xoa; so do, nhat ky lenh, phieu cam nhan GIU NGUYEN;
- che do mang tro ve gia tri NETWORK_MODE trong .env (go lua chon tren dashboard), de khong bi
  ket o "Chi Wi-Fi nha" khi da doi router;
- dashboard / app hien lai man hinh "Thiet lap lan dau": dung ma tren tem de tao quan tri vien moi.
Ma thiet lap KHONG doi, nen tem dan cu van dung duoc.

Chay bang python he thong (gpiozero co san tren Raspberry Pi OS) qua pbl5-reset.service.
"""
from __future__ import annotations

import logging
import signal
import sqlite3
from pathlib import Path

import accounts
import netmode
import settings

HOLD_S = 10.0
BUTTON_PIN = 17

log = logging.getLogger("reset_button")


def do_reset(db_path: str, mode_file: Path | None = None) -> int:
    """Xoa tai khoan va lua chon che do mang. Tra ve so tai khoan da xoa."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        accounts.init(conn)
        removed = accounts.reset_accounts(conn)
    finally:
        conn.close()
    (mode_file or netmode.MODE_FILE).unlink(missing_ok=True)
    return removed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from gpiozero import Button  # chi co tren Pi; import o day de test chay duoc tren may tinh

    button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05, hold_time=HOLD_S)

    def held() -> None:
        n = do_reset(settings.DB_PATH)
        log.warning("Nut reset giu %.0f s: da xoa %d tai khoan. Mo dashboard de thiet lap lai.", HOLD_S, n)

    button.when_pressed = lambda: log.info("Nut reset duoc nhan, giu %.0f giay de xoa tai khoan", HOLD_S)
    button.when_held = held
    log.info("Cho nut reset o GPIO %d (giu %.0f s)", BUTTON_PIN, HOLD_S)
    signal.pause()


if __name__ == "__main__":
    main()
