// =====================================================================
//  PBL5 - Kiem tra cam bien truoc khi nap firmware chinh (xem docs/hardware/sensors.md)
//
//  1. Quet I2C, doc thu SHT3x (0x44 / 0x45)
//  2. LD2420: tim xem GPIO 6 / GPIO 7 chan nao la OUT (co nguoi), chan nao la TX (UART),
//     roi nghe UART o 115200 va 256000 de doan phien ban firmware va che do bao cao
//  3. Chay mai: in nhiet do / do am moi 2 s va moi lan trang thai "co nguoi" thay doi
//
//  Noi day: SHT3x VIN->3V3, GND, SDA->GPIO 8, SCL->GPIO 9
//           LD2420 3V3->3V3 (KHONG dung 5V), GND, OT1->GPIO 6, OT2->GPIO 7, RX de trong
//  Thu vien: Adafruit SHT31 Library. Serial Monitor 115200.
// =====================================================================
#include <Wire.h>
#include <Adafruit_SHT31.h>

const int SDA_PIN = 8, SCL_PIN = 9;
const int PIN_A = 6;          // noi OT1
const int PIN_B = 7;          // noi OT2

Adafruit_SHT31 sht;
bool shtOk = false;
int outPin = -1, txPin = -1;

// Khai bao kieu TRUOC moi ham: Arduino IDE tu chen prototype ham ngay truoc ham dau tien,
// neu kieu khai bao sau do thi prototype bao loi "'PinStats' was not declared".
struct PinStats { uint32_t edges = 0, high = 0, total = 0; };

// ------------------------------------------------------------------ I2C
void checkI2c() {
  Serial.println("\n--- 1. I2C ---");
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  Thay thiet bi o 0x%02X%s\n", a, (a == 0x44 || a == 0x45) ? "  (dia chi cua SHT3x / SHT4x)" : "");
      found++;
    }
  }
  if (!found) {
    Serial.println("  KHONG thay thiet bi nao. Kiem tra: VIN/GND, SDA<->GPIO 8, SCL<->GPIO 9 (co bi dao khong?).");
    return;
  }
  for (uint8_t addr : {0x44, 0x45}) {
    if (sht.begin(addr)) {
      shtOk = true;
      sht.heater(false);
      Serial.printf("  SHT3x tra loi o 0x%02X, thanh ghi trang thai 0x%04X\n", addr, sht.readStatus());
      for (int i = 0; i < 3; i++) {
        float t, h;
        if (sht.readBoth(&t, &h)) Serial.printf("  Doc thu: %.2f C  %.1f %%RH\n", t, h);
        else                      Serial.println("  Doc thu: LOI (I2C hoac CRC)");
        delay(500);
      }
      return;
    }
  }
  Serial.println("  Co thiet bi I2C nhung khong phai SHT3x (neu la SHT4x: dat CLIMATE_SENSOR SENSOR_SHT4X).");
}

// ------------------------------------------------------------------ LD2420: chan nao la chan nao
void sample(PinStats &a, PinStats &b, uint32_t ms) {
  int la = digitalRead(PIN_A), lb = digitalRead(PIN_B);
  uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    int va = digitalRead(PIN_A), vb = digitalRead(PIN_B);
    a.edges += (va != la); b.edges += (vb != lb);
    a.high += va; b.high += vb;
    a.total++; b.total++;
    la = va; lb = vb;
  }
}

void identifyLd2420() {
  Serial.println("\n--- 2. LD2420: tim chan OUT va chan TX (10 giay) ---");
  Serial.println("  Hay DI CHUYEN truoc cam bien trong luc do (cach 1-2 m).");
  pinMode(PIN_A, INPUT_PULLDOWN);
  pinMode(PIN_B, INPUT_PULLDOWN);
  PinStats a, b;
  for (int s = 1; s <= 10; s++) {
    PinStats sa, sb;
    sample(sa, sb, 1000);
    Serial.printf("  %2d s | GPIO %d (OT1): muc cao %3u%%, %5u lan doi muc | GPIO %d (OT2): muc cao %3u%%, %5u lan doi muc\n",
                  s, PIN_A, sa.high * 100 / sa.total, sa.edges, PIN_B, sb.high * 100 / sb.total, sb.edges);
    a.edges += sa.edges; a.high += sa.high; a.total += sa.total;
    b.edges += sb.edges; b.high += sb.high; b.total += sb.total;
  }
  // UART nghi o muc cao va doi muc lien tuc khi gui du lieu; chan OUT gan nhu khong doi muc
  bool aUart = a.edges > 50 && a.edges > 10 * (b.edges + 1);
  bool bUart = b.edges > 50 && b.edges > 10 * (a.edges + 1);
  if (bUart)      { txPin = PIN_B; outPin = PIN_A; }
  else if (aUart) { txPin = PIN_A; outPin = PIN_B; }

  if (a.high == 0 && b.high == 0) {
    Serial.println("  => Ca hai chan luon o muc thap: LD2420 chua co nguon hoac chua noi day. Kiem tra 3V3/GND.");
  } else if (outPin < 0) {
    Serial.println("  => Chua phan biet duoc (khong chan nao co du lieu UART). Di chuyen truoc cam bien roi nhan RESET.");
  } else {
    Serial.printf("  => TX (UART) la GPIO %d, OUT (co nguoi) la GPIO %d\n", txPin, outPin);
    Serial.printf("     Dat trong config.h:  #define PRESENCE_OUT_PIN %d   va   #define PRESENCE_TX_PIN %d\n", outPin, txPin);
  }
}

