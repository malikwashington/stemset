# Cowork Project Brief — Backing-Track Stem Pipeline

Standing instructions for this project. Read these before any task. If a request
conflicts with something here, surface the conflict instead of guessing.

## What this is
A pipeline that turns purchased stereo masters into bus-ready, bar-aligned stems
for live **wedding-band** backing tracks in Ableton (Arrangement view). The
separation engine (Stages 1–2) is built. Ableton assembly (Stage 3) is not.

## Your lane (Cowork) vs Claude Code
- **You (Cowork) handle the operational side:** running the pipeline over songs,
  organizing the stem library, renaming/sorting outputs, scheduled batch runs,
  and keeping BUILD_PLAN.md current.
- **Hand off to Claude Code (do not attempt here):** editing or debugging the
  Python in `src/`, building Stage 3 (the Max for Live stop device, the `.als`
  trimmer), or any change to separation logic. If a task needs code surgery,
  say so and stop.

## Hard conventions — do NOT re-decide these
- **Backend:** MLX (`mlx-audio-separator`); torch (`audio-separator`) only as fallback.
- **Quality tier:** Tier 2 — RoFormer vocals/instrumental, Demucs drums/bass/other,
  DrumSep kit, karaoke lead/BGV. Already set in `config.yaml`.
- **Paths:** songs in `/Volumes/MEW II/gig files/wedding band/songs`; model cache
  and raw stem library on `/Volumes/MEW II`; the venv and this repo live on the
  internal SSD.
- **Storage split:** external drive = source masters, full raw stem library, model
  cache, backups. Internal SSD = venv + gig-ready sets only.
- **Bus mapping (per song):** LeadVox = guide only (sung live), BGV, Bass→Bass/Sub-Bass,
  Other→Synths & Pads, Drums→Loop & Percussion, kit pieces→Sample Trigger.
  Click / Drummer Click / Cues are generated from the tempo map, not separated.

## Operational workflows
1. **Preflight:** `python -m src.preflight "/Volumes/MEW II/gig files/wedding band/songs"`
   — resolve every FAIL before running anything.
2. **One song:** `python -m src.separate "<path>" --song "<Title>"`, then
   `python -m src.ingest "<output.dir>/<Title>/manifest.json"`.
3. **Batch:** only AFTER I have ear-checked at least one song and approved quality.
   Then process the remaining songs, writing the raw library to the external drive.
4. **Organize:** outputs land as `<output.dir>/<Song>/` with `manifest.json` (the
   external drive per config.yaml); never overwrite a confirmed set.

## Stop and ask me (human gates)
- **Before batching the library:** I must ear-check the first song. Do not batch
  on your own.
- **Tempo:** never mark a grid confirmed yourself. Run ingest, show me the BPM and
  any rubato warning, and wait for my explicit `--confirm`.
- **Anything destructive** (deleting or overwriting stems or sets): confirm first.

## Honest limits (do not promise past these)
- BGV is summed, not per-voice.
- Separated stems carry artifacts vs studio multitracks — quality is judged by ear.
- Gospel/worship rubato breaks automatic tempo; those songs need manual mapping.

## Do this first (on project setup)
Read every file in this folder, compare the actual state against `BUILD_PLAN.md`,
and report back: what exists, what is missing or stale, and what differs from the
documented versions. Ask me about anything ambiguous. **Do not change files yet —
just give me the reconciliation.**

## File map
- `src/separate.py` — Stage 2 separation (Tier 2 flow)
- `src/ingest.py` — Stage 1 tempo map + confirm gate
- `src/backend.py` — MLX / torch backend switch
- `src/manifest.py` — the stem / bus / tempo contract
- `src/preflight.py` — environment + song-folder readiness check
- `config.yaml` — models, paths, bus mapping
- `BUILD_PLAN.md` — tracked steps; keep this current as work progresses
