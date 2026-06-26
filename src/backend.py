"""
backend.py — picks the separation backend and gives the rest of the pipeline a
single, stable interface regardless of which one is installed.

Two backends expose nearly the same `Separator` API:
  - mlx_audio_separator      (Apple-Silicon native; no torch/onnx at inference)
  - audio_separator.separator (the original, torch/onnx based; proven fallback)

On an M1 we prefer MLX; if it isn't installed we fall back to torch. Constructor
and method signatures differ slightly between versions, so every call here is
defensive — we probe rather than assume.
"""
from __future__ import annotations


def make_separator(cfg: dict):
    out = cfg["output"]
    model_dir = cfg.get("models", {}).get("model_file_dir") or None
    pref = cfg.get("backend", "auto").lower()

    order = []
    if pref in ("auto", "mlx"):
        order.append("mlx")
    if pref in ("auto", "torch"):
        order.append("torch")

    last_err = None
    for name in order:
        try:
            Separator = _import_separator(name)
        except ImportError as e:
            last_err = e
            continue
        sep = _construct(Separator, out, model_dir)
        sep._backend_name = name
        return sep

    raise ImportError(
        "No separation backend installed. Install one:\n"
        "  pip install mlx-audio-separator   # Apple Silicon, recommended\n"
        "  pip install 'audio-separator[cpu]' # torch fallback\n"
        f"(last import error: {last_err})"
    )


def _import_separator(name: str):
    if name == "mlx":
        from mlx_audio_separator import Separator  # type: ignore
        return Separator
    from audio_separator.separator import Separator  # type: ignore
    return Separator


def _construct(Separator, out: dict, model_dir):
    # try richest constructor first, then progressively simpler ones
    attempts = [
        dict(output_dir=out["dir"], output_format=out["format"],
             sample_rate=out["sample_rate"], model_file_dir=model_dir),
        dict(output_dir=out["dir"], output_format=out["format"],
             model_file_dir=model_dir),
        dict(output_dir=out["dir"], output_format=out["format"]),
        dict(output_dir=out["dir"]),
        dict(),
    ]
    last = None
    for kwargs in attempts:
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        try:
            return Separator(**kwargs)
        except TypeError as e:
            last = e
    raise last


def backend_name(sep) -> str:
    return getattr(sep, "_backend_name", "unknown")


def list_models(sep):
    """Return the backend's model registry (dict or list), or None."""
    for attr in ("list_supported_model_files", "list_models", "get_supported_models"):
        fn = getattr(sep, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    return None


def _model_pairs(models) -> list[tuple[str, str]]:
    """(friendly_name, model_filename) pairs from the backend registry.

    The registry nests as {group: {friendly_name: {'filename': ..., 'scores': ...}}}.
    `load_model` wants the filename, not the friendly name, so we keep both: match
    on either, return the filename. Older/other shapes (a plain list of names, or
    {name: filename}) are handled defensively."""
    if not models:
        return []
    if isinstance(models, dict):
        pairs: list[tuple[str, str]] = []
        for v in models.values():
            if isinstance(v, dict):
                for name, meta in v.items():
                    if isinstance(meta, dict) and meta.get("filename"):
                        pairs.append((str(name), str(meta["filename"])))
                    elif isinstance(meta, str):
                        pairs.append((str(name), meta))
                    else:
                        pairs.append((str(name), str(name)))
            elif isinstance(v, (list, tuple)):
                pairs.extend((str(x), str(x)) for x in v)
        return pairs
    return [(str(x), str(x)) for x in models]


def _flatten(models) -> list[str]:
    """Model filenames — the value config pins and load_model expects."""
    return [fname for _, fname in _model_pairs(models)]


def resolve_model(sep, requested: str, keywords: list[str]) -> str:
    """A concrete model filename. If `requested` is real, use it; if 'auto',
    pick the first registry entry whose friendly name OR filename matches
    `keywords` (in priority order), returning its filename."""
    if requested and requested.lower() != "auto":
        return requested
    pairs = _model_pairs(list_models(sep))
    for kw in keywords:
        hit = next((fn for name, fn in pairs
                    if kw.lower() in name.lower() or kw.lower() in fn.lower()), None)
        if hit:
            return hit
    raise RuntimeError(
        f"No installed model matched {keywords}. Run the backend's --list_models "
        f"and set an explicit filename in config.yaml."
    )


def run_model(sep, model_filename: str, input_path: str,
              want: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Load a model, separate one file, return {role: output_path}.

    `want` maps each desired role to a list of stem aliases (lowercase). mlx
    names outputs `<input>_(<stem>)_<model>.wav`, so each role is matched to the
    output whose parenthesized stem token equals an alias (exact match first,
    then substring), and the matched file is renamed to `<role>.wav` for clean
    import names. With no `want`, returns {stem_token: path} for every output.

    Matching on the `(stem)` token — not a substring of the whole basename — is
    deliberate: karaoke outputs are all prefixed `Vocals_`, so a naive
    `"vocals" in basename` test matched both lead and backing to one file."""
    import os
    import re
    sep.load_model(model_filename=model_filename)
    outputs = list(sep.separate(input_path) or [])

    def stem_of(p: str) -> str:
        b = os.path.basename(p)
        m = re.search(r"\(([^)]+)\)", b)
        return (m.group(1) if m else os.path.splitext(b)[0]).lower()

    if not want:
        return {stem_of(p): p for p in outputs}

    result: dict[str, str] = {}
    used: set[str] = set()
    for role, aliases in want.items():
        al = [a.lower() for a in aliases]
        hit = next((p for p in outputs if p not in used and stem_of(p) in al), None)
        if hit is None:
            hit = next((p for p in outputs if p not in used
                        and any(a in stem_of(p) for a in al)), None)
        if hit is None:
            continue
        used.add(hit)
        dest = os.path.join(os.path.dirname(hit), f"{role}.wav")
        if os.path.abspath(dest) != os.path.abspath(hit):
            os.replace(hit, dest)
        result[role] = dest
    return result
