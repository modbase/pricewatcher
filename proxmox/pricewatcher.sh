#!/usr/bin/env bash
# Run on a Proxmox VE host: creates a Debian 13 LXC and installs Pricewatcher in it.
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/modbase/pricewatcher/main/proxmox/pricewatcher.sh)"
# In a terminal it asks for Default or Advanced settings; without one (e.g. over ssh without -t) it uses the
# variables below, which also set the wizard's defaults: STORAGE=local-zfs VLAN=50 bash -c "$(curl ...)".
# Update an existing install: run `update` in its console, or run this again with CTID set to that container.
BASE_URL=${BASE_URL:-https://raw.githubusercontent.com/modbase/pricewatcher/main/proxmox}  # holds install.sh and ui.sh
SRC_URL=${SRC_URL:-https://github.com/modbase/pricewatcher/archive/refs/heads/main.tar.gz}  # ponytail: tracks main; switch to release tarballs once v1.0.0 exists
TMP=$(mktemp -d)
curl -fsSL "$BASE_URL/ui.sh" -o "$TMP/ui.sh" || { echo "Could not download $BASE_URL/ui.sh" >&2; exit 1; }
source "$TMP/ui.sh"
trap 'c=$?; stop_spinner; rm -rf "$TMP"; [ "$c" != 0 ] || rm -f "$LOG"' EXIT

command -v pct >/dev/null || { msg_error "Run this on a Proxmox VE host."; exit 1; }

CTID_GIVEN=${CTID:-}
CTID=${CTID:-$(pvesh get /cluster/nextid)}
CT_HOSTNAME=${CT_HOSTNAME:-pricewatcher}
STORAGE=${STORAGE:-local-lvm}             # container disk
TEMPLATE_STORAGE=${TEMPLATE_STORAGE:-local}
BRIDGE=${BRIDGE:-vmbr0}
VLAN=${VLAN:-}                            # VLAN tag, empty for none
CORES=${CORES:-2}
RAM=${RAM:-2048}                          # MB; Chromium needs room for the shops that block plain HTTP
DISK=${DISK:-8}                           # GB

cancelled() { msg_error "Cancelled, nothing was changed."; exit 0; }

# Asks for the value of variable $1 with prompt $2, prefilled with its current value.
ask() {
  local v
  v=$(whiptail --title "Pricewatcher: Advanced settings" --inputbox "$2" 8 60 "${!1}" 3>&1 1>&2 2>&3) || cancelled
  printf -v "$1" %s "$v"
}

summary() {
  printf 'Container ID   %s\nHostname       %s\nDisk           %s GB on %s\nCPU / RAM      %s cores / %s MB\nNetwork        %s, DHCP%s' \
    "$CTID" "$CT_HOSTNAME" "$DISK" "$STORAGE" "$CORES" "$RAM" "$BRIDGE" "${VLAN:+, VLAN $VLAN}"
}

settings() {
  local rc=0
  whiptail --title "Pricewatcher LXC" --yes-button Default --no-button Advanced \
    --yesno "Create a new container with these settings?\n\n$(summary)" 14 60 || rc=$?
  [ "$rc" = 255 ] && cancelled
  if [ "$rc" = 1 ]; then
    ask CTID "Container ID"
    ask CT_HOSTNAME "Hostname"
    ask STORAGE "Storage for the container disk"
    ask DISK "Disk size (GB)"
    ask CORES "CPU cores"
    ask RAM "RAM (MB)"
    ask BRIDGE "Network bridge"
    ask VLAN "VLAN tag (empty for none)"
    for n in CTID DISK CORES RAM ${VLAN:+VLAN}; do
      [[ ${!n} =~ ^[0-9]+$ ]] || { msg_error "$n must be a number, got '${!n}'."; exit 1; }
    done
    whiptail --title "Pricewatcher LXC" --yesno "Create the container now?\n\n$(summary)" 14 60 || cancelled
  fi
}

header
if [ -n "$CTID_GIVEN" ] && pct status "$CTID" >/dev/null 2>&1; then
  msg_ok "Container $CTID exists: updating Pricewatcher in it (data/ and .env are kept)"
else
  [ -t 0 ] && command -v whiptail >/dev/null && settings
  if pct status "$CTID" >/dev/null 2>&1; then msg_error "Container $CTID already exists; rerun with CTID=$CTID to update it."; exit 1; fi

  msg_info "Finding the Debian 13 template"
  silent pveam update
  TEMPLATE=$(pveam available --section system | awk '{print $2}' | grep "^debian-13-standard_.*_$(dpkg --print-architecture)\." | sort -V | tail -1)
  [ -n "$TEMPLATE" ] || { msg_error "No Debian 13 template found in 'pveam available'."; exit 1; }
  pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE" || silent pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  msg_ok "Using $TEMPLATE"

  msg_info "Creating container $CTID ($CT_HOSTNAME)"
  silent pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$CT_HOSTNAME" --cores "$CORES" --memory "$RAM" --swap 512 \
    --rootfs "$STORAGE:$DISK" --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp${VLAN:+,tag=$VLAN}" \
    --unprivileged 1 --features nesting=1 --onboot 1 --timezone host --ostype debian
  msg_ok "Created container $CTID ($CT_HOSTNAME)"
fi

[[ $(pct status "$CTID") == *running* ]] || silent pct start "$CTID"
msg_info "Waiting for the network"
for i in $(seq 30); do
  pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
  [ "$i" = 30 ] && { msg_error "Container $CTID has no network or DNS after 60 seconds."; exit 1; }
  sleep 2
done
msg_ok "Network is up"

msg_info "Downloading Pricewatcher"
curl -fsSL "$BASE_URL/install.sh" -o "$TMP/install.sh"
curl -fsSL "$SRC_URL" -o "$TMP/pricewatcher.tar.gz"
pct exec "$CTID" -- mkdir -p /root/pricewatcher-setup
for f in install.sh ui.sh pricewatcher.tar.gz; do pct push "$CTID" "$TMP/$f" "/root/pricewatcher-setup/$f"; done
msg_ok "Downloaded Pricewatcher"

pct exec "$CTID" -- bash /root/pricewatcher-setup/install.sh
pct exec "$CTID" -- rm -rf /root/pricewatcher-setup

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
cat <<EOF

 ${GN}${BD}✔ Completed successfully!${CL}

   Pricewatcher:  ${BL}http://$IP:8000${CL}
   Container:     $CTID ($CT_HOSTNAME)
   Update later:  run ${BD}update${CL} in the container console
   Telegram:      see the README

 ${YW}It has no login: keep it on your LAN.${CL}

EOF
