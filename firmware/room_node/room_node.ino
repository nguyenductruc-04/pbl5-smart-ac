// =====================================================================
//  PBL5 - Room Node (ESP32-S3) - v0.5.0
//  - Wi-Fi nha luu trong NVS; mat Wi-Fi nha -> chuyen sang mang du phong SmartAC-Backup (do Pi phat),
//    dinh ky thu quay ve Wi-Fi nha. Nhan Wi-Fi nha moi tu Pi qua home/<room>/config
//  - Tat modem sleep, tu ket noi lai khi mat mang
//  - Tim broker qua mDNS (gateway.local), co IP du phong
//  - MQTT co Last Will (home/<room>/status = offline, retained)
//  - Doc nhiet do / do am tu SHT3x (SHT30/31/35) hoac SHT4x qua I2C
//  - Doc cam bien hien dien LD2420 qua chan OUT; doi trang thai thi gui telemetry ngay
//  - Nhan lenh tai home/<room>/command -> PHAT IR toi dieu hoa,
//    tra ket qua tai home/<room>/command_result
//  - Nghe len remote goc -> gui home/<room>/ir_event
//
//  Thu vien (Arduino Library Manager):
//    - PubSubClient (Nick O'Leary)
//    - ArduinoJson (Benoit Blanchon) phien ban 7.x
//    - Adafruit SHT31 Library va Adafruit SHT4x Library (cai kem cac thu vien phu thuoc)
//    - IRremoteESP8266 (2.9.0)
//  Board core: esp32 by Espressif 2.0.17 (ban 3.x chua tuong thich IRremoteESP8266)
// =====================================================================
#include <WiFi.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <IRremoteESP8266.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <IRac.h>

// Gia tri cho CLIMATE_SENSOR trong config.h
#define SENSOR_SHT3X 3
#define SENSOR_SHT4X 4
#include "config.h"

#define FW_VERSION "0.10.0"

// config.h cu (truoc v0.5.0) chua co cac muc duoi day -> dung mac dinh va bao tren Serial luc khoi dong
// (Arduino IDE mac dinh tat canh bao bien dich nen #warning khong hien)
#ifndef CLIMATE_SENSOR
#define CONFIG_OUTDATED 1
#define CLIMATE_SENSOR SENSOR_SHT3X
#endif
#ifndef CLIMATE_I2C_ADDR
#define CLIMATE_I2C_ADDR 0x44
#endif
#ifndef CLIMATE_SIM_FALLBACK
#define CLIMATE_SIM_FALLBACK 0
#endif
#ifndef PRESENCE_OUT_PIN
#define CONFIG_OUTDATED 1
#define PRESENCE_OUT_PIN -1
#endif
#ifndef PRESENCE_TX_PIN
#define PRESENCE_TX_PIN -1
#endif

#if CLIMATE_SENSOR == SENSOR_SHT3X
#include <Adafruit_SHT31.h>
Adafruit_SHT31 sht;
#define CLIMATE_NAME "SHT3x"
#elif CLIMATE_SENSOR == SENSOR_SHT4X
#include <Adafruit_SHT4x.h>
Adafruit_SHT4x sht;
#define CLIMATE_NAME "SHT4x"
#else
#error "CLIMATE_SENSOR phai la SENSOR_SHT3X hoac SENSOR_SHT4X"
#endif

// ----------------------- Topic -----------------------
const String T_TELEMETRY = String("home/") + ROOM_ID + "/telemetry";
const String T_COMMAND   = String("home/") + ROOM_ID + "/command";
const String T_RESULT    = String("home/") + ROOM_ID + "/command_result";
const String T_STATUS    = String("home/") + ROOM_ID + "/status";
const String T_IR_EVENT  = String("home/") + ROOM_ID + "/ir_event";
const String T_CONFIG    = String("home/") + ROOM_ID + "/config";
const String T_CFG_RES   = String("home/") + ROOM_ID + "/config_result";

