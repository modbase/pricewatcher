#!/usr/bin/env bash
# Run on a Proxmox VE host: creates a Debian 13 LXC and installs Pricewatcher in it.
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/modbase/pricewatcher/main/proxmox/pricewatcher.sh)"
# Update an existing install: run it again with CTID set to that container, e.g. CTID=121 bash -c "$(curl ...)".
# Defaults can be overridden with the variables below, e.g. STORAGE=local-zfs VLAN=50 bash -c "$(curl ...)".
set -euo pipefail

REPO=${REPO:-https://github.com/modbase/pricewatcher}
SRC_URL=${SRC_URL:-$REPO/archive/refs/heads/main.tar.gz}  # ponytail: tracks main; switch to release tarballs once v1.0.0 exists
INSTALL_URL=${INSTALL_URL:-https://raw.githubusercontent.com/modbase/pricewatcher/main/proxmox/install.sh}
CTID=${CTID:-$(pvesh get /cluster/nextid)}
CT_HOSTNAME=${CT_HOSTNAME:-pricewatcher}
STORAGE=${STORAGE:-local-lvm}             # container disk
TEMPLATE_STORAGE=${TEMPLATE_STORAGE:-local}
BRIDGE=${BRIDGE:-vmbr0}
VLAN=${VLAN:-}                            # VLAN tag, empty for none
CORES=${CORES:-2}
RAM=${RAM:-2048}                          # MB; Chromium needs room for the shops that block plain HTTP
DISK=${DISK:-8}                           # GB

command -v pct >/dev/null || { echo "Run this on a Proxmox VE host." >&2; exit 1; }

if pct status "$CTID" >/dev/null 2>&1; then
  echo "Container $CTID exists: updating Pricewatcher in it (data/ and .env are kept)."
else
  pveam update >/dev/null
  TEMPLATE=$(pveam available --section system | awk '{print $2}' | grep "^debian-13-standard_.*_$(dpkg --print-architecture)\." | sort -V | tail -1)
  [ -n "$TEMPLATE" ] || { echo "No Debian 13 template found in 'pveam available'." >&2; exit 1; }
  pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE" || pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  echo "Creating container $CTID ($CT_HOSTNAME)..."
  pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$CT_HOSTNAME" --cores "$CORES" --memory "$RAM" --swap 512 \
    --rootfs "$STORAGE:$DISK" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp${VLAN:+,tag=$VLAN}" \
    --unprivileged 1 --features nesting=1 --onboot 1 --timezone host --ostype debian
  pct start "$CTID"
fi

for _ in $(seq 30); do  # wait for DHCP and DNS
  pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
  sleep 2
done

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$INSTALL_URL" -o "$TMP/install.sh"
curl -fsSL "$SRC_URL" -o "$TMP/pricewatcher.tar.gz"
pct push "$CTID" "$TMP/install.sh" /root/pricewatcher-install.sh
pct push "$CTID" "$TMP/pricewatcher.tar.gz" /root/pricewatcher.tar.gz
pct exec "$CTID" -- bash /root/pricewatcher-install.sh

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
echo "Pricewatcher runs at http://$IP:8000 (container $CTID)."
echo "It has no login: keep it on your LAN. Telegram alerts: see the README."
