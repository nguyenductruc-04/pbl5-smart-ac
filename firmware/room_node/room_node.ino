// =====================================================================
//  PBL5 - Room Node (ESP32-S3) - Milestone 1
//  - Ket noi Wi-Fi, tu ket noi lai khi mat mang
//  - Ket noi MQTT co Last Will (home/<room>/status = offline, retained)
//  - Doc SHT41 neu co; neu chua lap cam bien thi gui du lieu GIA LAP (sim=true)
//  - Kiem tra du lieu hop le truoc khi gui
//  - Nhan lenh tai home/<room>/command, tra ket qua tai home/<room>/command_result
//    (Milestone 1 chua phat IR, chi in lenh ra Serial)
//
//  Thu vien can cai (Arduino Library Manager):
//    - PubSubClient (Nick O'Leary)
//    - ArduinoJson (Benoit Blanchon) phien ban 7.x
//    - Adafruit SHT4x Library (cai kem cac thu vien phu thuoc)
// =====================================================================
#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_SHT4x.h>
#include "config.h"

// ----------------------- Topic -----------------------
const String T_TELEMETRY = String("home/") + ROOM_ID + "/telemetry";
const String T_COMMAND   = String("home/") + ROOM_ID + "/command";
const String T_RESULT    = String("home/") + ROOM_ID + "/command_result";
const String T_STATUS    = String("home/") + ROOM_ID + "/status";

WiFiClient    net;
PubSubClient  mqtt(net);
Adafruit_SHT4x sht4;

bool          shtOk          = false;
unsigned long lastTelemetry  = 0;
unsigned long lastMqttTry    = 0;
float         lastValidTemp  = NAN;
int           rejectStreak   = 0;
uint32_t      seq            = 0;

// ------------------------------------------------------------------
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[WiFi] Dang ket noi '%s' ...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] OK, IP = %s, RSSI = %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("[WiFi] That bai, se thu lai.");
  }
}

// ------------------------------------------------------------------
bool connectMqtt() {
  String clientId = String("node-") + ROOM_ID;
  Serial.printf("[MQTT] Ket noi %s:%d voi user '%s' ...\n", MQTT_HOST, MQTT_PORT, MQTT_USER);
  // Last Will: neu node mat ket noi bat thuong, broker tu publish "offline"
  bool ok = mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS,
                         T_STATUS.c_str(), 1, true, "offline");
  if (!ok) {
    // -4 timeout, -2 khong toi duoc broker, 4 sai user/pass, 5 khong duoc phep
    Serial.printf("[MQTT] That bai, state = %d\n", mqtt.state());
    return false;
  }
  mqtt.publish(T_STATUS.c_str(), "online", true);
  mqtt.subscribe(T_COMMAND.c_str(), 1);
  Serial.printf("[MQTT] OK, da subscribe %s\n", T_COMMAND.c_str());
  return true;
}

// ------------------------------------------------------------------
// Doc nhiet do / do am. Tra ve false neu doc loi.
bool readClimate(float &t, float &h, bool &simulated) {
  if (shtOk) {
    sensors_event_t hum, temp;
    if (!sht4.getEvent(&hum, &temp)) return false;
    t = temp.temperature;
    h = hum.relative_humidity;
    simulated = false;
  } else {
    // Du lieu gia lap de test duong truyen khi chua lap cam bien
    t = 28.0 + 1.5 * sin(millis() / 600000.0) + random(-10, 11) / 100.0;
    h = 65.0 + random(-50, 51) / 10.0;
    simulated = true;
  }
  return true;
}

// Kiem tra du lieu hop le: trong mien vat ly va khong nhay dot bien
bool isValid(float t, float h) {
  if (isnan(t) || isnan(h))       return false;
  if (t < -10.0 || t > 60.0)      return false;
  if (h < 0.0   || h > 100.0)     return false;
  if (!isnan(lastValidTemp) && fabs(t - lastValidTemp) > 5.0) {
    // Nhay > 5 do trong 1 chu ky la bat thuong. Neu lap lai 3 lan lien tiep
    // thi coi day la thay doi that va chap nhan lai moc moi.
    if (++rejectStreak < 3) return false;
  }
  rejectStreak = 0;
  return true;
}

// ------------------------------------------------------------------
void publishTelemetry() {
  float t, h;
  bool sim;
  if (!readClimate(t, h, sim)) {
    Serial.println("[SENSOR] Doc cam bien loi");
    return;
  }
  if (!isValid(t, h)) {
    Serial.printf("[SENSOR] Bo qua gia tri khong hop le: t=%.2f h=%.2f\n", t, h);
    return;
  }
  lastValidTemp = t;

  JsonDocument doc;
  doc["seq"]      = ++seq;
  doc["temp"]     = round(t * 100) / 100.0;
  doc["hum"]      = round(h * 10) / 10.0;
  doc["presence"] = nullptr;          // se dung LD2410 o milestone 3
  doc["sim"]      = sim;
  doc["rssi"]     = WiFi.RSSI();
  doc["uptime_s"] = millis() / 1000;

  char buf[256];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  bool ok = mqtt.publish(T_TELEMETRY.c_str(), (const uint8_t*)buf, n, false);
  Serial.printf("[TX] %s %s\n", buf, ok ? "" : "(GUI LOI)");
}

// ------------------------------------------------------------------
// Nhan lenh tu Gateway
void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument cmd;
  // Ep kieu const char* de ArduinoJson COPY chuoi (bo dem payload se bi ghi de khi publish)
  DeserializationError err = deserializeJson(cmd, (const char*)payload, len);

  JsonDocument res;
  if (err) {
    res["cmd_id"] = nullptr;
    res["ok"]     = false;
    res["error"]  = "bad_json";
  } else {
    char id[48];
    strlcpy(id, cmd["cmd_id"] | "", sizeof(id));
    const char* power = cmd["power"] | "?";
    const char* mode  = cmd["mode"]  | "?";
    int         temp  = cmd["temp"]  | -1;
    const char* fan   = cmd["fan"]   | "?";

    Serial.printf("[RX] cmd_id=%s power=%s mode=%s temp=%d fan=%s\n",
                  id, power, mode, temp, fan);

    // TODO Milestone 2: dung IRremoteESP8266 (IRDaikinESP / bien the phu hop) de phat IR
    res["cmd_id"]  = id;
    res["ok"]      = true;
    res["ir_sent"] = false;
    res["note"]    = "milestone1: chua phat IR";
  }

  char buf[200];
  size_t n = serializeJson(res, buf, sizeof(buf));
  mqtt.publish(T_RESULT.c_str(), (const uint8_t*)buf, n, false);
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1500);  // cho Serial USB san sang
  Serial.println("\n=== PBL5 Room Node - " ROOM_ID " ===");

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  shtOk = sht4.begin(&Wire);
  if (shtOk) {
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
    Serial.println("[SENSOR] Tim thay SHT4x");
  } else {
    Serial.println("[SENSOR] Khong thay SHT4x -> dung du lieu GIA LAP");
  }

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }

  if (!mqtt.connected()) {
    if (millis() - lastMqttTry > 5000) {
      lastMqttTry = millis();
      connectMqtt();
    }
    return;
  }

  mqtt.loop();

  if (lastTelemetry == 0 || millis() - lastTelemetry >= TELEMETRY_INTERVAL_MS) {
    lastTelemetry = millis();
    publishTelemetry();
  }
}
