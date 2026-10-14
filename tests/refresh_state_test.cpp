/* Host test: clang++ -std=c++17 -Wall -Wextra -Werror -Isrc
 * tests/refresh_state_test.cpp -o /tmp/federfunk-refresh-test
 */
#include "RefreshState.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <type_traits>

int main() {
  static_assert(std::is_trivial<refresh::State>::value, "RTC data has no constructor");
  static_assert(std::is_trivially_copyable<refresh::State>::value, "RTC data is POD");
  static_assert(sizeof(refresh::State) <= 512, "Keep RTC usage small");
  refresh::Digest context{};
  context[0] = 1;
  refresh::Digest firstPixels{};
  firstPixels[0] = 2;
  refresh::Digest changedPixels = firstPixels;
  changedPixels.back() ^= 1;
  refresh::State state{};

  // First boot: always download, even if the server incorrectly sends a 304.
  assert(!refresh::resume(state, false, context));
  assert(!refresh::matchesPixels(state, firstPixels));
  assert(std::strcmp(refresh::requestETag(state), "") == 0);
  assert(refresh::classifyResponse(304, false) == refresh::Response::Failed);
  assert(refresh::classifyResponse(200, false) == refresh::Response::Downloaded);

  // Remember only a validated frame successfully displayed, then timer wake.
  refresh::remember(state, context, firstPixels, "\"first\"");
  assert(refresh::resume(state, true, context));
  assert(std::strcmp(refresh::requestETag(state), "\"first\"") == 0);
  assert(refresh::classifyResponse(304, true) == refresh::Response::NotModified);
  assert(refresh::matchesPixels(state, firstPixels));
  assert(!refresh::matchesPixels(state, changedPixels));

  // Download/validation failures don't replace the known-good state or tag.
  const auto goodState = state;
  for (int status : {-1, 204, 404, 500}) {
    assert(refresh::classifyResponse(status, true) == refresh::Response::Failed);
  }
  assert(refresh::resume(state, true, context));
  assert(refresh::matchesPixels(state, firstPixels));

  // HTTP 200 can render to identical pixels despite a different ETag (JPEG
  // metadata/recompression, for example). Skip refresh and adopt its new tag.
  assert(refresh::classifyResponse(200, true) == refresh::Response::Downloaded);
  refresh::remember(state, context, firstPixels, "\"new-tag-same-pixels\"");
  assert(refresh::matchesPixels(state, firstPixels));
  assert(std::strcmp(refresh::requestETag(state), "\"new-tag-same-pixels\"") == 0);

  // Missing ETag: retain the pixel hash, but never send a stale validator.
  refresh::remember(state, context, firstPixels, "");
  assert(refresh::resume(state, true, context));
  assert(refresh::matchesPixels(state, firstPixels));
  assert(std::strcmp(refresh::requestETag(state), "") == 0);
  assert(refresh::classifyResponse(304, false) == refresh::Response::Failed);

  // Start any physical refresh by invalidating the old state. After a partial
  // failure even the old picture must refresh again, not return a false skip.
  state = goodState;
  refresh::invalidate(state);
  assert(!refresh::resume(state, true, context));
  assert(!refresh::matchesPixels(state, firstPixels));
  assert(!refresh::matchesPixels(state, changedPixels));
  assert(std::strcmp(refresh::requestETag(state), "") == 0);
  refresh::remember(state, context, changedPixels, "\"changed\"");
  assert(refresh::matchesPixels(state, changedPixels));
  assert(!refresh::matchesPixels(state, firstPixels));

  // A reset/power cycle, new URL/canvas/render settings, or incompatible RTC
  // state forces an unconditional download and a new refresh.
  assert(!refresh::resume(state, false, context));
  refresh::remember(state, context, firstPixels, "\"first\"");
  auto changedContext = context;
  changedContext.back() ^= 1;
  assert(!refresh::resume(state, true, changedContext));
  assert(!refresh::matchesPixels(state, firstPixels));
  state = goodState;
  ++state.version;
  assert(!refresh::resume(state, true, context));
  state = goodState;
  std::memset(state.etag, 'x', sizeof(state.etag));
  assert(!refresh::resume(state, true, context));

  // RFC entity-tags, bounded and complete. Never send unquoted tags,
  // wildcard/list values, injected headers, or silently truncated long tags.
  assert(refresh::validETag("\"\""));
  assert(refresh::validETag("\"strong\""));
  assert(refresh::validETag("W/\"weak\""));
  assert(refresh::validETag("W/\"\""));
  assert(!refresh::validETag(nullptr));
  for (const char* tag : {"", "*", "unquoted", "\"", "W/\"", "\"space tag\"",
                          "\"a\", \"b\"", "\"bad\r\nheader\"", "\"bad\x7F\""}) {
    assert(!refresh::validETag(tag));
    refresh::remember(state, context, firstPixels, tag);
    assert(refresh::matchesPixels(state, firstPixels));
    assert(std::strcmp(refresh::requestETag(state), "") == 0);
  }
  const std::string longestTag = "\"" + std::string(refresh::etagCapacity - 3, 'a') + "\"";
  assert(refresh::validETag(longestTag.c_str()));
  refresh::remember(state, context, firstPixels, longestTag.c_str());
  assert(std::strcmp(refresh::requestETag(state), longestTag.c_str()) == 0);
  const std::string oversizedTag = longestTag + "\"";
  assert(!refresh::validETag(oversizedTag.c_str()));
  refresh::setETag(state, oversizedTag.c_str());
  assert(std::strcmp(refresh::requestETag(state), "") == 0);
  assert(refresh::matchesPixels(state, firstPixels));

  puts("PASS: conditional HTTP, identical/changed pixels, RTC wake/reset, "
       "failure retry, context binding, and bounded ETags verified.");
}
