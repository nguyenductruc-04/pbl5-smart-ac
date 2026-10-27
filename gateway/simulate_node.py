"""
Room Node GIA LAP bang Python - dung de test Gateway khi chua nap code ESP32.
Hanh xu giong firmware: LWT status, gui telemetry, tra loi command.
Vi du:
    python simulate_node.py --room room01 --password MAT_KHAU_room01 --interval 5
"""
import argparse
import json
import math
import random
import time

import paho.mqtt.client as mqtt

import settings


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--room", default="room01")
    p.add_argument("--password", required=True, help="mat khau MQTT cua user = room")
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()

    base = f"home/{args.room}"

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print("Ket noi that bai:", reason_code)
            return
        client.publish(f"{base}/status", "online", qos=1, retain=True)
        client.subscribe(f"{base}/command", 1)
        print("Node gia lap da ket noi")

    def on_message(client, userdata, msg):
        cmd = json.loads(msg.payload)
        print("RX command:", cmd)
        res = {"cmd_id": cmd.get("cmd_id"), "ok": True, "ir_sent": False, "note": "simulated node"}
        client.publish(f"{base}/command_result", json.dumps(res), qos=1)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{args.room}")
    c.username_pw_set(args.room, args.password)
    c.will_set(f"{base}/status", "offline", qos=1, retain=True)
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
    c.loop_start()

    seq = 0
    try:
        while True:
            seq += 1
            data = {
                "seq": seq,
                "temp": round(28 + 1.5 * math.sin(time.time() / 600) + random.uniform(-0.1, 0.1), 2),
                "hum": round(65 + random.uniform(-5, 5), 1),
                "presence": None,
                "sim": True,
                "rssi": -55,
                "uptime_s": int(seq * args.interval),
            }
            c.publish(f"{base}/telemetry", json.dumps(data), qos=0)
            print("TX telemetry:", data)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        c.publish(f"{base}/status", "offline", qos=1, retain=True).wait_for_publish(2)
        c.loop_stop()


if __name__ == "__main__":
    main()
