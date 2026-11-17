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
PRESENCE = {None: "-", 0: "khong", 1: "CO"}
rows = db.execute("SELECT room, ts, temp, hum, presence, simulated, rssi FROM telemetry ORDER BY id DESC LIMIT 10")
for room, ts, t, h, presence, sim, rssi in rows:
    print(f"  {fmt(ts)} {room:8} {t:6.2f} C  {h:5.1f} %  nguoi={PRESENCE[presence]:5} rssi={rssi}"
          f" {'(gia lap)' if sim else ''}")

print("\n== Du lieu that da thu (khong tinh gia lap) ==")
for room, n, first, last, n_presence in db.execute(
    "SELECT room, COUNT(*), MIN(ts), MAX(ts), COUNT(presence) FROM telemetry WHERE simulated = 0 GROUP BY room"
):
    days = (last - first) / 86400
    print(f"  {room:8} {n} ban ghi trong {days:.1f} ngay, {n_presence} ban ghi co du lieu hien dien")

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

print("\n== 5 lan bam remote goc gan nhat (ir_event) ==")
rows = db.execute("SELECT ts, room, protocol, power, mode, temp, fan FROM ir_events ORDER BY id DESC LIMIT 5")
for ts, room, proto, power, mode, temp, fan in rows:
    print(f"  {fmt(ts)} {room:8} {proto} power={power} mode={mode} temp={temp} fan={fan}")
