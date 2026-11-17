// =====================================================================
//  PBL5 - Room Node config
//  Copy file nay thanh config.h (da nam trong .gitignore) roi sua gia tri that.
// =====================================================================
#pragma once

// --- Wi-Fi nha (chi ho tro bang tan 2.4 GHz) ---
// Chi dung o lan khoi dong DAU TIEN. Sau do node dung Wi-Fi luu trong NVS (Pi co the gui Wi-Fi moi
// qua MQTT). Muon quay lai gia tri nay: giu nut BOOT ~2 s ngay sau khi node khoi dong.
#define WIFI_SSID      "YOUR_WIFI_SSID"
#define WIFI_PASS      "YOUR_WIFI_PASSWORD"

// --- Wi-Fi du phong do Pi phat khi mat Wi-Fi nha (xem docs/SETUP.vi.md, Buoc 6) ---
#define BACKUP_SSID    "SmartAC-Backup"
#define BACKUP_PASS    "YOUR_BACKUP_AP_PASSWORD"
#define WIFI_CONNECT_TIMEOUT_MS 15000UL    // cho moi mang toi da bao lau
#define WIFI_HOME_RETRY_MS      300000UL   // dang o mang du phong, bao lau thu Wi-Fi nha mot lan
#define WIFI_BROKER_LOST_MS     120000UL   // co Wi-Fi nha nhung mat broker bao lau thi thu mang du phong

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

// --- Cam bien nhiet do / do am (I2C), xem docs/hardware/sensors.md ---
// SENSOR_SHT3X: SHT30 / SHT31 / SHT35 (module GY-SHT3x-D)   SENSOR_SHT4X: SHT40 / SHT41 / SHT45
#define CLIMATE_SENSOR   SENSOR_SHT3X
#define CLIMATE_I2C_ADDR 0x44     // SHT3x: 0x44 khi chan ADDR de trong hoac noi GND, 0x45 khi noi VCC
#define I2C_SDA_PIN      8
#define I2C_SCL_PIN      9
// 1 = khong thay cam bien thi gui du lieu GIA LAP (sim=true), chi de thu duong truyen.
// 0 = khong gui gi. Dung 0 khi thu du lieu that cho AI de khong lan du lieu gia.
#define CLIMATE_SIM_FALLBACK 0

// --- Cam bien hien dien HLK-LD2420 (CHI cap 3.3 V) ---
// Noi OT1 -> GPIO 6, OT2 -> GPIO 7. Chan nao la OUT (co nguoi) tuy phien ban firmware cua LD2420:
//   firmware >= 1.5.3: OT2 = OUT, OT1 = TX  ->  OUT 7, TX 6 (mac dinh duoi day)
//   firmware <  1.5.3: OT1 = OUT, OT2 = TX  ->  OUT 6, TX 7
// Chay firmware/tools/sensor_check de biet chac. Dat PRESENCE_OUT_PIN -1 neu chua lap cam bien.
#define PRESENCE_OUT_PIN 7
#define PRESENCE_TX_PIN  6        // chi doc muc logic de biet cam bien con song; -1 = khong kiem tra

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
