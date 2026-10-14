#!/bin/sh
# Install/update the existing LAN feed, preserving its configured BirdNET URL.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run as root inside the BirdNET-Go container.'; exit 1; }
cd "$(dirname "$0")"
test -f artwork/manifest.json
test -f web/index.html
if test -d /opt/federfunk-feed && ! test -f /opt/federfunk-feed/.federfunk-feed; then
    echo '/opt/federfunk-feed belongs to another installation; stopping.'
    exit 1
fi
apt-get update
apt-get install -y --no-install-recommends python3-pil python3-qrcode python3-astral fonts-dejavu-core ca-certificates
python3 -m unittest discover -v -p 'test_*.py'
python3 -c 'import render; print("Verified", len(render.catalogue()), "illustrations")'

install -d -m 755 /opt/federfunk-feed/releases
release_dir="$(mktemp -d /opt/federfunk-feed/releases/naturalist.XXXXXX)"
chmod 755 "$release_dir"
install -m 644 server.py render.py collage.py field_guide.py classic.py schedule.py audit_library.py demo.json "$release_dir/"
cp -R artwork web "$release_dir/"
chmod -R a+rX "$release_dir"
backup_dir="$(mktemp -d /opt/federfunk-feed/backup-naturalist.XXXXXX)"
previous_unit=/etc/systemd/system/federfunk-feed.service
if test -f "$previous_unit"; then cp "$previous_unit" "$backup_dir/service"; fi
if test -f /var/lib/federfunk-feed/current.zip; then cp /var/lib/federfunk-feed/current.zip "$backup_dir/current.zip"; fi
touch /opt/federfunk-feed/.federfunk-feed
if ! test -e /etc/default/federfunk-feed; then
    python3 - <<'PY'
import ipaddress, os, subprocess
from pathlib import Path
import render

url = os.getenv('DASHBOARD_URL')
if url is None:
    try:
        addresses = {ipaddress.ip_address(value) for value in subprocess.check_output(['hostname', '-I'], text=True).split()}
        lan = sorted(str(value) for value in addresses if value.version == 4 and value.is_private
                     and not (value.is_loopback or value.is_link_local or value.is_unspecified or value.is_multicast))
    except (OSError, ValueError, subprocess.CalledProcessError):
        lan = []
    url = 'http://' + lan[0] + ':8001/' if len(lan) == 1 else render.DEFAULTS['dashboard_url']
    if len(lan) != 1:
        print('Set the reachable QR address with DASHBOARD_URL in /etc/default/federfunk-feed, or in dashboard settings.')
try:
    render.validate_settings({'show_qr': True, 'dashboard_url': url}, {}, [])
except (ValueError, TypeError):
    raise SystemExit('Invalid DASHBOARD_URL: use a complete HTTP(S) address without credentials.')
# EnvironmentFile uses quoted strings, without shell evaluation. Escape quote
# and backslash characters and never print the private deployment address.
quoted = '"' + url.replace('\\', '\\\\').replace('"', '\\"') + '"'
Path('/etc/default/federfunk-feed').write_text(
    'BIRDNET_URL=http://127.0.0.1:8080\nFEED_PORT=8001\nFEED_INTERVAL=300\n'
    'MIN_CONFIDENCE=0.8\nFEED_TIMEZONE=America/Denver\nDASHBOARD_URL=' + quoted + '\n')
PY
fi
rollback() {
    echo 'Update did not become ready; restoring the previous feed.'
    systemctl stop federfunk-feed || true
    if test -f "$backup_dir/service"; then
        cp "$backup_dir/service" "$previous_unit"
        if test -f "$backup_dir/current.zip"; then
            cp "$backup_dir/current.zip" /var/lib/federfunk-feed/current.zip
        fi
        systemctl daemon-reload
        systemctl restart federfunk-feed
    else
        systemctl disable federfunk-feed || true
    fi
}
# Signals must stop the installation; a returning signal trap could resume it
# after rollback. EXIT performs the rollback exactly once on either failure.
trap rollback EXIT
trap 'exit 1' HUP INT TERM
cat > "$previous_unit" <<EOF
[Unit]
Description=FederFunk naturalist bird print and dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
StateDirectory=federfunk-feed
WorkingDirectory=$release_dir
EnvironmentFile=-/etc/default/federfunk-feed
Environment=PYTHONUNBUFFERED=1 FEED_BIND=0.0.0.0
ExecStart=/usr/bin/python3 $release_dir/server.py
Restart=on-failure
RestartSec=15
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
MemoryMax=384M
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable federfunk-feed
systemctl restart federfunk-feed
python3 - <<'PY'
import json, os, time, urllib.request
# Settings file remains shell-style KEY=value, never evaluate it as code here.
port = '8001'
for line in open('/etc/default/federfunk-feed'):
    if line.startswith('FEED_PORT='):
        port = str(int(line.split('=', 1)[1].strip().strip('"\'')))
base = 'http://127.0.0.1:' + port
for attempt in range(45):
    try:
        with urllib.request.urlopen(base + '/health', timeout=5) as response:
            state = json.load(response)
        assert state['renderVersion'] == 3 and state['ready'] and not state['demo']
        with urllib.request.urlopen(base + '/api/v1/display/current_large.bin', timeout=5) as response:
            frame = response.read(960001)
        assert len(frame) == 960000
        assert all(b >> 4 in (0, 1, 2, 3, 5, 6) and b & 15 in (0, 1, 2, 3, 5, 6) for b in frame)
        print('READY: naturalist print,', state['stats']['species_count'], 'species, dashboard port', port)
        break
    except (OSError, ValueError, KeyError, AssertionError):
        time.sleep(2)
else:
    raise SystemExit('New service did not pass the readiness check')
PY
trap - EXIT HUP INT TERM
echo "Previous service and frame: $backup_dir"
echo "Installed code: $release_dir"
