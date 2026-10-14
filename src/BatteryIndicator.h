#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace battery {

enum class ChargeState : uint8_t { Unknown, Charging, NotCharging };

inline const char* chargeLabel(ChargeState state) {
  switch (state) {
    case ChargeState::Charging: return "CHARGING";
    case ChargeState::NotCharging: return "NOT CHARGING";
    default: return "UNKNOWN";
  }
}

// STAT HIGH is not proof of a full battery: it can also be idle/unpowered.
// Reject unstable samples and require the installation's confirmed cell.
inline ChargeState classifyCharge(unsigned lowSamples, unsigned count,
                                 bool installed, bool voltageValid) {
  if (!installed || !voltageValid || count < 16 || lowSamples > count)
    return ChargeState::Unknown;
  if (lowSamples == count) return ChargeState::Charging;
  if (lowSamples == 0) return ChargeState::NotCharging;
  return ChargeState::Unknown;
}

struct Indicator {
  bool visible;
  bool low;
  uint8_t percentage;
  ChargeState charge;
  constexpr Indicator(bool shown = false, bool warning = false, uint8_t percent = 0,
                      ChargeState state = ChargeState::Unknown)
      : visible(shown), low(warning), percentage(percent), charge(state) {}
};

inline uint16_t key(const Indicator& indicator) {
  return indicator.visible
             ? static_cast<uint16_t>(0x100 | (indicator.low ? 0x200 : 0) |
                                     indicator.percentage |
                                     (static_cast<uint16_t>(indicator.charge) << 10))
             : 0;
}

inline Indicator fromKey(uint16_t value) {
  return {(value & 0x100) != 0, (value & 0x200) != 0,
          static_cast<uint8_t>(value & 0x7F),
          static_cast<ChargeState>((value >> 10) & 3)};
}

inline bool validVoltage(float volts) {
  // Reject failed/disconnected readings, rather than displaying a fake 0%.
  return std::isfinite(volts) && volts >= 2.5f && volts <= 4.5f;
}

template <typename ReadMilliVolts>
float sampleVoltage(ReadMilliVolts read, float divider, float calibration) {
  uint32_t samples[32];
  size_t count = 0;
  for (size_t i = 0; i < 32; ++i) {
    const uint32_t sample = read();
    if (sample != 0) samples[count++] = sample;
  }
  if (count < 24) return 0.0f;
  // Trim the upper/lower quarters to reject occasional ADC noise/outliers.
  for (size_t i = 1; i < count; ++i) {
    const uint32_t value = samples[i];
    size_t j = i;
    while (j > 0 && samples[j - 1] > value) {
      samples[j] = samples[j - 1];
      --j;
    }
    samples[j] = value;
  }
  const size_t trim = count / 4;
  uint64_t total = 0;
  for (size_t i = trim; i < count - trim; ++i) total += samples[i];
  return static_cast<float>(total) / (count - 2 * trim) * 0.001f * divider * calibration;
}

inline Indicator evaluate(float volts, const Indicator& previous,
                          float threshold, float hysteresis, bool onlyWhenLow,
                          float emptyVoltage, float fullVoltage,
                          unsigned percentageStep) {
  if (!validVoltage(volts)) return previous;
  const bool low = previous.low ? volts < threshold + hysteresis
                               : volts < threshold;
  float fraction = (volts - emptyVoltage) / (fullVoltage - emptyVoltage);
  if (fraction < 0.0f) fraction = 0.0f;
  if (fraction > 1.0f) fraction = 1.0f;
  const unsigned percent = static_cast<unsigned>(fraction * 100.0f + 0.5f);
  unsigned rounded =
      ((percent + percentageStep / 2) / percentageStep) * percentageStep;
  if (rounded > 100) rounded = 100;
  return {!onlyWhenLow || low, low, static_cast<uint8_t>(rounded)};
}

// A deliberately small, opaque badge. Never change any pixels outside it.
constexpr int badgeMargin = 16;
constexpr int badgeWidth = 384;
constexpr int badgeHeight = 56;

inline void pixel(uint8_t* frame, int width, int height, int x, int y,
                  uint8_t code) {
  if (x < 0 || x >= width || y < 0 || y >= height) return;
  const size_t index = (static_cast<size_t>(y) * width + x) / 2;
  if ((x & 1) == 0) {
    frame[index] = static_cast<uint8_t>((frame[index] & 0x0F) | (code << 4));
  } else {
    frame[index] = static_cast<uint8_t>((frame[index] & 0xF0) | code);
  }
}

