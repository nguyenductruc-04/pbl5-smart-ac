// =====================================================================
//  PBL5 - Room Node config
//  Copy file nay thanh config.h (da nam trong .gitignore) roi sua gia tri that.
// =====================================================================
#pragma once

// --- Wi-Fi (chi ho tro bang tan 2.4 GHz) ---
#define WIFI_SSID      "YOUR_WIFI_SSID"
#define WIFI_PASS      "YOUR_WIFI_PASSWORD"

// --- MQTT broker (Raspberry Pi) ---
// Ten mDNS cua Raspberry Pi (hostname, KHONG kem ".local"). ESP32 tu tim IP moi lan ket noi.
#define MQTT_HOSTNAME      "gateway"
// IP du phong khi mang chan mDNS (vd. mot so hotspot dien thoai). De "" neu khong dung.
#define MQTT_HOST_FALLBACK "10.42.0.1"
#define MQTT_PORT      1883

// --- Dinh danh phong ---
// ROOM_ID dong thoi la username MQTT (ACL tren broker dung %u = ROOM_ID).
#define ROOM_ID        "room01"
#define MQTT_USER      ROOM_ID
#define MQTT_PASS      "YOUR_MQTT_PASSWORD"

// --- Chu ky gui telemetry ---
#define TELEMETRY_INTERVAL_MS  30000UL   // 30 giay

// --- Chan I2C cho cam bien SHT41 (doi neu ban noi chan khac) ---
#define I2C_SDA_PIN    8
#define I2C_SCL_PIN    9

// --- IR (xem docs/hardware/ir-circuit.md) ---
#define IR_TX_PIN      4          // LED IR qua transistor 2N2222A
#define IR_RX_PIN      5          // TSOP38238 OUT
// Giao thuc dieu hoa (ten trong IRremoteESP8266: DAIKIN, DAIKIN2, DAIKIN216, DAIKIN64...).
// Khi co may that: bam remote goc, xem truong "protocol" trong ir_event roi sua dong nay.
#define IR_PROTOCOL    DAIKIN
#define IR_MODEL       -1         // -1 = mac dinh cua giao thuc
#define IR_TEMP_MIN    16         // gioi han nhiet do chap nhan tu lenh MQTT (do C)
#define IR_TEMP_MAX    30
#define IR_BLANKING_MS 300UL      // bo qua tin hieu IR thu duoc ngay sau khi tu phat
