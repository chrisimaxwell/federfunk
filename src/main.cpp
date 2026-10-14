#include <Arduino.h>
#include <FS.h>
#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <LittleFS.h>
#include <SPI.h>
#include <WiFi.h>
#include <esp_heap_caps.h>
#include <esp_sleep.h>
#include <esp_arduino_version.h>
#include <esp32-hal-rgb-led.h>
#include <esp_attr.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>

#if __has_include("BirdDisplayConfig.h")
#include "BirdDisplayConfig.h"
#else
#include "config.example.h"
#warning "Using config.example.h. Copy it to BirdDisplayConfig.h and add your settings."
#endif

#include "DisplaySelection.h"
#include "BoardPower.h"
#include "BatteryConfig.h"
#include "BatteryIndicator.h"
#include "BatteryTelemetry.h"
#include "RefreshState.h"
#include "ScheduleHold.h"

namespace {

constexpr char imagePath[] = "/image.jpg";
constexpr char temporaryImagePath[] = "/image.tmp";

RTC_DATA_ATTR refresh::State lastDisplayed{};
refresh::Digest refreshContext{};
battery::Indicator batteryIndicator{};
battery::Telemetry batteryTelemetry{};
// Per-wake only. A future network failure retains the normal retry interval.
uint32_t scheduleHoldSeconds = 0;

auto& DebugSerial = Serial;
SPIClass epdSpi(FSPI);
DisplayPanel panel = displayConfig::makePanel(epdSpi);
JPEGDEC jpeg;
uint8_t* frame = nullptr;
uint16_t* decodedRgb = nullptr;
int decodedRgbWidth = 0;
int decodedRgbHeight = 0;

bool fingerprint(const uint8_t* data, size_t size, refresh::Digest& digest) {
#if MBEDTLS_VERSION_MAJOR >= 3
  return mbedtls_sha256(data, size, digest.data(), 0) == 0;
#else
  return mbedtls_sha256_ret(data, size, digest.data(), 0) == 0;
#endif
}

bool initializeRefreshState() {
  // Bind the remembered image/ETag to this URL, canvas, and rendering settings.
  // Hash the URL rather than retaining another copy of a private backend URL.
  uint8_t contextBytes[refresh::digestBytes + 13 + sizeof(float) * 3];
  refresh::Digest urlDigest;
  if (!fingerprint(reinterpret_cast<const uint8_t*>(displayConfig::imageUrl),
                   strlen(displayConfig::imageUrl), urlDigest)) {
    refresh::invalidate(lastDisplayed);
    return false;
  }
  memcpy(contextBytes, urlDigest.data(), urlDigest.size());
  const uint32_t dimensions[] = {DisplayPanel::width, DisplayPanel::height};
  for (size_t i = 0; i < 2; ++i) {
    for (size_t byte = 0; byte < 4; ++byte) {
      contextBytes[refresh::digestBytes + i * 4 + byte] =
          static_cast<uint8_t>(dimensions[i] >> (byte * 8));
    }
  }
  contextBytes[refresh::digestBytes + 8] = config::enableDithering;
  contextBytes[refresh::digestBytes + 9] = config::bypassResamplingWhenExactSize;
  contextBytes[refresh::digestBytes + 10] =
      batteryConfig::enabled && displayConfig::batterySensePin >= 0;
  contextBytes[refresh::digestBytes + 11] = batteryConfig::batteryInstalled;
  contextBytes[refresh::digestBytes + 12] = batteryConfig::lowPercentage;
  const float batterySettings[] = {
      batteryConfig::emptyVoltage, batteryConfig::fullVoltage,
      batteryConfig::voltageCalibration};
  memcpy(contextBytes + refresh::digestBytes + 13, batterySettings,
         sizeof(batterySettings));
  if (!fingerprint(contextBytes, sizeof(contextBytes), refreshContext)) {
    refresh::invalidate(lastDisplayed);
    return false;
  }
  const bool retained = refresh::resume(
      lastDisplayed, esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER,
      refreshContext);
  DebugSerial.println(retained ? "Last displayed frame retained across sleep."
                               : "First update after reset: refresh required.");
  return true;
}

void sampleBattery() {
  batteryTelemetry = {};
  if (!batteryConfig::enabled || displayConfig::batterySensePin < 0) return;
  if (!batteryConfig::batteryInstalled) {
    DebugSerial.println("Battery not installed/configured; battery readout disabled.");
    return;
  }
  const auto previous = lastDisplayed.version == refresh::stateVersion
                            ? battery::fromKey(lastDisplayed.overlayKey)
                            : battery::Indicator{};
  // Unknown voltage must not remove an already displayed low-battery warning.
  batteryIndicator = previous;
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);  // Arduino name for the S3's 12 dB setting.
  (void)analogReadMilliVolts(displayConfig::batterySensePin);
  delay(10);
  const float volts = battery::sampleVoltage(
      []() {
        const auto millivolts = analogReadMilliVolts(displayConfig::batterySensePin);
        delay(2);
        return millivolts;
      },
      displayConfig::batteryVoltageDivider, batteryConfig::voltageCalibration);
  if (!battery::validVoltage(volts)) {
    DebugSerial.printf("Battery reading invalid (%.2f V); retaining the previous indicator.\n",
                       volts);
    return;
  }
  batteryIndicator = battery::evaluate(
      volts, previous, batteryConfig::lowPercentage,
      batteryConfig::emptyVoltage, batteryConfig::fullVoltage);
  batteryTelemetry.voltage = volts;
  batteryTelemetry.percentage = batteryIndicator.percentage;
  if (batteryConfig::reportCharging && displayConfig::chargeStatusPin >= 0) {
    // Input only: never alter the charger or power rails. ETA6098 STAT is
    // open-drain; the pull-up makes its inactive state readable.
    pinMode(displayConfig::chargeStatusPin, INPUT_PULLUP);
    delay(5);
    unsigned lowSamples = 0;
    constexpr unsigned count = 32;
    for (unsigned i = 0; i < count; ++i) {
      lowSamples += digitalRead(displayConfig::chargeStatusPin) == LOW;
      delay(2);
    }
    batteryTelemetry.charge = battery::classifyCharge(
        lowSamples, count, batteryConfig::batteryInstalled, true);
    // Remove the internal pull-up before sleep to avoid a continuous load
    // through STAT when it is LOW. The next wake configures it again.
    pinMode(displayConfig::chargeStatusPin, INPUT);
    DebugSerial.printf("Charger STAT: %u/%u LOW samples; %s.\n", lowSamples,
                       count, battery::chargeLabel(batteryTelemetry.charge));
  }
  DebugSerial.printf("Battery: %.2f V, estimated %u%%; %s; low warning %s (below %u%%).\n",
                     volts, batteryIndicator.percentage,
                     battery::chargeLabel(batteryTelemetry.charge),
                     batteryIndicator.low ? "ON" : "off", batteryConfig::lowPercentage);
}

