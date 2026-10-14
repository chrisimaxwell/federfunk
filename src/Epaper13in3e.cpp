#include "Epaper13in3e.h"

#include <driver/gpio.h>

// Register sequence and reset timing adapted from Waveshare's EPD_13in3e
// (MIT license; see LICENSE.waveshare) and its ESP-IDF epaper_port driver:
// https://github.com/waveshareteam/ESP32-S3-ePaper-13.3E6
// The ESP-IDF example explicitly switches DC for commands/data, unlike the
// Arduino example. Use its hardware SPI protocol here.

Epaper13in3e::Epaper13in3e(SPIClass& spi, int sck, int mosi, int csMaster,
                           int csSlave, int dc, int rst, int busy, int power)
    : spi_(spi), sck_(sck), mosi_(mosi), csMaster_(csMaster),
      csSlave_(csSlave), dc_(dc), rst_(rst), busy_(busy), power_(power) {}

void Epaper13in3e::begin() {
  if (powered_) powerOff();
  // Configure the retained LOW levels before releasing deep-sleep holds.
  // The interface must not feed a display whose supply is switched off.
  const int outputs[] = {power_, rst_, csMaster_, csSlave_, dc_, sck_, mosi_};
  for (int pin : outputs) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
    gpio_hold_dis(static_cast<gpio_num_t>(pin));
  }
  gpio_deep_sleep_hold_dis();
  pinMode(busy_, INPUT);
}

void Epaper13in3e::reset() {
  digitalWrite(rst_, HIGH);
  delay(30);
  digitalWrite(rst_, LOW);
  delay(30);
  digitalWrite(rst_, HIGH);
  delay(30);
  digitalWrite(rst_, LOW);
  delay(30);
  digitalWrite(rst_, HIGH);
  delay(30);
}

void Epaper13in3e::select(Target target) {
  digitalWrite(csMaster_, target == Target::Slave ? HIGH : LOW);
  digitalWrite(csSlave_, target == Target::Master ? HIGH : LOW);
}

void Epaper13in3e::deselect() {
  digitalWrite(csMaster_, HIGH);
  digitalWrite(csSlave_, HIGH);
}

void Epaper13in3e::command(Target target, uint8_t value,
                          const uint8_t* data, size_t length) {
  spi_.beginTransaction(SPISettings(spiHz, MSBFIRST, SPI_MODE0));
  select(target);
  digitalWrite(dc_, LOW);
  spi_.transfer(value);
  if (length != 0) {
    digitalWrite(dc_, HIGH);
    spi_.writeBytes(const_cast<uint8_t*>(data), length);
  }
  deselect();
  spi_.endTransaction();
}

bool Epaper13in3e::waitUntilIdle(uint32_t timeoutMs, const char* timeoutMessage) {
  const uint32_t startedAt = millis();
  while (digitalRead(busy_) == LOW) {
    if (millis() - startedAt >= timeoutMs) {
      Serial.println(timeoutMessage);
      return false;
    }
    delay(10);
  }
  delay(20);
  return true;
}

bool Epaper13in3e::initialize() {
  Serial.println("Display rail: enabling GPIO1.");
  digitalWrite(power_, HIGH);
  powered_ = true;
  initialized_ = false;
  delay(10);
  deselect();
  spi_.begin(sck_, -1, mosi_, -1);
  spiStarted_ = true;
  reset();
  if (!waitUntilIdle(10000, "Display reset: BUSY stayed LOW.")) return false;

  const uint8_t analog[] = {0xC0, 0x1C, 0x1C, 0xCC, 0xCC, 0xCC,
                            0x15, 0x15, 0x55};
  command(Target::Master, 0x74, analog, sizeof(analog));
  const uint8_t unlock[] = {0x49, 0x55, 0x13, 0x5D, 0x05, 0x10};
  command(Target::Both, 0xF0, unlock, sizeof(unlock));
  const uint8_t panel[] = {0xDF, 0x69};
  command(Target::Both, 0x00, panel, sizeof(panel));
  const uint8_t cdi[] = {0xF7};
  command(Target::Both, 0x50, cdi, sizeof(cdi));
  const uint8_t tcon[] = {0x03, 0x03};
  command(Target::Both, 0x60, tcon, sizeof(tcon));
  const uint8_t agid[] = {0x10};
  command(Target::Both, 0x86, agid, sizeof(agid));
  const uint8_t pws[] = {0x22};
  command(Target::Both, 0xE3, pws, sizeof(pws));
  const uint8_t ccset[] = {0x01};
  command(Target::Both, 0xE0, ccset, sizeof(ccset));
  const uint8_t resolution[] = {0x04, 0xB0, 0x03, 0x20};
  command(Target::Both, 0x61, resolution, sizeof(resolution));
  const uint8_t power[] = {0x0F, 0x00, 0x28, 0x2C, 0x28, 0x38};
  command(Target::Master, 0x01, power, sizeof(power));
  const uint8_t buffer[] = {0x07};
  command(Target::Master, 0xB6, buffer, sizeof(buffer));
  const uint8_t booster[] = {0xE8, 0x28};
  command(Target::Master, 0x06, booster, sizeof(booster));
  const uint8_t enable[] = {0x01};
  command(Target::Master, 0xB7, enable, sizeof(enable));
  command(Target::Master, 0x05, booster, sizeof(booster));
  command(Target::Master, 0xB0, enable, sizeof(enable));
  const uint8_t tftPower[] = {0x02};
  command(Target::Master, 0xB1, tftPower, sizeof(tftPower));
  initialized_ = true;
  return true;
}

