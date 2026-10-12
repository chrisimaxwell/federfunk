#pragma once

#include <cstddef>
#include <cstdint>

constexpr int LOW = 0;
constexpr int HIGH = 1;
constexpr int INPUT = 0;
constexpr int OUTPUT = 1;

namespace fake {
inline int pins[49] = {};
inline uint32_t now = 0;
inline bool busy = false;
inline bool failRefresh = false;
inline bool powerHeld = false;
}

inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int value) { fake::pins[pin] = value; }
inline int digitalRead(int) { return fake::busy ? LOW : HIGH; }
inline uint32_t millis() { return fake::now; }
inline void delay(uint32_t ms) { fake::now += ms; }
struct FakeSerial { void println(const char*) {} };
inline FakeSerial Serial;
