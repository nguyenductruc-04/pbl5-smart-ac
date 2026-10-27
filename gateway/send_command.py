"""
Gui mot lenh thu toi Room Node va cho command_result.
Vi du:
    python send_command.py --room room01 --power on --mode cool --temp 26 --fan auto
"""
import argparse
import json
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

import settings
from gateway import open_db


def main():
    p = argparse.ArgumentParser(description="Gui lenh dieu khien thu")
    p.add_argument("--room", required=True)
    p.add_argument("--power", choices=["on", "off"], default="on")
    p.add_argument("--mode", choices=["cool", "dry", "fan", "auto", "heat"], default="cool")
    p.add_argument("--temp", type=int, default=26)
    p.add_argument("--fan", choices=["auto", "low", "mid", "high"], default="auto")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()

    if not 16 <= args.temp <= 32:
        sys.exit("Nhiet do phai trong khoang 16-32")

    cmd = {
        "cmd_id": "c-" + uuid.uuid4().hex[:8],
        "power": args.power,
        "mode": args.mode,
        "temp": args.temp,
        "fan": args.fan,
        "source": "cli",
        "ts": int(time.time()),
    }
    payload = json.dumps(cmd)
    t_cmd = f"home/{args.room}/command"
    t_res = f"home/{args.room}/command_result"

    got = threading.Event()
    result = {}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print("Ket noi broker that bai:", reason_code)
            got.set()
            return
        client.subscribe(t_res, 1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        client.publish(t_cmd, payload, qos=1)
        result["t0"] = time.perf_counter()
        print(f"-> {t_cmd}: {payload}")

    def on_message(client, userdata, msg):
        data = json.loads(msg.payload)
        if data.get("cmd_id") == cmd["cmd_id"]:
            result["data"] = data
            result["dt_ms"] = (time.perf_counter() - result["t0"]) * 1000
            got.set()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)
    c.on_connect, c.on_subscribe, c.on_message = on_connect, on_subscribe, on_message

    db = open_db(settings.DB_PATH)
    db.execute("INSERT INTO commands(cmd_id, room, ts_sent, source, payload) VALUES (?,?,?,?,?)",
               (cmd["cmd_id"], args.room, time.time(), "cli", payload))
    db.commit()

    c.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
    c.loop_start()
    got.wait(args.timeout)
    c.loop_stop()
    c.disconnect()

    if "data" in result:
        print(f"<- command_result sau {result['dt_ms']:.0f} ms: {json.dumps(result['data'], ensure_ascii=False)}")
    else:
        print(f"Khong nhan duoc command_result trong {args.timeout}s (node offline?)")
        sys.exit(1)


if __name__ == "__main__":
    main()
