# Backing-Track Stem Pipeline

Turns a stereo master into **bus-ready, bar-aligned stems** for a live wedding/event band's
backing tracks — when you have the finished record but not the studio multitracks. Source
separation recovers the parts, a tempo map aligns them to a grid, and the output is tagged to the
exact mixer buses a live rig expects (Ableton → an SPD-SX Pro for playback).

The design goal is **live reliability**, not a perfect studio remix: every stem lands on a known
bus, on the grid, with a human ear-check gate before anything reaches the performance stage.

## Pipeline

```
stereo master ──▶ Stage 2: separation ──▶ Stage 1: tempo-map ──▶ Stage 3: Ableton assembly
                  (per-stem models)        (grid + human gate)     (8 buses, click/cues, setlist)
```

- **Stage 2 — separation engine** *(built).* Per-stem models, each chosen for the part it is best
  at: **RoFormer** (vocals/instrumental), **Demucs** (drums/bass/other on the instrumental),
  **DrumSep** (kit decomposed to kick/snare/toms/hihat/cymbals, with a DSP fallback), and a
  lead/BGV split (BGV summed; lead kept as a live guide). Output is a **bus-tagged `manifest.json`**
  — the contract every later stage consumes.
- **Stage 1 — ingest & tempo-map** *(built).* Tempo + grid detection (librosa, optional madmom),
  a rubato/variance warning, and a **human-confirm gate** — gospel/worship rubato breaks automatic
  tempo, so the pipeline warns and refuses to auto-confirm. The tempo map drives the Click and Cue
  tracks downstream.
- **Stage 3 — Ableton assembly** *(in progress).* Map stems to the 8 performance buses, generate
  Click / Drummer Click / Cues from the tempo map, a per-song full-stop MIDI clip, master-file
  assembly in Arrangement view, and setlist navigation (AbleSet over a master file).

**Live buses:** Click · Drummer Click · Cues · Loop & Percussion · Synths & Pads · BGV ·
Bass/Sub-Bass · Sample-Trigger drum rack.

## Engineering decisions
- **MLX-first, torch-fallback** (`src/backend.py`) — runs natively on Apple Silicon (M1), falls
  back to torch elsewhere; a `preflight.py` check verifies the environment + song-folder readiness
  before a run.
- **Config-driven, no hardcoded model filenames** — `config.yaml` + runtime model resolution
  (`--list-models` to pin exact versions for determinism, or `auto` to resolve current ones).
- **The manifest is the stage contract** — Stage 2 emits it, Stages 1 and 3 consume it; stages
  stay decoupled and independently runnable.
- **A human is in the loop by design** — separation carries artifacts and tempo detection can be
  wrong, so both gate on an ear/grid check rather than trusting the model blindly. Live use sets
  the bar.

## Setup (macOS, M1)
```bash
brew install ffmpeg libsndfile
python3 -m venv ~/stemset/.venv && source ~/stemset/.venv/bin/activate

# pick ONE backend — MLX recommended on Apple Silicon:
pip install mlx-audio-separator
# fallback:  pip install "audio-separator[cpu]"

pip install librosa soundfile PyYAML numpy
```
Then edit `config.yaml` — set `models.model_file_dir` to a persistent path (the default backend
cache is `/tmp` and clears on reboot), and optionally pin exact model filenames.

## Run order (Stage 2, then Stage 1)
```bash
# Stage 2 — separate one test song first and LISTEN before batching:
python -m src.separate "path/to/master.wav" --song "Song Title"

# Stage 1 — add the tempo map (gates on a human grid check):
python -m src.ingest "<output.dir>/Song_Title/manifest.json"
python -m src.ingest "<output.dir>/Song_Title/manifest.json" --confirm
```
`<output.dir>/<Song>/manifest.json` is the contract Stage 3 consumes, including the bus each stem
feeds.

## Honest limits
- BGV is summed, not per-voice; the lead vocal is a live guide, not a backing bus.
- Click / Drummer Click / Cues are generated from the tempo map, not separated.
- Separated stems carry artifacts vs. studio multitracks — ear-check each song.
- Gospel/worship rubato breaks automatic tempo; Stage 1 warns and won't auto-confirm.

## Status
- **Built:** the separation engine (Stage 2) and the tempo-map/ingest (Stage 1), both config-driven
  with the bus-tagged manifest contract and a preflight check.
- **In progress:** Stage 3 (Ableton assembly) and first live-set use. See `BUILD_PLAN.md` for the
  tracked steps.
