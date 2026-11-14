// =====================================================================
//  PBL5 - Room Node (ESP32-S3) - Milestone 2
//  - Ket noi Wi-Fi (tat modem sleep), tu ket noi lai khi mat mang
//  - Tim broker qua mDNS (gateway.local), co IP du phong
//  - MQTT co Last Will (home/<room>/status = offline, retained)
//  - Doc SHT41 neu co; neu chua lap cam bien thi gui du lieu GIA LAP (sim=true)
//  - Nhan lenh tai home/<room>/command -> PHAT IR toi dieu hoa,
//    tra ket qua tai home/<room>/command_result
//  - Nghe len remote goc -> gui home/<room>/ir_event
//
//  Thu vien (Arduino Library Manager):
//    - PubSubClient (Nick O'Leary)
//    - ArduinoJson (Benoit Blanchon) phien ban 7.x
//    - Adafruit SHT4x Library (cai kem cac thu vien phu thuoc)
//    - IRremoteESP8266 (2.9.0)
//  Board core: esp32 by Espressif 2.0.17 (ban 3.x chua tuong thich IRremoteESP8266)
// =====================================================================
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_SHT4x.h>
#include <IRremoteESP8266.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <IRac.h>
#include "config.h"

// ----------------------- Topic -----------------------
const String T_TELEMETRY = String("home/") + ROOM_ID + "/telemetry";
const String T_COMMAND   = String("home/") + ROOM_ID + "/command";
const String T_RESULT    = String("home/") + ROOM_ID + "/command_result";
const String T_STATUS    = String("home/") + ROOM_ID + "/status";
const String T_IR_EVENT  = String("home/") + ROOM_ID + "/ir_event";

WiFiClient    net;
PubSubClient  mqtt(net);
Adafruit_SHT4x sht4;

// IR
IRac            irac(IR_TX_PIN);
IRrecv          irrecv(IR_RX_PIN, 1024, 50, true);  // buffer 1024, timeout 50 ms (khung A/C dai)
decode_results  irResults;
stdAc::state_t  acState;          // trang thai DU KIEN cua dieu hoa (IR mot chieu, khong xac nhan duoc)
unsigned long   lastIrTx = 0;

bool          shtOk          = false;
unsigned long lastTelemetry  = 0;
unsigned long lastMqttTry    = 0;
float         lastValidTemp  = NAN;
int           rejectStreak   = 0;
uint32_t      seq            = 0;
IPAddress     brokerIp;
bool          mdnsStarted    = false;

// ------------------------------------------------------------------
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[WiFi] Dang ket noi '%s' ...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // tat modem sleep: giam do tre nhan lenh (v0.1.1)
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
    if (!mdnsStarted) {
      mdnsStarted = MDNS.begin(ROOM_ID);
      Serial.printf("[mDNS] %s\n", mdnsStarted ? "OK, ten = " ROOM_ID ".local" : "Khoi dong that bai");
    }
  } else {
    Serial.println("[WiFi] That bai, se thu lai.");
  }
}

// ------------------------------------------------------------------
// Tim IP cua broker: uu tien mDNS (gateway.local), neu that bai thi dung IP du phong.
bool resolveBroker() {
  char host[] = MQTT_HOSTNAME;
  IPAddress ip = MDNS.queryHost(host, 2000);
  if (ip != IPAddress(0, 0, 0, 0)) {
    brokerIp = ip;
    Serial.printf("[mDNS] %s.local -> %s\n", MQTT_HOSTNAME, ip.toString().c_str());
    return true;
  }
  if (strlen(MQTT_HOST_FALLBACK) > 0 && brokerIp.fromString(MQTT_HOST_FALLBACK)) {
    Serial.printf("[mDNS] Khong tim thay %s.local, dung IP du phong %s\n",
                  MQTT_HOSTNAME, MQTT_HOST_FALLBACK);
    return true;
  }
  Serial.printf("[mDNS] Khong tim thay %s.local va khong co IP du phong\n", MQTT_HOSTNAME);
  return false;
}

