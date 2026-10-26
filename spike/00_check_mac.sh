#!/usr/bin/env bash
# ClosingCount spike 00: is this Mac able to run the offline stack?
# Read-only. Installs nothing, downloads nothing.
# Usage: bash spike/00_check_mac.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$HERE/results"; mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/00_check_mac.json"

MIN_MEM_GB=32      # 24 GB = Glimmer alone, no room for SAM; see spike/README.md
MIN_DISK_GB=30     # Glimmer Q4_K_M ~17 GB + SAM 3 ~3.5 GB + venv + headroom

jesc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== ClosingCount spike 00: Mac check =="
OS="$(uname -s)"; ARCH="$(uname -m)"
echo "OS: $OS  arch: $ARCH"

echo; echo "\$ system_profiler SPHardwareDataType | grep -E \"Chip:|Memory:|Model Name:\""
HW=""
if have system_profiler; then
  HW="$(system_profiler SPHardwareDataType 2>/dev/null | grep -E "Chip:|Memory:|Model Name:")"
fi
echo "${HW:-<system_profiler not available>}"

echo; echo "\$ df -h /System/Volumes/Data"
DISK_PATH=/System/Volumes/Data; [ -d "$DISK_PATH" ] || DISK_PATH=/
DFH="$(df -h "$DISK_PATH" 2>/dev/null)"; echo "$DFH"
FREE_KB="$(df -k "$DISK_PATH" 2>/dev/null | awk 'NR==2{print $4}')"
FREE_GB=$(( ${FREE_KB:-0} / 1024 / 1024 ))

CHIP="$(printf '%s\n' "$HW" | sed -n 's/.*Chip: *//p' | head -1)"
MODEL="$(printf '%s\n' "$HW" | sed -n 's/.*Model Name: *//p' | head -1)"
MEM_GB="$(printf '%s\n' "$HW" | sed -n 's/.*Memory: *\([0-9][0-9]*\) *GB.*/\1/p' | head -1)"
if [ -z "$MEM_GB" ] && have sysctl; then
  MEM_B="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"; MEM_GB=$(( MEM_B / 1024 / 1024 / 1024 ))
fi
MEM_GB="${MEM_GB:-0}"

echo; echo "== Tools =="
PY_VER=""; PY_OK=false
for p in python3.13 python3.14 python3; do
  if have "$p"; then
    v="$("$p" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)" || v=""
    if [ -n "$v" ]; then
      echo "$p -> $v"
      [ -z "$PY_VER" ] && PY_VER="$v"
      case "$v" in 3.1[3-9].*|3.[2-9][0-9].*) PY_OK=true ;; esac
    fi
  fi
done
tool_json=""
for t in uv ollama llama llama-server llama-cli hf huggingface-cli brew git lsof nettop; do
  if have "$t"; then echo "  [x] $t: $(command -v "$t")"; s=true; else echo "  [ ] $t"; s=false; fi
  tool_json="$tool_json\"$t\": $s, "
done
OLLAMA_VER=""; have ollama && OLLAMA_VER="$(ollama --version 2>/dev/null | tail -1)"
LLAMA_VER=""; if have llama; then LLAMA_VER="$(llama --version 2>&1 | head -2 | tr '\n' ' ')"; elif have llama-server; then LLAMA_VER="$(llama-server --version 2>&1 | head -2 | tr '\n' ' ')"; fi
[ -n "$OLLAMA_VER" ] && echo "ollama version: $OLLAMA_VER (need >= 0.32.7)"
[ -n "$LLAMA_VER" ] && echo "llama.cpp version: $LLAMA_VER (need build >= b10353)"

echo; echo "== Verdict =="
FAILS=""; WARNS=""
[ "$OS" = "Darwin" ] || FAILS="$FAILS not-macOS;"
[ "$ARCH" = "arm64" ] || FAILS="$FAILS not-Apple-Silicon;"
if [ "$MEM_GB" -lt 24 ]; then FAILS="$FAILS memory<24GB(Glimmer Q4 does not fit);"
elif [ "$MEM_GB" -lt "$MIN_MEM_GB" ]; then WARNS="$WARNS memory=${MEM_GB}GB(<32: Glimmer only, SAM must run separately or hybrid);"; fi
[ "$FREE_GB" -ge "$MIN_DISK_GB" ] || FAILS="$FAILS free-disk=${FREE_GB}GB(<${MIN_DISK_GB});"
if ! $PY_OK && ! have uv; then FAILS="$FAILS no-python>=3.13-and-no-uv(sam3-mlx needs 3.13);"; fi
if ! have ollama && ! have llama && ! have llama-server; then WARNS="$WARNS no-ollama/llama.cpp-yet(install one, see spike/README.md);"; fi

if [ -z "$FAILS" ]; then STATUS=PASS; else STATUS=FAIL; fi
echo "chip=${CHIP:-?} memory=${MEM_GB}GB free_disk=${FREE_GB}GB python=${PY_VER:-none}"
[ -n "$WARNS" ] && echo "WARN:$WARNS"
[ -n "$FAILS" ] && echo "FAIL reasons:$FAILS"
echo "RESULT: $STATUS"

cat > "$OUT" <<JSON
{
  "spike": "00_check_mac",
  "timestamp": "$(date '+%Y-%m-%dT%H:%M:%S%z')",
  "status": "$STATUS",
  "fail_reasons": "$(jesc "$FAILS")",
  "warnings": "$(jesc "$WARNS")",
  "os": "$OS", "arch": "$ARCH",
  "model_name": "$(jesc "$MODEL")",
  "chip": "$(jesc "$CHIP")",
  "memory_gb": $MEM_GB,
  "free_disk_gb": $FREE_GB,
  "system_profiler_raw": "$(jesc "$HW")",
  "df_h_raw": "$(jesc "$DFH")",
  "python_version": "$(jesc "$PY_VER")",
  "python_ge_3_13": $PY_OK,
  "ollama_version": "$(jesc "$OLLAMA_VER")",
  "llama_cpp_version": "$(jesc "$LLAMA_VER")",
  "tools": { ${tool_json%, } },
  "thresholds": { "min_memory_gb": $MIN_MEM_GB, "min_free_disk_gb": $MIN_DISK_GB }
}
JSON
echo "Saved: $OUT"
[ "$STATUS" = PASS ]
