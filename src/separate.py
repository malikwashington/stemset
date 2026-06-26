"""
separate.py — Stage 2 separation engine (Tier 2, backend-agnostic).

Flow:
  master.wav
    A) RoFormer            -> Vocals, Instrumental         (best vocals)
    B) Demucs on Instrumental -> Drums, Bass, Other        (best drums/bass/other)
    C) DrumSep on Drums    -> kick/snare/toms/hihat/cymbals
    D) Karaoke on Vocals   -> LeadVox, BGV(summed)
  => bus-tagged WAVs + manifest.json (the Stage-3 contract)

Runs on whichever backend is installed (MLX preferred on Apple Silicon, torch as
fallback) — see backend.py. Backend imports are lazy, so --help and --list-models
work without the ML stack present.

Usage:
  python -m src.separate --list-models
  python -m src.separate "path/to/master.wav" --song "Song Title" --config config.yaml
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.manifest import Manifest, Stem          # noqa: E402
from src import backend as be                     # noqa: E402

ROLE_ORDER = ["LeadVox", "BGV", "Bass", "Synths", "Guitar", "Piano", "Drums",
              "Kick", "Snare", "Toms", "HiHat", "Cymbals", "Ride", "Crash",
              "Instrumental"]

KIT_DEPTH = {
    4: ["Kick", "Snare", "Toms", "Cymbals"],
    5: ["Kick", "Snare", "Toms", "HiHat", "Cymbals"],
    6: ["Kick", "Snare", "Toms", "HiHat", "Ride", "Crash"],
}

# DrumSep (MDX23C) emits: kick / snare / toms / hh / ride / crash. "Cymbals" is
# not one of them — it's the sum of ride + crash (handled in separate_song).
DRUMSEP_ALIAS = {
    "Kick": ["kick"], "Snare": ["snare"], "Toms": ["toms"],
    "HiHat": ["hh", "hihat"], "Ride": ["ride"], "Crash": ["crash"],
}


def _load_cfg(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def list_models(cfg: dict) -> None:
    sep = be.make_separator(cfg)
    print(f"backend: {be.backend_name(sep)}\n")
    models = be.list_models(sep)
    flat = be._flatten(models)
    for name in sorted(flat):
        print(f"  {name}")
    if not flat:
        print("(registry not exposed by this backend — use its CLI --list_models)")


def separate_song(audio_path: str, song: str, cfg: dict) -> Manifest:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", song).strip("_") or "song"
    out_dir = os.path.join(cfg["output"]["dir"], slug)
    os.makedirs(out_dir, exist_ok=True)
    run_cfg = {**cfg, "output": {**cfg["output"], "dir": out_dir}}

    sep = be.make_separator(run_cfg)
    bname = be.backend_name(sep)
    man = Manifest(song=song, source_file=os.path.abspath(audio_path), backend=bname)
    buses = cfg["buses"]

    def add(role: str, path: str, model: str, notes: str = ""):
        b = buses.get(role, {"bus": role, "color": "#9AA0A6"})
        man.stems.append(Stem(role=role, path=os.path.abspath(path),
                              bus=b["bus"], color=b["color"],
                              produced_by=f"{bname}:{model}",
                              sample_rate=cfg["output"]["sample_rate"], notes=notes))

    # A) RoFormer: vocals + instrumental
    voc_model = be.resolve_model(sep, cfg["vocals_separation"]["model"],
                                 ["roformer", "mel_band", "bs_roformer"])
    a = be.run_model(sep, voc_model, audio_path,
                     {"Vocals": ["vocals"], "Instrumental": ["instrumental"]})
    vocals = a.get("Vocals")
    instrumental = a.get("Instrumental")
    if instrumental:
        add("Instrumental", instrumental, voc_model, notes="full backing, reference")

    # B) Demucs (htdemucs_ft) on the instrumental: drums / bass + synth bed
    drums = None
    if instrumental:
        inst_model = be.resolve_model(sep, cfg["instrumental_separation"]["model"],
                                      ["htdemucs_ft", "htdemucs", "demucs"])
        b = be.run_model(sep, inst_model, instrumental,
                         {"Drums": ["drums"], "Bass": ["bass"], "Synths": ["other"]})
        if "Bass" in b:
            add("Bass", b["Bass"], inst_model)
        if "Synths" in b:
            add("Synths", b["Synths"], inst_model,
                notes="Demucs 'other' — synth/pad bed (still contains guitar/piano)")
        drums = b.get("Drums")
        if drums:
            add("Drums", drums, inst_model, notes="full kit; feeds Loop & Perc bus")

    # B2) 6-source Demucs on the instrumental: harvest guitar / piano if present
    if cfg.get("guitar_separation", {}).get("enabled") and instrumental:
        gcfg = cfg["guitar_separation"]
        g_model = be.resolve_model(sep, gcfg["model"], ["htdemucs_6s", "6s", "demucs"])
        g = be.run_model(sep, g_model, instrumental,
                         {"Guitar": ["guitar", "guitars"], "Piano": ["piano"]})
        thr = gcfg.get("silence_threshold_db", -50)
        for role in ("Guitar", "Piano"):
            p = g.get(role)
            if not p:
                continue
            if _is_silent(p, thr):
                os.remove(p)          # song lacks this part — drop the dead stem
            else:
                add(role, p, g_model, notes="harvested from htdemucs_6s")

    # C) Drum-kit decomposition
    if cfg["drum_kit"]["enabled"] and drums:
        roles = KIT_DEPTH.get(cfg["drum_kit"]["depth"], KIT_DEPTH[5])
        if cfg["drum_kit"]["method"] == "dsp":
            kit = _dsp_kit_split(drums, roles, out_dir, cfg["output"]["sample_rate"])
            for role, p in kit.items():
                add(role, p, "dsp(HPSS)")
        else:
            kit_model = be.resolve_model(sep, cfg["drum_kit"]["model"],
                                         ["drumsep", "drum", "kit"])
            direct = {r: DRUMSEP_ALIAS[r] for r in roles if r in DRUMSEP_ALIAS}
            kit = be.run_model(sep, kit_model, drums, direct)
            for role in roles:
                if role in kit:
                    add(role, kit[role], kit_model)
            # "Cymbals" has no DrumSep stem — sum the ride + crash outputs into it.
            if "Cymbals" in roles and "Cymbals" not in kit:
                cym = _sum_outputs(out_dir, ["ride", "crash"], "Cymbals",
                                   cfg["output"]["sample_rate"])
                if cym:
                    add("Cymbals", cym, kit_model, notes="ride + crash summed")

    # D) Lead / backing vocal split
    if cfg["vocal_split"]["enabled"] and vocals:
        kara = be.resolve_model(sep, cfg["vocal_split"]["model"], ["karaoke", "kara"])
        d = be.run_model(sep, kara, vocals,
                         {"LeadVox": ["vocals"], "BGV": ["instrumental"]})
        if "LeadVox" in d:
            add("LeadVox", d["LeadVox"], kara, notes="sung live; guide/reference only")
        if "BGV" in d:
            add("BGV", d["BGV"], kara, notes="SUMMED backing vocals — not per-voice")

    man.stems.sort(key=lambda s: ROLE_ORDER.index(s.role) if s.role in ROLE_ORDER else 99)
    man.stage2_complete = True

    # Normalize every kept stem to the session bit depth, then drop intermediates
    # (Demucs residuals, the pre-split vocals) so the folder imports cleanly.
    bits = f"PCM_{cfg['output'].get('bit_depth', 24)}"
    for s in man.stems:
        _to_bits(s.path, bits)
    if cfg["output"].get("prune_intermediates", True):
        _prune(out_dir, [s.path for s in man.stems])

    man.to_json(os.path.join(out_dir, "manifest.json"))
    return man


def _dsp_kit_split(drums_path, roles, out_dir, sr):
    """CPU-only HPSS + band-mask fallback. Below ML quality; for no-GPU use."""
    import numpy as np, librosa, soundfile as sf
    y = librosa.load(drums_path, sr=sr, mono=True)[0]
    perc = librosa.effects.hpss(y)[1]
    bands = {"Kick": (20, 120), "Snare": (120, 400), "Toms": (80, 300),
             "HiHat": (6000, 16000), "Cymbals": (4000, 18000),
             "Ride": (3000, 12000), "Crash": (4000, 18000)}
    freqs = librosa.fft_frequencies(sr=sr)
    stft = librosa.stft(perc)
    out = {}
    for role in roles:
        lo, hi = bands.get(role, (20, 18000))
        mask = ((freqs >= lo) & (freqs <= hi)).astype(float)[:, None]
        p = os.path.join(out_dir, f"{role}.wav")
        sf.write(p, librosa.istft(stft * mask), sr)
        out[role] = p
    return out


def _is_silent(path: str, thresh_db: float = -50.0) -> bool:
    """True if the stem's RMS is below thresh_db (i.e. the song lacks this part)."""
    import math
    import numpy as np, soundfile as sf
    y, _ = sf.read(path, dtype="float32")
    if y.size == 0:
        return True
    rms = float(np.sqrt(np.mean(np.square(y))))
    return rms <= 0 or 20 * math.log10(rms) < thresh_db


