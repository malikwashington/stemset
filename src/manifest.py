"""
manifest.py — the contract between the separation engine (Stages 1-2) and the
Ableton assembly layer (Stage 3).

Describes one song's stem set: each stem's role, the performance bus it feeds,
its colour, the model that produced it, plus the song-level tempo map. No heavy
deps, so it imports anywhere.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
import json
import time


@dataclass
class Stem:
    role: str            # canonical role: "Bass", "Kick", "BGV", "LeadVox", ...
    path: str            # absolute path to the rendered WAV
    bus: str             # target Ableton performance bus (find-or-create key)
    color: str           # hex, drives the track colour
    produced_by: str     # backend + model id that created it
    sample_rate: int = 44100
    notes: str = ""      # honest caveats, e.g. "summed BGV", "guide only"


@dataclass
class TempoMap:
    bpm: float = 0.0
    time_signature: str = "4/4"
    beat_times: list[float] = field(default_factory=list)      # seconds
    downbeat_times: list[float] = field(default_factory=list)  # seconds
    is_variable: bool = False
    variance_warning: str = ""
    confirmed_by_human: bool = False   # Stage 1 gate
    source: str = ""


@dataclass
class Manifest:
    song: str
    source_file: str
    backend: str = ""
    created_at: float = field(default_factory=time.time)
    stems: list[Stem] = field(default_factory=list)
    tempo: TempoMap = field(default_factory=TempoMap)
    stage2_complete: bool = False
    stage1_complete: bool = False

    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @staticmethod
    def from_json(path: str) -> "Manifest":
        with open(path) as f:
            d = json.load(f)
        d["stems"] = [Stem(**s) for s in d.get("stems", [])]
        d["tempo"] = TempoMap(**d.get("tempo", {}))
        return Manifest(**d)