// ------------------------------------------------------------------
bool connectMqtt() {
  if (!resolveBroker()) return false;
  mqtt.setServer(brokerIp, MQTT_PORT);

  String clientId = String("node-") + ROOM_ID;
  Serial.printf("[MQTT] Ket noi %s:%d voi user '%s' ...\n",
                brokerIp.toString().c_str(), MQTT_PORT, MQTT_USER);
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

// ======================= IR helpers ===============================
// Chuoi trong lenh MQTT <-> kieu chung cua IRac
bool parseMode(const char *s, stdAc::opmode_t &out) {
  if      (!strcmp(s, "cool")) out = stdAc::opmode_t::kCool;
  else if (!strcmp(s, "dry"))  out = stdAc::opmode_t::kDry;
  else if (!strcmp(s, "fan"))  out = stdAc::opmode_t::kFan;
  else if (!strcmp(s, "heat")) out = stdAc::opmode_t::kHeat;
  else if (!strcmp(s, "auto")) out = stdAc::opmode_t::kAuto;
  else return false;
  return true;
}

bool parseFan(const char *s, stdAc::fanspeed_t &out) {
  if      (!strcmp(s, "auto")) out = stdAc::fanspeed_t::kAuto;
  else if (!strcmp(s, "low"))  out = stdAc::fanspeed_t::kLow;
  else if (!strcmp(s, "mid"))  out = stdAc::fanspeed_t::kMedium;
  else if (!strcmp(s, "high")) out = stdAc::fanspeed_t::kHigh;
  else return false;
  return true;
}

const char *modeToStr(stdAc::opmode_t m) {
  switch (m) {
    case stdAc::opmode_t::kCool: return "cool";
    case stdAc::opmode_t::kDry:  return "dry";
    case stdAc::opmode_t::kFan:  return "fan";
    case stdAc::opmode_t::kHeat: return "heat";
    case stdAc::opmode_t::kAuto: return "auto";
    default:                     return "off";
  }
}

const char *fanToStr(stdAc::fanspeed_t f) {
  switch (f) {
    case stdAc::fanspeed_t::kAuto:       return "auto";
    case stdAc::fanspeed_t::kMin:
    case stdAc::fanspeed_t::kLow:        return "low";
    case stdAc::fanspeed_t::kMedium:
    case stdAc::fanspeed_t::kMediumHigh: return "mid";
    default:                             return "high";
  }
}

// Phat TOAN BO trang thai acState. Tat bo thu trong luc phat de:
//  (1) ngat cua bo thu khong lam meo song mang 38 kHz tao bang phan mem
//  (2) node khong "nghe thay" chinh minh roi tuong nguoi dung bam remote
bool sendIr() {
  irrecv.disableIRIn();
  bool ok = irac.sendAc(acState, nullptr);
  irrecv.enableIRIn();
  lastIrTx = millis();
  return ok;
}

// Nghe len remote goc. Goi lien tuc trong loop().
void handleIrReceive() {
  if (!irrecv.decode(&irResults)) return;

  // Cua so bo qua: tin hieu doi lai cua chinh node ngay sau khi phat
  if (millis() - lastIrTx < IR_BLANKING_MS) {
    irrecv.resume();
    return;
  }

  stdAc::state_t rx;
  if (IRAcUtils::decodeToState(&irResults, &rx)) {
    // Remote dieu hoa: nguoi dung vua bam -> uu tien cao nhat, dong bo trang thai du kien
    if (rx.protocol == acState.protocol) acState = rx;

    JsonDocument ev;
    ev["protocol"] = typeToString(irResults.decode_type);
    ev["power"]    = rx.power ? "on" : "off";
    ev["mode"]     = modeToStr(rx.mode);
    ev["temp"]     = (int)rx.degrees;
    ev["fan"]      = fanToStr(rx.fanspeed);
    ev["source"]   = "remote";
    ev["uptime_s"] = millis() / 1000;

    char buf[200];
    size_t n = serializeJson(ev, buf, sizeof(buf));
    bool sent = mqtt.connected() &&
                mqtt.publish(T_IR_EVENT.c_str(), (const uint8_t*)buf, n, false);
    Serial.printf("[IR RX] %s %s\n", buf, sent ? "" : "(chua gui duoc)");
  } else {
    // Khong phai remote dieu hoa (TV, quat...) -> bo qua
    Serial.printf("[IR RX] Bo qua: %s\n", typeToString(irResults.decode_type).c_str());
  }
  irrecv.resume();
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
    res["cmd_id"] = id;

    // Ap dung len BAN SAO, chi ghi vao acState khi toan bo lenh hop le
    stdAc::state_t next = acState;
    const char *error = nullptr;

    if (cmd["power"].is<const char*>()) {
      const char *p = cmd["power"];
      if      (!strcmp(p, "on"))  next.power = true;
      else if (!strcmp(p, "off")) next.power = false;
      else error = "bad_power";
    }
    if (!error && cmd["mode"].is<const char*>() && !parseMode(cmd["mode"], next.mode)) error = "bad_mode";
    if (!error && cmd["fan"].is<const char*>()  && !parseFan(cmd["fan"], next.fanspeed)) error = "bad_fan";
    if (!error && cmd["temp"].is<int>()) {
      int t = cmd["temp"];
      if (t < IR_TEMP_MIN || t > IR_TEMP_MAX) error = "temp_out_of_range";
      else next.degrees = t;
    }

    if (error) {
      res["ok"]      = false;
      res["ir_sent"] = false;
      res["error"]   = error;
      Serial.printf("[RX] cmd_id=%s TU CHOI: %s\n", id, error);
    } else {
      acState = next;
      bool sent = sendIr();
      res["ok"]      = sent;
      res["ir_sent"] = sent;
      if (!sent) res["error"] = "protocol_not_supported";
      Serial.printf("[RX] cmd_id=%s power=%s mode=%s temp=%d fan=%s -> IR %s\n", id,
                    acState.power ? "on" : "off", modeToStr(acState.mode),
                    (int)acState.degrees, fanToStr(acState.fanspeed), sent ? "DA PHAT" : "LOI");
    }
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

  // Trang thai du kien ban dau: TAT, cool 26 do, quat auto
  IRac::initState(&acState);
  acState.protocol = decode_type_t::IR_PROTOCOL;
  acState.model    = IR_MODEL;
  acState.power    = false;
  acState.mode     = stdAc::opmode_t::kCool;
  acState.degrees  = 26;
  acState.fanspeed = stdAc::fanspeed_t::kAuto;
  irrecv.enableIRIn();
  Serial.printf("[IR] Giao thuc %s, TX GPIO %d, RX GPIO %d\n",
                typeToString(acState.protocol).c_str(), IR_TX_PIN, IR_RX_PIN);

  connectWiFi();
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  mqtt.setCallback(onMessage);
}

void loop() {
  handleIrReceive();   // nghe remote ca khi mat mang (van dong bo trang thai du kien)

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
