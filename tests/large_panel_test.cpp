/* Host test: clang++ -std=c++17 -Wall -Wextra -Werror -Itests/host -Isrc
 * tests/large_panel_test.cpp src/Epaper13in3e.cpp -o /tmp/large-panel-test
 */
#include "Epaper13in3e.h"
#include <cassert>
#include <cstdio>
#include <vector>

uint8_t expectedPixel(size_t x, size_t y) {
  constexpr uint8_t codes[] = {0, 1, 2, 3, 5, 6};
  return codes[(x * 13 + y * 7 + (x >> 4) + (y >> 3)) % 6];
}

int main() {
  static_assert(Epaper13in3e::frameBytes == 960000, "Large frame size");
  std::vector<uint8_t> frame(Epaper13in3e::frameBytes);
  for (size_t y = 0; y < 1200; ++y) {
    for (size_t x = 0; x < 1600; x += 2) {
      frame[y * 800 + x / 2] =
          (expectedPixel(x, y) << 4) | expectedPixel(x + 1, y);
    }
  }

  SPIClass spi;
  Epaper13in3e panel(spi, 9, 46, 10, 3, 11, 2, 12, 1);
  panel.begin();
  assert(fake::pins[1] == LOW);
  assert(panel.display(frame.data()));
  assert(fake::pins[1] == LOW && fake::pins[2] == LOW);

  // Validate the actual SPI payload, every pixel, including the IC seam.
  // Count coverage separately to catch omissions/duplicates during rotation.
  std::vector<bool> seen(1600 * 1200, false);
  size_t controllerCount = 0;
  bool resolutionSeen = false;
  bool refreshSeen = false;
  bool sleepSeen = false;
  for (const auto& packet : spi.packets) {
    if (packet.command == 0x61) {
      assert(packet.master && packet.slave);
      assert((packet.data == std::vector<uint8_t>{0x04, 0xB0, 0x03, 0x20}));
      resolutionSeen = true;
    }
    if (packet.command == 0x12) {
      assert(packet.master && packet.slave && packet.data.size() == 1);
      refreshSeen = true;
    }
    if (packet.command == 0x07) {
      assert(packet.master && packet.slave);
      assert((packet.data == std::vector<uint8_t>{0xA5}));
      sleepSeen = true;
    }
    if (packet.command != 0x10) continue;
    assert(packet.master != packet.slave);
    assert(packet.master == (controllerCount == 0));
    assert(packet.data.size() == 480000);
    for (size_t nx = 0; nx < 600; ++nx) {
      for (size_t ny = 0; ny < 1600; ++ny) {
        const size_t x = ny;
        const size_t y = 1199 - nx - (packet.slave ? 600 : 0);
        const uint8_t byte = packet.data[ny * 300 + nx / 2];
        const uint8_t pixel = (nx & 1) ? byte & 0x0F : byte >> 4;
        assert(pixel == expectedPixel(x, y));
        assert(!seen[y * 1600 + x]);
        seen[y * 1600 + x] = true;
      }
    }
    ++controllerCount;
  }
  assert(controllerCount == 2 && resolutionSeen && refreshSeen && sleepSeen);
  for (bool pixel : seen) assert(pixel);
  panel.prepareForDeepSleep();
  assert(fake::powerHeld && fake::pins[1] == LOW);

  // A stuck BUSY line must time out and remove panel power, both during
  // initialization and after the refresh command. Timer wake releases hold.
  panel.begin();
  assert(!fake::powerHeld);
  fake::busy = true;
  uint32_t startedAt = fake::now;
  assert(!panel.display(frame.data()));
  assert(fake::now - startedAt >= 10000 && fake::now - startedAt < 12000);
  assert(fake::pins[1] == LOW);
  fake::busy = false;
  fake::failRefresh = true;
  startedAt = fake::now;
  assert(!panel.display(frame.data()));
  assert(fake::now - startedAt >= 120000 && fake::now - startedAt < 125000);
  assert(fake::pins[1] == LOW);
  panel.prepareForDeepSleep();
  assert(fake::powerHeld);
  puts("PASS: both controller payloads cover all 1920000 pixels exactly; "
       "DC/CS protocol, power hold, and BUSY failure cleanup verified.");
}