WiFiClient    net;
PubSubClient  mqtt(net);

// IR
IRac            irac(IR_TX_PIN);
IRrecv          irrecv(IR_RX_PIN, 1024, 50, true);  // buffer 1024, timeout 50 ms (khung A/C dai)
decode_results  irResults;
stdAc::state_t  acState;          // trang thai DU KIEN cua dieu hoa (IR mot chieu, khong xac nhan duoc)
unsigned long   lastIrTx = 0;

// Cam bien nhiet do / do am
bool          climateOk      = false;
uint8_t       climateFails   = 0;      // so lan doc loi lien tiep
unsigned long lastClimateTry = 0;      // lan cuoi thu khoi dong lai cam bien
// Cam bien hien dien LD2420 (xem docs/hardware/sensors.md)
bool          presenceRaw    = false;  // muc logic vua doc
unsigned long presenceRawAt  = 0;      // muc logic doi lan cuoi luc nao
bool          presence       = false;  // da loc nhieu (on dinh >= 300 ms)
bool          presenceAlive  = false;  // cam bien con song (chan TX con len muc cao)
unsigned long aliveSince     = 0;      // song lai tu luc nao
bool          presenceKnown  = false;  // da qua thoi gian cho LD2420 on dinh sau khi song lai
bool          txSeenHigh     = false;  // da tung thay chan TX o muc cao
uint16_t      txLowCount     = 0;      // so lan doc lien tiep chan TX o muc thap
unsigned long txLowSince     = 0;
bool          presenceWarned = false;
bool          presenceDirty  = false;  // trang thai doi, can gui telemetry som
unsigned long lastPresencePub = 0;
unsigned long lastTelemetry  = 0;
unsigned long lastMqttTry    = 0;
float         lastValidTemp  = NAN;
int           rejectStreak   = 0;
uint32_t      seq            = 0;
IPAddress     brokerIp;
bool          mdnsStarted    = false;

// Wi-Fi (xem docs/adr/0001-node-wifi-provisioning.md)
Preferences   prefs;
String        homeSsid, homePass, lastCfgId;   // doc tu NVS
bool          lastNetBackup  = false;           // lan ket noi thanh cong gan nhat la mang du phong? (NVS)
bool          onBackup       = false;           // dang o mang du phong SmartAC-Backup?
char          netHint        = 0;               // Pi bao truoc sap doi mang: 'b' = sang mang rieng, 'h' = ve nha
unsigned long netHintAt      = 0;
unsigned long lastHintTry    = 0;
const unsigned long NET_HINT_DELAY_MS = 15000;  // Pi doi mang trong vong ~15 s sau khi bao
const unsigned long NET_HINT_RETRY_MS = 20000;
const unsigned long NET_HINT_TTL_MS   = 180000; // qua 3 phut chua theo duoc -> bo, quay ve cach cu
unsigned long lastHomeTry    = 0;
volatile uint8_t lastDiscReason = 0;           // ly do mat ket noi Wi-Fi (driver bao)
unsigned long brokerLostSince = 0;              // co Wi-Fi nha nhung khong toi duoc broker tu luc nao
// Cau hinh Wi-Fi moi nhan tu Pi: xu ly trong loop(), KHONG xu ly trong callback MQTT
bool          cfgPending     = false;
String        cfgId, cfgSsid, cfgPass;
String        pendingCfgResult;                 // gui khi MQTT ket noi lai

// ------------------------------------------------------------------
// NVS: Wi-Fi nha. Lan dau (NVS trong) lay tu config.h
void loadWifiConfig() {
  prefs.begin("pbl5", true);
  homeSsid  = prefs.getString("home_ssid", WIFI_SSID);
  homePass  = prefs.getString("home_pass", WIFI_PASS);
  lastCfgId = prefs.getString("last_cfg", "");
  lastNetBackup = prefs.getBool("last_backup", false);
  prefs.end();
}

