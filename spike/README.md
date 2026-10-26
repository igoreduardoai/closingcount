# Day-0 feasibility spike (run on the Mac)

Goal: decide with evidence whether a 32 GB Apple Silicon laptop can run the offline stack
(SAM 3 for counting + Muse Glimmer 30B for commands) **one model at a time**.
Every script prints `RESULT: PASS` or `RESULT: FAIL` and writes JSON to `spike/results/`.
Nothing here is clinical evidence; household objects stand in for instruments.

```bash
git clone https://github.com/igoreduardoai/closingcount.git && bash closingcount/spike/00_check_mac.sh
```

## Order

| # | Command (from the folder that contains `closingcount/`) | PASS means | Time / download |
|---|---|---|---|
| 00 | `bash closingcount/spike/00_check_mac.sh` | Apple Silicon, >= 32 GB memory, >= 30 GB free disk, Python >= 3.13 or `uv` | seconds, nothing |
| 01 | `bash closingcount/spike/01_setup.sh` | venv + `sam3-mlx` importable + SAM 3 weights (`mlx-community/sam3-image`) on disk. Prints the Glimmer download commands | ~3.5 GB |
| — | Run **one** Glimmer option printed by 01 (Ollama `muse-glimmer:30b-mlx` **or** llama.cpp + official GGUF Q4_K_M) | — | ~17 GB |
| 02 | Stop the Glimmer server, then `closingcount/spike/.venv/bin/python closingcount/spike/02_sam_count.py` | exact count on >= 9 of 10 photos | ~1-5 min |
| 03 | Stop anything using SAM, start Glimmer, then `python3 closingcount/spike/03_glimmer_commands.py --base-url http://127.0.0.1:8080/v1 --model muse-glimmer` (Ollama: `--base-url http://127.0.0.1:11434/v1 --model muse-glimmer:30b-mlx`) | >= 9 of 10 commands become the right tool call, every turn < 45 s | ~5-10 min |
| 04 | Wi-Fi **off**, then wrap 02 and 03: `bash closingcount/spike/04_offline_check.sh -- closingcount/spike/.venv/bin/python closingcount/spike/02_sam_count.py` and the same with the 03 command | no non-loopback connection observed (a check by sampling, **not a proof**) | same as 02/03 |

Before 02 and 03: quit Chrome, Docker and other heavy apps. Keep Activity Monitor > Memory open and note the
"Memory Used" peak and whether "Memory Pressure" turns yellow/red (the scripts' RSS numbers are a coarse proxy).

## Photo guide (for 02)

- **Items:** 12 household items of 4-6 types, e.g. scissors, tweezers, binder clips, spoons, forks.
  Items of a type should look alike; types should look clearly different.
- **Setup:** a baking tray on a plain cloth (one solid color, no pattern), even light, no strong shadows.
- **Camera:** phone held straight down (top-down), whole tray in frame, ~40-60 cm above. No people, no screens,
  nothing personal in the frame (these photos may become public test data later, only if you approve).
- **Layout:** items **separated, not touching** (this spike tests the simple case; overlaps come later).
- **10 photos** `p01.jpg` ... `p10.jpg` in `closingcount/spike/photos/`:
  - p01-p06: all 12 items, reshuffle the layout each time;
  - p07-p08: remove 1 item (a different type each time) -> 11 items;
  - p09: remove 2 items -> 10 items;
  - p10: add 1 extra item of an existing type -> 13 items.
- **labels.csv** in `closingcount/spike/`: count by hand **from the photo** and write one row per photo per type.
  Copy `labels.example.csv` and edit. Prompts are short English nouns (`scissors`, `spoon`, `fork`,
  `binder clip`, `tweezers`):

```csv
filename,prompt,count
p01.jpg,scissors,2
p01.jpg,spoon,3
```

A photo counts as exact only if **every** type in it matches. `photos/`, `labels.csv`, `results/` and
`models/` are git-ignored, so nothing personal is pushed by accident.

## What to send back

1. The text output of each script (copy from Terminal) and the JSON files in `closingcount/spike/results/`.
2. One photo (e.g. `p01.jpg`) and your `labels.csv`.
3. The Activity Monitor memory peak during 02 and during 03.
4. Which Glimmer option you used (Ollama or llama.cpp) and its version.

## Decision rule (from the plan)

Switch to the backup project if: memory < 24 GB; SAM misses the exact count on more than 2 of 10 spread-out
photos; Glimmer gets fewer than 9 of 10 commands right or takes more than ~45 s per turn.
