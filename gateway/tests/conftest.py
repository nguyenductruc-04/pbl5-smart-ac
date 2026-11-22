"""Fixture dung chung: Gateway voi MQTT gia (khong can broker) va mot "node gia" tra loi lenh."""
import json

import pytest

import gateway as gw
import settings


class FakeMqttClient:
    """Thay cho paho Client. `node` quyet dinh node gia phan hoi lenh the nao."""

    def __init__(self, *args, **kwargs):
        self.connected = True
        self.published = []          # [(topic, payload_dict)]
        self.config = []             # [(topic, payload_dict, retain)] gui toi home/<room>/config
        self.node = "ok"             # "ok" | "silent" | "error"
        self.gateway = None
        self.clock = None

    def username_pw_set(self, *a, **k): ...
    def reconnect_delay_set(self, *a, **k): ...

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload, qos=0, retain=False):
        cmd = json.loads(payload)
        if topic.endswith("/config"):                 # ban tin cau hinh / bao doi mang: khong tra loi
            self.config.append((topic, cmd, retain))
            return
        self.published.append((topic, cmd))
        room = topic.split("/")[1]
        if self.node == "silent":
            return
        res = {"cmd_id": cmd["cmd_id"], "ok": self.node == "ok", "ir_sent": self.node == "ok"}
        if self.node == "error":
            res["error"] = "protocol_not_supported"
        self.gateway.handle_result(room, self.clock(), json.dumps(res))


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def gateway(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(settings, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "IR_PROTOCOL", "")
    monkeypatch.setattr(gw.mqtt, "Client", FakeMqttClient)
    g = gw.Gateway()
    g.client.gateway = g
    g.client.clock = clock
    return g
