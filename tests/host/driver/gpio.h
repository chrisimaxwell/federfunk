#pragma once
#include <cassert>
#include "Arduino.h"
using gpio_num_t = int;
inline void gpio_hold_en(gpio_num_t pin) {
  assert(fake::pinModes[pin] == OUTPUT && fake::pins[pin] == LOW);
  fake::heldPins[pin] = true;
  fake::powerHeld = fake::heldPins[1];
}
inline void gpio_hold_dis(gpio_num_t pin) {
  if (fake::heldPins[pin]) {
    assert(fake::pinModes[pin] == OUTPUT && fake::pins[pin] == LOW);
  }
  fake::heldPins[pin] = false;
  fake::powerHeld = fake::heldPins[1];
}
inline void gpio_deep_sleep_hold_en() { fake::deepSleepHeld = true; }
inline void gpio_deep_sleep_hold_dis() { fake::deepSleepHeld = false; }
