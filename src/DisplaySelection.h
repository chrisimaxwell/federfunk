#pragma once

// Select via PlatformIO environment; never auto-detect a controller by size.
#ifndef BIRDDISPLAY_PANEL_13IN3E6
#define BIRDDISPLAY_PANEL_13IN3E6 0
#endif

#if BIRDDISPLAY_PANEL_13IN3E6
#include "Epaper13in3e.h"
using DisplayPanel = Epaper13in3e;
namespace displayConfig {
constexpr char name[] = "Waveshare ESP32-S3-ePaper-13.3E6";
constexpr const char* imageUrl = config::largeImageUrl;
// The integrated board has no documented GPIO48 WS2812.
constexpr int statusLedPin = -1;
// VBAT -> 2 MOhm / 1 MOhm divider -> ADC1 channel 7, verified in the schematic.
constexpr int batterySensePin = 8;
constexpr float batteryVoltageDivider = 3.0f;
inline DisplayPanel makePanel(SPIClass& spi) {
  // Fixed on-board wiring from Waveshare's epaper_port example:
  // SCK, MOSI, master CS, slave CS, DC, RST, BUSY, power enable.
  return DisplayPanel(spi, 9, 46, 10, 3, 11, 2, 12, 1);
}
}  // namespace displayConfig
#else
#include "Epaper7in3e.h"
using DisplayPanel = Epaper7in3e;
namespace displayConfig {
constexpr char name[] = "Waveshare 7.3-inch e-Paper HAT (E)";
constexpr const char* imageUrl = config::imageUrl;
constexpr int statusLedPin = config::statusLedPin;
constexpr int batterySensePin = -1;
constexpr float batteryVoltageDivider = 1.0f;
inline DisplayPanel makePanel(SPIClass& spi) {
  return DisplayPanel(spi, config::epdSck, config::epdMosi, config::epdCs,
                      config::epdDc, config::epdRst, config::epdBusy);
}
}  // namespace displayConfig
#endif
