"""Analysis engine.

Models run SEQUENTIALLY: one model is loaded, analyzes every file, is unloaded
(freeing the GPU) and only then is the next one loaded. It is slower than
keeping them all in memory, but it fits on modest GPUs and avoids VRAM spikes.
"""
from __future__ import annotations

import gc
import math
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

import numpy as np

from . import audio as audio_mod
from . import scoring
from .i18n import tr
from .registry import ModelInfo, create_detector

TIMELINE_STEP = 0.25   # resolution of the forensic timeline (s)
MIN_DURATION = 0.3     # shorter audio is rejected (s)
CACHE_SAMPLES = 150_000_000  # ~600 MB of decoded audio kept in memory


class Cancelled(Exception):
    pass


@dataclass
class ModelResult:
    model_id: str
    model_name: str
    threshold: float
    weight: float = 1.0
    prob: float | None = None      # P(fake) pooled over the windows
    peak: float | None = None      # highest P(fake) of any window
    score: float | None = None     # 0-100, calibrated with the threshold
    n_windows: int = 0
    elapsed: float = 0.0
    error: str | None = None
    timeline: list | None = None   # 0-100 scores every TIMELINE_STEP s

    @property
    def is_fake(self) -> bool:
        return self.score is not None and self.score >= scoring.DECISION


@dataclass
class FileResult:
    path: str
    name: str
    duration: float
    sample_rate: int
    channels: int
    format: str
    size: int
    sha256: str = ""
    analyzed_at: str = ""
    forensic: bool = False
    device: str = "cpu"
    aggregation: str = "sensitive"
    models: list = field(default_factory=list)
    total: float | None = None
    timeline: list | None = None
    timeline_step: float = TIMELINE_STEP
    segments: list = field(default_factory=list)
    envelope: tuple | None = None
    error: str | None = None

    @property
    def ok_models(self) -> list[ModelResult]:
        return [m for m in self.models if m.score is not None]

    @property
    def n_fake(self) -> int:
        return sum(1 for m in self.models if m.is_fake)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("envelope", None)
        d["verdict"] = scoring.verdict(self.total)
        return d


def configure_torch() -> None:
    """Global PyTorch settings applied before analyzing.

    DF-Arena's weights contain denormal numbers, which make computations ~20x
    slower on x86 CPUs. Flushing them to zero does not change the result
    (measured difference: 0) and has no effect on GPU.
    """
    try:
        import torch

        torch.set_flush_denormal(True)
    except Exception:
        pass


def resolve_device(pref: str = "auto") -> str:
    try:
        import torch

        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False
    if pref == "cpu":
        return "cpu"
    return "cuda" if has_cuda else "cpu"


