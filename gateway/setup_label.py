"""In tem dan len Pi: ma thiet lap + QR cho app, va QR vao Wi-Fi du phong.

    cd ~/pbl5-smart-ac/gateway
    .venv/bin/python setup_label.py                 # hoi mat khau Wi-Fi du phong (Enter de bo qua)
    .venv/bin/python setup_label.py --ap-pass ...   # hoac truyen thang

Tao file setup_label.svg (khoang 70 x 45 mm) de in, va in QR ra terminal. KHONG chay bang sudo:
file ma thiet lap phai thuoc user chay gateway. Tem chua bi mat: ai co tem va vao duoc mang cua Pi thi
tao duoc quan tri vien khi Pi chua co chu (hoac vua reset). Dan tem o mat duoi / ben trong hop Pi.
"""
from __future__ import annotations

import argparse
import getpass
import html
import io
import os
import sys
from pathlib import Path

import segno

import accounts

AP_SSID = "SmartAC-Backup"
BACKSLASH = chr(92)
SPECIAL = BACKSLASH + ';,:"'   # ky tu phai thoat trong chuoi WIFI:
OUT = Path(__file__).resolve().parent / "setup_label.svg"


def wifi_qr_text(ssid: str, password: str) -> str:
    """Chuoi QR chuan de camera dien thoai tu vao Wi-Fi."""
    esc = lambda s: "".join(BACKSLASH + c if c in SPECIAL else c for c in s)   # noqa: E731
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def qr_svg(text: str, size: float) -> str:
    """Ma QR vuong canh `size` don vi cua tem (le trang 2 o)."""
    qr = segno.make(text, error="m")
    buf = io.BytesIO()
    scale = size / qr.symbol_size(border=2)[0]
    qr.save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=False)
    return buf.getvalue().decode()


def label_svg(code: str, dev_id: str, ap_pass: str | None) -> str:
    """Tem 70 x 45 mm (don vi 1 = 0.1 mm)."""
    t = html.escape
    setup = qr_svg(accounts.setup_uri(code, dev_id), 290)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="70mm" height="45mm" viewBox="0 0 700 450" '
        'font-family="DejaVu Sans, Arial, sans-serif">',
        '<rect x="2" y="2" width="696" height="446" rx="18" fill="#fff" stroke="#000" stroke-width="3"/>',
        f'<g transform="translate(18 50)">{setup}</g>',
        '<text x="32" y="44" font-size="24" font-weight="700">Quét bằng app để thiết lập</text>',
    ]
    x = 330
    parts += [
        f'<text x="{x}" y="70" font-size="24">Mã thiết lập</text>',
        f'<text x="{x}" y="112" font-size="38" font-weight="700" font-family="DejaVu Sans Mono, monospace">'
        f'{t(code)}</text>',
        f'<text x="{x}" y="150" font-size="20">Thiết bị {t(dev_id)}</text>',
        f'<text x="{x}" y="215" font-size="24">Wi-Fi dự phòng</text>',
        f'<text x="{x}" y="250" font-size="26" font-weight="700">{t(AP_SSID)}</text>',
    ]
    if ap_pass:
        parts.append(f'<text x="{x}" y="285" font-size="22">Mật khẩu: {t(ap_pass)}</text>')
        parts.append(f'<g transform="translate({x + 205} 282)">{qr_svg(wifi_qr_text(AP_SSID, ap_pass), 145)}</g>')
        parts.append(f'<text x="{x}" y="340" font-size="18">Quét mã bên phải</text>')
        parts.append(f'<text x="{x}" y="364" font-size="18">để vào Wi-Fi này</text>')
    else:
        parts.append(f'<text x="{x}" y="290" font-size="22">Mật khẩu: ______________</text>')
    parts += [
        '<text x="30" y="425" font-size="18">Quên mật khẩu quản trị: giữ nút reset 10 giây.</text>',
        "</svg>",
    ]
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ap-pass", help="mat khau Wi-Fi SmartAC-Backup (de in len tem)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        sys.exit("Dung chay bang sudo: file ma thiet lap phai thuoc user chay gateway (vd. truc0404).")
    code, dev = accounts.setup_code(), accounts.device_id()
    ap_pass = args.ap_pass
    if ap_pass is None and sys.stdin.isatty():
        ap_pass = getpass.getpass(f"Mat khau Wi-Fi {AP_SSID} de in len tem (Enter de bo qua): ") or None
    args.out.write_text(label_svg(code, dev, ap_pass), encoding="utf-8")
    os.chmod(args.out, 0o600)
    print(f"Ma thiet lap: {code}   (thiet bi {dev})")
    segno.make(accounts.setup_uri(code, dev), error="m").terminal(compact=True)
    print(f"Da ghi tem: {args.out}  (mo bang trinh duyet roi in, kich thuoc that 70 x 45 mm)")
    print("Tem chua ma bi mat: dung gui anh tem len mang, xoa file sau khi in.")


if __name__ == "__main__":
    main()
