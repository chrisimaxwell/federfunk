#include <algorithm>
#include <cassert>
#include <iostream>
#include "config.example.h"
#include "DisplaySelection.h"
#include "BoardPower.h"
#include <Wire.h>

void reset() {
  std::fill(std::begin(fake::pins), std::end(fake::pins), HIGH);
  std::fill(std::begin(fake::pinModes), std::end(fake::pinModes), INPUT);
  std::fill(std::begin(fake::heldPins), std::end(fake::heldPins), false);
  fake::events.clear();
  fake::serialLines.clear();
  fake::i2cTransactions.clear();
  fake::registers.clear();
  fake::missingAddress = -1;
  fake::failedRegister = -1;
  fake::i2cBeginWorks = true;
  fake::i2cShortRead = false;
  fake::i2cCorruptRead = false;
  fake::i2cEnded = false;
  fake::deepSleepHeld = false;
}

bool logged(const char* expected) {
  return std::any_of(fake::serialLines.begin(), fake::serialLines.end(),
                    [expected](const auto& line) { return line.find(expected) != std::string::npos; });
}

void runCycle() {
  boardPower::begin();
  boardPower::disableUnusedAudio();
  boardPower::prepareForDeepSleep();
}

int main() {
  reset();
  runCycle();
#if BIRDDISPLAY_PANEL_13IN3E6 && BIRDDISPLAY_AUDIO_POWERDOWN
  assert(logged("ES8311 confirmed; ES7210 confirmed"));
  assert(fake::i2cSda == 41 && fake::i2cScl == 42);
  assert(fake::i2cFrequency == 100000 && fake::i2cTimeout == 25);
  assert(fake::i2cEnded);
  assert(fake::pinModes[41] == INPUT && fake::pinModes[42] == INPUT);
  assert(fake::heldPins[13] && fake::pins[13] == LOW && fake::deepSleepHeld);
  // Never address other devices/charger or drive any other GPIO.
  for (const auto& tx : fake::i2cTransactions) assert(tx.address == 0x18 || tx.address == 0x40);
  for (const auto& event : fake::events) assert(event.pin == 13 && event.value == LOW);
  assert((fake::registers[{0x18, 0x0d}] == 0xfc));
  assert((fake::registers[{0x18, 0x00}] == 0x1f));
  assert((fake::registers[{0x18, 0x01}] == 0x00));
  for (uint8_t reg = 0x47; reg <= 0x4c; ++reg) assert((fake::registers[{0x40, reg}] == 0xff));
  assert((fake::registers[{0x40, 0x06}] == 0x07));
  // Timer wake restores the low latch before releasing the amplifier hold.
  boardPower::begin();
  assert(!fake::heldPins[13] && fake::pins[13] == LOW);
  boardPower::prepareForDeepSleep();
  assert(fake::heldPins[13]);

  for (int missing : {0x18, 0x40}) {
    reset();
    fake::missingAddress = missing;
    runCycle();
    assert(logged(missing == 0x18 ? "ES8311 unconfirmed; ES7210 confirmed" : "ES8311 confirmed; ES7210 unconfirmed"));
    assert(fake::i2cTransactions.size() <= 30 && fake::i2cEnded && fake::heldPins[13]);
  }
  // A single failed write must not suppress later shutdown writes or falsely
  // report success just because the final register happened to match.
  reset();
  fake::failedRegister = 0x47;
  runCycle();
  assert(logged("ES7210 unconfirmed"));
  assert((fake::registers[{0x40, 0x06}] == 0x07));
  assert(fake::i2cTransactions.size() <= 30 && fake::heldPins[13]);
  for (bool corrupt : {false, true}) {
    reset();
    fake::i2cShortRead = !corrupt;
    fake::i2cCorruptRead = corrupt;
    runCycle();
    assert(logged("ES8311 unconfirmed; ES7210 unconfirmed"));
    assert(fake::i2cEnded && fake::heldPins[13]);
  }
  reset();
  fake::i2cBeginWorks = false;
  runCycle();
  assert(logged("I2C unavailable"));
  assert(fake::i2cTransactions.empty() && fake::i2cEnded && fake::heldPins[13]);
#else
  assert(fake::events.empty() && fake::i2cTransactions.empty());
  assert(!fake::deepSleepHeld && !fake::i2cEnded);
#endif
  std::cout << "Board power tests passed.\n";
}
