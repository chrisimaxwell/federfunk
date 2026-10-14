#pragma once

#include <cstddef>
#include <cstdint>
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>

constexpr int LOW = 0;
constexpr int HIGH = 1;
constexpr int INPUT = 0;
constexpr int OUTPUT = 1;

namespace fake {
inline int pins[49] = {};
inline int pinModes[49] = {};
inline bool heldPins[49] = {};
inline uint32_t now = 0;
enum class EventKind { Write, SpiBegin, SpiEnd, Command };
struct Event {
  EventKind kind;
  uint32_t at;
  int pin;
  int value;
};
inline std::vector<Event> events;
inline bool busy = false;
enum class RefreshBusyMode { Completes, NeverAsserts, StaysBusy };
inline RefreshBusyMode refreshBusyMode = RefreshBusyMode::Completes;
inline uint32_t refreshStartDelay = 0;
inline uint32_t refreshDuration = 25000;
inline uint32_t refreshCommandAt = 0;
inline bool refreshCommandSeen = false;
enum class PowerOffBusyMode { Idle, DelayedBusy, StaysBusy, Flaps };
inline PowerOffBusyMode powerOffBusyMode = PowerOffBusyMode::Idle;
inline uint32_t powerOffCommandAt = 0;
inline bool powerOffCommandSeen = false;
inline uint32_t powerOffStartDelay = 100;
inline uint32_t powerOffDuration = 40;
inline bool powerHeld = false;
inline bool deepSleepHeld = false;
inline std::vector<std::string> serialLines;
}

inline void pinMode(int pin, int mode) { fake::pinModes[pin] = mode; }
inline void digitalWrite(int pin, int value) {
  // Writes while held update the latch but must not request a different level.
  assert(!fake::heldPins[pin] || fake::pins[pin] == value);
  fake::pins[pin] = value;
  fake::events.push_back({fake::EventKind::Write, fake::now, pin, value});
}
inline int digitalRead(int) {
  if (fake::busy) return LOW;
  if (fake::powerOffCommandSeen) {
    const uint32_t elapsed = fake::now - fake::powerOffCommandAt;
    if (fake::powerOffBusyMode == fake::PowerOffBusyMode::StaysBusy) return LOW;
    if (fake::powerOffBusyMode == fake::PowerOffBusyMode::Flaps) {
      return elapsed % 200 < 100 ? HIGH : LOW;
    }
    if (fake::powerOffBusyMode == fake::PowerOffBusyMode::DelayedBusy &&
        elapsed >= fake::powerOffStartDelay &&
        elapsed - fake::powerOffStartDelay < fake::powerOffDuration) return LOW;
    return HIGH;
  }
  if (!fake::refreshCommandSeen ||
      fake::refreshBusyMode == fake::RefreshBusyMode::NeverAsserts) return HIGH;
  const uint32_t elapsed = fake::now - fake::refreshCommandAt;
  if (elapsed < fake::refreshStartDelay) return HIGH;
  return fake::refreshBusyMode == fake::RefreshBusyMode::StaysBusy ||
                 elapsed - fake::refreshStartDelay < fake::refreshDuration
             ? LOW : HIGH;
}
inline uint32_t millis() { return fake::now; }
inline void delay(uint32_t ms) { fake::now += ms; }
struct FakeSerial {
  void println(const char* text) { fake::serialLines.emplace_back(text); }
  void printf(const char* format, ...) {
    char buffer[512];
    va_list args;
    va_start(args, format);
    std::vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);
    fake::serialLines.emplace_back(buffer);
  }
};
inline FakeSerial Serial;
