# FederFunk agent playbook

FederFunk is an Arduino/PlatformIO ESP32-S3 firmware project. The user-facing
goal is a working color e-paper display that downloads an HTTP image and
deep-sleeps between refreshes. Read README.md and platformio.ini first.

## When asked to set up a display

Carry the user's requested setup through to verified hardware operation.
Don't stop at a plan or a successful build. Discover what you can yourself,
and ask only for missing settings, ambiguous hardware, or physical actions
that require the owner. A request to set up/program the connected display
authorizes the necessary build and flash of that identified device. A request
to edit/review code alone does not authorize flashing.

1. Inspect existing local changes and configuration; preserve them. If the
   checkout is missing, clone the repository the user supplied. Never reset
   or overwrite another project, local Wi-Fi settings, or uncommitted work.
2. Determine which physical display/board is in use. Use the product name,
   USB identity, and a read-only `esptool flash_id` query of the selected
   ESP32-S3. Don't infer screen size from the chip alone. If ambiguous, ask.
   Entering download mode may require the owner's BOOT/RESET button press.
3. Bootstrap with `python3 scripts/bootstrap.py` (Windows: `python`). It uses
   `.venv`, preserves existing private config, and sets up the commit guard.
   PlatformIO keeps downloaded toolchains in the ignored `.pio/core` cache.
   Reuse an existing working PlatformIO installation when appropriate. Avoid
   sudo, global Python package installs, or unnecessary toolchain upgrades.
4. Configure `src/BirdDisplayConfig.h` locally using `src/config.example.h`
   as the schema. Obtain Wi-Fi settings privately and the intended HTTP URL
   from the owner. Use a secure input mechanism if the host offers one;
   otherwise have the owner fill this ignored file locally. Never require
   posting a password into a public issue, PR, README, or command argument.
5. Validate the image endpoint and selected canvas. Raw `.bin` URLs must
   return the exact size and valid codes listed below; HTTP 200 alone is not
   enough. If no backend is available, generate a test frame and serve only
   its demo directory on the LAN. Keep the server alive through the refresh.
6. Build the explicit matching environment. Verify actual flash/PSRAM before
   upload; don't flash a 32 MB partition table onto a smaller module. If a
   hardware revision differs from the supported profile, adapt it based on
   actual memory and official board examples before uploading, or ask if its
   wiring/identity is unclear. Never change/burn eFuses to fix a build.
7. Upload over the selected native USB CDC/JTAG port. Start a serial monitor
   immediately afterward at 115200 baud, with DTR/RTS disabled. Close other
   monitors first so upload can acquire the port. Read enough of the boot log
   to verify profile, PSRAM allocation, Wi-Fi, download/validation, successful
   refresh, and sleep. Allow up to two minutes for a display refresh.
8. Report the observed result and ask the owner to confirm the visual image
   when appearance/orientation can't be observed directly. A build/upload
   does not prove a refresh. If the backend, network, or hardware prevents a
   complete update, explain the concrete evidence and next required action.

## Profiles and packed frames

| Environment | Physical hardware | Logical canvas | Raw bytes | URL setting |
| --- | --- | --- | ---: | --- |
| `esp32-s3` | Existing 16 MB flash / 8 MB PSRAM ESP32-S3 breakout with Waveshare 7.3-inch HAT (E), SKU 32694 | 800×480 | 192000 | `imageUrl` |
| `esp32-s3-13in3e6` | Integrated Waveshare ESP32-S3-ePaper-13.3E6, WROOM-2-N32R16V, 32 MB flash / 16 MB PSRAM | 1600×1200 | 960000 | `largeImageUrl` |

Small profile: QIO flash + OPI PSRAM (`qio_opi`), Arduino-ESP32 2.0.17.
Large profile: OPI flash + OPI PSRAM (`opi_opi`), Arduino-ESP32 3.2.0 via the
pinned pioarduino platform. The Waveshare docs contain inconsistent module
descriptions and a QIO screenshot; the actual connected N32R16V was verified
to require octal flash. Prefer device evidence over that screenshot.

Raw frames are landscape, row-major, left-to-right/top-to-bottom. First pixel
is the high nibble. Valid codes: black 0, white 1, yellow 2, red 3, blue 5,
green 6. There is no header. The large driver rotates addressing into native
1200×1600 portrait memory and sends 480000 bytes to each controller. Do not
rotate the backend frame again or change its codes/dithering. JPEG URLs use
the same logical canvas but require decoding and six-color conversion.

Small wiring: BUSY 7 (purple), RST 6 (white), DC 9 (green), CS 10 (orange),
MOSI 11 (blue), SCK 12 (yellow), GND (brown), 3V3 (gray). These assignments
are configurable; inspect the local config if it already exists.

Integrated large-board wiring is fixed: SCK 9, MOSI 46, master CS 10, slave
CS 3, DC 11, RST 2, BUSY 12, display power enable 1. No external jumpers are
needed. The small breakout's GPIO48 WS2812 output is disabled on this board.

Battery sensing is large-board-only: GPIO8, ADC1 channel 7, VBAT divided by
three (schematic: 2 MOhm above / 1 MOhm below the sense node). BatteryConfig.h
contains non-secret threshold/overlay settings; it does not change private
Wi-Fi configuration. The small profile must never touch a battery GPIO.
Local charging readout uses GPIO38 (ETA6098 active-LOW STAT) as an input only.
The owner confirmed a connected cell (`batteryInstalled = true`). Without
that confirmation or with unstable/invalid readings, report unknown; HIGH
means not charging, not necessarily full. Never change charger settings.

## Commands

Run from the repository root. On Windows substitute `.venv/Scripts/pio.exe`
for `.venv/bin/pio`; use the discovered serial port, never a copied example.