void setStatusLed(uint8_t red, uint8_t green, uint8_t blue) {
  if (displayConfig::statusLedPin >= 0) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    rgbLedWrite(displayConfig::statusLedPin, red, green, blue);
#else
    neopixelWrite(displayConfig::statusLedPin, red, green, blue);
#endif
  }
}

void blinkStatus(bool success) {
  if (displayConfig::statusLedPin < 0) {
    DebugSerial.println(success ? "Update succeeded." : "Update failed.");
    return;
  }
  const uint8_t red = success ? 0 : config::statusLedBrightness;
  const uint8_t green = success ? config::statusLedBrightness : 0;
  DebugSerial.printf("Status LED: blinking %s.\n", success ? "green" : "red");
  for (uint8_t blink = 0; blink < config::statusLedBlinkCount; ++blink) {
    setStatusLed(red, green, 0);
    delay(config::statusLedOnMs);
    setStatusLed(0, 0, 0);
    delay(config::statusLedOffMs);
  }
}

void enterDeepSleep() {
  const uint64_t sleepDurationUs = scheduleHold::sleepMicroseconds(
      config::refreshIntervalMs, scheduleHoldSeconds);

  setStatusLed(0, 0, 0);
  panel.prepareForDeepSleep();
  boardPower::prepareForDeepSleep();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  LittleFS.end();

  if (scheduleHoldSeconds > 0) {
    DebugSerial.printf("Schedule pause: sleeping for %u seconds until updates resume.\n",
                       static_cast<unsigned>(scheduleHoldSeconds));
  } else {
    DebugSerial.printf("Sleeping for %u minutes.\n",
                       static_cast<unsigned>(config::refreshIntervalMs /
                                             (60UL * 1000UL)));
  }
  DebugSerial.flush();
  delay(50);
  esp_sleep_enable_timer_wakeup(sleepDurationUs);
  esp_deep_sleep_start();
}

struct PaletteEntry {
  uint8_t r;
  uint8_t g;
  uint8_t b;
  uint8_t code;
};

static constexpr PaletteEntry palette[] = {
    {0, 0, 0, DisplayPanel::Black},
    {255, 255, 255, DisplayPanel::White},
    {255, 255, 0, DisplayPanel::Yellow},
    {255, 0, 0, DisplayPanel::Red},
    {0, 0, 255, DisplayPanel::Blue},
    {0, 255, 0, DisplayPanel::Green},
};

size_t nearestPaletteIndex(int r, int g, int b) {
  uint32_t bestDistance = UINT32_MAX;
  size_t bestIndex = 0;
  for (size_t index = 0; index < sizeof(palette) / sizeof(palette[0]);
       ++index) {
    const PaletteEntry& candidate = palette[index];
    const int dr = r - candidate.r;
    const int dg = g - candidate.g;
    const int db = b - candidate.b;
    const uint32_t distance =
        30UL * dr * dr + 59UL * dg * dg + 11UL * db * db;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  }
  return bestIndex;
}