// Nho mang vua ket noi thanh cong: lan khoi dong sau thu mang do TRUOC (v0.10.0).
// Mang di thu nghiem chi co Pi phat Wi-Fi -> khoi dong la vao ngay, khong mat ~20 s cho Wi-Fi nha.
void rememberNetwork(bool backup) {
  onBackup = backup;
  if ((backup && netHint == 'b') || (!backup && netHint == 'h')) netHint = 0;   // da theo xong
  if (backup == lastNetBackup) return;           // khong ghi flash khi khong doi
  lastNetBackup = backup;
  prefs.begin("pbl5", false);
  prefs.putBool("last_backup", backup);
  prefs.end();
}

void saveWifiConfig() {
  prefs.begin("pbl5", false);
  prefs.putString("home_ssid", homeSsid);
  prefs.putString("home_pass", homePass);
  prefs.putString("last_cfg", lastCfgId);
  prefs.end();
}

// Chi xoa Wi-Fi; GIU last_cfg de cau hinh cu con retained tren broker khong bi ap dung lai sau khi reset
void clearWifiConfig() {
  prefs.begin("pbl5", false);
  prefs.remove("home_ssid");
  prefs.remove("home_pass");
  prefs.end();
}

void startMdnsOnce() {
  if (mdnsStarted) return;
  mdnsStarted = MDNS.begin(ROOM_ID);
  Serial.printf("[mDNS] %s\n", mdnsStarted ? "OK, ten = " ROOM_ID ".local" : "Khoi dong that bai");
}

// Ly do thuong gap (esp_wifi_types.h): 15/204 = sai mat khau (handshake), 201 = khong thay mang,
// 202 = xac thuc that bai, 2 = auth het han
void onWifiDisconnected(arduino_event_id_t event, arduino_event_info_t info) {
  lastDiscReason = info.wifi_sta_disconnected.reason;
}

// Mang co dang phat quanh day khong (quet ~2-3 s, khong ngat ket noi hien tai)
bool ssidVisible(const char *ssid) {
  int n = WiFi.scanNetworks();
  bool found = false;
  for (int i = 0; i < n && !found; i++) found = (WiFi.SSID(i) == ssid);
  WiFi.scanDelete();
  return found;
}

// Quet xem mang co dang phat khong (chi goi khi ket noi that bai, mat ~2-3 s)
void reportScan(const char *ssid) {
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i) == ssid) {
      Serial.printf("[WiFi]   '%s' CO phat: kenh %d, RSSI %d dBm, bao mat %d\n",
                    ssid, WiFi.channel(i), WiFi.RSSI(i), (int)WiFi.encryptionType(i));
      WiFi.scanDelete();
      return;
    }
  }
  Serial.printf("[WiFi]   KHONG thay '%s' (quet duoc %d mang)\n", ssid, n);
  WiFi.scanDelete();
}

