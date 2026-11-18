#!/usr/bin/env bash
# Runs inside the container (pricewatcher.sh pushes it there together with /root/pricewatcher.tar.gz).
# Installs or updates Pricewatcher natively in /opt/pricewatcher; data/ and .env are never touched.
set -euo pipefail

APP=/opt/pricewatcher
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive PLAYWRIGHT_BROWSERS_PATH=$APP/browsers

echo "Installing packages..."
apt-get update -qq
# libatomic1: Playwright's bundled Node needs it (same as the Dockerfile).
apt-get install -y -qq python3 python3-venv libatomic1 ca-certificates >/dev/null

id pricewatcher >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin pricewatcher
mkdir -p "$APP/data"
rm -rf "$APP/app"  # drop files that a newer version removed
tar -xzf /root/pricewatcher.tar.gz -C "$APP" --strip-components=1 --wildcards '*/app' '*/requirements.txt'
rm /root/pricewatcher.tar.gz

echo "Installing Python packages and Chromium (takes a few minutes)..."
[ -x "$APP/.venv/bin/python" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"
"$APP/.venv/bin/python" -m playwright install --with-deps --only-shell chromium >/dev/null
chown -R pricewatcher: "$APP"

TZ_NAME=$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')
cat > /etc/systemd/system/pricewatcher.service <<EOF
[Unit]
Description=Pricewatcher
Wants=network-online.target
After=network-online.target

[Service]
User=pricewatcher
WorkingDirectory=$APP
Environment=PRICEWATCHER_DB=$APP/data/pricewatcher.db
Environment=PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH
Environment=TZ=${TZ_NAME:-Europe/Brussels}
# TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; alerts are off without them.
EnvironmentFile=-$APP/.env
# Exactly 1 worker: the scheduler runs in-process, more workers would check everything twice.
ExecStart=$APP/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q pricewatcher
systemctl restart pricewatcher
rm "$0"
