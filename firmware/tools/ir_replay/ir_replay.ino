// =====================================================================
//  PBL5 - IR replay (ban 2, mach phat 5 V): thu tin hieu remote roi phat lai
//
//  Thu: bam remote vao mat thu (GPIO 5). Ban ghi duoc LUU VAO FLASH, nen rut
//  laptop, cam cu sac/sac du phong roi mang node di xa van con.
//
//  Khong can laptop (nut BOOT tren board):
//    Bam nhanh      = phat lai 1 lan
//    Giu >= 1 giay  = BAT/TAT che do tu phat lai moi 3 giay
//                     (dat node o xa, dung canh thiet bi xem co phan ung khong)
//    Den RGB (neu board co): XANH DUONG = vua thu duoc remote,
//      XANH LA = vua phat lai, TIM = vua bat tu phat, DO = tat tu phat/chua co ban ghi
//
//  Lenh Serial Monitor (115200, kem Enter):
//    p  phat lai y nguyen tin hieu tho
//    s  phat lai byte STATE qua thu vien (chi remote dieu hoa)
//    r  in tin hieu tho
//    t  bat/tat che do tu phat lai moi 3 giay
//    b  nhay LED IR ~2 s (soi camera)
//    h  giu LED sang 5 s de do ap tren dien tro 33 ohm (dung: ~2,8-3,4 V)
//
//  Mach: LED IR (5 V, 33 ohm) qua 2N2222A o GPIO 4, TSOP38238 o GPIO 5
//  Yeu cau: ESP32 Arduino core 2.0.17, IRremoteESP8266 2.9.0
// =====================================================================
#include <Preferences.h>
#include <IRremoteESP8266.h>
#include <IRrecv.h>
#include <IRsend.h>
#include <IRutils.h>
#include <IRac.h>

const uint16_t kIrLed       = 4;
const uint16_t kRecvPin     = 5;
const uint8_t  kBootPin     = 0;      // nut BOOT tren board
const uint16_t kRxBufSize   = 1024;   // khung dieu hoa dai
const uint8_t  kRxTimeoutMs = 50;     // ms
const uint16_t kFreqKHz     = 38;
const uint32_t kBlankMs     = 300;    // bo qua tin hieu doi lai ngay sau khi tu phat
const uint32_t kLongPressMs = 1000;
const uint32_t kAutoEveryMs = 3000;

IRrecv irrecv(kRecvPin, kRxBufSize, kRxTimeoutMs, true);
IRsend irsend(kIrLed);
decode_results results;
Preferences prefs;

uint16_t*     lastRaw    = nullptr;
uint16_t      lastRawLen = 0;
decode_type_t lastType   = decode_type_t::UNKNOWN;
uint8_t       lastState[kStateSizeMax];
uint16_t      lastBytes  = 0;
uint16_t      captures   = 0;
uint32_t      lastTx     = 0;
bool          autoMode   = false;
uint32_t      lastAuto   = 0;
uint32_t      autoCount  = 0;

void flash(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  neopixelWrite(RGB_BUILTIN, r, g, b);
  delay(300);
  neopixelWrite(RGB_BUILTIN, 0, 0, 0);
#endif
}

void printHelp() {
  Serial.println("Lenh: p = phat lai | s = phat qua thu vien | r = in raw | t = bat/tat tu phat 3 s | b = nhay LED | h = giu LED sang 5 s");
  Serial.println("Nut BOOT: bam nhanh = phat lai, giu >= 1 s = bat/tat tu phat 3 s");
}

void beginTx() { irrecv.disableIRIn(); }
void endTx()   { irrecv.enableIRIn(); lastTx = millis(); }

// ---------------------------------------------------------------- flash
void saveCapture() {
  prefs.putBytes("raw", lastRaw, lastRawLen * sizeof(uint16_t));
  prefs.putUShort("len", lastRawLen);
  prefs.putUInt("type", (uint32_t)lastType);
  prefs.putUShort("nbytes", lastBytes);
  if (lastBytes) prefs.putBytes("state", lastState, lastBytes);
}

void loadCapture() {
  uint16_t len = prefs.getUShort("len", 0);
  if (!len || len > kRxBufSize) return;
  lastRaw = new uint16_t[len];
  if (prefs.getBytes("raw", lastRaw, len * sizeof(uint16_t)) != len * sizeof(uint16_t)) {
    delete[] lastRaw; lastRaw = nullptr; return;
  }
  lastRawLen = len;
  lastType   = (decode_type_t)prefs.getUInt("type", (uint32_t)decode_type_t::UNKNOWN);
  lastBytes  = prefs.getUShort("nbytes", 0);
  if (lastBytes > kStateSizeMax || (lastBytes && prefs.getBytes("state", lastState, lastBytes) != lastBytes))
    lastBytes = 0;
  Serial.printf("Da nap ban ghi tu flash: %s, %u gia tri raw.\n", typeToString(lastType).c_str(), lastRawLen);
}