bool tryWifi(const char *ssid, const char *pass, uint32_t timeoutMs) {
  Serial.printf("[WiFi] Thu ket noi '%s' ...\n", ssid);
  WiFi.disconnect();
  // Cho ngat han mang cu (ngat ket noi la bat dong bo) truoc khi sang mang moi
  unsigned long t0 = millis();
  while (WiFi.status() == WL_CONNECTED && millis() - t0 < 2000) delay(50);
  lastDiscReason = 0;
  WiFi.begin(ssid, pass);
  unsigned long start = millis(), lastBegin = millis();
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(250);
    // Lan dau sau khi bat nguon ESP32 hay that bai som (vd. ly do 2 = auth het han).
    // Driver da tat tu ket noi lai, nen tu goi lai toi da 2 lan trong thoi gian cho.
    wl_status_t st = WiFi.status();
    if ((st == WL_DISCONNECTED || st == WL_CONNECT_FAILED) && lastDiscReason != 0 &&
        retries < 2 && millis() - lastBegin > 2000) {
      retries++;
      Serial.printf("[WiFi]   that bai som (ly do %u) -> thu lai lan %d\n", lastDiscReason, retries);
      lastDiscReason = 0;
      WiFi.disconnect();
      delay(100);
      WiFi.begin(ssid, pass);
      lastBegin = millis();
    }
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[WiFi] That bai '%s' (status %d, ly do %u)\n", ssid, (int)WiFi.status(), lastDiscReason);
    reportScan(ssid);
    return false;
  }
  Serial.printf("[WiFi] OK '%s', IP = %s, RSSI = %d dBm\n", ssid,
                WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

bool tryBackup() {
  if (strlen(BACKUP_SSID) == 0 || !tryWifi(BACKUP_SSID, BACKUP_PASS, WIFI_CONNECT_TIMEOUT_MS)) return false;
  rememberNetwork(true);
  lastHomeTry = millis();
  Serial.println("[WiFi] Dang dung MANG DU PHONG");
  return true;
}

bool tryHome() {
  if (!tryWifi(homeSsid.c_str(), homePass.c_str(), WIFI_CONNECT_TIMEOUT_MS)) return false;
  rememberNetwork(false);
  return true;
}

// Thu mang thanh cong lan truoc TRUOC, roi moi den mang con lai.
// Mac dinh (lan dau, hoac lan truoc o nha): Wi-Fi nha truoc, mang du phong cua Pi sau.
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);   // tu quan ly viec chon mang; tranh driver tu noi lai mang cu
  WiFi.setSleep(false);   // tat modem sleep: giam do tre nhan lenh (v0.1.1)
  bool backupFirst = netHint ? netHint == 'b' : lastNetBackup;   // Pi vua bao truoc thi theo loi bao
  bool ok = backupFirst ? (tryBackup() || tryHome()) : (tryHome() || tryBackup());
  if (!ok) return;   // loop() se goi lai
  startMdnsOnce();
}

// Dang o mang du phong: co nen thu quay ve Wi-Fi nha khong? (v0.10.0)
// - Dang noi duoc broker -> O LAI. Pi chi co mot card Wi-Fi: khi Pi phat mang du phong thi Pi (va broker)
//   khong o tren Wi-Fi nha, ve nha chi lam mat ket noi. Khi Pi ve nha, Pi tat mang du phong -> node mat
//   Wi-Fi -> connectWiFi() tu tim lai (thu mang cu truoc, roi Wi-Fi nha).
// - Mat broker qua WIFI_HOME_RETRY_MS: quet truoc, chi roi mang du phong khi THAY Wi-Fi nha.
// Truoc ban nay node roi mang du phong moi 5 phut de thu, mat ket noi ~30 s moi lan.
void maybeReturnHome() {
  if (!onBackup) return;
  if (mqtt.connected()) { lastHomeTry = millis(); return; }
  if (millis() - lastHomeTry < WIFI_HOME_RETRY_MS) return;
  lastHomeTry = millis();
  if (!ssidVisible(homeSsid.c_str())) {
    Serial.printf("[WiFi] Khong thay '%s' quanh day -> o lai mang du phong\n", homeSsid.c_str());
    return;
  }
  Serial.println("[WiFi] Thay Wi-Fi nha -> thu quay ve");
  mqtt.disconnect();
  if (!tryHome()) tryBackup();   // that bai ca hai thi loop() tu xu ly
}

// Pi bao truoc "sap sang mang rieng" (nguoi dung doi che do tren dashboard, v0.10.0):
// doi Pi doi mang (~15 s) roi chu dong sang mang du phong, khong cho mat broker 120 s.
void maybeFollowHint() {
  if (!netHint) return;
  unsigned long age = millis() - netHintAt;
  if (age > NET_HINT_TTL_MS) { netHint = 0; return; }
  if (netHint != 'b' || onBackup) return;
  if (age < NET_HINT_DELAY_MS || millis() - lastHintTry < NET_HINT_RETRY_MS) return;
  lastHintTry = millis();
  Serial.println("[NET] Di theo Pi sang mang du phong");
  mqtt.disconnect();
  if (!tryBackup()) tryHome();   // Pi chua kip phat -> ve tam Wi-Fi nha, 20 s sau thu lai
}

