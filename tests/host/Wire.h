#pragma once
#include "Arduino.h"
#include <array>
#include <map>

namespace fake {
struct I2cTransaction {
  uint8_t address;
  std::vector<uint8_t> bytes;
};
inline std::vector<I2cTransaction> i2cTransactions;
inline std::map<std::pair<uint8_t, uint8_t>, uint8_t> registers;
inline int missingAddress = -1;
inline int failedRegister = -1;
inline bool i2cBeginWorks = true;
inline bool i2cShortRead = false;
inline bool i2cCorruptRead = false;
inline bool i2cEnded = false;
inline int i2cSda = -1;
inline int i2cScl = -1;
inline uint32_t i2cFrequency = 0;
inline uint16_t i2cTimeout = 0;
}

struct FakeWire {
  uint8_t address = 0;
  uint8_t selectedRegister = 0;
  std::vector<uint8_t> bytes;
  void setTimeOut(uint16_t timeout) { fake::i2cTimeout = timeout; }
  bool begin(int sda, int scl, uint32_t frequency) {
    fake::i2cSda = sda;
    fake::i2cScl = scl;
    fake::i2cFrequency = frequency;
    return fake::i2cBeginWorks;
  }
  void end() { fake::i2cEnded = true; }
  void beginTransmission(uint8_t target) { address = target; bytes.clear(); }
  size_t write(uint8_t value) { bytes.push_back(value); return 1; }
  uint8_t endTransmission(bool = true) {
    assert(fake::pins[13] == LOW && fake::pinModes[13] == OUTPUT);
    fake::i2cTransactions.push_back({address, bytes});
    if (address == fake::missingAddress) return 2;
    if (!bytes.empty()) selectedRegister = bytes[0];
    if (bytes.size() == 2) {
      if (bytes[0] == fake::failedRegister) return 3;
      fake::registers[{address, bytes[0]}] = bytes[1];
    }
    return 0;
  }
  uint8_t requestFrom(uint8_t target, uint8_t count) {
    address = target;
    assert(count == 1);
    return fake::i2cShortRead ? 0 : count;
  }
  int read() {
    return fake::i2cCorruptRead ? 0 : fake::registers[{address, selectedRegister}];
  }
};
inline FakeWire Wire;
