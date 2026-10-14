# FederFunk 🐦📡

*Your backyard, on the air.*

Bring your backyard birds to life on color e-paper. FederFunk combines
German *Feder* (feather) and *Funk* (radio): a little wireless window into
the birds outside.

ESP32-S3 firmware for two Waveshare E Ink Spectra 6 displays. It joins Wi-Fi,
downloads a JPEG or a packed six-color frame over HTTP, refreshes only when
the displayed pixels change, and then deep-sleeps for the configured interval
(currently 30 minutes).

## Start with your agent

Give your coding agent this repository's URL and this prompt:

> Set up FederFunk from https://github.com/tschmid/federfunk on the ESP32
> connected to my computer.
> Read README.md and AGENTS.md first. Identify my board and display, install
> the build tools, keep my Wi-Fi credentials private, configure an image URL,
> build the correct profile, flash the board, and verify a complete refresh
> and deep sleep from the serial log. If I don't have an image server yet,
> use the included test-frame generator. Ask me only for settings or physical
> actions you can't obtain or perform yourself.

The agent playbook is in [AGENTS.md](AGENTS.md). It explains the supported
hardware, how to verify flash/PSRAM before choosing a profile, how to provision
local settings, which commands to run, and what counts as a successful setup.
Agents can handle software setup, image checks, building, flashing, and logs.
You still need to identify the physical screen, provide network settings, and
occasionally press BOOT/RESET if the board is asleep.

Requirements: a supported display/ESP32-S3, a USB **data** cable, a computer
with Git and Python 3.10 or newer, Internet access for the first toolchain
download, and a 2.4 GHz Wi-Fi network. The ESP32 and image server need to be
able to reach each other on the network.

## Quick start without an agent

Clone this repository and bootstrap from the checkout:

```sh
git clone https://github.com/tschmid/federfunk.git
cd federfunk
python3 scripts/bootstrap.py
```

This installs PlatformIO in a project-local `.venv`, keeps its toolchain
cache in ignored `.pio/core`, creates the ignored
`src/BirdDisplayConfig.h` from the example **only if it does not exist**, and
enables the credential-check commit hook when no other hook setup is present.
Existing Wi-Fi settings are preserved. On Windows, use `python` instead of
`python3`; commands below use `.venv/Scripts/pio.exe` instead of
`.venv/bin/pio`.

Edit `src/BirdDisplayConfig.h` locally to set your SSID/password and image
URL. Choose the profile in the table below, then run:

```sh
.venv/bin/pio device list
.venv/bin/pio run -e esp32-s3-13in3e6
.venv/bin/pio run -e esp32-s3-13in3e6 -t upload --upload-port YOUR_PORT
.venv/bin/pio device monitor --port YOUR_PORT --baud 115200 --dtr 0 --rts 0
```

