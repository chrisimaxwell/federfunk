# The naturalist edition

A portrait print of the birds heard today: historical illustrations, generous
white space, and optional names, counts and a small dashboard QR code. The
companion runs beside BirdNET-Go. The existing ESP32 image URL and packed
six-color protocol continue to work.

## Try it

From this directory, with Python 3.10 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py --demo
```

Open `http://127.0.0.1:8001/`. Sample data is clearly labeled and is never
reused in live mode. For the actual station:

```sh
.venv/bin/python server.py --birdnet http://YOUR_BIRDNET_HOST:8080 --bind 0.0.0.0 --timezone America/Denver
```

Keep this service on a trusted LAN. Its controls intentionally have no login;
same-origin checks and a per-process CSRF token prevent cross-site settings
writes, but anyone with access to the dashboard can change the picture.
Do not expose this port directly to the Internet. An authenticated reverse
proxy can provide remote access separately.

For the existing Debian feed container, copy this directory without `.venv/`
or `state/` and run `sh install.sh` as root. It checks artwork hashes and runs
tests, installs into a versioned directory, preserves the existing BirdNET URL
and service settings, backs up the old service/frame, and rolls back if the
new endpoint fails readiness. It installs Debian's Pillow, qrcode, Astral and fonts.
The installer reports the backup path for manual rollback. It does not flash
the ESP32 or change BirdNET-Go.

## Picture controls

Choose a presentation in the dashboard:

- **Naturalist collage** (default): historical drawings arranged by silhouette,
  with frequency-based sizing and all illustrated species heard today.
- **Classic display**: the previous local feed's featured bird and daily summary,
  adapted to portrait or landscape. Photos are the default; Historical drawings
  uses the reviewed catalogue for the same featured species. Names and counts
  remain optional. The daily list includes all birds unless a limit is selected.
- **Field guide**: historical drawings in ordered rows, retaining frequency
  sizing and optional labels.

Classic is based on the earlier local BirdNET adapter. Thomas's published
FederFunk repository supplies firmware, not the original server-side renderer;
this option does not claim to reproduce an unpublished renderer. Photos come
from BirdNET-Go's species image API, with its author and license attribution.
Missing drawings never cause another species to be substituted. A failed photo
request preserves the last successful print and settings.

The dashboard saves presentation, classic photo/drawing choice, names, scientific names, counts, title, QR URL, maximum
birds, orientation, sizing, the daylight schedule, and illustration choices. Settings,
stats and all three image representations are committed as one atomic bundle.
Changes appear on the web after saving; the frame receives them on its normal
next wake, approximately every 30 minutes. A QR URL must be reachable by the
phone scanning it; localhost is usually not suitable. The QR is on by default in the bottom-right corner, with two-pixel modules
and the required four-module white border. Set `DASHBOARD_URL` or
`--dashboard-url` to the station’s LAN address; the generic development
default is localhost. Slightly softened dark modules keep the code discreet;
solid corner markers preserve scan reliability after dithering. Physical
scanning still needs a phone check when changing the QR size or contrast.

The three area scales are:

| Mode | Visible drawing area |
| --- | --- |
| Gentle (default) | proportional to `log(1 + detections)` |
| Proportional | proportional to detections |
| Equal | equal for each illustration |

Scale is based on alpha-weighted visible ink area, with a common resizing
factor for all birds. It is not a measure of a bird's physical size or the
number of individual animals. Branches included in an illustration also count
toward its ink area. Integer pixel rounding introduces small differences.
No minimum individual size is imposed; very rare birds may be tiny in linear
mode. Composition packs expanded silhouette masks around asymmetrical anchors
in an oval, with protected spaces for optional labels. Drawings fit around one
another instead of occupying table cells. Stable placement and variant
selection avoid unnecessary refreshes.

## Daylight schedule

The default location is ZIP 84105's approximate center (40.7372, -111.8581),
America/Denver. Updates run from sunrise through one hour after sunset.
The dashboard can disable the pause, choose fixed start/end times, adjust
solar offsets by up to three hours either way, or change coordinates/timezone.
Astral calculates sunrise and sunset offline; no external geocoding call is
needed at runtime. Times account for daylight saving, but not mountain shadows.

During the pause, the service preserves the last image and its observations,
including across midnight and restart. Settings saved overnight are queued
for the next active window. Normal polling resumes in the morning. The pause
does not delete or reclassify BirdNET detections; the next active daily summary
still includes that day's qualifying detections from before sunrise.