// ---------------------------------------------------------------- thu / phat
void capture() {
  if (!irrecv.decode(&results)) return;
  if (millis() - lastTx < kBlankMs) { irrecv.resume(); return; }

  captures++;
  Serial.printf("\n=== Lan bam #%u ===\n", captures);
  Serial.print(resultToHumanReadableBasic(&results));
  String desc = IRAcUtils::resultAcToString(&results);
  if (desc.length()) Serial.printf("Thu vien doc la: %s\n", desc.c_str());

  delete[] lastRaw;
  lastRaw    = resultToRawArray(&results);
  lastRawLen = getCorrectedRawLength(&results);
  lastType   = results.decode_type;
  lastBytes  = 0;
  if (hasACState(lastType)) {
    lastBytes = results.bits / 8;
    memcpy(lastState, results.state, lastBytes);
    Serial.print("STATE:");
    for (uint16_t i = 0; i < lastBytes; i++) Serial.printf(" %02X", lastState[i]);
    Serial.println();
  }
  saveCapture();
  flash(0, 0, 40);
  Serial.printf("Da luu %u gia tri raw (ca vao flash).\n", lastRawLen);
  irrecv.resume();
}

void replayRaw() {
  if (!lastRaw) { Serial.println("Chua co ban ghi. Bam remote vao mat thu truoc."); flash(40, 0, 0); return; }
  beginTx();
  irsend.sendRaw(lastRaw, lastRawLen, kFreqKHz);
  endTx();
  Serial.printf("[p] Da phat lai %u gia tri raw\n", lastRawLen);
  flash(0, 40, 0);
}

void replayState() {
  if (!lastBytes) { Serial.println("Ban ghi khong co byte STATE (khong phai remote dieu hoa da biet)."); return; }
  beginTx();
  bool ok = irsend.send(lastType, lastState, lastBytes);
  endTx();
  Serial.printf("[s] Phat %s qua thu vien: %s\n", typeToString(lastType).c_str(), ok ? "OK" : "KHONG HO TRO");
}

void printRaw() {
  if (!lastRaw) { Serial.println("Chua co ban ghi."); return; }
  Serial.printf("RAW[%u] = {", lastRawLen);
  for (uint16_t i = 0; i < lastRawLen; i++) Serial.printf(i ? ", %u" : "%u", lastRaw[i]);
  Serial.println("}");
}

void toggleAuto() {
  if (!autoMode && !lastRaw) { Serial.println("Chua co ban ghi de tu phat."); flash(40, 0, 0); return; }
  autoMode = !autoMode;
  autoCount = 0;
  lastAuto = millis();
  Serial.printf("[t] Tu phat lai moi %lu ms: %s\n", (unsigned long)kAutoEveryMs, autoMode ? "BAT" : "TAT");
  if (autoMode) flash(30, 0, 40); else flash(40, 0, 0);
}

void blink() {
  beginTx();
  for (int i = 0; i < 20; i++) { irsend.sendNEC(0x00FF00FFUL); delay(40); }
  endTx();
  Serial.println("[b] Da nhay LED. Camera phai thay chop tim/trang o dau LED.");
}

void holdOn() {
  beginTx();
  Serial.println("[h] LED SANG lien tuc 5 s: do ap giua hai dau dien tro 33 ohm ngay bay gio.");
  digitalWrite(kIrLed, HIGH);            // ~90 mA trong 5 s: trong gioi han LED (100 mA lien tuc)
  delay(5000);
  digitalWrite(kIrLed, LOW);
  endTx();
  Serial.println("[h] Da tat LED.");
}

// ---------------------------------------------------------------- nut BOOT
void checkBootButton() {
  static bool     stable = HIGH, lastRead = HIGH;
  static uint32_t changedAt = 0, pressedAt = 0;
  bool now = digitalRead(kBootPin);
  if (now != lastRead) { lastRead = now; changedAt = millis(); }
  if (millis() - changedAt < 50 || now == stable) return;   // chong doi phim
  stable = now;
  if (stable == LOW) {
    pressedAt = millis();
  } else if (millis() - pressedAt >= kLongPressMs) {
    toggleAuto();
  } else {
    replayRaw();
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  irsend.begin();
  irrecv.enableIRIn();
  pinMode(kBootPin, INPUT_PULLUP);
  prefs.begin("irreplay", false);
  Serial.println("\nPBL5 IR replay (ban 2). Bam remote vao mat thu (GPIO 5).");
  loadCapture();
  printHelp();
}

void loop() {
  capture();
  checkBootButton();
  if (autoMode && millis() - lastAuto >= kAutoEveryMs) {
    lastAuto = millis();
    autoCount++;
    Serial.printf("[auto #%lu] ", (unsigned long)autoCount);
    replayRaw();
  }
  while (Serial.available()) {
    switch (Serial.read()) {
      case 'p': replayRaw();   break;
      case 's': replayState(); break;
      case 'r': printRaw();    break;
      case 't': toggleAuto();  break;
      case 'b': blink();       break;
      case 'h': holdOn();      break;
      default: break;          // bo qua Enter va ky tu khac
    }
  }
}