def _sum_outputs(out_dir: str, tokens: list, role: str, sr: int):
    """Sum DrumSep outputs whose parenthesized token is in `tokens` into
    <role>.wav, remove the summed sources, and return the new path (or None)."""
    import glob
    import numpy as np, soundfile as sf
    paths = sorted({p for t in tokens
                    for p in glob.glob(os.path.join(out_dir, f"*({t})*.wav"))})
    if not paths:
        return None
    mix = None
    for p in paths:
        y, _ = sf.read(p, dtype="float32")
        mix = y if mix is None else mix + y
    dest = os.path.join(out_dir, f"{role}.wav")
    sf.write(dest, mix, sr, subtype="PCM_24")
    for p in paths:
        if os.path.abspath(p) != os.path.abspath(dest):
            os.remove(p)
    return dest


def _to_bits(path: str, subtype: str = "PCM_24") -> None:
    """Rewrite a WAV at the given PCM bit depth if it isn't already."""
    import soundfile as sf
    if sf.info(path).subtype == subtype:
        return
    y, sr = sf.read(path, dtype="float64")
    sf.write(path, y, sr, subtype=subtype)


def _prune(out_dir: str, keep_paths: list) -> None:
    """Remove every WAV in out_dir except the manifest stems (drops Demucs
    residuals, the pre-split vocals, and unused kit pieces)."""
    import glob
    keep = {os.path.abspath(p) for p in keep_paths}
    for p in glob.glob(os.path.join(out_dir, "*.wav")):
        if os.path.abspath(p) not in keep:
            os.remove(p)


def main():
    ap = argparse.ArgumentParser(description="Stage 2 — separation engine (Tier 2)")
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--song", default=None)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    cfg = _load_cfg(args.config)
    if args.list_models:
        list_models(cfg)
        return
    if not args.audio:
        ap.error("audio path required (or use --list-models)")

    song = args.song or os.path.splitext(os.path.basename(args.audio))[0]
    man = separate_song(args.audio, song, cfg)
    print(f"\nStage 2 complete ({man.backend}): {len(man.stems)} stems")
    for s in man.stems:
        tail = f"  ({s.notes})" if s.notes else ""
        print(f"  {s.role:11s} -> {s.bus:20s} {os.path.basename(s.path)}{tail}")
    print("\nNext: run Stage 1 (ingest.py) to add the tempo map, then ear-check the stems.")


if __name__ == "__main__":
    main()