void setPixel(int x, int y, uint8_t color) {
  if (x < 0 || x >= DisplayPanel::width || y < 0 ||
      y >= DisplayPanel::height) {
    return;
  }

  const size_t index = static_cast<size_t>(y) * (DisplayPanel::width / 2) +
                       static_cast<size_t>(x / 2);
  if ((x & 1) == 0) {
    frame[index] = (frame[index] & 0x0F) | (color << 4);
  } else {
    frame[index] = (frame[index] & 0xF0) | color;
  }
}

int storeJpegBlock(JPEGDRAW* block) {
  if (decodedRgb == nullptr || block->x >= decodedRgbWidth ||
      block->y >= decodedRgbHeight) {
    return decodedRgb != nullptr;
  }

  const int copyWidth = min(block->iWidth, decodedRgbWidth - block->x);
  const int copyHeight = min(block->iHeight, decodedRgbHeight - block->y);
  for (int row = 0; row < copyHeight; ++row) {
    memcpy(decodedRgb + static_cast<size_t>(block->y + row) * decodedRgbWidth +
               block->x,
           block->pPixels + static_cast<size_t>(row) * block->iWidth,
           static_cast<size_t>(copyWidth) * sizeof(uint16_t));
  }
  return 1;
}

void unpackRgb565(uint16_t pixel, int& r, int& g, int& b) {
  r = ((pixel >> 11) & 0x1F) * 255 / 31;
  g = ((pixel >> 5) & 0x3F) * 255 / 63;
  b = (pixel & 0x1F) * 255 / 31;
}

void sampleBilinear(int64_t xFixed, int64_t yFixed, int& r, int& g, int& b) {
  const int x0 = static_cast<int>(xFixed >> 16);
  const int y0 = static_cast<int>(yFixed >> 16);
  const int x1 = min(x0 + 1, decodedRgbWidth - 1);
  const int y1 = min(y0 + 1, decodedRgbHeight - 1);
  const int xFraction = static_cast<int>((xFixed >> 8) & 0xFF);
  const int yFraction = static_cast<int>((yFixed >> 8) & 0xFF);

  int r00, g00, b00;
  int r10, g10, b10;
  int r01, g01, b01;
  int r11, g11, b11;
  unpackRgb565(decodedRgb[static_cast<size_t>(y0) * decodedRgbWidth + x0],
               r00, g00, b00);
  unpackRgb565(decodedRgb[static_cast<size_t>(y0) * decodedRgbWidth + x1],
               r10, g10, b10);
  unpackRgb565(decodedRgb[static_cast<size_t>(y1) * decodedRgbWidth + x0],
               r01, g01, b01);
  unpackRgb565(decodedRgb[static_cast<size_t>(y1) * decodedRgbWidth + x1],
               r11, g11, b11);

  const auto interpolate = [xFraction, yFraction](int c00, int c10, int c01,
                                                   int c11) {
    const int top = c00 * (256 - xFraction) + c10 * xFraction;
    const int bottom = c01 * (256 - xFraction) + c11 * xFraction;
    return (top * (256 - yFraction) + bottom * yFraction + 32768) >> 16;
  };
  r = interpolate(r00, r10, r01, r11);
  g = interpolate(g00, g10, g01, g11);
  b = interpolate(b00, b10, b01, b11);
}

