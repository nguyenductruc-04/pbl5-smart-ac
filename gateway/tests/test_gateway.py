"""Unit tests for telemetry validation and database handlers (no broker needed)."""
import json
import sqlite3

import pytest

import gateway as gw
import settings


@pytest.mark.parametrize(
    "payload",
    [
        {"temp": 26.5, "hum": 60},
        {"temp": -10, "hum": 0},
        {"temp": 60, "hum": 100},
    ],
)
def test_validate_accepts_plausible(payload):
    assert gw.validate_telemetry(payload) == (True, None)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"temp": 26},
        {"temp": "26", "hum": 50},
        {"temp": 85.0, "hum": 50},
        {"temp": 25, "hum": 101},
        {"temp": -40, "hum": 50},
    ],
)
def test_validate_rejects_bad(payload):
    ok, reason = gw.validate_telemetry(payload)
    assert ok is False and reason


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_PATH", str(tmp_path / "t.db"))
    return gw.Gateway()


def rows(g, sql):
    return g.db.execute(sql).fetchall()


def test_valid_telemetry_is_stored(gateway):
    gateway.handle_telemetry("room01", 100.0, json.dumps({"temp": 27.1, "hum": 55, "sim": True, "seq": 1}))
    assert rows(gateway, "SELECT room, temp, hum, simulated, presence FROM telemetry") == [
        ("room01", 27.1, 55, 1, None)
    ]


def test_invalid_telemetry_goes_to_rejected(gateway):
    gateway.handle_telemetry("room01", 1.0, json.dumps({"temp": 99, "hum": 50}))
    gateway.handle_telemetry("room01", 2.0, "not json")
    assert rows(gateway, "SELECT COUNT(*) FROM telemetry") == [(0,)]
    assert rows(gateway, "SELECT COUNT(*) FROM rejected") == [(2,)]


def test_status_upsert(gateway):
    gateway.handle_status("room01", 1.0, "online")
    gateway.handle_status("room01", 2.0, "offline")
    assert rows(gateway, "SELECT room, status, ts FROM node_status") == [("room01", "offline", 2.0)]


def test_command_result_upsert(gateway):
    gateway.handle_result("room01", 5.0, json.dumps({"cmd_id": "c1", "ok": True}))
    assert rows(gateway, "SELECT cmd_id, ok FROM commands") == [("c1", 1)]


def test_schema_is_idempotent(tmp_path):
    p = str(tmp_path / "x.db")
    gw.open_db(p).close()
    conn = gw.open_db(p)
    assert isinstance(conn, sqlite3.Connection)
