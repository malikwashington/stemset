"""
preflight.py — scope a test run BEFORE committing to it.

Checks your actual environment (Python, backend, ffmpeg, model dir, free space),
scans your song folder, and prints the exact command to run the first test.
Separates nothing — it just tells you what it would take.

Usage:
  python -m src.preflight "/Volumes/MEW II/gig files/wedding band" --config config.yaml
"""
from __future__ import annotations
import argparse
import importlib.util
import os
import re
import shutil
import sys

AUDIO_EXTS = (".wav", ".aiff", ".aif", ".flac", ".mp3", ".m4a", ".aac", ".ogg")


def _ok(b):  # checkmark / cross
    return "PASS" if b else "FAIL"


def check_python():
    v = sys.version_info
    good = v >= (3, 10)
    print(f"[{_ok(good)}] Python {v.major}.{v.minor} (need >= 3.10)")
    return good


def check_backend():
    mlx = importlib.util.find_spec("mlx_audio_separator") is not None
    torch = importlib.util.find_spec("audio_separator") is not None
    if mlx:
        print("[PASS] backend: mlx-audio-separator (fast path)")
    elif torch:
        print("[PASS] backend: audio-separator (torch fallback)")
    else:
        print("[FAIL] no backend installed — "
              "pip install mlx-audio-separator  (or 'audio-separator[cpu]')")
    return mlx or torch


def check_ffmpeg():
    found = shutil.which("ffmpeg") is not None
    print(f"[{_ok(found)}] ffmpeg on PATH" + ("" if found else " — brew install ffmpeg"))
    return found


def check_model_dir(cfg):
    import yaml  # local import so the file scans even without pyyaml at top
    path = (cfg.get("models", {}) or {}).get("model_file_dir") or ""
    if not path or "CHANGEME" in path:
        print("[FAIL] models.model_file_dir not set in config.yaml "
              "(point it at your external drive)")
        return False
    parent = path if os.path.isdir(path) else os.path.dirname(path) or "/"
    if not os.path.isdir(parent):
        print(f"[FAIL] model dir parent does not exist: {parent}")
        return False
    free_gb = shutil.disk_usage(parent).free / 1e9
    enough = free_gb > 8
    print(f"[{_ok(enough)}] model dir {path}  ({free_gb:.0f} GB free; ~5-8 GB needed first run)")
    return enough


def scan_songs(folder):
    if not os.path.isdir(folder):
        print(f"[FAIL] song folder not found: {folder}")
        return []
    files = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(AUDIO_EXTS) and not f.startswith("."))
    print(f"\n[{_ok(bool(files))}] {len(files)} audio files in {folder}")
    rows = []
    for f in files:
        full = os.path.join(folder, f)
        size_mb = os.path.getsize(full) / 1e6
        dur = _duration(full)
        rows.append((f, size_mb, dur))
    for f, mb, dur in rows[:25]:
        d = f"{dur/60:4.1f} min" if dur else "  ? min"
        print(f"     {d}  {mb:6.1f} MB  {f}")
    if len(rows) > 25:
        print(f"     ... and {len(rows)-25} more")
    return rows


def _duration(path):
    try:
        import soundfile as sf
        info = sf.info(path)
        return info.frames / info.samplerate
    except Exception:
        pass
    if path.lower().endswith(".wav"):  # stdlib fallback, no deps
        try:
            import wave
            with wave.open(path) as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            pass
    return None  # mp3/m4a may need ffprobe; fine to skip for scoping


def suggest(rows, folder, cfg=None):
    # a good first test: mid-length (3-5 min), not the shortest or longest
    timed = [r for r in rows if r[2]]
    pick = None
    if timed:
        mids = [r for r in timed if 150 <= r[2] <= 300]
        pick = (mids or sorted(timed, key=lambda r: abs(r[2] - 210)))[0]
    elif rows:
        pick = rows[0]
    if pick:
        path = os.path.join(folder, pick[0])
        song = os.path.splitext(pick[0])[0]
        # Mirror separate.py's slug + output layout so the suggested ingest
        # command points at where the manifest is actually written.
        slug = re.sub(r"[^A-Za-z0-9]+", "_", song).strip("_") or "song"
        out_root = (cfg or {}).get("output", {}).get("dir", "out")
        manifest = os.path.join(out_root, slug, "manifest.json")
        print("\nSuggested first test (mid-length, clean read on the models):")
        print(f'  python -m src.separate "{path}" --song "{song}"')
        print(f'  python -m src.ingest "{manifest}"')


def main():
    ap = argparse.ArgumentParser(description="Scope a test run")
    ap.add_argument("folder", help="folder of source songs")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    print("=== environment ===")
    checks = [check_python(), check_backend(), check_ffmpeg()]
    cfg = None
    try:
        import yaml
        cfg = yaml.safe_load(open(args.config))
        checks.append(check_model_dir(cfg))
    except FileNotFoundError:
        print(f"[FAIL] config not found: {args.config}")
        checks.append(False)
    except ImportError:
        print("[FAIL] PyYAML not installed — pip install PyYAML")
        checks.append(False)

    print("\n=== songs ===")
    rows = scan_songs(args.folder)
    suggest(rows, args.folder, cfg)

    print("\n=== verdict ===")
    if all(checks) and rows:
        print("Ready. Run the suggested command above for your first test.")
    else:
        print("Not ready yet — resolve the FAIL lines above, then re-run preflight.")


if __name__ == "__main__":
    main()
