#!/usr/bin/env bash
# ClosingCount spike 01: Python env + SAM 3 (MLX) weights. Prints, but does NOT run, the Glimmer download.
# Downloads ~3.5 GB (mlx-community/sam3-image, not gated, no token needed). No API keys are used or stored.
# Usage: bash spike/01_setup.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
MODELS="$HERE/models"
SAM_DIR="$MODELS/sam3-image"
OUT_DIR="$HERE/results"; mkdir -p "$OUT_DIR" "$MODELS"
OUT="$OUT_DIR/01_setup.json"
have() { command -v "$1" >/dev/null 2>&1; }
STEP_FAIL=""
fail() { echo "FAIL: $1"; STEP_FAIL="$STEP_FAIL $1;"; }

echo "== ClosingCount spike 01: setup =="
[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || echo "WARN: sam3-mlx only runs on Apple Silicon macOS."

# 1) venv with Python >= 3.13 (required by sam3-mlx)
if [ ! -x "$VENV/bin/python" ]; then
  if have uv; then
    echo "\$ uv venv --python 3.13 $VENV"
    uv venv --python 3.13 "$VENV" || fail "uv-venv"
  elif have python3.13; then
    echo "\$ python3.13 -m venv $VENV"
    python3.13 -m venv "$VENV" || fail "venv"
  else
    fail "need uv or python3.13 (install uv: 'brew install uv' or https://docs.astral.sh/uv/)"
  fi
fi
PY="$VENV/bin/python"

# 2) packages (light: sam3-mlx pulls mlx, numpy, pillow, huggingface-hub)
if [ -x "$PY" ]; then
  if have uv; then
    echo "\$ uv pip install --python $PY sam3-mlx huggingface_hub"
    uv pip install --python "$PY" "sam3-mlx>=0.1.1" "huggingface_hub>=1.1.6" || fail "pip-install"
  else
    "$PY" -m pip install -q --upgrade pip && "$PY" -m pip install "sam3-mlx>=0.1.1" "huggingface_hub>=1.1.6" || fail "pip-install"
  fi
  SAM_VER="$("$PY" -c 'import sam3_mlx;print(sam3_mlx.__version__)' 2>/dev/null)" || SAM_VER=""
  MLX_VER="$("$PY" -c 'import mlx.core as mx;print(mx.__version__)' 2>/dev/null)" || MLX_VER=""
  echo "sam3_mlx=${SAM_VER:-not importable}  mlx=${MLX_VER:-not importable}"
  [ -n "$SAM_VER" ] || fail "sam3_mlx-import"
fi

# 3) SAM 3 MLX weights (not gated). 'hf' is the current CLI; 'huggingface-cli' is the legacy name.
HF=""
[ -x "$VENV/bin/hf" ] && HF="$VENV/bin/hf"
[ -z "$HF" ] && [ -x "$VENV/bin/huggingface-cli" ] && HF="$VENV/bin/huggingface-cli"
[ -z "$HF" ] && have hf && HF="hf"
[ -z "$HF" ] && have huggingface-cli && HF="huggingface-cli"
if [ -f "$SAM_DIR/model.safetensors" ]; then
  echo "SAM 3 weights already present: $SAM_DIR"
elif [ -n "$HF" ]; then
  echo "\$ $HF download mlx-community/sam3-image --local-dir $SAM_DIR"
  "$HF" download mlx-community/sam3-image --local-dir "$SAM_DIR" --include "*.safetensors" --include "*.json" || fail "sam-download"
else
  fail "no hf/huggingface-cli found"
fi
SAM_BYTES=0
[ -f "$SAM_DIR/model.safetensors" ] && SAM_BYTES="$(stat -f %z "$SAM_DIR/model.safetensors" 2>/dev/null || stat -c %s "$SAM_DIR/model.safetensors")"
[ "$SAM_BYTES" -gt 1000000000 ] || fail "sam-weights-missing-or-small"
echo "SAM weights: $SAM_DIR/model.safetensors ($((SAM_BYTES/1024/1024)) MB)"

GLIMMER_DIR="$MODELS/muse-glimmer"
cat <<TXT

== Muse Glimmer 30B: run ONE of these yourself (not run by this script; ~17 GB) ==
Source: Meta docs https://dev.meta.ai/docs/muse-glimmer/get-the-model (repo meta-models/Muse-Glimmer-30B-GGUF, no key, not gated)

Option A - Ollama (>= 0.32.7), MLX engine on Apple Silicon:
  ollama pull muse-glimmer:30b-mlx
  # endpoint for spike 03: --base-url http://127.0.0.1:11434/v1 --model muse-glimmer:30b-mlx

Option B - llama.cpp (build >= b10353), official GGUF Q4_K_M 17 GB, text only (vision is SAM's job):
  $HF download meta-models/Muse-Glimmer-30B-GGUF --local-dir $GLIMMER_DIR \\
      --include "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
  llama serve -m $GLIMMER_DIR/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf \\
      -a muse-glimmer --no-mmproj -ngl 99 -c 8192 -np 1 --host 127.0.0.1 --port 8080 \\
      --chat-template-kwargs '{"reasoning_strength":"low"}'
  # (Homebrew builds name the binary 'llama-server' with the same flags.)
  # endpoint for spike 03: --base-url http://127.0.0.1:8080/v1 --model muse-glimmer

Close Chrome/Docker first. Load ONE model at a time: stop the Glimmer server before spike 02, and vice versa.
TXT

if [ -z "$STEP_FAIL" ]; then STATUS=PASS; else STATUS=FAIL; fi
cat > "$OUT" <<JSON
{
  "spike": "01_setup",
  "timestamp": "$(date '+%Y-%m-%dT%H:%M:%S%z')",
  "status": "$STATUS",
  "fail_reasons": "$(printf '%s' "$STEP_FAIL" | sed 's/"/\\"/g')",
  "python": "$("$PY" -c 'import sys;print(sys.version.split()[0])' 2>/dev/null)",
  "sam3_mlx_version": "${SAM_VER:-}",
  "mlx_version": "${MLX_VER:-}",
  "sam_weights_path": "$SAM_DIR/model.safetensors",
  "sam_weights_bytes": $SAM_BYTES
}
JSON
echo; echo "RESULT: $STATUS"; echo "Saved: $OUT"
[ "$STATUS" = PASS ]