void Epaper13in3e::sendFrame(const uint8_t* frame, Target target) {
  uint8_t row[panel13in3e::controllerRowBytes];
  spi_.beginTransaction(SPISettings(spiHz, MSBFIRST, SPI_MODE0));
  select(target);
  digitalWrite(dc_, LOW);
  spi_.transfer(0x10);
  digitalWrite(dc_, HIGH);
  for (uint16_t y = 0; y < panel13in3e::nativeHeight; ++y) {
    panel13in3e::packControllerRow(frame, target == Target::Slave, y, row);
    spi_.writeBytes(row, sizeof(row));
    // Feed the watchdog and keep the vendor's per-row pacing.
    delay(1);
  }
  deselect();
  spi_.endTransaction();
}

bool Epaper13in3e::refresh() {
  Serial.println("PON 0x04: requesting display booster power.");
  command(Target::Both, 0x04);
  if (!waitUntilIdle(30000, "PON: BUSY stayed LOW.")) return false;
  Serial.println("PON: observed BUSY HIGH.");
  delay(50);
  const uint8_t zero[] = {0x00};
  Serial.println("DRF 0x12: requesting refresh.");
  command(Target::Both, 0x12, zero, sizeof(zero));
  // An idle/disconnected BUSY line is not evidence of a completed refresh.
  // Observe the controller enter BUSY first, including a delayed assertion.
  const uint32_t refreshCommandAt = millis();
  while (digitalRead(busy_) == HIGH) {
    if (millis() - refreshCommandAt >= 1000) {
      Serial.println("13.3-inch e-paper refresh did not start: BUSY never went LOW.");
      return false;
    }
    delay(10);
  }
  Serial.println("13.3-inch e-paper refresh started (BUSY LOW).");
  if (!waitUntilIdle(120000,
      "13.3-inch e-paper refresh completion timed out: BUSY stayed LOW.")) {
    return false;
  }
  delay(50);
  return true;
}

bool Epaper13in3e::waitForPowerOffIdle() {
  // Manual p.15 requires >200 ms after POF BUSY returns HIGH. Restart the
  // guard if BUSY goes LOW, including an assertion just after the command.
  // Do not require sampling a LOW pulse: its minimum width is unspecified.
  const uint32_t startedAt = millis();
  uint32_t idleSince = startedAt;
  bool wasIdle = false;
  while (millis() - startedAt < 30000) {
    const uint32_t now = millis();
    if (digitalRead(busy_) == HIGH) {
      if (!wasIdle) idleSince = now;
      wasIdle = true;
      if (now - idleSince >= 250) return true;
    } else {
      wasIdle = false;
    }
    delay(1);
  }
  Serial.println("POF: BUSY did not remain HIGH for the shutdown guard.");
  return false;
}

void Epaper13in3e::interfaceLow() {
  // Hold reset first so lowering CS and detaching the clock cannot be
  // interpreted as another command. Release the SPI peripheral before GPIO.
  digitalWrite(rst_, LOW);
  if (spiStarted_) {
    spi_.end();
    spiStarted_ = false;
  }
  const int outputs[] = {rst_, csMaster_, csSlave_, dc_, sck_, mosi_};
  for (int pin : outputs) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
}

bool Epaper13in3e::powerOff() {
  if (!powered_) return true;

  bool orderly = false;
  // Try the normal POF sequence on idle failures too (e.g. refresh never
  // asserted BUSY). Never send sleep or further commands into stuck BUSY.
  if (initialized_ && digitalRead(busy_) == HIGH) {
    Serial.println("POF 0x02: requesting display booster power off.");
    const uint8_t zero[] = {0x00};
    command(Target::Both, 0x02, zero, sizeof(zero));
    orderly = waitForPowerOffIdle();
    if (orderly) {
      Serial.println("Sleep 0x07: power-off idle guard completed.");
      const uint8_t key[] = {0xA5};
      command(Target::Both, 0x07, key, sizeof(key));
      delay(100);
    }
  }
  if (!orderly) {
    // The vendor has no timeout recovery. This bounded fallback removes
    // drive/power; it is not a validated emergency discharge or thermal trip.
    Serial.println("Display abort: resetting and removing power without sleep.");
  }
  interfaceLow();
  // Manual p.15 requires >50 ms with interface LOW before removing VDD.
  delay(60);
  Serial.println("Display rail: disabling GPIO1.");
  digitalWrite(power_, LOW);
  powered_ = false;
  initialized_ = false;
  return orderly;
}

void Epaper13in3e::prepareForDeepSleep() {
  powerOff();
  // Retain every connected output LOW, not just the switched supply enable.
  const int outputs[] = {power_, rst_, csMaster_, csSlave_, dc_, sck_, mosi_};
  for (int pin : outputs) gpio_hold_en(static_cast<gpio_num_t>(pin));
  gpio_deep_sleep_hold_en();
}

bool Epaper13in3e::display(const uint8_t* frame) {
  if (frame == nullptr) return false;
  Serial.println("Initializing 13.3-inch Spectra 6 display...");
  if (!initialize()) {
    powerOff();
    return false;
  }
  Serial.println("Sending 960000-byte landscape frame to both controllers...");
  sendFrame(frame, Target::Master);
  sendFrame(frame, Target::Slave);
  Serial.println("Refreshing 13.3-inch e-paper...");
  const bool refreshed = refresh();
  const bool shutDown = powerOff();
  const bool ok = refreshed && shutDown;
  Serial.println(ok ? "E-paper refresh complete." : "E-paper refresh failed.");
  return ok;
}
