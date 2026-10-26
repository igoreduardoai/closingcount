#!/usr/bin/env python3
"""ClosingCount spike 02: can SAM 3 (MLX, local) count household items exactly?

Counts a text-prompted class in every photo listed in labels.csv and compares the
count with the manual count you wrote down. Prints PASS/FAIL against the threshold
(default: exact match on >= 9 of 10 photos) and writes spike/results/02_sam_count.json.

This is a feasibility check on household objects, never evidence of clinical accuracy.

labels.csv (header required; one row per photo x class):
    filename,prompt,count
    p01.jpg,scissors,3
    p01.jpg,spoon,2
A photo passes only if every row for it matches exactly.

Usage (inside spike/.venv, Glimmer server stopped):
    spike/.venv/bin/python spike/02_sam_count.py --photos spike/photos --labels spike/labels.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import resource
import sys
import time
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports kilobytes
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024


def mlx_peak_mb(mx) -> float | None:
    for fn in ("get_peak_memory",):
        for owner in (mx, getattr(mx, "metal", None)):
            f = getattr(owner, fn, None) if owner is not None else None
            if callable(f):
                try:
                    return f() / (1024 * 1024)
                except Exception:
                    pass
    return None


def read_labels(path: Path, default_prompt: str | None):
    rows: "OrderedDict[str, list[tuple[str, int]]]" = OrderedDict()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = {c.strip().lower() for c in (reader.fieldnames or [])}
        if "filename" not in cols or "count" not in cols:
            sys.exit(f"labels.csv needs columns filename,prompt,count (got {reader.fieldnames})")
        for r in reader:
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("filename") or r["filename"].startswith("#"):
                continue
            prompt = r.get("prompt") or default_prompt
            if not prompt:
                sys.exit(f"row for {r['filename']} has no prompt and --prompt was not given")
            rows.setdefault(r["filename"], []).append((prompt, int(r["count"])))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", default=str(HERE / "photos"))
    ap.add_argument("--labels", default=str(HERE / "labels.csv"))
    ap.add_argument("--prompt", default=None, help="default text prompt if labels.csv has no prompt column")
    ap.add_argument("--weights", default=str(HERE / "models" / "sam3-image" / "model.safetensors"))
    ap.add_argument("--resolution", type=int, default=1008, help="multiple of 14; 672 is faster")
    ap.add_argument("--confidence", type=float, default=0.5)
    ap.add_argument("--pass-rate", type=float, default=0.9, help="fraction of photos that must match exactly")
    ap.add_argument("--out", default=str(HERE / "results" / "02_sam_count.json"))
    args = ap.parse_args()

    if args.resolution % 14:
        sys.exit("--resolution must be a multiple of 14")
    labels = read_labels(Path(args.labels), args.prompt)
    photos_dir = Path(args.photos)
    weights = Path(args.weights)
    if not weights.exists():
        sys.exit(f"weights not found: {weights} (run spike/01_setup.sh)")

    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # local weights only; no hub calls
    import numpy as np
    import mlx.core as mx
    from PIL import Image
    from sam3_mlx import build_sam3_image_model, __version__ as sam_ver
    from sam3_mlx.model.sam3_image_processor import Sam3Processor

    t0 = time.perf_counter()
    model = build_sam3_image_model(checkpoint_path=str(weights), load_from_HF=False)
    proc = Sam3Processor(model, resolution=args.resolution, confidence_threshold=args.confidence)
    load_s = time.perf_counter() - t0
    print(f"SAM 3 loaded in {load_s:.1f}s (sam3_mlx {sam_ver}, mlx {mx.__version__}, res {args.resolution})")

    per_image = []
    for fname, items in labels.items():
        p = photos_dir / fname
        if not p.exists():
            print(f"  MISSING {fname}")
            per_image.append({"filename": fname, "error": "file not found", "match": False})
            continue
        img = Image.open(p).convert("RGB")
        t1 = time.perf_counter()
        state = proc.set_image(img)
        enc_s = time.perf_counter() - t1
        cls = []
        for prompt, expected in items:
            t2 = time.perf_counter()
            out = proc.set_text_prompt(prompt=prompt, state=state)
            scores = np.asarray(out["scores"]).reshape(-1)
            masks = np.asarray(out["masks"])
            n = int(scores.shape[0])
            areas = masks.reshape(n, -1).sum(axis=1).astype(float) if n else np.array([])
            med = float(np.median(areas)) if n else 0.0
            big = int((areas > 1.7 * med).sum()) if n >= 2 and med > 0 else 0
            low = int(((scores >= args.confidence) & (scores < args.confidence + 0.15)).sum())
            cls.append({
                "prompt": prompt, "expected": expected, "observed": n, "match": n == expected,
                "scores": [round(float(s), 3) for s in scores],
                "suspect_large_masks": big, "low_margin_detections": low,
                "prompt_seconds": round(time.perf_counter() - t2, 3),
            })
        secs = time.perf_counter() - t1
        ok = all(c["match"] for c in cls)
        per_image.append({"filename": fname, "width": img.width, "height": img.height,
                          "encode_seconds": round(enc_s, 3), "seconds": round(secs, 3),
                          "match": ok, "classes": cls})
        detail = ", ".join(f"{c['prompt']} {c['observed']}/{c['expected']}" for c in cls)
        flag = " (uncertain: overlap/low score)" if any(c["suspect_large_masks"] or c["low_margin_detections"] for c in cls) else ""
        print(f"  {'OK  ' if ok else 'MISS'} {fname}: {detail}  [{secs:.2f}s]{flag}")

    scored = [r for r in per_image if "error" not in r]
    n_img = len(scored)
    n_ok = sum(r["match"] for r in scored)
    all_cls = [c for r in scored for c in r["classes"]]
    mae = (sum(abs(c["observed"] - c["expected"]) for c in all_cls) / len(all_cls)) if all_cls else None
    # Overcounts are the dangerous direction: they can hide a missing item.
    over = sum(1 for c in all_cls if c["observed"] > c["expected"])
    under = sum(1 for c in all_cls if c["observed"] < c["expected"])
    secs = sorted(r["seconds"] for r in scored)
    rate = n_ok / n_img if n_img else 0.0
    status = "PASS" if n_img >= 10 and rate >= args.pass_rate and len(scored) == len(per_image) else "FAIL"
    peak_mlx = mlx_peak_mb(mx)

    result = {
        "spike": "02_sam_count", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": status,
        "rule": f"exact match on >= {args.pass_rate:.0%} of photos, at least 10 photos, no missing files",
        "photos_scored": n_img, "photos_exact": n_ok, "exact_rate": round(rate, 3),
        "class_rows": len(all_cls), "mae_per_class_row": round(mae, 3) if mae is not None else None,
        "overcounts": over, "undercounts": under,
        "seconds_per_image_median": secs[len(secs) // 2] if secs else None,
        "seconds_per_image_max": secs[-1] if secs else None,
        "model_load_seconds": round(load_s, 2),
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "peak_mlx_mb": round(peak_mlx, 1) if peak_mlx is not None else None,
        "config": {"resolution": args.resolution, "confidence": args.confidence, "weights": str(weights)},
        "env": {"python": platform.python_version(), "machine": platform.machine(), "mac_ver": platform.mac_ver()[0],
                "sam3_mlx": sam_ver, "mlx": mx.__version__},
        "per_image": per_image,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"\nExact: {n_ok}/{n_img} photos ({rate:.0%}); over={over} under={under}; MAE/row={result['mae_per_class_row']}")
    print(f"Seconds/photo median={result['seconds_per_image_median']} max={result['seconds_per_image_max']}; "
          f"peak RSS={result['peak_rss_mb']} MB; peak MLX={result['peak_mlx_mb']} MB")
    print(f"RESULT: {status}  (feasibility on household items only; not clinical evidence)")
    print(f"Saved: {out}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
