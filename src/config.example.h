#pragma once

#include <Arduino.h>

namespace config {

// Copy this file to BirdDisplayConfig.h and edit the network and image URLs.
static constexpr char wifiSsid[] = "YOUR_WIFI_SSID";
static constexpr char wifiPassword[] = "YOUR_WIFI_PASSWORD";
static constexpr char imageUrl[] = "http://192.168.1.10:8000/image.jpg";
// Used only by the esp32-s3-13in3e6 build profile. Raw .bin frames must be
// 1600x1200 landscape, exactly 960000 bytes.
static constexpr char largeImageUrl[] = "http://192.168.1.10:8000/image_large.bin";
// Large-board battery warning/percentage settings are in BatteryConfig.h.

// How long to deep-sleep after each update. A full refresh takes about 25 s.
static constexpr uint32_t refreshIntervalMs = 30UL * 60UL * 1000UL;
static constexpr uint32_t wifiTimeoutMs = 20UL * 1000UL;

// Image processing options. Exact-size images can bypass crop/resampling, but
// JPEG decoding and conversion to the panel's six-color format are mandatory.
static constexpr bool enableDithering = true;
static constexpr bool bypassResamplingWhenExactSize = true;

// On-board WS2812 status LED. A successful refresh blinks green; a failed
// download, validation, or display refresh blinks red.
static constexpr uint8_t statusLedPin = 48;
static constexpr uint8_t statusLedBrightness = 24;
static constexpr uint8_t statusLedBlinkCount = 3;
static constexpr uint16_t statusLedOnMs = 180;
static constexpr uint16_t statusLedOffMs = 180;

// ESP32-S3 GPIO -> Waveshare 8-pin SPI connector.
// Change these to match your breakout-board wiring.
static constexpr int epdSck = 12;   // CLK
static constexpr int epdMosi = 11;  // DIN
static constexpr int epdCs = 10;    // CS
static constexpr int epdDc = 9;     // DC
static constexpr int epdRst = 6;    // RST
static constexpr int epdBusy = 7;   // BUSY

}  // namespace config
