#include "RefreshState.h"
#include "ScheduleHold.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>

int main() {
  assert(scheduleHold::parseSeconds(nullptr) == 0);
  for (const char* invalid : {"", "0", "0000", "-1", "+60", " 60", "60 ",
                              "60.0", "1e3", "30,60", "90\r\n", "100seconds",
                              "999999999999999999999x"}) {
    assert(scheduleHold::parseSeconds(invalid) == 0);
  }
  assert(scheduleHold::parseSeconds("1") == 1);
  assert(scheduleHold::parseSeconds("00060") == 60);
  assert(scheduleHold::parseSeconds("86399") == 86399);
  assert(scheduleHold::parseSeconds("86400") == 86400);
  assert(scheduleHold::parseSeconds("86401") == 86400);
  assert(scheduleHold::parseSeconds("4294967296") == 86400);
  assert(scheduleHold::parseSeconds(std::string(1000, '9').c_str()) == 86400);

  for (bool conditional : {false, true}) {
    for (int status : {200, 304}) {
      assert(refresh::classifyResponse(status, conditional, 1) == refresh::Response::Deferred);
      assert(refresh::classifyResponse(status, conditional, 86400) == refresh::Response::Deferred);
    }
    for (int status : {-1, 204, 301, 302, 400, 404, 500, 503}) {
      assert(refresh::classifyResponse(status, conditional, 86400) == refresh::Response::Failed);
    }
    assert(refresh::classifyResponse(200, conditional, 0) == refresh::Response::Downloaded);
  }
  assert(refresh::classifyResponse(304, false, 0) == refresh::Response::Failed);
  assert(refresh::classifyResponse(304, true, 0) == refresh::Response::NotModified);

  // Holds neither claim a successful display nor replace remembered ETags or
  // pixels; a cold state still requests its first real frame after the pause.
  refresh::State state{};
  refresh::Digest context{};
  context[0] = 4;
  assert(refresh::classifyResponse(200, false, 100) == refresh::Response::Deferred);
  assert(!refresh::resume(state, true, context));
  refresh::Digest pixels{};
  pixels[0] = 8;
  refresh::remember(state, context, pixels, "\"known\"");
  const auto before = state;
  assert(refresh::classifyResponse(304, true, 100) == refresh::Response::Deferred);
  assert(std::memcmp(&state, &before, sizeof(state)) == 0);

  constexpr uint32_t normal = 30UL * 60UL * 1000UL;
  assert(scheduleHold::sleepMicroseconds(normal, 0) == 1800000000ULL);
  assert(scheduleHold::sleepMicroseconds(normal, 1) == 1000000ULL);
  assert(scheduleHold::sleepMicroseconds(normal, 60) == 60000000ULL);
  assert(scheduleHold::sleepMicroseconds(normal, 86400) == 86400000000ULL);
  assert(scheduleHold::sleepMicroseconds(normal, UINT32_MAX) == 86400000000ULL);
  assert(scheduleHold::sleepMicroseconds(UINT32_MAX, 0) == 4294967295000ULL);
  puts("PASS: strict schedule holds, status gating, retry semantics and 64-bit sleep duration.");
}
