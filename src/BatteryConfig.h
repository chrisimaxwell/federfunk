#pragma once

// Non-secret, compile-time settings for the integrated 13.3-inch board only.
// The small breakout profile never samples an ADC or draws a battery overlay.
namespace batteryConfig {
constexpr bool enabled = true;
constexpr bool showOnlyWhenLow = true;
constexpr float lowVoltage = 3.5f;
// A low warning clears only at lowVoltage + recoveryHysteresis volts.
constexpr float recoveryHysteresis = 0.1f;

// Voltage-based percentage estimate, NOT a fuel gauge. Adjust for your cell.
constexpr float emptyVoltage = 3.3f;
constexpr float fullVoltage = 4.2f;
// Round the shown percentage to this step to avoid noise-driven refreshes.
constexpr unsigned percentageStep = 5;
// Fine-tune against a multimeter: actual battery voltage / logged voltage.
constexpr float voltageCalibration = 1.0f;

static_assert(lowVoltage >= 2.5f && lowVoltage <= 4.2f, "Invalid battery threshold");
static_assert(recoveryHysteresis >= 0.0f && recoveryHysteresis <= 0.5f,
              "Invalid battery hysteresis");
static_assert(fullVoltage > emptyVoltage && emptyVoltage >= 2.5f &&
                  fullVoltage <= 4.5f,
              "Invalid battery percentage range");
static_assert(percentageStep >= 1 && percentageStep <= 100,
              "Invalid battery percentage step");
static_assert(voltageCalibration > 0.0f && voltageCalibration <= 2.0f,
              "Invalid battery voltage calibration");
}  // namespace batteryConfig
