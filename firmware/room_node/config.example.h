// =====================================================================
//  PBL5 - Room Node config
//  Copy file nay thanh config.h (da nam trong .gitignore) roi sua gia tri that.
// =====================================================================
#pragma once

// --- Wi-Fi (chi ho tro bang tan 2.4 GHz) ---
#define WIFI_SSID      "YOUR_WIFI_SSID"
#define WIFI_PASS      "YOUR_WIFI_PASSWORD"

// --- MQTT broker (Raspberry Pi) ---
// Dung dia chi IP cua Pi (vi du 192.168.1.50). Nen dat IP tinh / DHCP reservation tren router.
#define MQTT_HOST      "192.168.1.50"
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