// Co Wi-Fi nha nhung khong toi duoc broker qua lau (vd. Pi mat Wi-Fi nha va da bat AP du phong,
// trong khi router van song) -> "di theo Pi": thu sang mang du phong
void maybeFollowGateway() {
  if (onBackup || strlen(BACKUP_SSID) == 0) { brokerLostSince = 0; return; }
  if (brokerLostSince == 0) brokerLostSince = millis();
  unsigned long lost = millis() - brokerLostSince;
  Serial.printf("[WiFi] Mat broker %lus / %lus (sau do thu mang du phong)\n",
                lost / 1000, (unsigned long)(WIFI_BROKER_LOST_MS / 1000));
  if (lost < WIFI_BROKER_LOST_MS) return;
  brokerLostSince = 0;
  Serial.println("[WiFi] Khong toi duoc broker tren Wi-Fi nha -> thu mang du phong");
  if (!tryBackup()) tryHome();
}

// Ap dung Wi-Fi nha moi: THU TRUOC, thanh cong moi luu; that bai thi quay lai mang cu
void applyPendingConfig() {
  cfgPending = false;
  Serial.printf("[CFG] cfg_id=%s: thu Wi-Fi moi '%s'\n", cfgId.c_str(), cfgSsid.c_str());
  mqtt.disconnect();

  JsonDocument res;
  res["cfg_id"] = cfgId;
  res["ssid"]   = cfgSsid;            // KHONG bao gio gui lai mat khau
  if (tryWifi(cfgSsid.c_str(), cfgPass.c_str(), WIFI_CONNECT_TIMEOUT_MS)) {
    homeSsid = cfgSsid;
    homePass = cfgPass;
    rememberNetwork(false);
    res["ok"] = true;
    Serial.println("[CFG] Thanh cong -> da luu Wi-Fi nha moi");
  } else {
    res["ok"]    = false;
    res["error"] = "connect_failed";
    Serial.println("[CFG] That bai -> giu Wi-Fi cu");
    WiFi.disconnect();
    connectWiFi();
  }
  lastCfgId = cfgId;                   // luu ca khi that bai: khong thu lai cung mot cau hinh
  saveWifiConfig();
  cfgPass = "";

  pendingCfgResult = "";
  serializeJson(res, pendingCfgResult);   // gui khi MQTT ket noi lai (co the o mang khac)
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
  mqtt.subscribe(T_CONFIG.c_str(), 1);
  Serial.printf("[MQTT] OK, da subscribe %s va %s\n", T_COMMAND.c_str(), T_CONFIG.c_str());
  if (pendingCfgResult.length()) {
    mqtt.publish(T_CFG_RES.c_str(), pendingCfgResult.c_str());
    Serial.printf("[CFG] Gui ket qua: %s\n", pendingCfgResult.c_str());
    pendingCfgResult = "";
  }
  return true;
}

// ------------------------------------------------------------------
// Khoi dong cam bien nhiet do / do am. Tra ve false neu khong thay.
bool beginClimate() {
#if CLIMATE_SENSOR == SENSOR_SHT3X
  if (!sht.begin(CLIMATE_I2C_ADDR)) return false;
  sht.heater(false);                         // bo gia nhiet lam sai so do
#else
  if (!sht.begin(&Wire)) return false;
  sht.setPrecision(SHT4X_HIGH_PRECISION);
  sht.setHeater(SHT4X_NO_HEATER);
#endif
  return true;
}