bool renderRgbToFrame() {
  if (decodedRgb == nullptr || decodedRgbWidth <= 0 || decodedRgbHeight <= 0) {
    return false;
  }

  const bool exactSize = decodedRgbWidth == DisplayPanel::width &&
                         decodedRgbHeight == DisplayPanel::height;
  const bool bypassResampling =
      exactSize && config::bypassResamplingWhenExactSize;

  int cropX = 0;
  int cropY = 0;
  int cropWidth = decodedRgbWidth;
  int cropHeight = decodedRgbHeight;
  if (static_cast<int64_t>(decodedRgbWidth) * DisplayPanel::height >
      static_cast<int64_t>(decodedRgbHeight) * DisplayPanel::width) {
    cropWidth = static_cast<int>(static_cast<int64_t>(decodedRgbHeight) *
                                 DisplayPanel::width / DisplayPanel::height);
    cropX = (decodedRgbWidth - cropWidth) / 2;
  } else {
    cropHeight = static_cast<int>(static_cast<int64_t>(decodedRgbWidth) *
                                  DisplayPanel::height / DisplayPanel::width);
    cropY = (decodedRgbHeight - cropHeight) / 2;
  }

  if (bypassResampling) {
    DebugSerial.printf("Using exact-size %ux%u pixels directly, %s.\n",
                       DisplayPanel::width, DisplayPanel::height,
                       config::enableDithering
                           ? "with serpentine Floyd-Steinberg dithering"
                           : "without dithering");
  } else {
    DebugSerial.printf(
        "Resampling centered crop %d,%d %dx%d to %ux%u with bilinear "
        "filtering, %s.\n",
        cropX, cropY, cropWidth, cropHeight,
        DisplayPanel::width, DisplayPanel::height,
        config::enableDithering
            ? "with serpentine Floyd-Steinberg dithering"
            : "without dithering");
  }
  // White is color code 1 in both nibbles. It remains visible anywhere an
  // undersized source image does not cover the panel.
  memset(frame, 0x11, DisplayPanel::frameBytes);

  // Errors are stored multiplied by 16 so the Floyd-Steinberg weights can be
  // accumulated with integers: 7/16, 3/16, 5/16, and 1/16. Two padded rows
  // make both left-to-right and right-to-left diffusion bounds-safe.
  constexpr int errorColumns = DisplayPanel::width + 2;
  int16_t* errors = nullptr;
  int16_t* currentR = nullptr;
  int16_t* currentG = nullptr;
  int16_t* currentB = nullptr;
  int16_t* nextR = nullptr;
  int16_t* nextG = nullptr;
  int16_t* nextB = nullptr;
  if (config::enableDithering) {
    errors = static_cast<int16_t*>(
        heap_caps_calloc(errorColumns * 6, sizeof(int16_t), MALLOC_CAP_8BIT));
    if (errors == nullptr) {
      DebugSerial.println("Could not allocate dithering error rows.");
      return false;
    }
    currentR = errors;
    currentG = currentR + errorColumns;
    currentB = currentG + errorColumns;
    nextR = currentB + errorColumns;
    nextG = nextR + errorColumns;
    nextB = nextG + errorColumns;
  }

  for (int y = 0; y < DisplayPanel::height; ++y) {
    int64_t yFixed = 0;
    if (!bypassResampling) {
      yFixed = (static_cast<int64_t>(2 * y + 1) * cropHeight << 15) /
                   DisplayPanel::height -
               32768 + (static_cast<int64_t>(cropY) << 16);
      yFixed = constrain(yFixed, int64_t{0},
                         static_cast<int64_t>(decodedRgbHeight - 1) << 16);
    }

    const bool leftToRight = !config::enableDithering || (y & 1) == 0;
    const int startX = leftToRight ? 0 : DisplayPanel::width - 1;
    const int endX = leftToRight ? DisplayPanel::width : -1;
    const int stepX = leftToRight ? 1 : -1;
    for (int x = startX; x != endX; x += stepX) {
      int r, g, b;
      if (bypassResampling) {
        unpackRgb565(
            decodedRgb[static_cast<size_t>(y) * decodedRgbWidth + x], r, g,
            b);
      } else {
        int64_t xFixed =
            (static_cast<int64_t>(2 * x + 1) * cropWidth << 15) /
                DisplayPanel::width -
            32768 + (static_cast<int64_t>(cropX) << 16);
        xFixed = constrain(xFixed, int64_t{0},
                           static_cast<int64_t>(decodedRgbWidth - 1) << 16);
        sampleBilinear(xFixed, yFixed, r, g, b);
      }
      const int errorIndex = x + 1;
      if (config::enableDithering) {
        r = constrain(r + currentR[errorIndex] / 16, 0, 255);
        g = constrain(g + currentG[errorIndex] / 16, 0, 255);
        b = constrain(b + currentB[errorIndex] / 16, 0, 255);
      }
      const PaletteEntry& chosen = palette[nearestPaletteIndex(r, g, b)];
      setPixel(x, y, chosen.code);

      if (config::enableDithering) {
        const int errorR = r - chosen.r;
        const int errorG = g - chosen.g;
        const int errorB = b - chosen.b;
        const int forwardIndex = errorIndex + stepX;
        const int backwardIndex = errorIndex - stepX;
        currentR[forwardIndex] += errorR * 7;
        currentG[forwardIndex] += errorG * 7;
        currentB[forwardIndex] += errorB * 7;
        nextR[backwardIndex] += errorR * 3;
        nextG[backwardIndex] += errorG * 3;
        nextB[backwardIndex] += errorB * 3;
        nextR[errorIndex] += errorR * 5;
        nextG[errorIndex] += errorG * 5;
        nextB[errorIndex] += errorB * 5;
        nextR[forwardIndex] += errorR;
        nextG[forwardIndex] += errorG;
        nextB[forwardIndex] += errorB;
      }
    }

    if (config::enableDithering) {
      std::swap(currentR, nextR);
      std::swap(currentG, nextG);
      std::swap(currentB, nextB);
      memset(nextR, 0, errorColumns * sizeof(int16_t));
      memset(nextG, 0, errorColumns * sizeof(int16_t));
      memset(nextB, 0, errorColumns * sizeof(int16_t));
    }
    yield();
  }
  free(errors);
  return true;
}

int32_t readJpegFile(JPEGFILE* handle, uint8_t* buffer, int32_t length) {
  File* file = static_cast<File*>(handle->fHandle);
  return static_cast<int32_t>(file->read(buffer, length));
}

