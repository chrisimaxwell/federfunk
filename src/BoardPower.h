#pragma once

#include <Arduino.h>

// Set to 0 only for a controlled before/after current measurement.
#ifndef BIRDDISPLAY_AUDIO_POWERDOWN
#define BIRDDISPLAY_AUDIO_POWERDOWN 1
#endif

#if BIRDDISPLAY_PANEL_13IN3E6 && BIRDDISPLAY_AUDIO_POWERDOWN
#include <Wire.h>
#include <driver/gpio.h>
#endif

namespace boardPower {

#if BIRDDISPLAY_PANEL_13IN3E6 && BIRDDISPLAY_AUDIO_POWERDOWN

// Call before panel.begin() releases the global deep-sleep hold. Restore the
// output latch before releasing this pin's hold so the amplifier stays off.
inline void begin() {
  pinMode(displayConfig::audioAmplifierEnablePin, OUTPUT);
  digitalWrite(displayConfig::audioAmplifierEnablePin, LOW);
  gpio_hold_dis(static_cast<gpio_num_t>(displayConfig::audioAmplifierEnablePin));
}

struct RegisterValue { uint8_t reg; uint8_t value; };

// Register sequences adapted from Espressif esp_codec_dev's es8311_suspend()
// and es7210_stop(). Copyright 2023 Espressif Systems (Shanghai) CO LTD.
// SPDX-License-Identifier: Apache-2.0. See LICENSE.espressif and
// docs/sleep-power.md for the source URLs and board evidence.
constexpr RegisterValue dacSuspend[] = {
    {0x32, 0x00}, {0x17, 0x00}, {0x0e, 0xff}, {0x12, 0x02},
    {0x14, 0x00}, {0x0d, 0xfa}, {0x15, 0x00}, {0x02, 0x10},
    {0x00, 0x00}, {0x00, 0x1f}, {0x01, 0x30}, {0x01, 0x00},
    {0x45, 0x00}, {0x0d, 0xfc}, {0x02, 0x00}};
constexpr RegisterValue adcSuspend[] = {
    {0x47, 0xff}, {0x48, 0xff}, {0x49, 0xff}, {0x4a, 0xff},
    {0x4b, 0xff}, {0x4c, 0xff}, {0x40, 0xc0}, {0x01, 0x7f},
    {0x06, 0x07}};

inline bool registerMatches(uint8_t address, uint8_t reg, uint8_t expected) {
  Wire.beginTransmission(address);
  const bool queued = Wire.write(reg) == 1;
  if (Wire.endTransmission(false) != 0 || !queued) return false;
  if (Wire.requestFrom(address, static_cast<uint8_t>(1)) != 1) return false;
  return Wire.read() == expected;
}

template <size_t N>
inline bool suspendCodec(uint8_t address, const RegisterValue (&sequence)[N]) {
  Wire.beginTransmission(address);
  if (Wire.endTransmission() != 0) return false;
  bool success = true;
  // Continue after an individual NACK: later power-down writes may still work.
  // No unbounded retry; Wire's per-transaction timeout bounds a stuck bus.
  for (const auto& entry : sequence) {
    Wire.beginTransmission(address);
    const bool regQueued = Wire.write(entry.reg) == 1;
    const bool valueQueued = Wire.write(entry.value) == 1;
    if (Wire.endTransmission() != 0 || !regQueued || !valueQueued) success = false;
  }
  return success;
}

inline void disableUnusedAudio() {
  // Audio is unused by this display client. Shut it down even on reset/wake
  // after a different sketch left the independently powered codecs running.
  Wire.setTimeOut(25);
  if (!Wire.begin(displayConfig::audioSdaPin, displayConfig::audioSclPin, 100000)) {
    Serial.println("Audio shutdown: I2C unavailable; amplifier remains off.");
  } else {
    bool dac = suspendCodec(displayConfig::audioDacAddress, dacSuspend);
    bool adc = suspendCodec(displayConfig::audioAdcAddress, adcSuspend);
    dac = registerMatches(displayConfig::audioDacAddress, 0x0d, 0xfc) && dac;
    dac = registerMatches(displayConfig::audioDacAddress, 0x00, 0x1f) && dac;
    adc = registerMatches(displayConfig::audioAdcAddress, 0x4b, 0xff) && adc;
    adc = registerMatches(displayConfig::audioAdcAddress, 0x06, 0x07) && adc;
    Serial.printf("Audio shutdown: ES8311 %s; ES7210 %s.\n",
                  dac ? "confirmed" : "unconfirmed",
                  adc ? "confirmed" : "unconfirmed");
  }
  Wire.end();
  // Release the bus rather than sinking current through pull-ups. INPUT also
  // removes Arduino's internal pull resistors; there is no audio rail switch.
  pinMode(displayConfig::audioSdaPin, INPUT);
  pinMode(displayConfig::audioSclPin, INPUT);
}

inline void prepareForDeepSleep() {
  digitalWrite(displayConfig::audioAmplifierEnablePin, LOW);
  gpio_hold_en(static_cast<gpio_num_t>(displayConfig::audioAmplifierEnablePin));
  gpio_deep_sleep_hold_en();
}

#else
// The 7.3-inch breakout has different wiring: never touch its GPIO13/41/42.
inline void begin() {}
inline void disableUnusedAudio() {}
inline void prepareForDeepSleep() {}
#endif

}  // namespace boardPower