inline void rectangle(uint8_t* frame, int width, int height, int x, int y,
                      int w, int h, uint8_t code) {
  for (int row = y; row < y + h; ++row) {
    for (int col = x; col < x + w; ++col) pixel(frame, width, height, col, row, code);
  }
}

// Original 5x7 numeric glyphs; each byte is a row, most significant pixel first.
inline void glyph(uint8_t* frame, int width, int height, int x, int y, char c) {
  static constexpr uint8_t rows[][7] = {
      {14, 17, 19, 21, 25, 17, 14},  // 0
      {4, 12, 4, 4, 4, 4, 14},      // 1
      {14, 17, 1, 2, 4, 8, 31},     // 2
      {30, 1, 1, 14, 1, 1, 30},     // 3
      {2, 6, 10, 18, 31, 2, 2},     // 4
      {31, 16, 16, 30, 1, 1, 30},   // 5
      {14, 16, 16, 30, 17, 17, 14}, // 6
      {31, 1, 2, 4, 8, 8, 8},       // 7
      {14, 17, 17, 14, 17, 17, 14}, // 8
      {14, 17, 17, 15, 1, 1, 14},   // 9
      {17, 18, 2, 4, 8, 9, 17},    // %
  };
  const int index = c == '%' ? 10 : c - '0';
  if (index < 0 || index > 10) return;
  constexpr int scale = 3;
  for (int row = 0; row < 7; ++row) {
    for (int col = 0; col < 5; ++col) {
      if ((rows[index][row] & (1 << (4 - col))) != 0) {
        rectangle(frame, width, height, x + col * scale, y + row * scale,
                  scale, scale, 0);  // Black.
      }
    }
  }
}

inline void chargeGlyph(uint8_t* frame, int width, int height, int x, int y, char c) {
  // Original 5x7 uppercase glyphs used by the three charge-state labels.
  static constexpr char letters[] = "ACGHIKNORTUW";
  static constexpr uint8_t rows[][7] = {
      {14,17,17,31,17,17,17}, {14,17,16,16,16,17,14},
      {14,17,16,23,17,17,14}, {17,17,17,31,17,17,17},
      {31,4,4,4,4,4,31}, {17,18,20,24,20,18,17},
      {17,25,25,21,19,19,17}, {14,17,17,17,17,17,14},
      {30,17,17,30,20,18,17}, {31,4,4,4,4,4,4},
      {17,17,17,17,17,17,14}, {17,17,17,21,21,21,10}};
  for (size_t index = 0; letters[index]; ++index) {
    if (letters[index] != c) continue;
    for (int row = 0; row < 7; ++row)
      for (int col = 0; col < 5; ++col)
        if (rows[index][row] & (1 << (4 - col)))
          rectangle(frame, width, height, x + col * 2, y + row * 2, 2, 2, 0);
    break;
  }
}

inline void draw(uint8_t* frame, int width, int height, const Indicator& indicator) {
  if (!indicator.visible || frame == nullptr) return;
  const int x = badgeMargin;
  const int y = height - badgeMargin - badgeHeight;
  rectangle(frame, width, height, x, y, badgeWidth, badgeHeight, 1);  // White paper.
  const int bx = x + 10;
  const int by = y + 11;
  const uint8_t border = indicator.low ? 3 : 0;  // Red warning / black normal.
  const uint8_t fill = indicator.low ? 3 : 6;    // Red warning / green normal.
  rectangle(frame, width, height, bx, by, 64, 34, border);
  rectangle(frame, width, height, bx + 3, by + 3, 58, 28, 1);
  rectangle(frame, width, height, bx + 64, by + 11, 6, 12, border);
  rectangle(frame, width, height, bx + 6, by + 6,
            52 * indicator.percentage / 100, 22, fill);
  if (indicator.low) {
    // Exclamation mark remains legible even when the fill extends underneath.
    rectangle(frame, width, height, bx + 42, by + 5, 12, 24, 1);
    rectangle(frame, width, height, bx + 46, by + 7, 4, 13, 3);
    rectangle(frame, width, height, bx + 46, by + 24, 4, 4, 3);
  }
  char text[5];
  std::snprintf(text, sizeof(text), "%u%%", static_cast<unsigned>(indicator.percentage));
  for (size_t i = 0; text[i] != '\0'; ++i) {
    glyph(frame, width, height, x + 92 + static_cast<int>(i) * 18, y + 18, text[i]);
  }
  const char* charge = chargeLabel(indicator.charge);
  for (size_t i = 0; charge[i]; ++i)
    chargeGlyph(frame, width, height, x + 210 + static_cast<int>(i) * 12,
                y + 21, charge[i]);
}

}  // namespace battery
