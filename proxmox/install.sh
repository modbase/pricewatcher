#!/usr/bin/env bash
# Runs inside the container, from a directory that also holds ui.sh and pricewatcher.tar.gz
# (pricewatcher.sh on the host and /usr/bin/update in the container put them there).
# Installs or updates Pricewatcher natively in /opt/pricewatcher; data/ and .env are never touched.
cd "$(dirname "$0")"
source ./ui.sh

APP=/opt/pricewatcher
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive PLAYWRIGHT_BROWSERS_PATH=$APP/browsers

msg_info "Installing dependencies"
silent apt-get update
# libatomic1: Playwright's bundled Node needs it (same as the Dockerfile). curl: used by `update`.
silent apt-get install -y python3 python3-venv libatomic1 ca-certificates curl
msg_ok "Installed dependencies"

msg_info "Unpacking Pricewatcher"
id pricewatcher >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin pricewatcher
mkdir -p "$APP/data"
rm -rf "$APP/app"  # drop files that a newer version removed
tar -xzf pricewatcher.tar.gz -C "$APP" --strip-components=1 --wildcards '*/app' '*/requirements.txt'
msg_ok "Unpacked Pricewatcher"

msg_info "Installing Python packages"
[ -x "$APP/.venv/bin/python" ] || silent python3 -m venv "$APP/.venv"
silent "$APP/.venv/bin/pip" install --disable-pip-version-check -r "$APP/requirements.txt"
msg_ok "Installed Python packages"

msg_info "Installing Chromium (takes a few minutes)"
silent "$APP/.venv/bin/python" -m playwright install --with-deps --only-shell chromium
chown -R pricewatcher: "$APP"
msg_ok "Installed Chromium"

msg_info "Creating service and update command"
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
# Optional TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; they override the Settings page.
EnvironmentFile=-$APP/.env
# Exactly 1 worker: the scheduler runs in-process, more workers would check everything twice.
ExecStart=$APP/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
cat > /usr/bin/update <<'EOF'
#!/usr/bin/env bash
# Updates Pricewatcher in this container; data/ and .env are kept.
# Set BASE_URL (folder with install.sh and ui.sh) and SRC_URL (source tarball) to update from a fork or mirror.
set -euo pipefail
BASE_URL=${BASE_URL:-https://raw.githubusercontent.com/modbase/pricewatcher/main/proxmox}
SRC_URL=${SRC_URL:-https://github.com/modbase/pricewatcher/archive/refs/heads/main.tar.gz}
D=$(mktemp -d)
trap 'rm -rf "$D"' EXIT
for f in install.sh ui.sh; do curl -fsSL "$BASE_URL/$f" -o "$D/$f"; done
curl -fsSL "$SRC_URL" -o "$D/pricewatcher.tar.gz"
bash "$D/install.sh"
EOF
chmod +x /usr/bin/update
msg_ok "Created service and update command"

msg_info "Starting Pricewatcher"
systemctl daemon-reload
systemctl enable -q pricewatcher
systemctl restart pricewatcher
msg_ok "Started Pricewatcher"
