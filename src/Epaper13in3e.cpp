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
  // Release the power-enable hold from the previous timer deep sleep.
  gpio_deep_sleep_hold_dis();
  gpio_hold_dis(static_cast<gpio_num_t>(power_));
  pinMode(power_, OUTPUT);
  digitalWrite(power_, LOW);
  pinMode(csMaster_, OUTPUT);
  pinMode(csSlave_, OUTPUT);
  pinMode(dc_, OUTPUT);
  pinMode(rst_, OUTPUT);
  pinMode(busy_, INPUT);
  deselect();
  digitalWrite(dc_, LOW);
  digitalWrite(rst_, LOW);
  spi_.begin(sck_, -1, mosi_, -1);
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

bool Epaper13in3e::waitUntilIdle(uint32_t timeoutMs) {
  const uint32_t startedAt = millis();
  while (digitalRead(busy_) == LOW) {
    if (millis() - startedAt >= timeoutMs) {
      Serial.println("13.3-inch e-paper BUSY timeout.");
      return false;
    }
    delay(10);
  }
  delay(20);
  return true;
}

bool Epaper13in3e::initialize() {
  digitalWrite(power_, HIGH);
  powered_ = true;
  delay(10);
  reset();
  if (!waitUntilIdle(10000)) return false;

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
  command(Target::Both, 0x04);
  if (!waitUntilIdle(30000)) return false;
  delay(50);
  const uint8_t zero[] = {0x00};
  command(Target::Both, 0x12, zero, sizeof(zero));
  if (!waitUntilIdle(120000)) return false;
  delay(50);
  command(Target::Both, 0x02, zero, sizeof(zero));
  return waitUntilIdle(30000);
}

void Epaper13in3e::powerOff() {
  if (powered_) {
    const uint8_t key[] = {0xA5};
    command(Target::Both, 0x07, key, sizeof(key));
    delay(100);
  }
  digitalWrite(power_, LOW);
  digitalWrite(rst_, LOW);
  digitalWrite(dc_, LOW);
  powered_ = false;
}

void Epaper13in3e::prepareForDeepSleep() {
  powerOff();
  // Keep the board's display power switch off throughout ESP32 deep sleep.
  gpio_hold_en(static_cast<gpio_num_t>(power_));
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
  const bool ok = refresh();
  powerOff();
  Serial.println(ok ? "E-paper refresh complete." : "E-paper refresh failed.");
  return ok;
}
