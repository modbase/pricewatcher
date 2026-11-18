# Output helpers in the style of the Proxmox VE community helper scripts.
# Sourced by pricewatcher.sh (on the host) and by install.sh (in the container).
set -Eeuo pipefail

RD=$'\e[31m' GN=$'\e[32m' YW=$'\e[33m' BL=$'\e[36m' BD=$'\e[1m' CL=$'\e[0m'
[ -t 1 ] || RD= GN= YW= BL= BD= CL=
LOG=$(mktemp /tmp/pricewatcher-XXXX.log)
SPINNER_PID=

header() {
  cat <<EOF
${BL}  ___     _                     _       _
 | _ \\_ _(_)__ ___ __ __ ____ _| |_ __| |_  ___ _ _
 |  _/ '_| / _/ -_) V  V / _\` |  _/ _| ' \\/ -_) '_|
 |_| |_| |_\\__\\___|\\_/\\_/\\__,_|\\__\\__|_||_\\___|_|${CL}

EOF
}

spinner() {
  local s='|/-\' i=0
  while :; do printf '\r %s%s%s %s' "$YW" "${s:i++%4:1}" "$CL" "$MSG"; sleep 0.1; done
}

stop_spinner() {
  if [ -n "$SPINNER_PID" ]; then
    kill "$SPINNER_PID" 2>/dev/null || true
    wait "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=
    printf '\r\e[K'
  fi
}

msg_info() {
  stop_spinner
  MSG=$1
  if [ -t 1 ]; then spinner & SPINNER_PID=$!; else echo " - $1"; fi
}
msg_ok() { stop_spinner; printf ' %s✔%s %s\n' "$GN" "$CL" "$1"; }
msg_error() { stop_spinner; printf ' %s✖%s %s\n' "$RD" "$CL" "$1" >&2; }

# Runs a noisy command with its output in $LOG; shows the tail of it when the command fails.
silent() {
  "$@" >>"$LOG" 2>&1 || {
    local code=$?
    msg_error "Failed: $*"
    tail -n 20 "$LOG" >&2
    echo "Full log: $LOG" >&2
    exit "$code"
  }
}

trap 'code=$?; msg_error "Failed (exit $code) at line $LINENO: $BASH_COMMAND"; exit $code' ERR
trap 'c=$?; stop_spinner; [ "$c" != 0 ] || rm -f "$LOG"' EXIT  # keep the log only after a failure
