#pragma once

#include "BatteryIndicator.h"

namespace battery {

// Per-wake telemetry is deliberately separate from Indicator/RTC fingerprints.
// A charging transition alone must never trigger an e-paper refresh.
struct Telemetry {
  float voltage = 0.0f;
  uint8_t percentage = 0;
  ChargeState charge = ChargeState::Unknown;
};

inline const char* chargeHeader(ChargeState state) {
  switch (state) {
    case ChargeState::Charging: return "charging";
    case ChargeState::NotCharging: return "not_charging";
    default: return "unknown";
  }
}

template <typename AddHeader>
bool addTelemetryHeaders(const Telemetry& reading, AddHeader add) {
  if (!validVoltage(reading.voltage) || reading.percentage > 100) return false;
  char percent[4];
  char voltage[8];
  std::snprintf(percent, sizeof(percent), "%u", static_cast<unsigned>(reading.percentage));
  std::snprintf(voltage, sizeof(voltage), "%.2f", static_cast<double>(reading.voltage));
  add("X-FederFunk-Battery-Percent", percent);
  add("X-FederFunk-Battery-Voltage", voltage);
  add("X-FederFunk-Charging", chargeHeader(reading.charge));
  return true;
}

}  // namespace battery