bool readSensor(float &t, float &h) {
#if CLIMATE_SENSOR == SENSOR_SHT3X
  return sht.readBoth(&t, &h);               // false neu loi I2C hoac sai CRC
#else
  sensors_event_t hum, temp;
  if (!sht.getEvent(&hum, &temp)) return false;
  t = temp.temperature;
  h = hum.relative_humidity;
  return true;
#endif
}

// Cam bien mat (long day, mat nguon) -> thu khoi dong lai moi 30 s
void maybeRetryClimate() {
  if (climateOk || millis() - lastClimateTry < 30000) return;
  lastClimateTry = millis();
  climateOk = beginClimate();
  if (climateOk) {
    climateFails = 0;
    Serial.println("[SENSOR] Da tim lai cam bien " CLIMATE_NAME);
  }
}

// Doc nhiet do / do am. Tra ve false neu khong co so do de gui.
bool readClimate(float &t, float &h, bool &simulated) {
  simulated = false;
  if (climateOk) {
    if (readSensor(t, h)) {
      climateFails = 0;
      return true;
    }
    if (++climateFails >= 3) {
      climateOk = false;
      lastClimateTry = millis();
      Serial.println("[SENSOR] " CLIMATE_NAME " loi 3 lan lien tiep -> coi nhu mat cam bien, se thu lai");
    }
    return false;
  }
#if CLIMATE_SIM_FALLBACK
  // Du lieu gia lap de test duong truyen khi chua lap cam bien (sim=true, gateway luu rieng)
  t = 28.0 + 1.5 * sin(millis() / 600000.0) + random(-10, 11) / 100.0;
  h = 65.0 + random(-50, 51) / 10.0;
  simulated = true;
  return true;
#else
  return false;   // KHONG gui du lieu gia: tranh lan vao du lieu that dung de huan luyen AI
#endif
}