int32_t seekJpegFile(JPEGFILE* handle, int32_t position) {
  File* file = static_cast<File*>(handle->fHandle);
  return file->seek(position) ? 1 : 0;
}

void closeJpegFile(void* handle) {
  // The File object lives in decodeImageToFrame() and is closed there after
  // JPEGDEC has finished with it.
  (void)handle;
}

bool connectToWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  if (strcmp(config::wifiSsid, "YOUR_WIFI_SSID") == 0 ||
      config::wifiSsid[0] == '\0') {
    DebugSerial.println(
        "Wi-Fi is not configured. Copy config.example.h to "
        "BirdDisplayConfig.h and edit it.");
    return false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  DebugSerial.printf("Connecting to Wi-Fi %s", config::wifiSsid);
  WiFi.begin(config::wifiSsid, config::wifiPassword);

  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - startedAt < config::wifiTimeoutMs) {
    DebugSerial.print('.');
    delay(500);
  }
  DebugSerial.println();

  if (WiFi.status() != WL_CONNECTED) {
    DebugSerial.println("Wi-Fi connection timed out.");
    return false;
  }

  DebugSerial.print("Connected. IP address: ");
  DebugSerial.println(WiFi.localIP());
  return true;
}

bool urlEndsWithBin(const char* url) {
  const size_t length = strlen(url);
  return length >= 4 && strcmp(url + length - 4, ".bin") == 0;
}

refresh::Response downloadImage(const char* url, String& responseETag,
                                size_t expectedBytes = 0, bool allowConditional = true) {
  responseETag = "";
  if (strncmp(url, "http://", 7) != 0) {
    DebugSerial.println("IMAGE_URL must begin with http:// in this first version.");
    return refresh::Response::Failed;
  }

  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(30000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);

  DebugSerial.printf("Downloading %s\n", url);
  if (!http.begin(client, url)) {
    DebugSerial.println("Could not start the HTTP request.");
    return refresh::Response::Failed;
  }

  const char* headerKeys[] = {"ETag", scheduleHold::headerName};
  http.collectHeaders(headerKeys, 2);
  // Ask for the same representation on conditional and unconditional requests.
  http.addHeader("Accept-Encoding", "identity");
  battery::addTelemetryHeaders(batteryTelemetry, [&http](const char* name, const char* value) {
    http.addHeader(name, value);
  });
  const char* previousETag = refresh::requestETag(lastDisplayed);
  const bool sentETag = allowConditional && previousETag[0] != '\0';
  if (sentETag) http.addHeader("If-None-Match", previousETag);

  const int status = http.GET();
  const uint32_t requestedHold = scheduleHold::parseSeconds(
      http.header(scheduleHold::headerName).c_str());
  const auto response = refresh::classifyResponse(status, sentETag, requestedHold);
  if (response == refresh::Response::Deferred) {
    scheduleHoldSeconds = requestedHold;
    http.end();
    DebugSerial.println("Server schedule paused: preserving the displayed image and battery badge.");
    return response;  // No body, cache write, ETag adoption, or panel refresh.
  }
  if (response == refresh::Response::NotModified) {
    responseETag = http.header("ETag");
    http.end();
    DebugSerial.println("Server image unchanged (HTTP 304).");
    return response;
  }
  if (response == refresh::Response::Failed) {
    DebugSerial.printf("HTTP request failed: %d (%s)\n", status,
                  http.errorToString(status).c_str());
    http.end();
    return response;
  }

  responseETag = http.header("ETag");

  const int contentLength = http.getSize();
  if (expectedBytes != 0 && contentLength >= 0 &&
      static_cast<size_t>(contentLength) != expectedBytes) {
    DebugSerial.printf("Unexpected Content-Length: %d (expected %u).\n",
                       contentLength, static_cast<unsigned>(expectedBytes));
    http.end();
    return refresh::Response::Failed;
  }

  // FILE_WRITE uses truncate/create semantics, so no pre-delete is needed.
  File destination = LittleFS.open(temporaryImagePath, FILE_WRITE);
  if (!destination) {
    DebugSerial.println("Could not open temporary image file.");
    http.end();
    return refresh::Response::Failed;
  }

  const int bytesWritten = http.writeToStream(&destination);
  destination.close();
  http.end();

  if (bytesWritten <= 0) {
    DebugSerial.printf("Image download failed while reading body: %d\n", bytesWritten);
    LittleFS.remove(temporaryImagePath);
    return refresh::Response::Failed;
  }

  if ((expectedBytes != 0 && static_cast<size_t>(bytesWritten) != expectedBytes) ||
      (contentLength >= 0 && bytesWritten != contentLength)) {
    DebugSerial.printf("Downloaded %d bytes; expected exactly %u.\n",
                       bytesWritten, static_cast<unsigned>(
                                         expectedBytes != 0 ? expectedBytes
                                                            : contentLength));
    LittleFS.remove(temporaryImagePath);
    return refresh::Response::Failed;
  }

  DebugSerial.printf("Downloaded %d bytes.\n", bytesWritten);
  return refresh::Response::Downloaded;
}

