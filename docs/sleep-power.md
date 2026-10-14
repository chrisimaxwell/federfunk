# Integrated 13.3-inch board sleep power

Thomas's reported baseline is about **11.06 mA asleep**, at roughly 4.10 V
through the battery input with USB disconnected. It is a whole-board
measurement. On **2026-10-14**, the installed audio shutdown firmware reported
both codecs confirmed and completed a display refresh followed by sleep.
The revised battery-only warning and dashboard telemetry were also installed
and verified that day: a valid 100% estimate kept the warning off, the dashboard
received the charging state, and the frame completed its refresh and entered
30-minute sleep. The owner confirmed the revised artwork colors.
**Sleep current after audio shutdown has not yet been measured.** Do not
replace the baseline with an estimated lower figure.

## What this change turns off

`src/BoardPower.h` runs only for the integrated 13.3-inch profile. The
7.3-inch breakout does not touch these pins or attempt audio I2C transactions.

| Part | Connection | Action |
| --- | --- | --- |
| NS4150B speaker amplifier, U10 | PA_CTRL / GPIO13 | Drive LOW before other setup; retain LOW in deep sleep |
| ES8311 output codec, U8 | Audio I2C, 7-bit address 0x18 | Apply Espressif's suspend sequence; check final analog-power and reset registers |
| ES7210 microphone ADC, U9 | Audio I2C, 7-bit address 0x40 | Disable all four microphone channels, their bias, analog circuitry, clocks and DLL; check final registers |
| Audio I2C | SDA GPIO41, SCL GPIO42 | Use a 25 ms transaction timeout; stop Wire and release both pins as inputs afterward |

The schematic connects the codecs to the board's 3.3 V supply, not to the
panel's switched rail. The microphones are supplied by ES7210 MICBIAS12.
Merely sleeping the ESP32 or switching off the display does not send these
audio devices their shutdown commands. FederFunk does not use local audio.

Shutdown happens on every boot before battery sampling, filesystem allocation
and networking. This also handles audio state left by a previous sketch or
retained across an ESP32-only reset. Every normal success/failure path still
enters timer sleep. A missing codec, failed write or failed
readback is reported as `unconfirmed`; it does not prevent the other codec's
shutdown attempt, the amplifier hold, or sleep. No I2C scan or retry loop is
used. The log's `confirmed` means register writes/readback succeeded, not that
the electrical current has been measured.

The existing display shutdown, interface-pin holds, Wi-Fi shutdown, charging
status input cleanup and default 30-minute interval are preserved. The code does not
alter charger configuration, eFuses, flash/PSRAM power modes, or undocumented
power-control pins.

## Hardware verification still required

1. The 2026-10-14 large-profile test captured `Audio shutdown: ES8311 confirmed;
   ES7210 confirmed.` and a completed refresh/sleep cycle. Repeat log and image
   verification after later firmware changes, uploading only when authorized.
2. Repeat Thomas's battery-input measurement at the same supply voltage, with
   USB fully disconnected and the same SD-card/accessory state. Wait at least
   60 seconds after entering sleep; record mean/min/max over a steady interval.
   USB disconnect by itself is not evidence of low current.
3. Measure after a cold start, an actual timer wake with an unchanged image,
   and a deliberately unreachable image server. All should settle to the same
   sleep state. At least one full timer wake must download/display successfully.
4. For an A/B comparison, build once with
   `-D BIRDDISPLAY_AUDIO_POWERDOWN=0` appended to the large environment's
   `build_flags`, retaining its existing flags. This bypasses only this new
   audio cleanup. **Fully remove battery and USB power between the two runs**:
   the codec shutdown state can survive an ESP32 reset and otherwise invalidate
   the comparison. Remove the flag for the normal build.
5. If current remains high, record each codec's result first. Then measure
   board loads independently, including an inserted SD card and the existing
   power-converter/USB circuitry. Do not guess new GPIO rail controls. Further
   reduction could require board-level changes, which this patch does not make.

