#pragma once

#include <Arduino.h>
#include <SPI.h>

#include "PanelFrame13in3e.h"

class Epaper13in3e {
 public:
  static constexpr uint16_t width = panel13in3e::width;
  static constexpr uint16_t height = panel13in3e::height;
  static constexpr size_t frameBytes = panel13in3e::frameBytes;

  enum Color : uint8_t {
    Black = 0x0, White = 0x1, Yellow = 0x2, Red = 0x3,
    Blue = 0x5, Green = 0x6,
  };

  Epaper13in3e(SPIClass& spi, int sck, int mosi, int csMaster, int csSlave,
              int dc, int rst, int busy, int power);
  void begin();
  bool display(const uint8_t* frame);
  void prepareForDeepSleep();

 private:
  // Below the 10 MHz used by Waveshare's ESP-IDF example.
  static constexpr uint32_t spiHz = 4000000;
  enum class Target { Master, Slave, Both };
  SPIClass& spi_;
  int sck_, mosi_, csMaster_, csSlave_, dc_, rst_, busy_, power_;
  bool powered_ = false;

  void reset();
  void select(Target target);
  void deselect();
  void command(Target target, uint8_t value, const uint8_t* data = nullptr,
               size_t length = 0);
  bool waitUntilIdle(uint32_t timeoutMs);
  bool initialize();
  void sendFrame(const uint8_t* frame, Target target);
  bool refresh();
  void powerOff();
};
