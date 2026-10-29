"""Reading, resampling and metadata of audio files.

soundfile is used (WAV, FLAC, OGG, MP3...) and, if it fails, PyAV (FFmpeg) for
any other container (M4A, AAC, WMA, MP4, WEBM...). It does not depend on
torchaudio, to avoid version mismatches with torch.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np

AUDIO_EXTENSIONS = {
    ".wav", ".flac", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma",
    ".aif", ".aiff", ".aifc", ".caf", ".webm", ".mp4", ".mka", ".amr", ".au",
}


@dataclass
class AudioInfo:
    path: str
    name: str
    duration: float
    sample_rate: int
    channels: int
    format: str
    size: int


def is_audio(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def collect_audio(paths) -> list[str]:
    """Expands folders (recursively) and returns unique audio paths."""
    seen, out = set(), []

    def add(p: Path):
        key = os.path.normcase(str(p.resolve()))
        if key not in seen:
            seen.add(key)
            out.append(str(p.resolve()))

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*"), key=lambda q: str(q).lower()):
                if f.is_file() and is_audio(f):
                    add(f)
        elif p.is_file() and is_audio(p):
            add(p)
    return out


def probe(path: str) -> AudioInfo:
    """Reads the metadata without decoding the whole audio."""
    p = Path(path)
    size = p.stat().st_size
    try:
        import soundfile as sf

        info = sf.info(str(p))
        if info.frames <= 0 or info.samplerate <= 0:
            raise RuntimeError("empty")
        return AudioInfo(str(p), p.name, info.frames / info.samplerate, int(info.samplerate),
                         int(info.channels), info.format, size)
    except Exception:
        pass

    import av

    with av.open(str(p)) as container:
        if not container.streams.audio:
            raise ValueError("The file has no audio tracks")
        stream = container.streams.audio[0]
        ctx = stream.codec_context
        sr = int(ctx.sample_rate or getattr(stream, "rate", 0) or 0)
        layout = getattr(ctx, "layout", None)
        channels = int(getattr(layout, "nb_channels", 0) or getattr(ctx, "channels", 0) or 1)
        if container.duration:
            duration = container.duration / 1_000_000
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = 0.0
        fmt = (container.format.name or "").split(",")[0].upper()
        return AudioInfo(str(p), p.name, float(duration), sr, channels, fmt or p.suffix[1:].upper(), size)


def resample(wave: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return wave.astype(np.float32, copy=False)
    from scipy.signal import resample_poly

    g = gcd(int(orig_sr), int(target_sr))
    out = resample_poly(wave, int(target_sr) // g, int(orig_sr) // g)
    return out.astype(np.float32, copy=False)


def load(path: str, target_sr: int) -> np.ndarray:
    """Returns the mono float32 waveform in [-1, 1] at `target_sr` Hz."""
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if data.size == 0:
            raise RuntimeError("empty")
        wave = data.mean(axis=1)
        return np.ascontiguousarray(resample(wave, sr, target_sr))
    except Exception:
        pass

    import av

    chunks = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=int(target_sr))
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        try:
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
        except Exception:
            pass
    if not chunks:
        raise ValueError("The audio could not be decoded")
    return np.ascontiguousarray(np.concatenate(chunks).astype(np.float32))


def envelope(wave: np.ndarray, buckets: int = 1600) -> tuple[list[float], list[float]]:
    """Minimum and maximum per bucket, to draw the waveform."""
    n = len(wave)
    if n == 0:
        return [0.0], [0.0]
    buckets = max(1, min(buckets, n))
    edges = np.linspace(0, n, buckets + 1).astype(np.int64)
    mins = np.minimum.reduceat(wave, edges[:-1])
    maxs = np.maximum.reduceat(wave, edges[:-1])
    peak = float(max(np.abs(mins).max(), np.abs(maxs).max(), 1e-6))
    return (mins / peak).round(4).tolist(), (maxs / peak).round(4).tolist()


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def fmt_time(seconds: float, precise: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    if precise:
        m, s = divmod(seconds, 60)
        h, m = divmod(int(m), 60)
        return f"{h:d}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
