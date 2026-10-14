#pragma once

// Non-secret, compile-time settings for the integrated 13.3-inch board only.
// The small breakout profile never samples an ADC or draws a battery overlay.
namespace batteryConfig {
constexpr bool enabled = true;
// Owner confirmed a battery is attached. Set false if it is removed: the
// charger STAT signal alone cannot distinguish charging from an absent cell.
constexpr bool batteryInstalled = true;
constexpr bool reportCharging = true;
// Only a small red warning appears on the frame, strictly below this percent.
// Clear at the threshold immediately; hysteresis must not leave it visible
// when the current estimate is 15% or higher. Charging is dashboard-only.
constexpr unsigned lowPercentage = 15;

// Voltage-based percentage estimate, NOT a fuel gauge. Adjust for your cell.
constexpr float emptyVoltage = 3.3f;
constexpr float fullVoltage = 4.2f;
// Percentages use whole percent estimates; trimmed ADC sampling reduces noise.
// Fine-tune against a multimeter: actual battery voltage / logged voltage.
constexpr float voltageCalibration = 1.0f;

static_assert(lowPercentage >= 1 && lowPercentage <= 100,
              "Invalid battery percentage threshold");
static_assert(fullVoltage > emptyVoltage && emptyVoltage >= 2.5f &&
                  fullVoltage <= 4.5f,
              "Invalid battery percentage range");
static_assert(voltageCalibration > 0.0f && voltageCalibration <= 2.0f,
              "Invalid battery voltage calibration");
}  // namespace batteryConfig