These commands target the integrated 13.3-inch board. For the 7.3-inch HAT,
replace `esp32-s3-13in3e6` with `esp32-s3`. Replace `YOUR_PORT` with the actual
device listed by PlatformIO (for example `/dev/cu.usbmodem…` on macOS,
`/dev/ttyACM0` on Linux, or `COM3` on Windows). Don't select a Bluetooth port.
The agent should verify the chip and memory rather than picking the first
port it sees. See [troubleshooting](#troubleshooting) if the USB port is absent.

On the first run, watch for a successful download, frame validation,
`E-paper refresh complete.`, and `Sleeping for 30 minutes.` The display keeps
the picture while the ESP32 sleeps. USB disappearing at this point is expected.

## Select the display

The toggle is the PlatformIO environment in `platformio.ini`:

| Environment | Hardware | Landscape canvas | Raw frame length | URL setting |
| --- | --- | --- | ---: | --- |
| `esp32-s3` | Existing ESP32-S3 breakout + 7.3-inch HAT (E), SKU 32694 | 800×480 | 192,000 bytes | `imageUrl` |
| `esp32-s3-13in3e6` | Integrated ESP32-S3-ePaper-13.3E6 board | 1600×1200 | 960,000 bytes | `largeImageUrl` |

Build either explicitly with `pio run -e esp32-s3` or
`pio run -e esp32-s3-13in3e6`. To change the default used by plain `pio run`,
set `default_envs` at the top of `platformio.ini` to the chosen environment.
The small profile remains the default. Each profile selects its driver,
dimensions, wiring, image URL, and memory/toolchain settings together.

The large profile uses Arduino-ESP32 3.2.0 through the pinned pioarduino
platform and 32 MB flash. The connected WROOM-2-N32R16V was verified with
`esptool flash_id` to have octal flash and 16 MB PSRAM, so this profile uses
OPI flash and OPI PSRAM (`opi_opi`). This corrects the QIO flash setting in
[Waveshare's Arduino screenshot](https://docs.waveshare.com/ESP32-S3-ePaper-13.3E6/Arduino)
for this board revision.
The small profile retains its existing Arduino version and 16 MB flash layout.
The large driver targets the integrated board in those docs; it is not a
pin-compatible replacement for the separate 7.3-inch HAT.

## Small display wiring

The defaults use these ESP32-S3 pins. All six GPIO assignments can be changed
in `src/BirdDisplayConfig.h`.

| Waveshare 8-pin connector | Wire color on existing cable | ESP32-S3 default | Notes |
| --- | --- | ---: | --- |
| VCC | Gray | 3V3 | Keep the display supply and I/O voltage compatible |
| GND | Brown | GND | Common ground is required |
| DIN | Blue | GPIO 11 | SPI MOSI |
| CLK | Yellow | GPIO 12 | SPI clock |
| CS | Orange | GPIO 10 | Chip select |
| DC | Green | GPIO 9 | Data/command |
| RST | White | GPIO 6 | Reset |
| BUSY | Purple | GPIO 7 | Display status output |

The pin numbers are GPIO numbers, not physical header positions. Do not connect
the display until you have checked the labels/pinout for your particular
breakout board. The HAT accepts 3.3 V operation; never put a 5 V logic signal
directly into the ESP32-S3.

The breakout board's WS2812 RGB status LED is connected to GPIO 48. After each
scheduled update it blinks green three times when the download, frame
validation, and display refresh succeed (or the image is unchanged), or red
three times if any step fails. Its pin, brightness, blink count, and timing
are configurable in `BirdDisplayConfig.h`.

## Large display wiring

The ESP32-S3-ePaper-13.3E6 already connects its ESP32 to the screen internally;
no breakout-board jumper wires are needed. The pin map in
`src/DisplaySelection.h` comes from
[Waveshare's example](https://github.com/waveshareteam/ESP32-S3-ePaper-13.3E6):

| Signal | On-board ESP32-S3 GPIO |
| --- | ---: |
| SCK | 9 |
| MOSI | 46 |
| Master CS | 10 |
| Slave CS | 3 |
| DC | 11 |
| RST | 2 |
| BUSY | 12 |
| Display power enable | 1 |

The large profile disables the GPIO48 WS2812 status output because that LED
is a feature of the existing breakout, not a documented feature of this
integrated board. Update success/failure is still logged over USB CDC.

## Configure

This project uses [PlatformIO](https://platformio.org/). Copy the example
configuration and edit it:

`scripts/bootstrap.py` creates the local configuration safely. If setting up
manually, copy `src/config.example.h` to `src/BirdDisplayConfig.h` only when
the local file does not already exist.

Set `wifiSsid`, `wifiPassword`, `imageUrl` for the small display, and
`largeImageUrl` for the large display. The small display's GPIO numbers are
also configurable here.
`src/BirdDisplayConfig.h` is ignored by Git so Wi-Fi credentials are not accidentally
committed.

Keep real Wi-Fi credentials and backend URLs in that local file. The
repository includes only `config.example.h` with placeholders. Compiled
firmware also contains your credentials, so build output and firmware binaries
are excluded from Git and should not be attached to issues or releases.

Enable the included credential check for commits from this checkout:

```sh
git config core.hooksPath .githooks
```

The check rejects private configuration/build files and looks for the local
SSID, password, and image URLs in staged content without printing their
values. It is an extra guard, not a substitute for reviewing a commit.

The firmware accepts `http://` URLs only. For JPEG URLs, it decodes the
highest-resolution RGB565 image that fits in PSRAM, takes a centered crop
with the selected canvas's aspect ratio (5:3 small, 4:3 large), and performs
a bilinear resize to that canvas. For example, a 3840×2160 JPEG is decoded to a
1920×1080 buffer (about 4 MiB) on an 8 MiB PSRAM board; a full-size RGB565
buffer would require about 15.8 MiB. Pixels are mapped directly to the panel's
six colors using serpentine Floyd-Steinberg error diffusion, which preserves
far more photographic detail than direct nearest-color mapping. A truly white
source background remains white because it has no quantization error to
diffuse. PNG is not supported yet.

`enableDithering` controls Floyd-Steinberg error diffusion.
`bypassResamplingWhenExactSize` makes a source matching the selected canvas
(800×480 or 1600×1200) skip cropping and
bilinear sampling. JPEG decoding and conversion to the display's six-color
pixel format cannot be bypassed.

When the selected URL ends in `.bin`, the response is treated as a packed
frame and bypasses all JPEG decoding and image processing. It must contain
exactly 192,000 bytes for an 800×480 small image, or 960,000 bytes for a
1600×1200 large image, in left-to-right, top-to-bottom order. Each byte stores
the first pixel in its high nibble and the second in
its low nibble. Valid codes are `0x0` black, `0x1` white, `0x2` yellow, `0x3`
red, `0x5` blue, and `0x6` green. The firmware rejects incorrect lengths and
unknown color codes before refreshing the panel.

For the large screen, send a landscape frame from
`/api/v1/display/current_large.bin` on your existing backend. Its two
controllers expect the halves of a native 1200×1600 portrait layout.
The driver rotates pixel addressing by 90 degrees during transfer, using
only a 300-byte row buffer. It preserves all color codes and pixels without
resizing, cropping, dithering, or allocating another full framebuffer.

### Unchanged images

At each 30-minute wake, FederFunk checks whether an update is needed:

- If the server supplied an `ETag` for the last successfully displayed image,
  the next request sends `If-None-Match`. A `304 Not Modified` skips both the
  image download and the e-paper refresh, unless the local battery indicator
  changed (see below).
- If the server returns an image (including servers without ETags), the
  firmware validates/renders it and compares a SHA-256 fingerprint of the
  final packed panel pixels, including any battery badge. Identical pixels
  skip the refresh, even if a JPEG's metadata or the ETag changed.

The fingerprint and ETag are retained in RTC memory across timer deep sleep,
without extra flash writes for change-detection metadata. This works with
both sizes and both JPEG and `.bin` URLs; no new configuration is required.
A manual reset, power loss, or firmware upload forces a fresh download and
refresh. Failed downloads don't become the new reference image, and a failed
panel refresh invalidates the reference so the next attempt repairs it.
Both unchanged and failed updates still end with the normal sleep interval.

Serial output says
`Image and battery indicator unchanged; skipping e-paper refresh.`
or `Image pixels unchanged; skipping e-paper refresh.` when an update is skipped.
For best battery life, the backend should return a stable, quoted ETag for
unchanged image content and honor `If-None-Match` with a bodyless 304 response.
`X-BirdFrame-Revision` alone isn't used: a composition revision need not mean
that the displayed pixels changed.

### Battery indicator (13.3-inch board only)

The integrated board measures battery voltage on GPIO8 (ADC1 channel 7)
through its 2 MOhm / 1 MOhm divider. The firmware uses calibrated millivolt
readings and multiplies by three, matching
[Waveshare's schematic](https://files.waveshare.com/wiki/ESP32-S3-ePaper-13.3E6/ESP32-S3-ePaper-Driver-Board.pdf)
and [ADC example](https://docs.waveshare.com/ESP32-S3-ePaper-13.3E6/Arduino#01_adc_test).
The small breakout profile does not read any battery GPIO or draw a badge.

Edit the non-secret settings in `src/BatteryConfig.h`, then rebuild/upload:

```cpp
constexpr bool enabled = true;
constexpr bool showOnlyWhenLow = true;
constexpr float lowVoltage = 3.5f;
constexpr float recoveryHysteresis = 0.1f;
```

With these defaults, a red battery symbol, exclamation mark, and estimated
percentage appear at the bottom left below **3.5 V**. The warning stays until
the voltage reaches **3.6 V** to avoid toggling around the threshold. Set
`showOnlyWhenLow = false` to always show the battery/percentage bar (green
when healthy, red when low), or `enabled = false` to leave the image untouched.
The badge covers only a 192×56-pixel rectangle, 16 pixels from the left and
bottom edges; reserve that corner in your backend layout if needed.

Battery is sampled once each wake, before Wi-Fi and panel power are enabled,
using 32 samples with outliers removed. A voltage change alone does not
trigger refresh: only a change to the visible badge does. Percentages are
rounded to `percentageStep` (5% by default) to reduce noise-driven refreshes.
An invalid reading retains the previous indicator, not a fabricated 0%.

The original, unmodified source image stays in LittleFS. If HTTP returns 304
but the badge needs to appear, disappear, or change, the firmware verifies
that cache and redraws it with the current badge. Removing the warning
restores the original pixels, not a white rectangle. A missing/corrupt cache
forces a full download. During network failures, a verified cache from the
last successful display can still show a battery change; the network failure
is logged and the normal 30-minute sleep remains. This fallback requires a
previous successful update in the current power session.

Percentage is only a voltage-based estimate, **not a fuel-gauge measurement**.
`emptyVoltage` (3.3 V) and `fullVoltage` (4.2 V) set its linear scale; adjust
for your battery. Charging and load affect the estimate. The voltage threshold
uses the measured voltage directly, independently of that percentage scale.
Compare the logged voltage with a multimeter on your actual board; set
`voltageCalibration` to *actual voltage / logged voltage* if correction is
needed. This is an advisory display feature, not a battery cutoff or charge
controller.

## Build and upload

```sh
pio run -e esp32-s3
pio run -e esp32-s3 --target upload --upload-port /dev/cu.usbmodemXXX

# Integrated 13.3-inch board:
pio run -e esp32-s3-13in3e6
pio run -e esp32-s3-13in3e6 --target upload --upload-port /dev/cu.usbmodemXXX
```

Both profiles use the chip's native USB CDC/JTAG connection for both
uploads and runtime diagnostics at 115200 baud. The USB serial device is only
present while the ESP32 is awake; it disappears during deep sleep and returns
at the next timed wake or manual reset. To upload while it is sleeping, hold
**BOOT**, tap **RESET/EN**, release **BOOT**, and select the resulting
`USB JTAG/serial debug unit` port.

Expected output includes the assigned IP, HTTP byte count, JPEG size, and
e-paper refresh progress. A refresh is slow by design (about 25 seconds). Once
the status indication finishes, Wi-Fi is shut down, the panel is already in
its own sleep mode, and the ESP32 enters timer deep sleep. The large profile
also switches off display power and holds its power-enable GPIO low during
deep sleep, including after download or display failures.

Deep sleep minimizes the ESP32 chip's consumption, but the complete breakout
board may still draw additional current through its regulator, USB-to-serial
chip, power LED, and the WS2812's standby current.

A bench measurement of the integrated 13.3-inch board with this firmware
settled at approximately **11 mA at 4.10 V** after a completed refresh,
powered through the battery connector with USB disconnected. That baseline
alone is about 265 mAh per day, before updates. This is a whole-board result,
not the ESP32 chip's deep-sleep specification; further board-level power
optimization is still needed.

## Serving a test image

No bird backend yet? You can verify the complete setup with a six-color
test pattern and Python's built-in HTTP server. The colored corner markers,
white margin, and stripes make size/orientation issues visible.

```sh
# Use --panel small for the 7.3-inch HAT.
python3 scripts/generate_test_frame.py --panel large --output demo/test.bin
python3 -m http.server 8000 --bind 0.0.0.0 --directory demo
```

Keep the server running. Set the selected URL in your private configuration
to `http://YOUR_COMPUTER_LAN_IP:8000/test.bin`, then build/upload. Use the
computer's LAN address, not `localhost` or its public Internet address.
If the computer's firewall asks, allow local-network access to the server.
This unauthenticated server is for a local smoke test; it serves only `demo/`,
and no Wi-Fi settings should be placed there. Generated `.bin` files are
ignored by Git.

Once the pattern appears correctly, switch to your own bird-image URL and
rebuild. FederFunk is the **display client**; it doesn't include a camera,
bird detector, or image compositor. Any reachable HTTP server that produces
the documented JPEG or packed-frame format can supply images.

From a computer on the same Wi-Fi network, put an 800×480 (small) or
1600×1200 (large) baseline JPEG in a
directory and run:

```sh
python3 -m http.server 8000
```

Then set `imageUrl` to that computer's LAN address, for example
`http://192.168.1.10:8000/image.jpg`. `localhost` would refer to the ESP32, not
the computer.

## Planned configuration mode

The code keeps runtime settings and hardware pin definitions separate so the
next milestone can replace the compile-time settings with preferences stored
in flash. That milestone can add:

1. a timeout while joining the saved network;
2. a fallback access point such as `FederFunk-AB12`;
3. a captive configuration page for SSID/password;
4. an on-device page at `http://bird-display.local/` for image URL and refresh
   interval;
5. validation and atomic saving before rebooting into station mode.

For now these settings are compiled into the firmware. There is no Wi-Fi
setup access point or configuration website yet. Changes to SSID, URL, or
sleep interval require another build/upload. The interval is a sleep duration
after each attempt, so refresh and download time are added to it.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| USB port disappeared after an update | Expected during deep sleep. Hold BOOT, tap RESET/EN, release BOOT to enter the bootloader for another upload. |
| No USB port, even after entering the bootloader | Try a known USB data cable and a direct computer port. Check OS device enumeration before installing a driver; use the board's actual USB identity. |
| Board resets or cannot initialize PSRAM | Verify the real module/flash size. The integrated WROOM-2-N32R16V uses `opi_opi`; the existing small-board profile uses `qio_opi`. |
| Wi-Fi times out | Verify private settings, 2.4 GHz connectivity, and signal. A failed attempt sleeps for the configured interval; RESET retries immediately. |
| Unexpected Content-Length | A `.bin` response must be exactly 192,000 or 960,000 bytes for the selected profile. An HTML error/fallback page is not a frame, even with HTTP 200. |
| HTTP request fails | Check the server's LAN address, port, firewall, and endpoint from the same network. Only `http://` is currently supported. |
| JPEG is rejected or looks poor | Use a baseline JPEG, ideally the exact canvas size. A backend-dithered `.bin` avoids JPEG artifacts and firmware quantization entirely. |
| BUSY timeout or no screen change | Check display identity, correct profile, power, and—on the small HAT—wiring. Cut power before changing GPIO or ribbon connections. |

On the small HAT revision used during development, the display FPC needed
contacts **down** in the connector; a reversed cable caused excess current.
Confirm the connector contacts and pin-1 alignment on your own revision rather
than relying on product photos. Do not apply this orientation rule blindly to
the integrated large board.

## Display identification

This controller sequence and color encoding are for the **7.3-inch e-Paper HAT
(E)** / Spectra 6 model. Waveshare also sells older 7.3-inch `(F)` and other
7.3-inch models with different controllers. Confirm that the label or product
page for SKU 32694 says `(E)` before powering the panel.

The large controller sequence is for the **ESP32-S3-ePaper-13.3E6** integrated
board and its Spectra 6 screen, not other 13.3-inch monochrome or four-color
models.

## Host verification

The large driver's test captures both actual SPI payloads and checks every
pixel, the controller seam, command/data and chip-select signals, BUSY
timeouts, and power shutdown/hold:

```sh
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Itests/host -Isrc tests/large_panel_test.cpp src/Epaper13in3e.cpp \
  -o /tmp/birddisplay-large-panel-test
/tmp/birddisplay-large-panel-test
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Isrc tests/refresh_state_test.cpp -o /tmp/federfunk-refresh-test
/tmp/federfunk-refresh-test
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -Isrc tests/battery_indicator_test.cpp -o /tmp/federfunk-battery-test
/tmp/federfunk-battery-test
```

This verifies software behavior; a refresh on the physical board is still
needed to confirm its orientation and power behavior.

Python helper tests need no extra packages:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/check_private_config.py
```

GitHub Actions builds both firmware profiles with placeholder settings and
runs the host tests. It does not publish firmware binaries.

## Credits

Display initialization sequences are adapted from Waveshare's examples;
see [LICENSE.waveshare](LICENSE.waveshare) for their permission notice.
JPEG decoding uses [JPEGDEC](https://github.com/bitbank2/JPEGDEC).
