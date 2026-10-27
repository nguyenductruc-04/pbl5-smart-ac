"""Xem nhanh du lieu da luu trong database.  Chay: python show_data.py"""
import datetime as dt
import sqlite3

import settings


def fmt(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "-"


db = sqlite3.connect(settings.DB_PATH)

print("== Trang thai node ==")
for room, status, ts in db.execute("SELECT room, status, ts FROM node_status ORDER BY room"):
    print(f"  {room:8} {status:8} luc {fmt(ts)}")

print("\n== 10 telemetry gan nhat ==")
rows = db.execute("SELECT room, ts, temp, hum, simulated, rssi FROM telemetry ORDER BY id DESC LIMIT 10")
for room, ts, t, h, sim, rssi in rows:
    print(f"  {fmt(ts)} {room:8} {t:6.2f} C  {h:5.1f} %  rssi={rssi} {'(gia lap)' if sim else ''}")

print("\n== 5 lenh gan nhat ==")
rows = db.execute(
    "SELECT cmd_id, room, ts_sent, ts_result, ok FROM commands"
    " ORDER BY COALESCE(ts_sent, ts_result) DESC LIMIT 5"
)
for cmd_id, room, ts_sent, ts_res, ok in rows:
    lat = f"{(ts_res - ts_sent) * 1000:.0f} ms" if ts_sent and ts_res else "-"
    verdict = "OK" if ok else ("LOI" if ok is not None else "chua co")
    print(f"  {cmd_id} {room:8} gui {fmt(ts_sent)} ket qua {verdict} ({lat})")

n_rej = db.execute("SELECT COUNT(*) FROM rejected").fetchone()[0]
print(f"\nSo ban tin bi loai bo: {n_rej}")
