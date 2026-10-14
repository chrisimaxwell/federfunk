/* Host test: clang++ -std=c++17 -Wall -Wextra -Werror -Isrc
 * tests/battery_indicator_test.cpp -o /tmp/federfunk-battery-test
 */
#include "BatteryConfig.h"
#include "BatteryIndicator.h"
#include "BatteryTelemetry.h"
#include "RefreshState.h"
#include <array>
#include <cassert>
#include <fstream>
#include <limits>
#include <map>
#include <string>
#include <vector>

uint8_t getPixel(const std::vector<uint8_t>& frame, int width, int x, int y) {
  const uint8_t byte = frame[(static_cast<size_t>(y) * width + x) / 2];
  return (x & 1) == 0 ? byte >> 4 : byte & 0x0F;
}

battery::Indicator evaluate(float volts, battery::Indicator previous = {}) {
  return battery::evaluate(volts, previous, 15, 3.3f, 4.2f);
}

float voltageForPercent(unsigned percentage) {
  return 3.3f + 0.009f * percentage;
}

int main(int argc, char** argv) {
  using battery::ChargeState;
  assert(battery::classifyCharge(32, 32, true, true) == ChargeState::Charging);
  assert(battery::classifyCharge(0, 32, true, true) == ChargeState::NotCharging);
  for (unsigned count : {1U, 15U, 31U, 33U})
    assert(battery::classifyCharge(count, 32, true, true) == ChargeState::Unknown);
  assert(battery::classifyCharge(8, 8, true, true) == ChargeState::Unknown);
  assert(battery::classifyCharge(32, 32, false, true) == ChargeState::Unknown);
  assert(battery::classifyCharge(32, 32, true, false) == ChargeState::Unknown);
  // Strict percentage threshold: no hysteresis may leave a warning at15%.
  auto healthy = evaluate(3.5f);
  assert(!healthy.low && !healthy.visible && battery::key(healthy) == 0);
  auto low = evaluate(voltageForPercent(14), healthy);
  assert(low.low && low.visible);
  assert(low.percentage == 14);
  auto recovered = evaluate(voltageForPercent(15), low);
  assert(!recovered.low && !recovered.visible);
  assert(battery::key(recovered) == 0);
  for (unsigned percent = 0; percent <= 100; ++percent) {
    const auto state = evaluate(voltageForPercent(percent), low);
    assert(state.percentage == percent);
    assert(state.visible == (percent < 15));
    assert(state.low == (percent < 15));
    if (percent >= 15) assert(battery::key(state) == 0);
  }
  for (float bad : {0.0f, -1.0f, 2.49f, 4.51f,
                    std::numeric_limits<float>::infinity(),
                    std::numeric_limits<float>::quiet_NaN()}) {
    assert(battery::key(evaluate(bad, low)) == battery::key(low));
    assert(battery::key(evaluate(bad, healthy)) == 0);
  }
  assert(evaluate(2.5f).percentage == 0);
  assert(evaluate(3.3f).percentage == 0);
  assert(evaluate(4.2f).percentage == 100);
  assert(evaluate(4.5f).percentage == 100);
  assert(evaluate(3.75f).percentage == 50);
  assert(evaluate(3.74f).percentage == 49);
  assert(evaluate(3.76f).percentage == 51);
  assert(!evaluate(3.70f).visible);
  const auto changedThreshold = battery::evaluate(3.65f, {}, 40, 3.3f, 4.2f);
  assert(changedThreshold.low && changedThreshold.visible);
  for (const auto indicator : {low, healthy, evaluate(3.75f), evaluate(4.2f)}) {
    assert(battery::key(battery::fromKey(battery::key(indicator))) == battery::key(indicator));
  }

  // The real sampling algorithm: trim outliers, reject too many failed reads,
  // scale the 3:1 board divider, and apply user voltage calibration.
  std::array<uint32_t, 32> samples;
  samples.fill(1200);
  size_t readIndex = 0;
  auto read = [&]() { return samples.at(readIndex++); };
  auto volts = battery::sampleVoltage(read, 3.0f, 1.0f);
  assert(readIndex == 32 && std::fabs(volts - 3.6f) < 0.001f);
  for (size_t i = 0; i < 8; ++i) samples[i] = 50;
  for (size_t i = 24; i < 32; ++i) samples[i] = 3000;
  readIndex = 0;
  volts = battery::sampleVoltage(read, 3.0f, 1.0f);
  assert(std::fabs(volts - 3.6f) < 0.001f);
  samples.fill(1200);
  for (size_t i = 0; i < 8; ++i) samples[i] = 0;
  readIndex = 0;
  assert(std::fabs(battery::sampleVoltage(read, 3.0f, 1.05f) - 3.78f) < 0.001f);
  samples[8] = 0;
  readIndex = 0;
  assert(!battery::validVoltage(battery::sampleVoltage(read, 3.0f, 1.0f)));

  // Verify every pixel on the large frame. A hidden badge is byte-for-byte
  // untouched; a visible badge changes only its bottom-left rectangle.
  constexpr int width = 1600;
  constexpr int height = 1200;
  constexpr uint8_t codes[] = {0, 1, 2, 3, 5, 6};
  std::vector<uint8_t> source(width * height / 2);
  for (size_t i = 0; i < source.size(); ++i) {
    source[i] = static_cast<uint8_t>((codes[i % 6] << 4) | codes[(i + 3) % 6]);
  }
  auto frame = source;
  battery::draw(frame.data(), width, height, healthy);
  assert(frame == source);
  battery::draw(frame.data(), width, height, low);
  size_t redPixels = 0;
  size_t whitePixels = 0;
  const int top = height - battery::badgeMargin - battery::badgeHeight;
  for (int y = 0; y < height; ++y) {
    for (int x = 0; x < width; ++x) {
      const auto pixel = getPixel(frame, width, x, y);
      assert(pixel == 0 || pixel == 1 || pixel == 2 || pixel == 3 || pixel == 5 || pixel == 6);
      const bool inside = x >= battery::badgeMargin &&
                          x < battery::badgeMargin + battery::badgeWidth &&
                          y >= top && y < top + battery::badgeHeight;
      if (!inside) assert(pixel == getPixel(source, width, x, y));
      else {
        assert(pixel == 1 || pixel == 3);  // Only red ink on white paper.
        redPixels += pixel == 3;
        whitePixels += pixel == 1;
      }
    }
  }
  assert(frame != source && redPixels > 100 && whitePixels > 1000);
  auto restored = source;  // Reload original source, never erase badge to white.
  battery::draw(restored.data(), width, height, recovered);
  assert(restored == source);
  // Tiny canvases clip safely; a single written pixel preserves its neighbor.
  std::array<uint8_t, 4> tiny{};
  battery::draw(tiny.data(), 4, 2, low);
  battery::pixel(tiny.data(), 4, 2, 0, 0, 3);
  assert(tiny[0] == 0x30);
  battery::pixel(tiny.data(), 4, 2, 1, 0, 1);
  assert(tiny[0] == 0x31);
  battery::draw(nullptr, width, height, low);

  // HTTP 304 doesn't suppress a local battery change. The source hash and
  // final (overlaid) pixel hash are separate, and invalidated on refresh failure.
  refresh::State state{};
  refresh::Digest context{};
  refresh::Digest base{};
  base[0] = 1;
  refresh::Digest composite = base;
  composite[0] = 2;
  refresh::remember(state, context, base, "\"stable-image\"", base, 0);
  assert(refresh::classifyResponse(304, true) == refresh::Response::NotModified);
  assert(refresh::overlayChanged(state, battery::key(low)));
  assert(refresh::matchesSource(state, base));
  refresh::remember(state, context, composite, "\"stable-image\"", base, battery::key(low));
  assert(refresh::resume(state, true, context));
  assert(!refresh::overlayChanged(state, battery::key(low)));
  assert(refresh::overlayChanged(state, battery::key(recovered)));
  assert(refresh::matchesSource(state, base));
  assert(!refresh::matchesSource(state, composite));
  assert(refresh::matchesPixels(state, composite));
  auto changedUnderBadge = base;
  changedUnderBadge.back() = 3;
  assert(!refresh::matchesSource(state, changedUnderBadge));
  refresh::remember(state, context, composite, "\"new-source\"", changedUnderBadge,
                    battery::key(low));
  assert(refresh::matchesPixels(state, composite));
  assert(refresh::matchesSource(state, changedUnderBadge));
  refresh::invalidate(state);
  assert(!refresh::matchesSource(state, changedUnderBadge));
  assert(refresh::overlayChanged(state, battery::key(low)));
  // Telemetry carries charge state; the frame key and pixels never do.
  refresh::remember(state, context, composite, "\"same-bird\"", base, battery::key(low));
  const std::vector<uint8_t> warningPixels = frame;
  for (auto charge : {ChargeState::Unknown, ChargeState::Charging, ChargeState::NotCharging}) {
    std::map<std::string, std::string> headers;
    battery::Telemetry reading{4.16f, 96, charge};
    auto add = [&headers](const char* name, const char* value) { headers[name] = value; };
    assert(battery::addTelemetryHeaders(reading, add));
    assert(headers.size() == 3);
    assert(headers.at("X-FederFunk-Battery-Percent") == "96");
    assert(headers.at("X-FederFunk-Battery-Voltage") == "4.16");
    assert(headers.at("X-FederFunk-Charging") == battery::chargeHeader(charge));
    assert(!refresh::overlayChanged(state, battery::key(low)));
    auto unchanged = source;
    battery::draw(unchanged.data(), width, height, low);
    assert(unchanged == warningPixels);
  }
  for (float invalid : {0.0f, 2.49f, 4.51f, std::numeric_limits<float>::quiet_NaN()}) {
    unsigned calls = 0;
    assert(!battery::addTelemetryHeaders({invalid, 10, ChargeState::Unknown},
                                        [&calls](const char*, const char*) { ++calls; }));
    assert(calls == 0);
  }
  unsigned calls = 0;
  assert(!battery::addTelemetryHeaders({4.0f, 101, ChargeState::Charging},
                                      [&calls](const char*, const char*) { ++calls; }));
  assert(calls == 0);
  assert(std::string(battery::chargeHeader(ChargeState::Charging)) == "charging");
  assert(std::string(battery::chargeHeader(ChargeState::NotCharging)) == "not_charging");
  assert(std::string(battery::chargeHeader(ChargeState::Unknown)) == "unknown");

  // Optional visual QA output, created entirely by the firmware drawing code.
  if (argc == 2) {
    std::vector<uint8_t> preview(width * height / 2, 0x11);
    battery::draw(preview.data(), width, height / 3, evaluate(voltageForPercent(14)));
    battery::draw(preview.data(), width, height * 2 / 3, evaluate(voltageForPercent(5)));
    battery::draw(preview.data(), width, height, evaluate(voltageForPercent(0)));
    std::ofstream output(argv[1], std::ios::binary);
    output.write(reinterpret_cast<const char*>(preview.data()), preview.size());
    assert(output.good());
  }
  puts("PASS: strict percentage threshold, sampling/calibration, red badge bounds, "
       "charge-only telemetry, cache restoration, and 304 overlay updates verified.");
}
