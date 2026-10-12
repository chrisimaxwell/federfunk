#pragma once

#include <Arduino.h>
#include <SPI.h>

class Epaper7in3e {
 public:
  static constexpr uint16_t width = 800;
  static constexpr uint16_t height = 480;
  static constexpr size_t frameBytes = width * height / 2;

  enum Color : uint8_t {
    Black = 0x0,
    White = 0x1,
    Yellow = 0x2,
    Red = 0x3,
    Blue = 0x5,
    Green = 0x6,
  };

  Epaper7in3e(SPIClass& spi, int sck, int mosi, int cs, int dc, int rst,
             int busy);

  void begin();
  bool display(const uint8_t* frame);
  // display() already puts this HAT into controller sleep; it has no
  // GPIO-controlled power switch.
  void prepareForDeepSleep() {}

 private:
  static constexpr uint32_t spiHz = 4000000;

  SPIClass& spi_;
  int sck_;
  int mosi_;
  int cs_;
  int dc_;
  int rst_;
  int busy_;

  void reset();
  void command(uint8_t value);
  void data(uint8_t value);
  void data(const uint8_t* values, size_t length);
  bool waitUntilIdle(uint32_t timeoutMs);
  bool initialize();
  bool refresh();
  void sleep();
};
