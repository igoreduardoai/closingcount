#!/usr/bin/env bash
# ClosingCount spike 04: offline CHECK (not a proof).
#
# Runs a command and, while it runs, samples open internet sockets (lsof -i) of that command's
# process tree plus any running llama/ollama server. Any connection to a non-loopback address
# is recorded and makes the result FAIL. Sampling every 0.5 s can miss very short connections,
# and it only watches these processes, so a PASS means "none observed", not "proven impossible".
#
# Recommended: turn Wi-Fi OFF first (and unplug Ethernet), then run, e.g.:
#   bash spike/04_offline_check.sh -- spike/.venv/bin/python spike/02_sam_count.py
#   bash spike/04_offline_check.sh -- python3 spike/03_glimmer_commands.py --base-url http://127.0.0.1:8080/v1
# Optional second look in another Terminal while it runs:  nettop -m tcp -J bytes_in,bytes_out
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$HERE/results"; mkdir -p "$OUT_DIR"
INTERVAL=0.5

[ "${1:-}" = "--" ] && shift
if [ $# -eq 0 ]; then
  sed -n '2,15p' "$0"; exit 2
fi
TAG="$(basename "$1")"
for a in "$@"; do case "$a" in *.py|*.sh) TAG="$(basename "$a")"; break ;; esac; done
TAG="$(printf '%s' "$TAG" | tr -c 'A-Za-z0-9_.-' '_')"
OUT="$OUT_DIR/04_offline_check_${TAG}.json"
LOG="$OUT_DIR/04_offline_check_${TAG}.connections.txt"
: > "$LOG"
have() { command -v "$1" >/dev/null 2>&1; }
have lsof || { echo "FAIL: lsof not found"; exit 1; }

echo "== ClosingCount spike 04: offline check (not a proof) =="
WIFI="unknown"
if have networksetup; then
  for dev in en0 en1; do
    s="$(networksetup -getairportpower "$dev" 2>/dev/null)" && { WIFI="$s"; break; }
  done
fi
DEFAULT_ROUTE="none"
if have route; then route -n get default >/dev/null 2>&1 && DEFAULT_ROUTE="present"; fi
echo "Wi-Fi: $WIFI | default route: $DEFAULT_ROUTE"
[ "$DEFAULT_ROUTE" = "present" ] && echo "NOTE: a default route exists (network is up). For the demo claim, rerun with Wi-Fi off."

descendants() { # $1 = pid; prints pid and all descendants
  echo "$1"
  for c in $(pgrep -P "$1" 2>/dev/null); do descendants "$c"; done
}

echo "\$ $*"
START=$(date +%s)
"$@" &
CMD_PID=$!
SAMPLES=0
while kill -0 "$CMD_PID" 2>/dev/null; do
  PIDS="$(descendants "$CMD_PID"; pgrep -f 'llama|ollama' 2>/dev/null)"
  PIDS="$(printf '%s\n' $PIDS | sort -u | paste -sd, -)"
  if [ -n "$PIDS" ]; then
    lsof -nP -a -p "$PIDS" -i 2>/dev/null | awk 'NR>1' | while IFS= read -r line; do
      case "$line" in *"->"*) ;; *) continue ;; esac
      remote="${line##*->}"
      case "$remote" in 127.*|"[::1]"*|localhost*) ;; *) echo "$(date '+%H:%M:%S') $line" >> "$LOG" ;; esac
    done
  fi
  SAMPLES=$((SAMPLES + 1))
  sleep "$INTERVAL"
done
wait "$CMD_PID"; CMD_RC=$?
DUR=$(( $(date +%s) - START ))

NON_LOOP=$(sort -u -k2 "$LOG" | grep -c . || true)
if [ "$NON_LOOP" -eq 0 ]; then STATUS=PASS; else STATUS=FAIL; fi
echo
echo "command exit code: $CMD_RC | duration: ${DUR}s | samples: $SAMPLES | non-loopback connections seen: $NON_LOOP"
[ "$NON_LOOP" -gt 0 ] && { echo "Connections seen:"; sort -u -k2 "$LOG" | head -20; }
echo "RESULT: $STATUS (a check by sampling, not a proof of zero egress)"

esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
cat > "$OUT" <<JSON
{
  "spike": "04_offline_check",
  "timestamp": "$(date '+%Y-%m-%dT%H:%M:%S%z')",
  "status": "$STATUS",
  "meaning": "PASS = no non-loopback connection observed by lsof sampling every ${INTERVAL}s on the command's process tree and llama/ollama servers. Not a proof.",
  "command": "$(esc "$*")",
  "command_exit_code": $CMD_RC,
  "duration_s": $DUR,
  "samples": $SAMPLES,
  "wifi": "$(esc "$WIFI")",
  "default_route": "$DEFAULT_ROUTE",
  "non_loopback_connections": $NON_LOOP,
  "connections_log": "$(esc "$LOG")"
}
JSON
echo "Saved: $OUT"
[ "$STATUS" = PASS ]
