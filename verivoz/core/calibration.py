"""Decision threshold computed from the user's own real and fake audio.

The equal error rate (EER) point is chosen: the threshold at which the share of
real audio flagged as fake (FAR) equals the share of fake audio passing as real
(FRR).
"""
from __future__ import annotations

import numpy as np


def compute_threshold(real_probs, fake_probs) -> dict:
    real = np.array([p for p in real_probs if p is not None], dtype=float)
    fake = np.array([p for p in fake_probs if p is not None], dtype=float)
    if len(real) == 0 or len(fake) == 0:
        raise ValueError("At least one real and one fake file must be analyzed successfully")

    values = np.unique(np.concatenate([real, fake]))
    # Any threshold between two consecutive values classifies the same way:
    # the midpoints are used because they are the most robust choice.
    cands = list((values[:-1] + values[1:]) / 2) if len(values) > 1 else []
    cands = [max(0.0, values[0] - 1e-3)] + cands + [min(1.0, values[-1] + 1e-3)]

    rows = []
    for t in cands:
        far = float(np.mean(real >= t))   # real files flagged as fake
        frr = float(np.mean(fake < t))    # fake files passing as real
        rows.append((abs(far - frr), (far + frr) / 2, t, far, frr))
    best_gap = min(r[0] for r in rows)
    tied = [r for r in rows if r[0] - best_gap < 1e-12]
    best_eer = min(r[1] for r in tied)
    tied = [r for r in tied if r[1] - best_eer < 1e-12]
    _, eer, t, far, frr = tied[len(tied) // 2]

    t = float(min(0.99, max(0.01, t)))
    acc = (float(np.mean(real < t)) + float(np.mean(fake >= t))) / 2
    return {
        "threshold": round(t, 4),
        "eer": round(eer * 100, 2),
        "far": round(far * 100, 2),
        "frr": round(frr * 100, 2),
        "balanced_accuracy": round(acc * 100, 2),
        "n_real": int(len(real)),
        "n_fake": int(len(fake)),
    }