```sh
python3 scripts/bootstrap.py
.venv/bin/pio device list
.venv/bin/python -m esptool --chip esp32s3 --port YOUR_PORT flash_id
.venv/bin/pio run -e esp32-s3-13in3e6
.venv/bin/pio run -e esp32-s3-13in3e6 -t upload --upload-port YOUR_PORT
.venv/bin/pio device monitor --port YOUR_PORT --baud 115200 --dtr 0 --rts 0

python3 scripts/generate_test_frame.py --panel large --output demo/test.bin
python3 -m http.server 8000 --bind 0.0.0.0 --directory demo
```

Use the owner's computer LAN IP in the URL. `localhost` on the ESP32 points
at the ESP32. For a small screen, use `--panel small` and `-e esp32-s3`.
The default environment remains the small screen; always use `-e` explicitly.
Bootstrap provides esptool 4.9.0 for the read-only `flash_id` query above;
on Windows substitute `.venv/Scripts/python.exe` for `.venv/bin/python`.
PlatformIO uses its selected package for actual uploads. Espressif esptool
4.x uses `flash_id`; newer versions use `flash-id`. This project pins
toolchains and does not need a global ESP-IDF
installation. Only `http://` is implemented; do not promise HTTPS support.

## Credentials, Git, and publication

- Never commit `src/BirdDisplayConfig.h`, `.env` files, private keys, `.pio/`,
  firmware binaries, or serial logs containing private settings.
- Do not print/copy passwords or tokens into tool output, shell arguments,
  commits, public screenshots, docs, issues, or PRs. Inspect only the needed
  fields; redact output when checking existing private configuration.
- Firmware embeds credentials even though the source config is ignored.
  Do not attach a real configured firmware binary to GitHub releases.
- Run `python3 scripts/check_private_config.py` before commits/publication.
  It checks the Git index, including matching local config values. Review the
  staged paths/content as well; this guard does not detect every possible
  secret. Preserve the private config for the owner's future builds.
- Don't initialize a new repository, change remotes, or publish code unless
  the user asked for that work. Don't fabricate author identity or credentials.

## Code changes and verification

Keep board details in DisplaySelection.h and the relevant driver; keep the
HTTP/JPEG/rendering path in main.cpp independent of the selected dimensions.
Preserve six-color nibbles in raw frames. Preserve the 30-minute timer sleep
on success and failure, LED-off behavior, and large-panel power-off/hold.
The explicit daylight-schedule exception is a valid bounded
`X-FederFunk-Hold-Seconds` response: leave the entire picture and local badge
untouched and sleep until that hold expires. Never treat a hold as proof that
an image was displayed. Disable unused audio before normal operation on the
integrated board; the small profile must not touch its audio GPIOs.
Do not add back the rejected near-white image cutoff.

Unchanged images skip refresh: use ETag/If-None-Match/304 where available,
otherwise compare SHA-256 of validated final panel pixels. RefreshState.h
holds only the last successfully displayed frame's fingerprint/ETag in RTC
memory, bound to URL, canvas, JPEG, and battery settings. Cold boots/resets refresh;
timer wakes retain state. Invalidate the reference before a physical refresh
so partial failures can't cause a false skip. Never trust a downloaded file
or an unsolicited 304 as evidence that a frame was displayed successfully.

The local battery badge is an explicit exception to preserving the raw frame:
change only its bottom-left 160x48 pixel rectangle. Show a red icon and percent
only below 15%; charging state belongs in dashboard telemetry and must not
affect refresh fingerprints. Preserve the original
source in LittleFS; never cache the overlaid frame as the source or erase a
warning to white. Compare final pixels for refresh decisions, but keep a
separate source fingerprint to validate cache reuse. An HTTP 304 skips refresh
only if the local badge is unchanged. A badge transition can refresh the
verified cached source, even during network failure; missing/corrupt cache
requires an unconditional download, not guessing the background. Preserve
normal failure status and sleep. Test the 15% boundary, invalid ADC
readings, badge bounds, cache restoration, and unchanged-source overlay changes.

For a code change affecting shared firmware, build both environments. Build
with placeholder config in CI. Don't publish build artifacts. For a new
hardware setup, build only the selected environment unless changes affect
both. Run the relevant host tests; new tests should cover real risks.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Itests/host -Isrc tests/large_panel_test.cpp src/Epaper13in3e.cpp \
  -o /tmp/federfunk-large-panel-test
/tmp/federfunk-large-panel-test
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Isrc tests/refresh_state_test.cpp -o /tmp/federfunk-refresh-test
/tmp/federfunk-refresh-test
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Isrc tests/battery_indicator_test.cpp -o /tmp/federfunk-battery-test
/tmp/federfunk-battery-test
```

`g++` can replace `clang++`. The large-panel host test validates all 1.92
million pixels, both IC payloads, DC/CS, BUSY timeouts, and power cleanup.
It doesn't verify the electrical behavior of an actual display.

The `naturalist/` companion provides a LAN dashboard for artwork, counts,
labels, QR and solar scheduling. It does not configure ESP32 Wi-Fi or flash
firmware. There is no captive portal or OTA workflow.
Portrait artwork is inverse-rotated by the companion into the established
landscape wire protocol; do not add a second rotation in the driver.
Every catalogue asset must have source evidence, hashes and a recorded visual
review. The default collage shows all available species heard today; missing
illustrations remain explicit in the dashboard and must never be replaced by
another species. Keep live station data and local QR addresses out of Git.
USB disappears during deep sleep; that is normal. Hold BOOT, tap RESET/EN,
release BOOT for the ROM bootloader when another upload is needed.
