#!/usr/bin/env python3
"""ClosingCount spike 03: does local Muse Glimmer turn commands into the right ledger tool call?

Sends 10 fixed commands (English and Portuguese) to a LOCAL OpenAI-compatible endpoint
(llama.cpp or Ollama) with ledger tools, and scores:
  - tool-call correctness (right tool + right key arguments),
  - latency per turn, completion tokens/s (end to end, includes prefill and reasoning),
  - memory of the model server process (RSS sampled with ps).
PASS = >= 9/10 correct AND every scored turn under 45 s. Writes spike/results/03_glimmer_commands.json.

The model never decides the count: these tools only write intents to a ledger that
deterministic code reconciles. Standard library only (no pip install needed).

Usage (SAM stopped, Glimmer server running):
  llama.cpp: python3 spike/03_glimmer_commands.py --base-url http://127.0.0.1:8080/v1 --model muse-glimmer
  Ollama:    python3 spike/03_glimmer_commands.py --base-url http://127.0.0.1:11434/v1 --model muse-glimmer:30b-mlx
Optional: if the server was started with --api-key, export CC_LLM_API_KEY in your shell (never commit it).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS = ["scissors", "tweezers", "clip", "spoon", "fork", "towel"]
ZONES = ["A", "B", "C", "D", "E", "F"]

SYSTEM = (
    "You are the command interpreter of ClosingCount, a count ledger for a simulated instrument count "
    "(household objects). Convert the user's spoken or typed command (English or Portuguese) into exactly ONE "
    "tool call. Never answer in prose when a tool fits. Never decide or close the count yourself; a human confirms. "
    f"Use only these canonical item names: {', '.join(ITEMS)} "
    "(tesoura=scissors, pinça=tweezers, prendedor/clipe=clip, colher=spoon, garfo=fork, pano/compressa=towel). "
    f"Zones are single uppercase letters {', '.join(ZONES)} ('zona b' = B). Quantities are integers."
)

def _obj(props, required):
    return {"type": "object", "properties": props, "required": required}

ITEM = {"type": "string", "enum": ITEMS}
ZONE = {"type": "string", "enum": ZONES}
QTY = {"type": "integer", "minimum": 1}
TOOLS = [
    {"type": "function", "function": {"name": "log_addition", "description": "Record items added to the field during the procedure.",
     "parameters": _obj({"item": ITEM, "quantity": QTY, "zone": ZONE}, ["item", "quantity"])}},
    {"type": "function", "function": {"name": "log_removal", "description": "Record items deliberately removed from the field (handed off, dropped, taken out).",
     "parameters": _obj({"item": ITEM, "quantity": QTY, "zone": ZONE, "reason": {"type": "string"}}, ["item", "quantity"])}},
    {"type": "function", "function": {"name": "request_recount", "description": "Ask the team to recount a zone (optionally one item type) and take a new photo.",
     "parameters": _obj({"zone": ZONE, "item": ITEM}, ["zone"])}},
    {"type": "function", "function": {"name": "flag_item", "description": "Flag a concern about an item (cannot be seen, overlapping, damaged, uncertain).",
     "parameters": _obj({"item": ITEM, "zone": ZONE, "reason": {"type": "string"}}, ["item", "reason"])}},
    {"type": "function", "function": {"name": "take_count", "description": "Take a photo count of the tray. phase is baseline, interim or closing.",
     "parameters": _obj({"phase": {"type": "string", "enum": ["baseline", "interim", "closing"]}}, ["phase"])}},
    {"type": "function", "function": {"name": "record_human_confirmation", "description": "Record that a named human role confirmed the count. Does not close it by itself.",
     "parameters": _obj({"role": {"type": "string", "enum": ["scrub", "circulator"]}}, ["role"])}},
]

# (command, expected tool, expected key args)
CASES = [
    ("Add two scissors to zone B.", "log_addition", {"item": "scissors", "quantity": 2, "zone": "B"}),
    ("Adiciona três colheres na zona A.", "log_addition", {"item": "spoon", "quantity": 3, "zone": "A"}),
    ("One fork was handed off the field from zone C.", "log_removal", {"item": "fork", "quantity": 1, "zone": "C"}),
    ("Remove uma pinça da zona D, caiu no chão.", "log_removal", {"item": "tweezers", "quantity": 1, "zone": "D"}),
    ("Recount zone B, look for the scissors.", "request_recount", {"zone": "B", "item": "scissors"}),
    ("Reconta a zona C.", "request_recount", {"zone": "C"}),
    ("I can't see the second clip in zone E, the towels are overlapping.", "flag_item", {"item": "clip", "zone": "E"}),
    ("Começa a contagem inicial.", "take_count", {"phase": "baseline"}),
    ("Closing count now.", "take_count", {"phase": "closing"}),
    ("A circulante confirmou a contagem.", "record_human_confirmation", {"role": "circulator"}),
]


def server_rss_mb() -> float | None:
    """Largest RSS among llama/ollama processes (MB). A coarse proxy; Metal memory may not all show in RSS."""
    try:
        out = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    best = None
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and any(k in parts[1].lower() for k in ("llama", "ollama")):
            v = int(parts[0]) / 1024
            best = v if best is None else max(best, v)
    return best


def call(base_url, model, user, api_key, timeout, max_tokens):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "tools": TOOLS, "tool_choice": "auto", "max_tokens": max_tokens, "stream": False,
        # llama.cpp honors this; other servers ignore it. Do not send temperature 0 (Meta advises against greedy).
        "chat_template_kwargs": {"reasoning_strength": "low"},
    }
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key or 'local'}"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data, time.perf_counter() - t


def norm(v):
    return v.strip().upper() if isinstance(v, str) and len(v.strip()) == 1 else (v.strip().lower() if isinstance(v, str) else v)


def score(data, exp_tool, exp_args):
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    if not calls:
        return False, None, None, "no tool call (content: %r)" % (msg.get("content") or "")[:120]
    fn = calls[0].get("function") or {}
    name = fn.get("name")
    raw = fn.get("arguments")
    try:
        args = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return False, name, raw, "arguments not valid JSON"
    if name != exp_tool:
        return False, name, args, f"wrong tool (expected {exp_tool})"
    for k, v in exp_args.items():
        got = args.get(k)
        if k == "quantity":
            try:
                got = int(got)
            except (TypeError, ValueError):
                pass
        if norm(got) != norm(v):
            return False, name, args, f"arg {k}={got!r} expected {v!r}"
    if len(calls) > 1:
        return True, name, args, f"ok (+{len(calls) - 1} extra call ignored)"
    return True, name, args, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    ap.add_argument("--model", default="muse-glimmer")
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--max-tokens", type=int, default=1024, help="reasoning tokens count against this")
    ap.add_argument("--max-latency", type=float, default=45.0)
    ap.add_argument("--min-correct", type=int, default=9)
    ap.add_argument("--out", default=str(HERE / "results" / "03_glimmer_commands.json"))
    args = ap.parse_args()
    if not any(h in args.base_url for h in ("127.0.0.1", "localhost", "[::1]")):
        sys.exit("Refusing non-local endpoint: this spike measures the on-device model only.")
    key = os.environ.get("CC_LLM_API_KEY")

    print(f"== ClosingCount spike 03: Glimmer tool calls @ {args.base_url} model={args.model} ==")
    try:
        _, warm = call(args.base_url, args.model, "Reconta a zona A.", key, args.timeout * 2, args.max_tokens)
        print(f"warm-up (not scored): {warm:.1f}s")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"Cannot reach the local server: {e}. Start llama.cpp or Ollama first (see spike/01_setup.sh output).")

    rows, rss_peak = [], server_rss_mb()
    for i, (cmd, tool, exp) in enumerate(CASES, 1):
        try:
            data, secs = call(args.base_url, args.model, cmd, key, args.timeout, args.max_tokens)
            ok, name, got, note = score(data, tool, exp)
            usage = data.get("usage") or {}
            ctoks = usage.get("completion_tokens")
            finish = (data.get("choices") or [{}])[0].get("finish_reason")
        except Exception as e:  # timeout or HTTP error counts as a failure
            ok, name, got, note, secs, usage, ctoks, finish = False, None, None, f"error: {e}", args.timeout, {}, None, None
        r = server_rss_mb()
        if r is not None:
            rss_peak = r if rss_peak is None else max(rss_peak, r)
        tps = (ctoks / secs) if ctoks and secs else None
        rows.append({"n": i, "command": cmd, "expected_tool": tool, "expected_args": exp, "got_tool": name,
                     "got_args": got, "correct": ok, "note": note, "seconds": round(secs, 2),
                     "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": ctoks,
                     "tokens_per_second_e2e": round(tps, 2) if tps else None, "finish_reason": finish})
        print(f"  {'OK  ' if ok else 'FAIL'} {i:2d}. {secs:5.1f}s {('%.1f tok/s' % tps) if tps else '':>10}  {cmd}  -> {name} {got if got is not None else ''}  [{note}]")

    correct = sum(r["correct"] for r in rows)
    lat = sorted(r["seconds"] for r in rows)
    tps_vals = sorted(r["tokens_per_second_e2e"] for r in rows if r["tokens_per_second_e2e"])
    status = "PASS" if correct >= args.min_correct and lat[-1] < args.max_latency else "FAIL"
    result = {
        "spike": "03_glimmer_commands", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": status,
        "rule": f">= {args.min_correct}/{len(CASES)} correct and every turn < {args.max_latency:.0f}s",
        "correct": correct, "total": len(CASES),
        "latency_s": {"median": lat[len(lat) // 2], "max": lat[-1], "min": lat[0]},
        "tokens_per_second_e2e_median": tps_vals[len(tps_vals) // 2] if tps_vals else None,
        "server_rss_peak_mb": round(rss_peak, 1) if rss_peak is not None else None,
        "server_rss_note": "RSS of llama/ollama processes via ps; GPU (Metal) wired memory may not be fully included. Also note Activity Monitor > Memory.",
        "endpoint": args.base_url, "model": args.model, "max_tokens": args.max_tokens,
        "env": {"python": platform.python_version(), "machine": platform.machine(), "mac_ver": platform.mac_ver()[0]},
        "cases": rows,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nCorrect {correct}/{len(CASES)}; latency median {result['latency_s']['median']}s max {result['latency_s']['max']}s; "
          f"tok/s(e2e) median {result['tokens_per_second_e2e_median']}; server RSS peak {result['server_rss_peak_mb']} MB")
    print(f"RESULT: {status}")
    print(f"Saved: {out}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
