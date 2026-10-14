#pragma once

#include <stdint.h>

namespace scheduleHold {
constexpr char headerName[] = "X-FederFunk-Hold-Seconds";
constexpr uint32_t maximumSeconds = 86400;

// The server can defer a display update until its active window resumes.
// Reject signs, whitespace, fractions, lists and trailing junk. Saturate large
// decimal values without integer overflow, but still validate every character.
inline uint32_t parseSeconds(const char* value) {
  if (value == nullptr || *value == '\0') return 0;
  uint32_t seconds = 0;
  for (const char* next = value; *next != '\0'; ++next) {
    if (*next < '0' || *next > '9') return 0;
    const uint32_t digit = static_cast<uint32_t>(*next - '0');
    if (seconds > (maximumSeconds - digit) / 10) {
      seconds = maximumSeconds;
    } else {
      seconds = seconds * 10 + digit;
    }
  }
  return seconds;
}

inline uint64_t sleepMicroseconds(uint32_t defaultIntervalMs, uint32_t seconds) {
  if (seconds == 0) return static_cast<uint64_t>(defaultIntervalMs) * 1000ULL;
  if (seconds > maximumSeconds) seconds = maximumSeconds;
  // A short remaining hold replaces, rather than extends, the normal interval
  // so a wake a few seconds before sunrise does not sleep another 30 minutes.
  return static_cast<uint64_t>(seconds) * 1000000ULL;
}
}  // namespace scheduleHold
