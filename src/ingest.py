"""
ingest.py — Stage 1: tempo / beat-grid detection + human-confirm gate.

Runs AFTER Stage 2 (the 2 -> 1 order): reads a song's manifest, estimates a
tempo map from the source master, flags rubato/variable tempo loudly, and refuses
to mark the grid "confirmed" without explicit human sign-off or a manual override.
A backing track on the wrong grid is useless, so this is a gate, not a convenience.
The confirmed grid is what Stage 3 uses to generate the Click / Drummer Click / Cues.

Usage:
  python -m src.ingest "<output.dir>/Song_Title/manifest.json" --config config.yaml
  python -m src.ingest "<output.dir>/Song_Title/manifest.json" --confirm
"""
from __future__ import annotations
import argparse
import os
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.manifest import Manifest, TempoMap   # noqa: E402


def _load_cfg(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def estimate_tempo(audio_path: str, cfg: dict) -> TempoMap:
    tcfg = cfg["tempo"]
    ov = tcfg.get("manual_override") or {}
    if ov.get("bpm"):
        return TempoMap(bpm=float(ov["bpm"]),
                        time_signature=tcfg["assume_time_signature"],
                        downbeat_times=[float(ov.get("first_downbeat_sec") or 0.0)],
                        source="manual_override", confirmed_by_human=True)

    import numpy as np, librosa
    y, sr = librosa.load(audio_path, sr=None, mono=True)

    if tcfg["method"] == "madmom":
        tm = _madmom_grid(audio_path, tcfg)
        if tm:
            return tm

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    bpm = float(np.atleast_1d(tempo)[0])

    is_var, warn = False, ""
    if len(beats) > 4:
        ibis = np.diff(beats)
        cv = float(np.std(ibis) / (np.mean(ibis) + 1e-9))
        if cv > tcfg["variance_warn_threshold"]:
            is_var = True
            warn = (f"Tempo varies (CV={cv:.2f}). Likely rubato/live feel — auto grid "
                    f"unreliable. Set tempo.manual_override or beat-map by hand.")

    downbeats = list(beats[::4]) if len(beats) else []
    return TempoMap(bpm=round(bpm, 2), time_signature=tcfg["assume_time_signature"],
                    beat_times=[round(float(b), 4) for b in beats],
                    downbeat_times=[round(float(d), 4) for d in downbeats],
                    is_variable=is_var, variance_warning=warn,
                    source="librosa", confirmed_by_human=False)


def _madmom_grid(audio_path, tcfg):
    try:
        from madmom.features.downbeats import (RNNDownBeatProcessor,
                                               DBNDownBeatTrackingProcessor)
    except Exception:
        print("madmom not installed — falling back to librosa.")
        return None
    import numpy as np
    act = RNNDownBeatProcessor()(audio_path)
    bpb = int(tcfg["assume_time_signature"].split("/")[0])
    out = DBNDownBeatTrackingProcessor(beats_per_bar=[bpb], fps=100)(act)
    times = out[:, 0]
    downs = [round(float(t), 4) for t, b in out if int(b) == 1]
    bpm = float(60.0 / np.mean(np.diff(times))) if len(times) > 1 else 0.0
    return TempoMap(bpm=round(bpm, 2), time_signature=tcfg["assume_time_signature"],
                    beat_times=[round(float(t), 4) for t in times],
                    downbeat_times=downs, source="madmom", confirmed_by_human=False)


def run(manifest_path: str, cfg: dict, confirm: bool) -> Manifest:
    man = Manifest.from_json(manifest_path)
    if confirm:
        man.tempo.confirmed_by_human = True
        man.stage1_complete = man.tempo.bpm > 0
        man.to_json(manifest_path)
        print(f"Grid confirmed: {man.tempo.bpm} BPM, {man.tempo.time_signature}.")
        return man

    man.tempo = estimate_tempo(man.source_file, cfg)
    man.stage1_complete = man.tempo.confirmed_by_human
    man.to_json(manifest_path)
    print(f"Detected: {man.tempo.bpm} BPM, {man.tempo.time_signature} "
          f"({len(man.tempo.downbeat_times)} downbeats, {man.tempo.source})")
    if man.tempo.variance_warning:
        print("\n  !!  " + man.tempo.variance_warning + "\n")
    if not man.tempo.confirmed_by_human:
        print("GATE: grid NOT confirmed. Review, then re-run with --confirm "
              "(or set a manual_override) before Stage 3 uses it.")
    return man


def main():
    ap = argparse.ArgumentParser(description="Stage 1 — ingest & tempo map")
    ap.add_argument("manifest")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    run(args.manifest, _load_cfg(args.config), args.confirm)


if __name__ == "__main__":
    main()
