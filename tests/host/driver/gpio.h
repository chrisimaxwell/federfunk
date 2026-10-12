#pragma once
#include <cassert>
#include "Arduino.h"
using gpio_num_t = int;
inline void gpio_hold_en(gpio_num_t pin) {
  assert(pin == 1 && fake::pins[pin] == LOW);
  fake::powerHeld = true;
}
inline void gpio_hold_dis(gpio_num_t) { fake::powerHeld = false; }
inline void gpio_deep_sleep_hold_en() {}
inline void gpio_deep_sleep_hold_dis() {}
