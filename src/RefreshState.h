#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace refresh {

constexpr size_t digestBytes = 32;
constexpr size_t etagCapacity = 256;
constexpr uint32_t stateVersion = 0x46465204;  // "FFR", version 4 (low-only badge).
using Digest = std::array<uint8_t, digestBytes>;

// Plain data with no constructor: safe to retain in RTC memory across sleep.
struct State {
  uint32_t version;
  Digest context;
  Digest pixels;
  Digest sourcePixels;
  uint16_t overlayKey;
  char etag[etagCapacity];
};

inline void invalidate(State& state) { state = {}; }

inline bool resume(State& state, bool timerWake, const Digest& context) {
  if (!timerWake || state.version != stateVersion || state.context != context ||
      std::memchr(state.etag, '\0', sizeof(state.etag)) == nullptr) {
    invalidate(state);
    return false;
  }
  return true;
}

// Accept only a complete HTTP entity-tag, never a truncated tag or a wildcard.
inline bool validETag(const char* tag) {
  if (tag == nullptr) return false;
  const size_t length = std::strlen(tag);
  if (length < 2 || length >= etagCapacity) return false;
  const size_t start = length >= 4 && tag[0] == 'W' && tag[1] == '/' ? 2 : 0;
  if (tag[start] != '"' || tag[length - 1] != '"') return false;
  for (size_t i = start + 1; i < length - 1; ++i) {
    const auto c = static_cast<unsigned char>(tag[i]);
    if (c < 0x21 || c == '"' || c == 0x7F) return false;
  }
  return true;
}

inline void setETag(State& state, const char* tag) {
  state.etag[0] = '\0';
  if (validETag(tag)) std::memcpy(state.etag, tag, std::strlen(tag) + 1);
}

inline const char* requestETag(const State& state) {
  return state.version == stateVersion ? state.etag : "";
}

enum class Response { Failed, Downloaded, NotModified, Deferred };

inline Response classifyResponse(int httpStatus, bool sentETag,
                                 uint32_t holdSeconds = 0) {
  // A schedule hold requests no display work, not proof that a frame is on
  // the panel. It is valid on a cold wake as well as a conditional request.
  if ((httpStatus == 200 || httpStatus == 304) && holdSeconds > 0) {
    return Response::Deferred;
  }
  if (httpStatus == 200) return Response::Downloaded;
  // An unsolicited 304 does not prove anything is already on this screen.
  if (httpStatus == 304 && sentETag) return Response::NotModified;
  return Response::Failed;
}

inline bool matchesPixels(const State& state, const Digest& pixels) {
  return state.version == stateVersion && state.pixels == pixels;
}

inline bool matchesSource(const State& state, const Digest& pixels) {
  return state.version == stateVersion && state.sourcePixels == pixels;
}

inline bool overlayChanged(const State& state, uint16_t overlayKey) {
  return state.version != stateVersion || state.overlayKey != overlayKey;
}

// Call only after a successful refresh, or a comparison with that same frame.
inline void remember(State& state, const Digest& context, const Digest& pixels,
                     const char* etag, const Digest& sourcePixels,
                     uint16_t overlayKey) {
  invalidate(state);
  state.context = context;
  state.pixels = pixels;
  state.sourcePixels = sourcePixels;
  state.overlayKey = overlayKey;
  setETag(state, etag);
  state.version = stateVersion;
}

// No-overlay convenience overload, also used by the small-board host tests.
inline void remember(State& state, const Digest& context, const Digest& pixels,
                     const char* etag) {
  remember(state, context, pixels, etag, pixels, 0);
}

}  // namespace refresh