| Measurement | Battery voltage | SD/accessories | Sleep current | Notes |
| --- | --- | --- | --- | --- |
| Reported prior baseline | ~4.10 V | Record original setup | ~11.06 mA | USB disconnected |
| Audio shutdown, observed boot | Not recorded | Not recorded | Pending | Both codecs confirmed; refresh then sleep on 2026-10-14 |
| New code, timer wake | Pending | Same | Pending | Image unchanged |
| New code, network failure | Pending | Same | Pending | Reaches sleep |
| Audio-cleanup-disabled A/B | Pending | Same | Pending | Full power cycle first |

## Sources

- [Waveshare board schematic, sheet 1](https://files.waveshare.com/wiki/ESP32-S3-ePaper-13.3E6/ESP32-S3-ePaper-Driver-Board.pdf):
  GPIO signal table, codec supply/address straps, amplifier CTRL, microphone bias.
- [Waveshare board audio configuration](https://github.com/waveshareteam/ESP32-S3-ePaper-13.3E6/blob/main/example/ESP-IDF-5.5.1/02_Mic_test/components/codec_board/board_cfg.txt):
  `S3_ePaper_Driver_Board` confirms GPIO41/42 and amplifier GPIO13.
- [Waveshare audio cleanup](https://github.com/waveshareteam/ESP32-S3-ePaper-13.3E6/blob/main/example/ESP-IDF-5.5.1/03_Music/components/es8311_bsp/es8311_bsp.c):
  explicitly drives the amplifier pin LOW when shutting down.
- [Espressif ES8311 driver](https://github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es8311/es8311.c):
  `es8311_suspend()` register sequence.
- [Espressif ES7210 driver](https://github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es7210/es7210.c):
  `es7210_stop()` register sequence. ADF's address 0x80 is the 8-bit form;
  Arduino Wire uses the 7-bit 0x40 address shown on the board schematic.
- [Espressif GPIO hold documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/gpio.html):
  hold/release ordering and `gpio_deep_sleep_hold_en()` for ESP32-S3.

The two register sequences are adapted from Espressif's Apache-2.0 licensed
drivers; attribution and license are included in `LICENSE.espressif`.

## Automated checks

`python3 -m unittest discover -s tests -p 'test_board_power.py'` compiles the
actual header with address/undefined-behavior sanitizers. It checks successful
shutdown, independent missing-device failures, mid-sequence write failure,
short/corrupt readback, failed bus initialization, amplifier hold/wake behavior,
bounded transaction counts, correct seven-bit addresses, small-board isolation,
and the disabled A/B configuration. It runs with the existing Python test suite
in CI. Both PlatformIO environments must also build after shared changes.

## Scheduled overnight holds

The optional Naturalist server schedule adds `X-FederFunk-Hold-Seconds` to
successful image responses while updates are paused. The firmware accepts a
positive decimal duration only on HTTP 200/304 and caps it at 86400 seconds.
It skips the response body and all image/battery-badge refresh work, leaves
the source cache and last-displayed fingerprint untouched, and sleeps for that
duration. Even a cold/manual wake during a pause leaves the physical screen
alone. A short remaining duration replaces the normal interval so the frame
can wake near sunrise instead of sleeping an extra 30 minutes.

The hold is not stored across wakes. Without a valid hold header the original
behavior applies, including a 30-minute retry on network failure and a possible
cached battery-warning update. Thus an unreachable server on a later/manual
wake cannot communicate an overnight pause; the firmware does not guess the
sunrise or silently suppress its existing battery warning. The server's
calendar remains the authority. Test a hold followed by a real wake and active
response on the board before relying on the schedule.

`python3 -m unittest discover -s tests -p 'test_schedule_hold.py'` checks malformed
and overflowing headers, HTTP status gating, cold/conditional response handling,
unchanged RTC state, the one-day cap and 64-bit microsecond durations. The
Naturalist schedule tests separately cover solar events, DST, crossing midnight,
date-crossing offsets, polar fallback and settings validation.
