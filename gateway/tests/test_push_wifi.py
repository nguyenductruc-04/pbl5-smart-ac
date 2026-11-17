"""Unit tests cho push_wifi (khong can broker)."""
import json

from push_wifi import build_payload, validate


def test_validate_accepts_normal_and_open_networks():
    assert validate("Mai", "12345678") is None
    assert validate("Mai", "") is None                   # mang mo
    assert validate("x" * 32, "p" * 63) is None


def test_validate_rejects_bad_values():
    assert validate("", "12345678") == "bad_ssid"
    assert validate("x" * 33, "12345678") == "bad_ssid"
    assert validate("Mai", "1234567") == "bad_password_length"
    assert validate("Mai", "p" * 64) == "bad_password_length"


def test_validate_counts_ssid_bytes_not_characters():
    assert validate("Nhà" * 10, "12345678") == "bad_ssid"   # 30 ky tu nhung 40 byte UTF-8


def test_payload_shape_matches_firmware():
    data = json.loads(build_payload("w-1", "Mai", "secret123"))
    assert data == {"cfg_id": "w-1", "wifi": {"ssid": "Mai", "pass": "secret123"}}
