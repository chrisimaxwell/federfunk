#pragma once

#include "Arduino.h"
#include <algorithm>
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
  uint32_t at;
};
class SPIClass {
 public:
  std::vector<Packet> packets;
  bool started = false;
  bool inTransaction = false;
  size_t beginCount = 0;
  size_t endCount = 0;
  void begin(int sck, int miso, int mosi, int cs) {
    assert(sck == 9 && miso == -1 && mosi == 46 && cs == -1);
    assert(!started && fake::pins[1] == HIGH);
    assert(fake::pins[10] == HIGH && fake::pins[3] == HIGH);
    const auto powerOn = std::find_if(
        fake::events.rbegin(), fake::events.rend(),
        [](const fake::Event& event) {
          return event.kind == fake::EventKind::Write && event.pin == 1 &&
                 event.value == HIGH;
        });
    assert(powerOn != fake::events.rend() && fake::now - powerOn->at >= 10);
    started = true;
    ++beginCount;
    pinMode(sck, OUTPUT);
    pinMode(mosi, OUTPUT);
    digitalWrite(sck, LOW);
    digitalWrite(mosi, LOW);
    fake::events.push_back({fake::EventKind::SpiBegin, fake::now, -1, 0});
  }
  void end() {
    assert(started && !inTransaction);
    started = false;
    ++endCount;
    fake::events.push_back({fake::EventKind::SpiEnd, fake::now, -1, 0});
  }
  void beginTransaction(SPISettings) {
    assert(started && !inTransaction);
    inTransaction = true;
  }
  uint8_t transfer(uint8_t cmd) {
    assert(started && inTransaction);
    assert(fake::pins[11] == LOW);  // Command must have DC low.
    const bool master = fake::pins[10] == LOW;
    const bool slave = fake::pins[3] == LOW;
    assert(master || slave);
    packets.push_back({cmd, master, slave, {}, fake::now});
    fake::events.push_back({fake::EventKind::Command, fake::now, -1, cmd});
    if (cmd == 0x12) {
      fake::refreshCommandAt = fake::now;
      fake::refreshCommandSeen = true;
    }
    if (cmd == 0x02) {
      fake::powerOffCommandAt = fake::now;
      fake::powerOffCommandSeen = true;
    }
    return 0;
  }
  void writeBytes(uint8_t* data, size_t count) {
    assert(started && inTransaction);
    assert(fake::pins[11] == HIGH);  // Payload must have DC high.
    auto& packet = packets.back();
    assert(packet.master == (fake::pins[10] == LOW));
    assert(packet.slave == (fake::pins[3] == LOW));
    packet.data.insert(packet.data.end(), data, data + count);
  }
  void endTransaction() {
    assert(started && inTransaction);
    assert(fake::pins[10] == HIGH && fake::pins[3] == HIGH);
    inTransaction = false;
  }
};