def _check(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def _short_error(e: BaseException) -> str:
    msg = f"{type(e).__name__}: {e}".strip()
    return msg if len(msg) < 400 else msg[:400] + "…"


def _free_memory():
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


class _AudioCache:
    def __init__(self, limit: int = CACHE_SAMPLES):
        self.limit, self.used, self.data = limit, 0, {}

    def get(self, path: str, sr: int) -> np.ndarray:
        key = (path, sr)
        if key in self.data:
            return self.data[key]
        wave = audio_mod.load(path, sr)
        if self.used + len(wave) <= self.limit:
            self.data[key] = wave
            self.used += len(wave)
        return wave


def _predict_windows(det, wave, windows, batch_size, cancel, tick) -> list[float]:
    out = []
    for i in range(0, len(windows), batch_size):
        _check(cancel)
        chunk = [np.ascontiguousarray(wave[s:e]) for s, e in windows[i:i + batch_size]]
        probs = det.predict_batch(chunk) if len(chunk) > 1 else [det.predict(chunk[0])]
        if len(probs) != len(chunk):
            raise ValueError("predict_batch returned a different number of results than waveforms")
        for p in probs:
            v = float(p)
            if not math.isfinite(v):
                raise ValueError(f"The model returned a non-finite value: {v}")
            out.append(min(1.0, max(0.0, v)))
        tick(len(chunk))
    return out


def _units(duration: float, info: ModelInfo, forensic: bool) -> int:
    n = max(1, int(duration * info.sample_rate))
    u = len(scoring.standard_windows(n, info.sample_rate, info.window_seconds))
    if forensic:
        u += len(scoring.sliding_windows(n, info.sample_rate, info.forensic_window_seconds,
                                         info.forensic_hop_seconds))
    return u


def score_wave(det, info: ModelInfo, wave: np.ndarray, threshold: float, forensic: bool,
               cancel=None, tick: Callable[[int], None] = lambda n: None,
               aggregation: str = "sensitive") -> ModelResult:
    """Scores a waveform with an already loaded detector."""
    mr = ModelResult(info.id, info.name, threshold, info.weight)
    sr = info.sample_rate
    t0 = time.perf_counter()
    std = scoring.standard_windows(len(wave), sr, info.window_seconds)
    probs = _predict_windows(det, wave, std, info.batch_size, cancel, tick)
    mr.prob = scoring.aggregate(probs, aggregation)
    mr.peak = float(np.max(probs))
    mr.n_windows = len(probs)
    mr.score = scoring.calibrated_score(mr.prob, threshold)
    if forensic:
        fw = scoring.sliding_windows(len(wave), sr, info.forensic_window_seconds, info.forensic_hop_seconds)
        fprobs = _predict_windows(det, wave, fw, info.batch_size, cancel, tick)
        grid = scoring.to_grid(fw, fprobs, len(wave), sr, TIMELINE_STEP)
        mr.timeline = [round(scoring.calibrated_score(p, threshold), 2) for p in grid]
        mr.peak = max(mr.peak, float(np.max(fprobs)))
    mr.elapsed = time.perf_counter() - t0
    return mr


def run_analysis(files: list, models: list[ModelInfo], thresholds: dict, device_pref: str = "auto",
                 forensic: bool = False, report: Callable[[dict], None] | None = None,
                 cancel: threading.Event | None = None, aggregation: str = "sensitive") -> list[FileResult]:
    """Analyzes `files` (list of AudioInfo) with `models`, one after another."""
    report = report or (lambda e: None)
    configure_torch()
    device = resolve_device(device_pref)
    now = datetime.now().isoformat(timespec="seconds")
    results = [FileResult(f.path, f.name, f.duration, f.sample_rate, f.channels, f.format, f.size,
                          analyzed_at=now, forensic=forensic, device=device, aggregation=aggregation)
               for f in files]

    report({"type": "phase", "phase": "hashing"})
    for r in results:
        _check(cancel)
        try:
            r.sha256 = audio_mod.sha256(r.path)
        except Exception as e:
            r.error = _short_error(e)

    cache = _AudioCache()
    n_models = len(models)
    for mi, info in enumerate(models):
        _check(cancel)
        threshold = float(thresholds.get(info.id, info.default_threshold))
        units_total = sum(_units(r.duration or 1.0, info, forensic) for r in results if not r.error) or 1
        done = [0]

        def tick(n, mi=mi, units_total=units_total, done=done):
            done[0] += n
            frac = 0.1 + 0.9 * min(1.0, done[0] / units_total)
            report({"type": "progress", "value": (mi + frac) / n_models})

        report({"type": "stage", "index": mi, "count": n_models, "model": info.name, "phase": "loading"})
        report({"type": "progress", "value": mi / n_models})
        detector = None
        try:
            detector = create_detector(info, device)
            detector.load()
        except Exception as e:
            msg = _short_error(e)
            traceback.print_exc()
            for r in results:
                r.models.append(ModelResult(info.id, info.name, threshold, info.weight, error=msg))
            report({"type": "model_status", "index": mi, "status": "error", "message": msg})
            detector = None
            _free_memory()
            continue

        report({"type": "stage", "index": mi, "count": n_models, "model": info.name, "phase": "running"})
        report({"type": "progress", "value": (mi + 0.1) / n_models})
        n_err = 0
        try:
            for fi, r in enumerate(results):
                _check(cancel)
                report({"type": "file", "index": fi, "count": len(results), "name": r.name})
                if r.error:
                    continue
                try:
                    wave = cache.get(r.path, info.sample_rate)
                except Exception as e:
                    r.error = tr("error.read_audio", err=_short_error(e))
                    continue
                if r.envelope is None:
                    r.envelope = audio_mod.envelope(wave)
                    r.duration = len(wave) / info.sample_rate
                if len(wave) < MIN_DURATION * info.sample_rate:
                    r.error = tr("error.too_short")
                    continue
                try:
                    mr = score_wave(detector, info, wave, threshold, forensic, cancel, tick, aggregation)
                except Cancelled:
                    raise
                except Exception as e:
                    traceback.print_exc()
                    mr = ModelResult(info.id, info.name, threshold, info.weight, error=_short_error(e))
                    n_err += 1
                r.models.append(mr)
        finally:
            report({"type": "stage", "index": mi, "count": n_models, "model": info.name, "phase": "unloading"})
            try:
                detector.unload()
            except Exception:
                traceback.print_exc()
            del detector
            _free_memory()
        status = "error" if n_err and n_err == len(results) else "done"
        report({"type": "model_status", "index": mi, "status": status, "message": ""})

    for r in results:
        _finalize(r, forensic)
    report({"type": "progress", "value": 1.0})
    return results


def _finalize(r: FileResult, forensic: bool) -> None:
    ok = r.ok_models
    if r.error:
        return
    if not ok:
        r.error = tr("error.no_model")
        return
    r.total = scoring.combine([m.score for m in ok], [m.weight for m in ok])
    if forensic:
        lines = [(m.timeline, m.weight) for m in ok if m.timeline]
        if lines:
            k = min(len(t) for t, _ in lines)
            arr = np.array([t[:k] for t, _ in lines], dtype=float)
            w = np.array([wt for _, wt in lines], dtype=float)
            w = w if w.sum() > 0 else np.ones_like(w)
            r.timeline = (arr * w[:, None]).sum(0) / w.sum()
            r.timeline = [round(float(v), 2) for v in r.timeline]
            r.segments = scoring.find_segments(r.timeline, TIMELINE_STEP)


def score_files(paths: list[str], models: list[ModelInfo], device_pref: str = "auto",
                report: Callable[[dict], None] | None = None,
                cancel: threading.Event | None = None, aggregation: str = "sensitive") -> dict[str, list]:
    """Standard P(fake) of each file with each model (used to calibrate thresholds)."""
    report = report or (lambda e: None)
    configure_torch()
    device = resolve_device(device_pref)
    out: dict[str, list] = {}
    cache = _AudioCache()
    total = max(1, len(models) * len(paths))
    step = 0
    for mi, info in enumerate(models):
        _check(cancel)
        report({"type": "stage", "index": mi, "count": len(models), "model": info.name, "phase": "loading"})
        probs: list = [None] * len(paths)
        try:
            det = create_detector(info, device)
            det.load()
        except Exception as e:
            out[info.id] = probs
            report({"type": "model_status", "index": mi, "status": "error", "message": _short_error(e)})
            _free_memory()
            step += len(paths)
            continue
        report({"type": "stage", "index": mi, "count": len(models), "model": info.name, "phase": "running"})
        try:
            for i, p in enumerate(paths):
                _check(cancel)
                report({"type": "file", "index": i, "count": len(paths), "name": p})
                try:
                    wave = cache.get(p, info.sample_rate)
                    if len(wave) >= MIN_DURATION * info.sample_rate:
                        mr = score_wave(det, info, wave, 0.5, False, cancel, aggregation=aggregation)
                        probs[i] = mr.prob
                except Cancelled:
                    raise
                except Exception:
                    traceback.print_exc()
                step += 1
                report({"type": "progress", "value": step / total})
        finally:
            det.unload()
            del det
            _free_memory()
        out[info.id] = probs
        report({"type": "model_status", "index": mi, "status": "done", "message": ""})
    return out