bool isPanelColorCode(uint8_t code) {
  return code == DisplayPanel::Black || code == DisplayPanel::White ||
         code == DisplayPanel::Yellow || code == DisplayPanel::Red ||
         code == DisplayPanel::Blue || code == DisplayPanel::Green;
}

bool loadRawPanelFrame(const char* path) {
  File file = LittleFS.open(path, FILE_READ);
  if (!file) {
    DebugSerial.printf("Could not open %s.\n", path);
    return false;
  }

  const size_t fileSize = file.size();
  if (fileSize != DisplayPanel::frameBytes) {
    DebugSerial.printf("Raw panel frame is %u bytes; expected exactly %u.\n",
                       static_cast<unsigned>(fileSize),
                       static_cast<unsigned>(DisplayPanel::frameBytes));
    file.close();
    return false;
  }

  size_t totalRead = 0;
  while (totalRead < DisplayPanel::frameBytes) {
    const size_t bytesRead = file.read(
        frame + totalRead, DisplayPanel::frameBytes - totalRead);
    if (bytesRead == 0) break;
    totalRead += bytesRead;
    yield();
  }
  file.close();
  if (totalRead != DisplayPanel::frameBytes) {
    DebugSerial.printf("Raw frame read stopped at %u of %u bytes.\n",
                       static_cast<unsigned>(totalRead),
                       static_cast<unsigned>(DisplayPanel::frameBytes));
    return false;
  }

  for (size_t index = 0; index < DisplayPanel::frameBytes; ++index) {
    const uint8_t packed = frame[index];
    const uint8_t first = packed >> 4;
    const uint8_t second = packed & 0x0F;
    if (!isPanelColorCode(first) || !isPanelColorCode(second)) {
      DebugSerial.printf(
          "Invalid panel color code at byte %u: 0x%02X.\n",
          static_cast<unsigned>(index), packed);
      return false;
    }
  }

  DebugSerial.printf(
      "Validated %ux%u packed six-color frame; no image processing needed.\n",
      DisplayPanel::width, DisplayPanel::height);
  return true;
}

bool decodeImageToFrame(const char* path) {
  File file = LittleFS.open(path, FILE_READ);
  if (!file) {
    DebugSerial.printf("Could not open %s.\n", path);
    return false;
  }

  if (!jpeg.open(&file, static_cast<int>(file.size()), closeJpegFile,
                 readJpegFile, seekJpegFile, storeJpegBlock)) {
    DebugSerial.printf("Not a supported JPEG (decoder error %d).\n",
                  jpeg.getLastError());
    file.close();
    return false;
  }

  const int sourceWidth = jpeg.getWidth();
  const int sourceHeight = jpeg.getHeight();
  struct DecodeScale {
    int divisor;
    int option;
  };
  static constexpr DecodeScale scales[] = {
      {1, 0},
      {2, JPEG_SCALE_HALF},
      {4, JPEG_SCALE_QUARTER},
      {8, JPEG_SCALE_EIGHTH},
  };

  // Decode at the highest RGB565 resolution that fits in PSRAM while leaving
  // headroom for the JPEG decoder and networking. A 3840x2160 RGB565 image is
  // about 15.8 MiB, so this board's 8 MiB PSRAM uses its 1920x1080 half-scale
  // representation (about 4 MiB) instead.
  const uint32_t memoryCaps =
      psramFound() ? MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT : MALLOC_CAP_8BIT;
  const size_t largestBlock = heap_caps_get_largest_free_block(memoryCaps);
  constexpr size_t allocationHeadroom = 256 * 1024;
  const size_t maximumDecodeBytes =
      largestBlock > allocationHeadroom ? largestBlock - allocationHeadroom
                                        : largestBlock;
  int divisor = 0;
  int decodeOption = 0;
  for (const DecodeScale& scale : scales) {
    const int candidateWidth =
        (sourceWidth + scale.divisor - 1) / scale.divisor;
    const int candidateHeight =
        (sourceHeight + scale.divisor - 1) / scale.divisor;
    const size_t candidateBytes = static_cast<size_t>(candidateWidth) *
                                  candidateHeight * sizeof(uint16_t);
    if (candidateWidth >= DisplayPanel::width &&
        candidateHeight >= DisplayPanel::height &&
        candidateBytes <= maximumDecodeBytes) {
      divisor = scale.divisor;
      decodeOption = scale.option;
      break;
    }
  }
  if (divisor == 0) {
    for (const DecodeScale& scale : scales) {
      const int candidateWidth =
          (sourceWidth + scale.divisor - 1) / scale.divisor;
      const int candidateHeight =
          (sourceHeight + scale.divisor - 1) / scale.divisor;
      const size_t candidateBytes = static_cast<size_t>(candidateWidth) *
                                    candidateHeight * sizeof(uint16_t);
      if (candidateBytes <= maximumDecodeBytes) {
        divisor = scale.divisor;
        decodeOption = scale.option;
        break;
      }
    }
  }
  if (divisor == 0) {
    DebugSerial.println("No JPEG decode scale fits available memory.");
    jpeg.close();
    file.close();
    return false;
  }

  const int decodedWidth = (sourceWidth + divisor - 1) / divisor;
  const int decodedHeight = (sourceHeight + divisor - 1) / divisor;
  const size_t decodedBytes = static_cast<size_t>(decodedWidth) *
                              decodedHeight * sizeof(uint16_t);
  decodedRgb = static_cast<uint16_t*>(
      heap_caps_malloc(decodedBytes, memoryCaps));
  if (decodedRgb == nullptr) {
    DebugSerial.printf("Could not allocate %u-byte RGB decode buffer.\n",
                       static_cast<unsigned>(decodedBytes));
    jpeg.close();
    file.close();
    return false;
  }
  decodedRgbWidth = decodedWidth;
  decodedRgbHeight = decodedHeight;
  memset(decodedRgb, 0, decodedBytes);

  DebugSerial.printf(
      "Decoding %dx%d JPEG at 1/%d scale into %dx%d RGB buffer.\n",
      sourceWidth, sourceHeight, divisor, decodedWidth, decodedHeight);
  jpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  const bool decoded = jpeg.decode(0, 0, decodeOption);
  const int decoderError = jpeg.getLastError();
  jpeg.close();
  file.close();

  bool rendered = false;
  if (!decoded) {
    DebugSerial.printf("JPEG decode failed: %d\n", decoderError);
  } else {
    rendered = renderRgbToFrame();
  }

  free(decodedRgb);
  decodedRgb = nullptr;
  decodedRgbWidth = 0;
  decodedRgbHeight = 0;
  return rendered;
}

