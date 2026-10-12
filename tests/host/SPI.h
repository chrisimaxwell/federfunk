#pragma once

#include "Arduino.h"
#include <cassert>
#include <vector>

constexpr int MSBFIRST = 1;
constexpr int SPI_MODE0 = 0;
struct SPISettings { SPISettings(uint32_t, int, int) {} };
struct Packet {
  uint8_t command;
  bool master;
  bool slave;
  std::vector<uint8_t> data;
};
class SPIClass {
 public:
  std::vector<Packet> packets;
  void begin(int sck, int miso, int mosi, int cs) {
    assert(sck == 9 && miso == -1 && mosi == 46 && cs == -1);
  }
  void beginTransaction(SPISettings) {}
  uint8_t transfer(uint8_t cmd) {
    assert(fake::pins[11] == LOW);  // Command must have DC low.
    const bool master = fake::pins[10] == LOW;
    const bool slave = fake::pins[3] == LOW;
    assert(master || slave);
    packets.push_back({cmd, master, slave, {}});
    if (cmd == 0x12 && fake::failRefresh) fake::busy = true;
    return 0;
  }
  void writeBytes(uint8_t* data, size_t count) {
    assert(fake::pins[11] == HIGH);  // Payload must have DC high.
    auto& packet = packets.back();
    assert(packet.master == (fake::pins[10] == LOW));
    assert(packet.slave == (fake::pins[3] == LOW));
    packet.data.insert(packet.data.end(), data, data + count);
  }
  void endTransaction() {
    assert(fake::pins[10] == HIGH && fake::pins[3] == HIGH);
  }
};
