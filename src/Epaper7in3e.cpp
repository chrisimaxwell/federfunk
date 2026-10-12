#include "Epaper7in3e.h"

// Controller sequence adapted from Waveshare's MIT-licensed EPD_7in3e driver
// (permission notice: LICENSE.waveshare):
// https://github.com/waveshareteam/e-Paper/tree/master/Arduino_R4/src/e-Paper

Epaper7in3e::Epaper7in3e(SPIClass& spi, int sck, int mosi, int cs, int dc,
                         int rst, int busy)
    : spi_(spi),
      sck_(sck),
      mosi_(mosi),
      cs_(cs),
      dc_(dc),
      rst_(rst),
      busy_(busy) {}

void Epaper7in3e::begin() {
  pinMode(cs_, OUTPUT);
  pinMode(dc_, OUTPUT);
  pinMode(rst_, OUTPUT);
  pinMode(busy_, INPUT);
  digitalWrite(cs_, HIGH);
  digitalWrite(dc_, HIGH);
  digitalWrite(rst_, HIGH);
  spi_.begin(sck_, -1, mosi_, cs_);
}

void Epaper7in3e::reset() {
  digitalWrite(rst_, HIGH);
  delay(20);
  digitalWrite(rst_, LOW);
  delay(2);
  digitalWrite(rst_, HIGH);
  delay(20);
}

void Epaper7in3e::command(uint8_t value) {
  spi_.beginTransaction(SPISettings(spiHz, MSBFIRST, SPI_MODE0));
  digitalWrite(dc_, LOW);
  digitalWrite(cs_, LOW);
  spi_.transfer(value);
  digitalWrite(cs_, HIGH);
  spi_.endTransaction();
}

void Epaper7in3e::data(uint8_t value) {
  data(&value, 1);
}

void Epaper7in3e::data(const uint8_t* values, size_t length) {
  spi_.beginTransaction(SPISettings(spiHz, MSBFIRST, SPI_MODE0));
  digitalWrite(dc_, HIGH);
  digitalWrite(cs_, LOW);

  // Arduino-ESP32's bulk SPI API takes a mutable pointer even though it does
  // not modify transmit-only data.
  constexpr size_t chunkSize = 4096;
  while (length > 0) {
    const size_t chunk = min(length, chunkSize);
    spi_.writeBytes(const_cast<uint8_t*>(values), chunk);
    values += chunk;
    length -= chunk;
    yield();
  }

  digitalWrite(cs_, HIGH);
  spi_.endTransaction();
}

bool Epaper7in3e::waitUntilIdle(uint32_t timeoutMs) {
  const uint32_t startedAt = millis();
  while (digitalRead(busy_) == LOW) {
    if (millis() - startedAt >= timeoutMs) {
      Serial.println("E-paper BUSY timeout. Check BUSY wiring and power.");
      return false;
    }
    delay(10);
  }
  return true;
}

bool Epaper7in3e::initialize() {
  reset();
  if (!waitUntilIdle(10000)) return false;
  delay(30);

  command(0xAA);
  const uint8_t cmdh[] = {0x49, 0x55, 0x20, 0x08, 0x09, 0x18};
  data(cmdh, sizeof(cmdh));

  command(0x01);
  data(0x3F);

  command(0x00);
  const uint8_t panelSetting[] = {0x5F, 0x69};
  data(panelSetting, sizeof(panelSetting));

  command(0x03);
  const uint8_t powerOffSequence[] = {0x00, 0x54, 0x00, 0x44};
  data(powerOffSequence, sizeof(powerOffSequence));

  command(0x05);
  const uint8_t powerSetting[] = {0x40, 0x1F, 0x1F, 0x2C};
  data(powerSetting, sizeof(powerSetting));

  command(0x06);
  const uint8_t boosterSoftStart[] = {0x6F, 0x1F, 0x17, 0x49};
  data(boosterSoftStart, sizeof(boosterSoftStart));

  command(0x08);
  const uint8_t boosterSoftStart2[] = {0x6F, 0x1F, 0x1F, 0x22};
  data(boosterSoftStart2, sizeof(boosterSoftStart2));

  command(0x30);
  data(0x03);
  command(0x50);
  data(0x3F);

  command(0x60);
  const uint8_t tcon[] = {0x02, 0x00};
  data(tcon, sizeof(tcon));

  command(0x61);
  const uint8_t resolution[] = {0x03, 0x20, 0x01, 0xE0};
  data(resolution, sizeof(resolution));

  command(0x84);
  data(0x01);
  command(0xE3);
  data(0x2F);

  command(0x04);
  return waitUntilIdle(30000);
}

bool Epaper7in3e::refresh() {
  command(0x04);
  if (!waitUntilIdle(30000)) return false;

  command(0x06);
  const uint8_t boosterSoftStart[] = {0x6F, 0x1F, 0x17, 0x49};
  data(boosterSoftStart, sizeof(boosterSoftStart));

  command(0x12);
  data(0x00);
  if (!waitUntilIdle(120000)) return false;

  command(0x02);
  data(0x00);
  return waitUntilIdle(30000);
}

void Epaper7in3e::sleep() {
  command(0x07);
  data(0xA5);
}

bool Epaper7in3e::display(const uint8_t* frame) {
  if (frame == nullptr) return false;

  Serial.println("Initializing e-paper...");
  if (!initialize()) return false;

  Serial.println("Sending 192000-byte frame...");
  command(0x10);
  data(frame, frameBytes);

  Serial.println("Refreshing e-paper (this takes roughly 25 seconds)...");
  const bool ok = refresh();
  sleep();
  Serial.println(ok ? "E-paper refresh complete." : "E-paper refresh failed.");
  return ok;
}