// ------------------------------------------------------------------
// LD2420: chan OUT muc cao = co nguoi. Goi lien tuc trong loop(), ke ca khi mat mang.
// Chan TX cua LD2420 (UART, nghi o muc cao) chi duoc doc muc logic de biet cam bien con song:
// khong noi / mat nguon thi chan nay bi keo xuong thap -> bao presence = null thay vi "khong co nguoi".
void pollPresence() {
#if PRESENCE_OUT_PIN >= 0
  unsigned long now = millis();
#if PRESENCE_TX_PIN >= 0
  // UART dang song chi o muc thap vai chuc micro giay moi bit. Mat nguon / tuot day: thap LIEN TUC.
  // Can ca so lan doc lien tiep LAN thoi gian, de mot lan doc trung bit 0 (vd. ngay sau khi loop bi
  // chan vi ket noi Wi-Fi) khong bi tinh la mat cam bien.
  if (digitalRead(PRESENCE_TX_PIN) == HIGH) {
    txSeenHigh = true;
    txLowCount = 0;
  } else {
    if (txLowCount == 0) txLowSince = now;
    if (txLowCount < 65535) txLowCount++;
  }
  bool alive = txSeenHigh && !(txLowCount >= 10 && now - txLowSince >= 100);
#else
  bool alive = true;
#endif
  if (alive != presenceAlive) {
    presenceAlive = alive;
    aliveSince = now;
    presenceKnown = false;
    presenceDirty = true;
    Serial.println(alive ? "[PRESENCE] LD2420 hoat dong, cho 3 s de on dinh"
                         : "[PRESENCE] Mat tin hieu LD2420 (kiem tra day, nguon 3V3) -> presence = null");
  }
  if (!alive) {
    if (!presenceWarned && !txSeenHigh && now > 5000) {
      presenceWarned = true;
      Serial.println("[PRESENCE] Khong thay tin hieu LD2420 -> presence = null");
    }
    return;   // mat cam bien: KHONG cap nhat presence, tranh bao nham "khong co nguoi"
  }

  bool raw = digitalRead(PRESENCE_OUT_PIN) == HIGH;
  if (raw != presenceRaw) {
    presenceRaw = raw;
    presenceRawAt = now;
  }
  // LD2420 vua co nguon lai: chan OUT o muc thap ~1 s truoc khi phat hien -> cho 3 s roi moi bao
  if (!presenceKnown) {
    if (now - aliveSince < 3000) return;
    presenceKnown = true;
    presence = presenceRaw;
    presenceDirty = true;
    Serial.printf("[PRESENCE] %s\n", presence ? "CO NGUOI" : "khong co nguoi");
    return;
  }
  if (now - presenceRawAt >= 300 && presence != presenceRaw) {
    presence = presenceRaw;
    presenceDirty = true;
    Serial.printf("[PRESENCE] %s\n", presence ? "CO NGUOI" : "khong co nguoi");
  }
#endif
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
  presenceDirty = false;
  if (!readClimate(t, h, sim)) {
    Serial.println("[SENSOR] Khong co so do nhiet do / do am -> bo qua lan gui nay");
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
  if (PRESENCE_OUT_PIN >= 0 && presenceAlive && presenceKnown) doc["presence"] = presence;
  else                                         doc["presence"] = nullptr;   // khong co / mat cam bien
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
// Nhan lenh dieu khien tu Gateway
void handleCommand(byte* payload, unsigned int len) {
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
// Nhan cau hinh Wi-Fi tu Pi: {"cfg_id":"...","wifi":{"ssid":"...","pass":"..."}}
// hoac loi bao truoc doi mang: {"net":"backup"} / {"net":"home"} (v0.10.0)
void handleConfig(byte* payload, unsigned int len) {
  if (len == 0) return;                       // Pi vua xoa ban tin retained
  JsonDocument doc;
  if (deserializeJson(doc, (const char*)payload, len)) {
    Serial.println("[CFG] JSON loi -> bo qua");
    return;
  }
  String net = doc["net"] | "";
  if (net.length()) {
    if (net == "backup" || net == "home") {
      netHint = net[0];
      netHintAt = millis();
      lastHintTry = 0;
      Serial.printf("[NET] Pi bao sap %s\n", netHint == 'b' ? "phat mang rieng -> se di theo" : "ve Wi-Fi nha");
    }
    return;
  }
  String id   = doc["cfg_id"] | "";
  String ssid = doc["wifi"]["ssid"] | "";
  String pass = doc["wifi"]["pass"] | "";
  if (id.length() && id == lastCfgId) {
    Serial.printf("[CFG] cfg_id=%s da xu ly truoc do -> bo qua\n", id.c_str());
    return;
  }

  const char *error = nullptr;
  if (id.length() == 0)                                    error = "missing_cfg_id";
  else if (ssid.length() < 1 || ssid.length() > 32)        error = "bad_ssid";
  else if (pass.length() != 0 && (pass.length() < 8 || pass.length() > 63)) error = "bad_password_length";

  if (error) {
    JsonDocument res;
    res["cfg_id"] = id;
    res["ok"]     = false;
    res["error"]  = error;
    char buf[160];
    size_t n = serializeJson(res, buf, sizeof(buf));
    mqtt.publish(T_CFG_RES.c_str(), (const uint8_t*)buf, n, false);
    Serial.printf("[CFG] Tu choi cfg_id=%s: %s\n", id.c_str(), error);
    return;
  }
  cfgId = id; cfgSsid = ssid; cfgPass = pass;
  cfgPending = true;                          // loop() se xu ly sau khi mqtt.loop() tra ve
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  if (T_CONFIG == topic) handleConfig(payload, len);
  else                   handleCommand(payload, len);
}

// Giu nut BOOT (GPIO 0) khoang 1.5 s trong 3 s dau sau khi khoi dong -> xoa Wi-Fi da luu
void checkFactoryReset() {
  pinMode(0, INPUT_PULLUP);
  Serial.println("[CFG] Giu nut BOOT ngay bay gio (3 s) de xoa Wi-Fi da luu...");
  unsigned long t0 = millis(), held = 0;
  while (millis() - t0 < 3000) {
    if (digitalRead(0) == LOW) {
      if (!held) held = millis();
      if (millis() - held > 1500) {
        clearWifiConfig();
        Serial.println("[CFG] DA XOA Wi-Fi luu trong NVS -> dung lai gia tri trong config.h");
        return;
      }
    } else {
      held = 0;
    }
    delay(20);
  }
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1500);  // cho Serial USB san sang
  Serial.println("\n=== PBL5 Room Node " FW_VERSION " - " ROOM_ID " ===");
#ifdef CONFIG_OUTDATED
  Serial.println("[CFG] config.h CU: thieu muc cam bien (CLIMATE_SENSOR, PRESENCE_OUT_PIN...) -> dang dung mac dinh."
                 " Chep cac muc moi tu config.example.h");
#endif

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  climateOk = beginClimate();
  lastClimateTry = millis();
  if (climateOk) {
    Serial.printf("[SENSOR] Tim thay %s (dia chi 0x%02X)\n", CLIMATE_NAME, CLIMATE_I2C_ADDR);
  } else {
    Serial.printf("[SENSOR] KHONG thay %s tren SDA=%d SCL=%d -> %s\n", CLIMATE_NAME, I2C_SDA_PIN, I2C_SCL_PIN,
                  CLIMATE_SIM_FALLBACK ? "dung du lieu GIA LAP" : "khong gui telemetry, se thu lai moi 30 s");
  }

#if PRESENCE_OUT_PIN >= 0
  // Keo xuong: khong noi cam bien thi doc duoc muc thap (va chan TX bao "mat tin hieu")
  pinMode(PRESENCE_OUT_PIN, INPUT_PULLDOWN);
#if PRESENCE_TX_PIN >= 0
  pinMode(PRESENCE_TX_PIN, INPUT_PULLDOWN);
#endif
  Serial.printf("[PRESENCE] LD2420 OUT GPIO %d, TX GPIO %d\n", PRESENCE_OUT_PIN, PRESENCE_TX_PIN);
#else
  Serial.println("[PRESENCE] Tat (PRESENCE_OUT_PIN = -1)");
#endif

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

  checkFactoryReset();
  loadWifiConfig();
  Serial.printf("[WiFi] Wi-Fi nha: '%s', du phong: '%s'\n", homeSsid.c_str(), BACKUP_SSID);

  WiFi.onEvent(onWifiDisconnected, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  connectWiFi();
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  mqtt.setCallback(onMessage);
}

void loop() {
  handleIrReceive();   // nghe remote ca khi mat mang (van dong bo trang thai du kien)
  pollPresence();
  maybeRetryClimate();

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }
  maybeFollowHint();   // Pi vua bao truoc sap doi mang
  maybeReturnHome();   // dang o mang du phong -> dinh ky thu Wi-Fi nha

  if (!mqtt.connected()) {
    if (millis() - lastMqttTry > 5000) {
      lastMqttTry = millis();
      if (connectMqtt()) brokerLostSince = 0;
      else               maybeFollowGateway();
    }
    return;
  }
  brokerLostSince = 0;

  mqtt.loop();

  if (cfgPending) {
    applyPendingConfig();
    return;
  }

  // Gui dinh ky, hoac gui ngay khi co nguoi vao / ra (toi da 1 lan moi giay)
  bool presenceEvent = presenceDirty && millis() - lastPresencePub >= 1000;
  if (lastTelemetry == 0 || millis() - lastTelemetry >= TELEMETRY_INTERVAL_MS || presenceEvent) {
    lastTelemetry = millis();
    if (presenceEvent) lastPresencePub = millis();
    publishTelemetry();
  }
}
