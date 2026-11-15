"""
Gui Wi-Fi nha moi xuong Room Node qua MQTT (topic home/<room>/config) va cho config_result.

Mat khau duoc hoi bang getpass (khong hien tren man hinh, khong nam trong lich su lenh).
Ban tin duoc gui dang RETAINED: node dang offline (vd. dang o mang du phong) se nhan khi ket noi lai.
Nhan duoc ket qua thi xoa ban tin retained ngay (mat khau khong nam lai tren broker).

Vi du:
    python push_wifi.py --room room01 --ssid "Mai"
    python push_wifi.py --room room01 --clear      # xoa cau hinh dang cho tren broker
"""
import argparse
import getpass
import json
import sys
import threading
import uuid

import paho.mqtt.client as mqtt

import settings


def validate(ssid: str, password: str) -> str | None:
    """Cung quy tac voi firmware (handleConfig). Tra ve ma loi hoac None."""
    if not 1 <= len(ssid.encode()) <= 32:
        return "bad_ssid"
    if password and not 8 <= len(password) <= 63:
        return "bad_password_length"
    return None


def build_payload(cfg_id: str, ssid: str, password: str) -> str:
    return json.dumps({"cfg_id": cfg_id, "wifi": {"ssid": ssid, "pass": password}})


def main() -> None:
    p = argparse.ArgumentParser(description="Gui Wi-Fi nha moi xuong Room Node")
    p.add_argument("--room", required=True)
    p.add_argument("--ssid", help="ten Wi-Fi nha moi")
    p.add_argument("--timeout", type=float, default=90.0, help="cho config_result toi da (giay)")
    p.add_argument("--clear", action="store_true", help="chi xoa ban tin cau hinh retained")
    args = p.parse_args()

    t_cfg = f"home/{args.room}/config"
    t_res = f"home/{args.room}/config_result"

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)

    if args.clear:
        c.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
        c.loop_start()
        c.publish(t_cfg, b"", qos=1, retain=True).wait_for_publish(5)
        c.loop_stop()
        c.disconnect()
        print(f"Da xoa cau hinh retained tren {t_cfg}")
        return

    if not args.ssid:
        sys.exit("Can --ssid (hoac --clear)")
    password = getpass.getpass(f"Mat khau Wi-Fi '{args.ssid}' (de trong neu mang mo): ")
    err = validate(args.ssid, password)
    if err:
        sys.exit(f"Cau hinh khong hop le: {err}")

    cfg_id = "w-" + uuid.uuid4().hex[:8]
    payload = build_payload(cfg_id, args.ssid, password)
    got = threading.Event()
    result = {}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print("Ket noi broker that bai:", reason_code)
            got.set()
            return
        client.subscribe(t_res, 1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        client.publish(t_cfg, payload, qos=1, retain=True)
        print(f"-> {t_cfg}: cfg_id={cfg_id}, ssid='{args.ssid}' (dang cho node thu ket noi...)")

    def on_message(client, userdata, msg):
        data = json.loads(msg.payload)
        if data.get("cfg_id") == cfg_id:
            result.update(data)
            got.set()

    c.on_connect, c.on_subscribe, c.on_message = on_connect, on_subscribe, on_message
    c.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
    c.loop_start()
    got.wait(args.timeout)

    if result:
        c.publish(t_cfg, b"", qos=1, retain=True).wait_for_publish(5)   # xoa mat khau khoi broker
    c.loop_stop()
    c.disconnect()

    if not result:
        print(f"Chua nhan ket qua sau {args.timeout:.0f}s. Neu node da chuyen sang Wi-Fi moi ma Pi chua o mang do,"
              " ket qua se den sau. Cau hinh van cho tren broker; xoa bang --clear.")
        sys.exit(1)
    if result.get("ok"):
        print(f"<- OK: node da ket noi va luu Wi-Fi '{result.get('ssid')}'")
    else:
        print(f"<- THAT BAI: {result.get('error')} (node giu Wi-Fi cu)")
        sys.exit(2)


if __name__ == "__main__":
    main()
