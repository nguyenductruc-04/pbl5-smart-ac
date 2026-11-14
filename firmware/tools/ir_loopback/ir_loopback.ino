// =====================================================================
//  PBL5 - IR loopback test (Daikin)
//  ESP32-S3 phat 1 lenh Daikin qua LED IR (GPIO 4) va tu thu lai bang
//  TSOP38238 (GPIO 5), dem ty le giai ma dung sau kRuns lan.
//
//  - Bo thu duoc khoi dong tren nhan 0 de ngat cua no khong chen vao
//    luc phat (song mang 38 kHz duoc tao bang phan mem tren nhan 1).
//  - Lan nao sai thi in Raw Timing de phan tich.
//
//  Yeu cau: ESP32 Arduino core 2.0.17, IRremoteESP8266 2.9.0
//  Mach: xem docs/hardware/ir-circuit.md
// =====================================================================
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <ir_Daikin.h>

const uint16_t kIrLed         = 4;     // mach phat (2N2222A)
const uint16_t kRecvPin       = 5;     // TSOP38238 OUT
const uint8_t  kTestTolerance = 25;    // % sai so cho phep khi giai ma
const uint16_t kRuns          = 20;    // so lan phat
const uint32_t kGapMs         = 3000;  // khoang cach giua 2 lan phat
const uint32_t kWaitMs        = 1500;  // thoi gian cho thu sau moi lan phat

IRDaikinESP ac(kIrLed);
IRrecv irrecv(kRecvPin, 1024, 50, true);  // buffer 1024, timeout 50 ms (khung A/C dai)
decode_results results;

uint16_t sent = 0, ok = 0, bad = 0, none = 0;
uint32_t lastSend = 0;
bool waiting = false;

// Khoi dong bo thu tren nhan 0 -> ngat cua bo thu khong chen vao luc phat (nhan 1)
void rxInitTask(void *) {
  irrecv.setTolerance(kTestTolerance);
  irrecv.enableIRIn();
  vTaskDelete(NULL);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  ac.begin();
  ac.on();
  ac.setMode(kDaikinCool);
  ac.setTemp(26);
  ac.setFan(kDaikinFanAuto);
  xTaskCreatePinnedToCore(rxInitTask, "rxInit", 4096, NULL, 1, NULL, 0);
  delay(100);
  Serial.printf("Loopback test: %u lan, tolerance %u%%\n", kRuns, kTestTolerance);
}

void loop() {
  // 1. Phat lenh moi khi lan truoc da xong
  if (!waiting && sent < kRuns && millis() - lastSend >= kGapMs) {
    irrecv.resume();              // bo du lieu cu con sot lai
    ac.send();
    sent++;
    lastSend = millis();
    waiting = true;
  }

  // 2. Thu duoc tin hieu -> so sanh voi trang thai vua phat
  if (waiting && irrecv.decode(&results)) {
    bool match = results.decode_type == DAIKIN &&
                 memcmp(results.state, ac.getRaw(), kDaikinStateLength) == 0;
    if (match) ok++; else bad++;
    Serial.printf("[%2u] %s  %s, %u bits\n", sent, match ? "OK  " : "FAIL",
                  typeToString(results.decode_type).c_str(), results.bits);
    if (!match) Serial.println(resultToTimingInfo(&results));
    irrecv.resume();
    waiting = false;
  }

  // 3. Het thoi gian cho ma khong thu duoc gi
  if (waiting && millis() - lastSend > kWaitMs) {
    none++;
    Serial.printf("[%2u] NONE  khong thu duoc tin hieu\n", sent);
    waiting = false;
  }

  // 4. Tong ket sau khi phat du kRuns lan
  static bool printed = false;
  if (!printed && sent == kRuns && !waiting) {
    printed = true;
    Serial.printf("=== Ket qua: %u/%u dung, %u sai, %u khong thu duoc (tolerance %u%%) ===\n",
                  ok, kRuns, bad, none, kTestTolerance);
  }
}
