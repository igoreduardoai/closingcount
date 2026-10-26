# ClosingCount

**An offline, evidence-driven agent for physical inventory reconciliation.**

Built during the **Cerebral Valley x Meta AI Developer Hackathon (Oct 26 - Nov 4, 2026)**.
The first commit of this repository marks the start of the event work.

> **Research demo. Not a medical device. No clinical validity.**
> The demo simulates a surgical instrument count with **household objects standing in for instruments**
> (scissors, tweezers, binder clips, spoons, forks, cloth squares). It does not replace the manual count,
> it does not give clinical advice, and it has not been evaluated in any clinical setting.

## What it is meant to do

ClosingCount keeps a ledger of physical items across counts (baseline -> additions -> closing count) and
compares each new count against that ledger:

- **Reconciliation is deterministic code**, not a model guess. The ledger is the source of truth.
- **Vision** (SAM 3, Meta open weights) counts items per class and per zone from a still, top-down photo.
- **The agent** (Muse Glimmer 30B, Meta open weights) only turns spoken or typed commands into ledger
  tool calls and plans a recount. It never decides the count.
- **It never says where a missing item is.** On a mismatch it reports what is unaccounted for and
  the last zone where it was recorded:

```
COUNT DISCREPANCY
Expected 12 | Observed 11
Scissors: 1 unaccounted for
Last recorded in Zone B. Manual recount required.
Ledger reconciliation pending
```

- **It never closes the count on its own.** It can raise a discrepancy by itself; closing always
  requires a human confirmation. Overlapping or touching items produce *uncertainty*, not a confirmation.

## Status

Day 0. Only the feasibility spike exists so far: [`spike/`](spike/README.md). No numbers are claimed yet;
every figure will come from runs recorded in this repository.

## Meta models (planned, offline mode)

| Model | Role | Runtime | License |
|---|---|---|---|
| SAM 3 (`mlx-community/sam3-image`, community MLX conversion) | count items per class/zone in still photos | [`sam3-mlx`](https://pypi.org/project/sam3-mlx/) on Apple Silicon | SAM License (weights not redistributed here) |
| Muse Glimmer 30B (Q4_K_M GGUF / Ollama MLX build) | command -> ledger tool call, recount plan | llama.cpp or Ollama, `localhost` only | Apache 2.0 |
| Omnilingual ASR (later) | local speech -> text | local | Apache 2.0 |

Models are loaded sequentially on a single laptop. "No network calls" will only be stated after a full
run with networking disabled and connections monitored (see `spike/04_offline_check.sh`, which is a
check, not a proof).

## Prior work

The on-device vision pattern was previously explored in an earlier, unrelated project.
No code from it is used. Everything in this repository is new and was written during the event.

Third-party libraries and model weights are used under their own licenses and are not included in
this repository.

## License

Code: MIT (see `LICENSE`). Model weights are downloaded separately and remain under their own licenses.
