"""Nut reset (logic, khong can GPIO) va tem thiet lap."""
import sqlite3

import accounts
import netmode
import reset_button
import setup_label
import store


def test_reset_button_clears_accounts_and_network_choice(tmp_path):
    db = tmp_path / "pbl5.db"
    conn = sqlite3.connect(db)
    store.init(conn)
    u = accounts.create_user(conn, "truc", "mat-khau-dai", accounts.ADMIN, 1.0)
    accounts.new_session(conn, u["id"], 1.0)
    conn.execute("INSERT INTO comfort_votes(ts, room, vote) VALUES (1, 'room01', 'comfortable')")
    conn.commit()
    conn.close()
    mode = tmp_path / "network_mode"
    netmode.choose_mode("home", mode)
    assert reset_button.do_reset(str(db), mode) == 1
    conn = sqlite3.connect(db)
    assert not accounts.has_admin(conn)
    assert conn.execute("SELECT COUNT(*) FROM comfort_votes").fetchone()[0] == 1
    assert not mode.exists()
    assert reset_button.do_reset(str(db), mode) == 0          # bam lai khong loi


def test_wifi_qr_escapes_special_characters():
    b = chr(92)
    got = setup_label.wifi_qr_text("SmartAC-Backup", 'a;b:c"d' + b)
    assert got == f'WIFI:T:WPA;S:SmartAC-Backup;P:a{b};b{b}:c{b}"d{b}{b};;'


def test_label_has_code_qr_and_optional_wifi_password():
    svg = setup_label.label_svg("ABCD-EFGH-JKMN", "d3v1ce00", "pass<word>")
    assert svg.startswith("<svg") and "ABCD-EFGH-JKMN" in svg and "pass&lt;word&gt;" in svg
    assert svg.count("<path") >= 2                              # hai ma QR
    blank = setup_label.label_svg("ABCD-EFGH-JKMN", "d3v1ce00", None)
    assert "______" in blank and blank.count("<path") == 1