bool prepareSourceFrame(const char* path, refresh::Digest& sourcePixels) {
  const bool prepared = urlEndsWithBin(displayConfig::imageUrl)
                            ? loadRawPanelFrame(path)
                            : decodeImageToFrame(path);
  return prepared && fingerprint(frame, DisplayPanel::frameBytes, sourcePixels);
}

bool loadKnownCachedFrame(refresh::Digest& sourcePixels) {
  // The cache is the unmodified source, not a frame with a painted-over corner.
  // Verify it against the last successful source so removing the badge restores
  // the backend's original pixels, and a corrupt/stale cache is never trusted.
  if (lastDisplayed.version != refresh::stateVersion ||
      !prepareSourceFrame(imagePath, sourcePixels) ||
      !refresh::matchesSource(lastDisplayed, sourcePixels)) {
    DebugSerial.println("No verified source cache available for a battery-only update.");
    return false;
  }
  return true;
}

bool displayPreparedFrame(const refresh::Digest& sourcePixels, const String& etag,
                          bool downloaded) {
  if (downloaded) {
    // Keep the original body, even if only pixels hidden by the badge changed.
    // Saving the overlaid frame would make it impossible to remove the badge.
    LittleFS.remove(imagePath);
    if (!LittleFS.rename(temporaryImagePath, imagePath)) {
      DebugSerial.println("Could not commit the validated image to LittleFS.");
      LittleFS.remove(temporaryImagePath);
      return false;
    }
  }
  battery::draw(frame, DisplayPanel::width, DisplayPanel::height, batteryIndicator);
  refresh::Digest pixels;
  if (!fingerprint(frame, DisplayPanel::frameBytes, pixels)) {
    DebugSerial.println("Could not fingerprint the display frame.");
    return false;
  }
  const uint16_t overlayKey = battery::key(batteryIndicator);
  if (refresh::matchesPixels(lastDisplayed, pixels)) {
    refresh::remember(lastDisplayed, refreshContext, pixels, etag.c_str(),
                      sourcePixels, overlayKey);
    DebugSerial.println("Image pixels unchanged; skipping e-paper refresh.");
    return true;
  }
  // A partial refresh makes the physical screen uncertain; repair on next wake.
  refresh::invalidate(lastDisplayed);
  if (!panel.display(frame)) return false;
  refresh::remember(lastDisplayed, refreshContext, pixels, etag.c_str(),
                    sourcePixels, overlayKey);
  return true;
}

void updateBatteryFromCache() {
  if (lastDisplayed.version != refresh::stateVersion ||
      !refresh::overlayChanged(lastDisplayed, battery::key(batteryIndicator))) return;
  refresh::Digest sourcePixels;
  if (!loadKnownCachedFrame(sourcePixels)) return;
  const String etag = refresh::requestETag(lastDisplayed);
  DebugSerial.println("Updating battery indicator from cached image; network update failed.");
  if (!displayPreparedFrame(sourcePixels, etag, false)) {
    DebugSerial.println("Cached battery indicator refresh failed.");
  }
}

