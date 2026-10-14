/* Host test: clang++ -std=c++17 -Wall -Wextra -Werror -Itests/host -Isrc
 * tests/large_panel_test.cpp src/Epaper13in3e.cpp -o /tmp/large-panel-test
 */
#include "Epaper13in3e.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <vector>

uint8_t expectedPixel(size_t x, size_t y) {
  constexpr uint8_t codes[] = {0, 1, 2, 3, 5, 6};
  return codes[(x * 13 + y * 7 + (x >> 4) + (y >> 3)) % 6];
}

bool logged(const char* message) {
  return std::any_of(fake::serialLines.begin(), fake::serialLines.end(),
                    [message](const std::string& line) {
                      return line.find(message) != std::string::npos;
                    });
}

constexpr int outputPins[] = {1, 2, 3, 9, 10, 11, 46};
constexpr int interfacePins[] = {2, 3, 9, 10, 11, 46};

void assertPinsOff() {
  for (int pin : outputPins) {
    assert(fake::pinModes[pin] == OUTPUT && fake::pins[pin] == LOW);
  }
}

size_t commandCount(const SPIClass& spi, uint8_t command) {
  return static_cast<size_t>(std::count_if(
      spi.packets.begin(), spi.packets.end(),
      [command](const Packet& packet) { return packet.command == command; }));
}

const Packet& lastCommand(const SPIClass& spi, uint8_t command) {
  const auto found = std::find_if(
      spi.packets.rbegin(), spi.packets.rend(),
      [command](const Packet& packet) { return packet.command == command; });
  assert(found != spi.packets.rend());
  return *found;
}

void prepareScenario(SPIClass& spi, Epaper13in3e& panel,
                     fake::RefreshBusyMode mode, uint32_t startDelay = 0) {
  fake::busy = false;
  fake::refreshCommandSeen = false;
  fake::powerOffCommandSeen = false;
  fake::powerOffBusyMode = fake::PowerOffBusyMode::Idle;
  fake::refreshBusyMode = mode;
  fake::refreshStartDelay = startDelay;
  fake::serialLines.clear();
  spi.packets.clear();
  fake::events.clear();
  panel.begin();
  assertPinsOff();
  assert(!fake::powerHeld && !fake::deepSleepHeld && !spi.started);
  for (int pin : outputPins) assert(!fake::heldPins[pin]);
  fake::events.clear();
}

void assertPowerCutTiming(const SPIClass& spi) {
  assertPinsOff();
  assert(!spi.started && !spi.inTransaction && spi.beginCount == spi.endCount);
  size_t powerCut = fake::events.size();
  size_t spiEnd = fake::events.size();
  for (size_t index = 0; index < fake::events.size(); ++index) {
    const auto& event = fake::events[index];
    if (event.kind == fake::EventKind::Write && event.pin == 1 && event.value == LOW)
      powerCut = index;
    if (event.kind == fake::EventKind::SpiEnd) spiEnd = index;
  }
  assert(powerCut < fake::events.size() && spiEnd < powerCut);
  const uint32_t cutAt = fake::events[powerCut].at;
  for (int pin : interfacePins) {
    size_t lastWrite = fake::events.size();
    for (size_t index = 0; index < powerCut; ++index) {
      const auto& event = fake::events[index];
      if (event.kind == fake::EventKind::Write && event.pin == pin) lastWrite = index;
    }
    assert(lastWrite < powerCut && fake::events[lastWrite].value == LOW);
    assert(cutAt - fake::events[lastWrite].at >= 60);
  }
  // Reset must be LOW before changing SPI ownership or selecting both chips.
  bool resetAssertedBeforeEnd = false;
  for (size_t index = 0; index < spiEnd; ++index) {
    const auto& event = fake::events[index];
    if (event.kind == fake::EventKind::Write && event.pin == 2)
      resetAssertedBeforeEnd = event.value == LOW;
  }
  assert(resetAssertedBeforeEnd);
}

void assertGracefulShutdown(const SPIClass& spi, uint32_t finalBusyEndOffset = 0) {
  assert(commandCount(spi, 0x02) == 1 && commandCount(spi, 0x07) == 1);
  const Packet& pof = lastCommand(spi, 0x02);
  const Packet& sleep = lastCommand(spi, 0x07);
  assert(pof.master && pof.slave && pof.data == std::vector<uint8_t>{0x00});
  assert(sleep.master && sleep.slave && sleep.data == std::vector<uint8_t>{0xA5});
  assert(sleep.at - pof.at >= finalBusyEndOffset + 250);
  for (const auto& event : fake::events) {
    if (event.kind == fake::EventKind::SpiEnd) assert(event.at - sleep.at >= 100);
  }
  assertPowerCutTiming(spi);
}

