"""Plugin validator: checks the manifest, the code, loading and predictions.

Used by the interface (Settings > Models > Validate) and tools/validate_model.py.
"""
from __future__ import annotations

import inspect
import math
import time
import traceback
from pathlib import Path
from typing import Callable

import numpy as np

from .detector import BaseDetector
from .registry import ModelInfo, load_detector_class, parse_manifest

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


def _signals(sr: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    t3 = np.arange(int(3 * sr)) / sr
    sweep = 0.3 * np.sin(2 * np.pi * (100 + 900 * t3) * t3)
    return {
        "noise 0.5 s": (0.05 * rng.standard_normal(int(0.5 * sr))).astype(np.float32),
        "sweep 3 s": sweep.astype(np.float32),
        "noise 6 s": (0.1 * rng.standard_normal(int(6 * sr))).astype(np.float32),
    }


def validate(target: ModelInfo | str | Path, device: str = "cpu", deep: bool = True,
             audio_path: str | None = None, log: Callable[[str, str], None] | None = None) -> bool:
    """Returns True if the plugin is usable. `log(level, message)` receives the report."""
    log = log or (lambda level, msg: print(f"[{level.upper():4}] {msg}"))
    info = target if isinstance(target, ModelInfo) else parse_manifest(Path(target))
    passed = True

    log(INFO, f"Plugin: {info.name} (id={info.id}) in {info.plugin_dir}")
    # 1. manifest
    if info.errors:
        for e in info.errors:
            log(FAIL, e)
        return False
    log(OK, "manifest.json is valid")
    for it in info.downloads:
        log(INFO, f"Declared download: {it.name} · {it.source} · {len(it.files)} file(s)")
    if info.pending_downloads:
        for it in info.pending_downloads:
            log(FAIL, f"Not downloaded yet: {it.name} ({len(it.missing_files)} file(s)). "
                      "Download it from the app or with tools/download_models.py")
        return False
    log(INFO, f"sample_rate={info.sample_rate} Hz · window={info.window_seconds} s · "
              f"forensic={info.forensic_window_seconds}/{info.forensic_hop_seconds} s · batch={info.batch_size}")
    for key in info.files:
        log(OK, f"File '{key}' found: {info.resolve_file(key)}")

    # 2. code
    try:
        cls = load_detector_class(info)
    except Exception as e:
        log(FAIL, f"Could not import {info.entry_point}: {type(e).__name__}: {e}")
        log(INFO, traceback.format_exc(limit=3))
        return False
    log(OK, f"Class '{cls.__name__}' imported and inherits from BaseDetector")
    for method in ("load", "predict"):
        if getattr(cls, method) is getattr(BaseDetector, method):
            log(FAIL, f"The class does not implement {method}()")
            passed = False
    sig = inspect.signature(cls.__init__)
    if len(sig.parameters) > 1 and cls.__init__ is not BaseDetector.__init__:
        log(WARN, "The class overrides __init__: remember to call super().__init__(info, device)")
    if not passed or not deep:
        return passed

    # 3. loading
    from .engine import configure_torch

    configure_torch()
    try:
        det = cls(info, device)
        t0 = time.perf_counter()
        det.load()
        log(OK, f"load() finished in {time.perf_counter() - t0:.1f} s (device: {device})")
    except Exception as e:
        log(FAIL, f"load() failed: {type(e).__name__}: {e}")
        log(INFO, traceback.format_exc(limit=4))
        return False

    # 4. predictions
    try:
        for name, wave in _signals(info.sample_rate).items():
            t0 = time.perf_counter()
            p = det.predict(wave)
            dt = time.perf_counter() - t0
            if not isinstance(p, (float, int, np.floating)) and not hasattr(p, "item"):
                log(FAIL, f"predict() must return a float, it returned {type(p).__name__}")
                passed = False
                continue
            p = float(p)
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                log(FAIL, f"predict({name}) = {p}: it must be a probability between 0 and 1")
                passed = False
            else:
                log(OK, f"predict({name}) = {p:.4f}  ({dt * 1000:.0f} ms)")
        sig = _signals(info.sample_rate)["sweep 3 s"]
        batch = det.predict_batch([sig, sig])
        if len(batch) != 2:
            log(FAIL, "predict_batch() must return a list of the same length as its input")
            passed = False
        else:
            single = float(det.predict(sig))
            if abs(float(batch[0]) - single) > 1e-2:
                log(WARN, f"predict_batch and predict disagree ({float(batch[0]):.4f} vs {single:.4f})")
            else:
                log(OK, "predict_batch() is consistent with predict()")
        if audio_path:
            from . import engine
            from .audio import load

            wave = load(audio_path, info.sample_rate)
            mr = engine.score_wave(det, info, wave, info.default_threshold, forensic=True)
            log(OK, f"Test audio '{Path(audio_path).name}': P(fake)={mr.prob:.4f} · "
                    f"score={mr.score:.1f}/100 · {mr.n_windows} windows · {mr.elapsed:.1f} s")
    except Exception as e:
        log(FAIL, f"predict() failed: {type(e).__name__}: {e}")
        log(INFO, traceback.format_exc(limit=4))
        passed = False
    finally:
        try:
            det.unload()
            log(OK, "unload() finished")
        except Exception as e:
            log(WARN, f"unload() failed: {e}")
    return passed
