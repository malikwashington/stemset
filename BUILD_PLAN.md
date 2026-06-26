# Backing-Track Stem Pipeline — Build Tracker

Goal: stereo master -> bus-ready, bar-aligned stems for live wedding-band backing
tracks in Ableton Arrangement view.

Locked decisions:
- Repertoire focus: wedding band first.
- Quality: Tier 2 (per-stem best — RoFormer vocals, Demucs drums/bass/other).
- Backend: MLX on the M1 (torch fallback).
- Separation runs in an isolated venv; models cached on the external drive.
- Live target: Arrangement view; live track buses = Click, Drummer Click, Cues,
  Loop & Percussion, Synths & Pads, BGV, Bass/Sub-Bass, Sample Trigger drum rack.
- Setlists: AbleSet for live navigation over a master file. A physical .als
  trimmer is only built IF the master proves too heavy on the M1.

Legend: [x] done  [~] partial/needs input  [ ] todo  [GATE] blocks downstream

## Stage 2 — Separation engine  (BUILT)
- [x] 2.1  Repo + config-driven design
- [x] 2.2  Backend switch: MLX-first / torch-fallback (backend.py)
- [x] 2.3  Runtime model resolution (no hardcoded filenames)
- [x] 2.4  RoFormer vocals/instrumental split
- [x] 2.5  Demucs drums/bass/other (on the instrumental)
- [x] 2.6  DrumSep kit split (kick/snare/toms/hihat/cymbals) + DSP fallback
- [x] 2.7  Lead/BGV split (BGV summed; lead = guide)
- [x] 2.8  Bus-tagged manifest.json (Stage-3 contract)
- [x] 2.9  preflight.py — environment + song-folder readiness check
- [ ] 2.10 Install backend + first test song, ear-check quality  [GATE — you, on the M1]

## Stage 1 — Ingest & tempo-map  (BUILT)
- [x] 1.1  Tempo + grid detection (librosa; optional madmom)
- [x] 1.2  Rubato/variance warning
- [x] 1.3  Human-confirm gate + manual override  [GATE]
- [x] 1.4  Tempo merged into manifest (drives Click/Cues later)
- [ ] 1.5  Validate grid on a real song  [GATE — you]

## Stage 3 — Ableton assembly  (NOT STARTED)
- [ ] 3.1  Map stems -> the 8 performance buses
- [ ] 3.2  Generate Click / Drummer Click / Cues from the tempo map
- [ ] 3.3  Per-song full-stop MIDI clip + tiny M4L stop device (preserves tails)
- [ ] 3.4  Master-file assembly in Arrangement
- [ ] 3.5  Setlist: try AbleSet on master first; build .als trimmer only if needed  [DECISION]

## Storage
- [x] Internal SSD = gig-ready sets + streamed stems.
- [x] External = source masters, full raw stem library, model cache, backups.
