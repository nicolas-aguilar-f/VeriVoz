"""0-100 score, analysis windows, timeline and suspicious segments."""
from __future__ import annotations

import math

import numpy as np

DECISION = 50.0  # after calibration, every model's threshold sits at 50


def calibrated_score(prob: float, threshold: float) -> float:
    """Maps P(fake) to a 0-100 score where the threshold lands on 50.

    It is piecewise linear: [0, threshold] -> [0, 50] and [threshold, 1] -> [50, 100].
    With the default threshold (0.5) it equals prob * 100.
    """
    p = min(1.0, max(0.0, float(prob)))
    t = min(0.99, max(0.01, float(threshold)))
    if p < t:
        return 50.0 * p / t
    return 50.0 + 50.0 * (p - t) / (1.0 - t)


def verdict(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 25:
        return "authentic"
    if score < DECISION:
        return "likely_authentic"
    if score < 75:
        return "likely_fake"
    return "fake"


AGGREGATIONS = ("sensitive", "mean", "max")


def aggregate(probs, method: str = "sensitive") -> float:
    """Summarizes the P(fake) of a file's windows into a single value.

    - "mean": average. A short manipulated segment gets diluted in long audio.
    - "max": the most suspicious window. Very sensitive, but a single noisy
      segment can trigger a false positive.
    - "sensitive" (default): generalized mean of order 4, (mean(p^4))^(1/4).
      It weights suspicious windows much more, so it catches partial
      manipulations, but the evidence has to be strong or repeated. With a
      single window it matches the other two.
    """
    a = np.clip(np.asarray(probs, dtype=float), 0.0, 1.0)
    if method == "mean":
        return float(a.mean())
    if method == "max":
        return float(a.max())
    return float(np.mean(a ** 4) ** 0.25)


def combine(values, weights) -> float | None:
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None and w > 0]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total_w


# ------------------------------------------------------------------ windows
def standard_windows(n: int, sr: int, window_seconds: float | None) -> list[tuple[int, int]]:
    """Contiguous windows covering the whole audio (the last one overlaps if needed)."""
    if not window_seconds:
        return [(0, n)]
    w = int(round(window_seconds * sr))
    if n <= w:
        return [(0, n)]
    out = [(s, s + w) for s in range(0, n - w + 1, w)]
    if out[-1][1] < n:
        out.append((n - w, n))
    return out


def sliding_windows(n: int, sr: int, window_seconds: float, hop_seconds: float) -> list[tuple[int, int]]:
    """Overlapping sliding windows for the forensic analysis."""
    w = int(round(window_seconds * sr))
    h = max(1, int(round(hop_seconds * sr)))
    if n <= w:
        return [(0, n)]
    out = [(s, s + w) for s in range(0, n - w + 1, h)]
    if out[-1][1] < n:
        out.append((n - w, n))
    return out


def to_grid(windows, probs, n: int, sr: int, step: float) -> list[float]:
    """Averages the windows covering each instant -> grid of `step` seconds."""
    k = max(1, math.ceil(n / sr / step))
    acc = np.zeros(k)
    cnt = np.zeros(k)
    for (s, e), p in zip(windows, probs):
        a = min(k - 1, int(math.floor(s / sr / step)))
        b = max(a + 1, min(k, int(math.ceil(e / sr / step))))
        acc[a:b] += p
        cnt[a:b] += 1
    filled = cnt > 0
    if not filled.any():
        return [float(np.mean(probs))] * k
    grid = np.full(k, np.nan)
    grid[filled] = acc[filled] / cnt[filled]
    idx = np.arange(k)
    grid = np.interp(idx, idx[filled], grid[filled])
    return grid.tolist()


def find_segments(scores, step: float, threshold: float = DECISION,
                  merge_gap: float = 1.5, min_len: float = 0.5) -> list[dict]:
    """Groups the instants scoring >= threshold into [start, end] segments."""
    if not scores:
        return []
    arr = np.asarray(scores, dtype=float)
    above = arr >= threshold
    runs, start = [], None
    for i, flag in enumerate(above):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(arr)])
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) * step <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for a, b in merged:
        if (b - a) * step < min_len:
            continue
        seg = arr[a:b]
        out.append({"start": round(a * step, 3), "end": round(b * step, 3),
                    "peak": round(float(seg.max()), 2), "mean": round(float(seg.mean()), 2)})
    return out