// ------------------------------------------------------------------ LD2420: nghe UART
int listenUart(uint32_t baud, uint8_t *buf, int cap) {
  Serial1.begin(baud, SERIAL_8N1, txPin, -1);
  int n = 0;
  uint32_t t0 = millis();
  while (millis() - t0 < 3000) {
    while (Serial1.available()) {
      int c = Serial1.read();
      if (n < cap) buf[n] = c;
      n++;
    }
  }
  Serial1.end();
  return n;
}

bool contains(const uint8_t *buf, int n, const uint8_t *pat, int m) {
  for (int i = 0; i + m <= n; i++) if (!memcmp(buf + i, pat, m)) return true;
  return false;
}

void sniffUart() {
  if (txPin < 0) return;
  Serial.println("\n--- 3. LD2420: nghe UART (moi toc do 3 giay) ---");
  // Dinh dang theo driver ESPHome ld2420: che do co ban in chu "ON"/"OFF"/"Range xxx",
  // che do nang luong gui khung nhi phan bat dau bang F4 F3 F2 F1
  static const uint8_t ENERGY_HDR[] = {0xF4, 0xF3, 0xF2, 0xF1};
  static uint8_t buf[256];
  for (uint32_t baud : {115200UL, 256000UL}) {
    int n = listenUart(baud, buf, sizeof(buf));
    int m = min(n, (int)sizeof(buf));
    int printable = 0;
    for (int i = 0; i < m; i++) printable += (buf[i] >= 32 && buf[i] < 127) || buf[i] == '\r' || buf[i] == '\n';
    bool text = m > 8 && printable * 100 / m > 90 && (contains(buf, m, (const uint8_t *)"ON", 2) ||
                contains(buf, m, (const uint8_t *)"OFF", 3) || contains(buf, m, (const uint8_t *)"Range", 5));
    bool energy = contains(buf, m, ENERGY_HDR, 4);
    Serial.printf("  %6lu baud: nhan %d byte", (unsigned long)baud, n);
    if (text)        Serial.print("  -> DOC DUOC (che do co ban, dang chu)");
    else if (energy) Serial.print("  -> DOC DUOC (che do nang luong, khung F4 F3 F2 F1)");
    else if (n)      Serial.print("  -> khong giai ma duoc (sai toc do?)");
    Serial.println();
    if (text) {
      Serial.print("    Mau: ");
      for (int i = 0; i < min(m, 60); i++) Serial.print(buf[i] == '\r' || buf[i] == '\n' ? ' ' : (char)buf[i]);
      Serial.println();
    } else if (n) {
      Serial.print("    Mau (hex):");
      for (int i = 0; i < min(m, 24); i++) Serial.printf(" %02X", buf[i]);
      Serial.println();
    }
    if (text || energy) {
      Serial.printf("  => UART %lu baud: firmware LD2420 %s 1.5.3\n", (unsigned long)baud, baud == 115200 ? ">=" : "<");
      return;
    }
  }
  Serial.println("  => Chua giai ma duoc UART. Khong sao: firmware chinh chi dung chan OUT.");
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== PBL5 sensor_check ===");
  Wire.begin(SDA_PIN, SCL_PIN);
  checkI2c();
  identifyLd2420();
  sniffUart();
  Serial.println("\n--- 4. Theo doi lien tuc (nhiet do moi 2 s, bao ngay khi co nguoi vao / ra) ---");
}

void loop() {
  static uint32_t lastClimate = 0, changedAt = 0;
  static int lastOut = -1;
  if (outPin >= 0) {
    int v = digitalRead(outPin);
    if (v != lastOut) {
      uint32_t now = millis();
      if (lastOut >= 0) Serial.printf("[%7.1f s] %s (trang thai truoc keo dai %.1f s)\n", now / 1000.0,
                                       v ? "CO NGUOI" : "khong co nguoi", (now - changedAt) / 1000.0);
      else              Serial.printf("[%7.1f s] %s\n", now / 1000.0, v ? "CO NGUOI" : "khong co nguoi");
      lastOut = v;
      changedAt = now;
    }
  }
  if (shtOk && millis() - lastClimate >= 2000) {
    lastClimate = millis();
    float t, h;
    if (sht.readBoth(&t, &h)) Serial.printf("[%7.1f s] %.2f C  %.1f %%RH\n", millis() / 1000.0, t, h);
    else                      Serial.printf("[%7.1f s] SHT3x doc loi\n", millis() / 1000.0);
  }
  delay(5);
}