void assertIdempotentDeepSleep(const SPIClass& spi, Epaper13in3e& panel) {
  const uint32_t at = fake::now;
  const size_t packetCount = spi.packets.size();
  const size_t starts = spi.beginCount;
  const size_t ends = spi.endCount;
  panel.prepareForDeepSleep();
  panel.prepareForDeepSleep();
  assert(fake::now == at && spi.packets.size() == packetCount);
  assert(spi.beginCount == starts && spi.endCount == ends);
  assert(fake::powerHeld && fake::deepSleepHeld);
  for (int pin : outputPins) assert(fake::heldPins[pin]);
  assertPinsOff();
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
  assertPinsOff();
  assert(!spi.started && spi.beginCount == 0);
  // Allocation/network failures can request sleep before the first display.
  assertIdempotentDeepSleep(spi, panel);
  prepareScenario(spi, panel, fake::RefreshBusyMode::Completes);
  const uint32_t beforeNull = fake::now;
  assert(!panel.display(nullptr));
  assert(fake::now == beforeNull && spi.packets.empty() && spi.beginCount == 0);
  panel.begin();
  assertPinsOff();
  fake::events.clear();
  assert(panel.display(frame.data()));
  assertGracefulShutdown(spi);
  assert(fake::now - fake::refreshCommandAt >= fake::refreshDuration);
  assert(logged("13.3-inch e-paper refresh started (BUSY LOW)."));
  assert(logged("E-paper refresh complete."));

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
  // A second display without another begin must reacquire the SPI pins.
  const size_t firstStartCount = spi.beginCount;
  spi.packets.clear();
  fake::events.clear();
  fake::refreshCommandSeen = false;
  fake::powerOffCommandSeen = false;
  assert(panel.display(frame.data()));
  assert(spi.beginCount == firstStartCount + 1);
  assertGracefulShutdown(spi);
  assertIdempotentDeepSleep(spi, panel);

  // An initially idle line may assert BUSY after the refresh command. Wait for
  // both edges rather than returning while it still looks idle at command end.
  prepareScenario(spi, panel, fake::RefreshBusyMode::Completes, 250);
  assert(panel.display(frame.data()));
  assert(fake::now - fake::refreshCommandAt >= 250 + fake::refreshDuration);
  assert(logged("E-paper refresh complete."));
  assertGracefulShutdown(spi);

  // An initially HIGH POF response can briefly become BUSY. The complete
  // 250ms idle guard must restart at the final LOW-to-HIGH transition.
  prepareScenario(spi, panel, fake::RefreshBusyMode::Completes);
  fake::powerOffBusyMode = fake::PowerOffBusyMode::DelayedBusy;
  assert(panel.display(frame.data()));
  assertGracefulShutdown(spi, fake::powerOffStartDelay + fake::powerOffDuration);

  // A disconnected or stuck-HIGH BUSY line must fail in a bounded time and
  // must never be reported as a successful refresh.
  prepareScenario(spi, panel, fake::RefreshBusyMode::NeverAsserts);
  assert(!panel.display(frame.data()));
  assert(fake::now - fake::refreshCommandAt >= 1000);
  assert(fake::now - fake::refreshCommandAt < 2000);
  assert(logged("13.3-inch e-paper refresh did not start: BUSY never went LOW."));
  assert(!logged("13.3-inch e-paper refresh started (BUSY LOW)."));
  assert(!logged("E-paper refresh complete."));
  assertGracefulShutdown(spi);
  assertIdempotentDeepSleep(spi, panel);

  // A stuck BUSY line must time out and remove panel power, both during
  // initialization and after the refresh command. Timer wake releases hold.
  prepareScenario(spi, panel, fake::RefreshBusyMode::Completes);
  fake::busy = true;
  uint32_t startedAt = fake::now;
  assert(!panel.display(frame.data()));
  assert(fake::now - startedAt >= 10000 && fake::now - startedAt < 12000);
  assert(!fake::refreshCommandSeen);
  assert(commandCount(spi, 0x02) == 0 && commandCount(spi, 0x07) == 0);
  assert(!logged("E-paper refresh complete."));
  assertPowerCutTiming(spi);
  assertIdempotentDeepSleep(spi, panel);

  prepareScenario(spi, panel, fake::RefreshBusyMode::StaysBusy, 250);
  startedAt = fake::now;
  assert(!panel.display(frame.data()));
  assert(fake::now - startedAt >= 120000 && fake::now - startedAt < 125000);
  assert(fake::now - fake::refreshCommandAt >= 120250);
  assert(logged("13.3-inch e-paper refresh completion timed out: BUSY stayed LOW."));
  assert(!logged("13.3-inch e-paper refresh did not start: BUSY never went LOW."));
  assert(commandCount(spi, 0x02) == 0 && commandCount(spi, 0x07) == 0);
  assert(!logged("E-paper refresh complete."));
  assertPowerCutTiming(spi);
  assertIdempotentDeepSleep(spi, panel);

  // Failed or continually unstable POF must fail the display result, avoid
  // sleep/another POF, and cut power after the bounded best-effort abort.
  for (const auto mode : {fake::PowerOffBusyMode::StaysBusy,
                          fake::PowerOffBusyMode::Flaps}) {
    prepareScenario(spi, panel, fake::RefreshBusyMode::Completes);
    fake::powerOffBusyMode = mode;
    assert(!panel.display(frame.data()));
    assert(commandCount(spi, 0x02) == 1 && commandCount(spi, 0x07) == 0);
    assert(fake::now - fake::powerOffCommandAt >= 30000);
    assert(fake::now - fake::powerOffCommandAt < 30200);
    assert(!logged("E-paper refresh complete."));
    assertPowerCutTiming(spi);
    assertIdempotentDeepSleep(spi, panel);
  }
  puts("PASS: both controller payloads cover all 1920000 pixels exactly; "
       "DC/CS protocol, delayed/absent/stuck BUSY, POF idle guard/failures, "
       "GPIO shutdown timing, SPI reacquisition, and sleep holds verified.");
}