bool fetchAndDisplay() {
  if (displayConfig::imageUrl[0] == '\0') {
    DebugSerial.println("Configure the selected display's image URL first.");
    return false;
  }
  if (!connectToWifi()) {
    updateBatteryFromCache();
    return false;
  }
  const size_t expectedBytes = urlEndsWithBin(displayConfig::imageUrl)
                                   ? DisplayPanel::frameBytes : size_t{0};
  String responseETag;
  auto response = downloadImage(displayConfig::imageUrl, responseETag, expectedBytes);
  if (response == refresh::Response::Deferred) return true;
  if (response == refresh::Response::Failed) {
    updateBatteryFromCache();
    return false;
  }
  refresh::Digest sourcePixels;
  if (response == refresh::Response::NotModified) {
    if (!refresh::overlayChanged(lastDisplayed, battery::key(batteryIndicator))) {
      if (responseETag.length() != 0) refresh::setETag(lastDisplayed, responseETag.c_str());
      DebugSerial.println("Image and battery indicator unchanged; skipping e-paper refresh.");
      return true;
    }
    if (loadKnownCachedFrame(sourcePixels)) {
      if (responseETag.length() == 0) responseETag = refresh::requestETag(lastDisplayed);
      DebugSerial.println("Image unchanged; refreshing only because the battery indicator changed.");
      return displayPreparedFrame(sourcePixels, responseETag, false);
    }
    // Missing/corrupt cache: force a body instead of guessing the background.
    DebugSerial.println("Re-downloading unconditionally to restore the source cache.");
    response = downloadImage(displayConfig::imageUrl, responseETag, expectedBytes, false);
    if (response == refresh::Response::Deferred) return true;
    if (response != refresh::Response::Downloaded) return false;
  }
  if (!prepareSourceFrame(temporaryImagePath, sourcePixels)) {
    LittleFS.remove(temporaryImagePath);
    updateBatteryFromCache();
    return false;
  }
  return displayPreparedFrame(sourcePixels, responseETag, true);
}

}  // namespace

void setup() {
  boardPower::begin();
  // In particular, configure the large board's display power switch OFF
  // before filesystem/allocation/network operations can fail.
  panel.begin();
  // Serial is the ESP32-S3's native USB CDC port. It is available while the
  // chip is awake and disappears when timer deep sleep begins.
  DebugSerial.begin(115200);
  delay(1500);
  setStatusLed(0, 0, 0);
  DebugSerial.println("\nFederFunk starting...");
  boardPower::disableUnusedAudio();
  DebugSerial.printf("Display: %s, %ux%u, %u-byte frame.\n",
                     displayConfig::name, DisplayPanel::width,
                     DisplayPanel::height,
                     static_cast<unsigned>(DisplayPanel::frameBytes));

  if (!initializeRefreshState()) {
    DebugSerial.println("Could not initialize image change detection.");
#ifndef BIRDDISPLAY_DIAGNOSTIC_NO_WIFI
    blinkStatus(false);
    enterDeepSleep();
#endif
    return;
  }
  // Read with Wi-Fi and display power off to reduce load-induced voltage sag.
  sampleBattery();

  if (!LittleFS.begin(true)) {
    DebugSerial.println("LittleFS mount failed.");
#ifndef BIRDDISPLAY_DIAGNOSTIC_NO_WIFI
    blinkStatus(false);
    enterDeepSleep();
#endif
    return;
  }

  if (psramFound()) {
    frame = static_cast<uint8_t*>(heap_caps_malloc(
        DisplayPanel::frameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    DebugSerial.printf("PSRAM available: %u bytes.\n", ESP.getPsramSize());
  } else {
    frame = static_cast<uint8_t*>(
        heap_caps_malloc(DisplayPanel::frameBytes, MALLOC_CAP_8BIT));
    DebugSerial.println("PSRAM unavailable; using internal RAM for framebuffer.");
  }
  if (frame == nullptr) {
    DebugSerial.printf("Could not allocate the %u-byte display framebuffer.\n",
                       static_cast<unsigned>(DisplayPanel::frameBytes));
#ifndef BIRDDISPLAY_DIAGNOSTIC_NO_WIFI
    blinkStatus(false);
    enterDeepSleep();
#endif
    return;
  }

  DebugSerial.println("E-paper SPI bus ready.");
#ifdef BIRDDISPLAY_DIAGNOSTIC_NO_WIFI
  DebugSerial.println("Diagnostic mode: Wi-Fi startup skipped.");
#else
  DebugSerial.println("Starting network fetch...");
  blinkStatus(fetchAndDisplay());
  enterDeepSleep();
#endif
}

void loop() {
  // Normal operation never reaches loop(): setup() checks for an update and
  // enters timer deep sleep. Keep diagnostic builds responsive without a busy loop.
  delay(1000);
}