The new firmware honors `X-FederFunk-Hold-Seconds` on the image response,
leaves even the local battery badge unchanged, and sleeps until the next
window. Older firmware keeps fetching the same frozen image every 30 minutes
and may still redraw its local battery badge. A firmware update is needed for
the full overnight sleep behavior. A sleeping frame cannot receive a changed
schedule until it next wakes or is manually reset. Network failure before
receiving a hold preserves the existing retry and battery-warning behavior.

BirdNET's daily analytics are requested for the station timezone with
`min_confidence=80` by default (80%). This filters individual detections, not
just each species' highest confidence. Species without art remain visible in
the statistics; another species is never substituted. All species with available art appear by default. The optional bird limit
selects the 1–12 most-heard species only when “All birds heard today” is off. An empty day shows
“Listening for visitors”. Fetch failures retain the last successful print and
show a stale-data notice in the dashboard.

## Artwork collection

See [artwork/README.md](artwork/README.md) and `artwork/manifest.json` for
species, variants, original scans, creators, historical dates, rights evidence,
processing steps and checksums. These are historical illustrations, not
generated birds or photos. Adding a second asset with the same scientific
name makes it available in the dashboard's illustration selector. Keep exact
species identification, provenance and rights information when extending the
collection. The manifest is checked on service startup; restart after adding
assets. Unknown or mismatched variant IDs cannot be saved.

Source records, artists, dates and rights stay on the dashboard with clickable
archive, original-scan and license links. They are also embedded in exported
PNG metadata. No credits or references are printed on the e-paper artwork;
its QR code leads to the dashboard's full attribution.

The dashboard's image library compares the entire BirdNET species history
with exact scientific-name matches, shows every reviewed drawing, and lists
missing illustrations in detection-count order. Coverage counts all reported
labels, including low-confidence records; a BirdNET label is not a verified
sighting. Suspect records are flagged for review, not silently substituted
with a similar species. Historical totals remain on the station, outside Git.
The library audit refreshes at most once an hour.

Every displayed asset must have a recorded visual review of species,
orientation and cropping. Original scans, contour recipes and checksums make
the preparation reproducible. Missing artwork never becomes a placeholder
photo in the print. Two species currently offer multiple drawing choices;
additional exact-species variants can be added to the same catalogue.

## Display and endpoints

| Endpoint | Purpose |
| --- | --- |
| `/` | Dashboard and persistent print controls |
| `/art.png` | Full-color artwork, portrait by default |
| `/preview.png` | Same composition quantized to the six display colors |
| `/api/v1/display/current_large.bin` | Existing 960,000-byte firmware endpoint |
| `/api/state` | Settings, observations, availability, frame battery, last poll and errors |
| `/api/settings` | Settings and CSRF token; POST applies validated changes |
| `/api/library` | All-history coverage, missing species and review records |
| `/credits` | Artwork sources and rights metadata |
| `/health` | Readiness, frame size, error status and content ETag |

Portrait art is 1200×1600. The wire image remains 1600×1200, high nibble first,
using only codes 0,1,2,3,5,6. The server rotates portrait art counterclockwise
once to cancel the driver's existing clockwise address rotation. Tests check
native corners and controller seam pixels. Do not change the driver rotation.
The installed panel's upright portrait orientation was confirmed by its owner.

The firmware adds a small red battery warning only below 15%; that badge is
not in the web preview. The existing landscape badge placement maps to the
portrait upper-left edge, which the print reserves. Charging never appears
on the artwork. Updated firmware reports battery percentage, voltage and
charging state with its existing image request; the dashboard shows when
those readings were last received, with no additional frame wakeups. Older
firmware supplies no battery readings. Percentages are voltage estimates.

E-paper output lifts brightness and saturation in colored feathers before
six-color dithering, reducing black in colored areas. Near-neutral details,
white paper and the QR code retain their original tones.
Source scans and full-color web art stay unchanged; the six-color preview
shows the boosted output. Actual e-paper pigments still differ from screen
colors, so final color judgment needs the physical panel.

The 7.3-inch firmware remains supported by the parent project, but this
companion's output currently targets only the 13.3-inch display.

## Verification

```sh
.venv/bin/python -m unittest discover -v -p 'test_*.py'
.venv/bin/python artwork/verify.py
```

Checks cover palette/nibble packing, portrait rotation, sizing mathematics,
validated variant binding, confidence queries, missing artwork, empty days,
failure retention, atomic settings recovery, ETags, CSRF and file access.

For the separate firmware sleep-current improvement, see
[sleep-power.md](../docs/sleep-power.md). Build success does not establish
electrical power savings; a battery-only current measurement is required.
