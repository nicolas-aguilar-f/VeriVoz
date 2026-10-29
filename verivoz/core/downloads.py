"""Automatic download of the files each model needs.

Every plugin declares in its manifest.json a "downloads" list with WHAT to
download, FROM WHERE, its size, its SHA-256 and its license. This module:
  - detects what is missing (comparing sizes),
  - downloads into <file>.part and resumes if interrupted (HTTP Range header),
  - checks the SHA-256 before accepting the file.

Standard library only: install.py uses it before the .venv exists.

Format of each "downloads" entry:
    {"name": "...", "type": "huggingface", "repo": "org/model", "revision": "<commit>",
     "target": "weights/folder", "files": [{"path": "config.json", "size": 600, "sha256": "..."}],
     "license": "...", "license_url": "...", "requires_acceptance": false}
    {"name": "...", "type": "url", "url": "https://...", "page": "https://...",
     "target": "weights/file.pth", "size": 123, "sha256": "...", "license": "...", "license_url": "..."}
"""
from __future__ import annotations

import hashlib
import json
import shutil
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.client import IncompleteRead
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse

from .paths import PLUGINS_DIR

USER_AGENT = "VeriVoz-downloader/1.0"
CHUNK = 1 << 20
RETRIES = 5
REPORT_EVERY = 0.2  # seconds between progress events


class DownloadCancelled(Exception):
    pass


class IntegrityError(IOError):
    pass


@dataclass
class RemoteFile:
    url: str
    dest: Path
    size: int | None = None
    sha256: str | None = None

    @property
    def name(self) -> str:
        return self.dest.name

    def present(self) -> bool:
        return self.dest.is_file() and (self.size is None or self.dest.stat().st_size == self.size)


@dataclass
class DownloadItem:
    model_id: str
    model_name: str
    name: str
    page: str
    license: str = ""
    license_url: str = ""
    requires_acceptance: bool = False
    target: Path = Path()
    files: list = field(default_factory=list)
    # model data (to group versions and show approximate specs)
    family: str = ""
    family_name: str = ""
    hardware: dict = field(default_factory=dict)
    order: int = 100

    @property
    def source(self) -> str:
        """Origen legible: dominio + ruta (p. ej. huggingface.co/facebook/wav2vec2-xls-r-300m)."""
        u = urlparse(self.page)
        return (u.netloc + u.path).rstrip("/")

    @property
    def total_size(self) -> int:
        return sum(f.size or 0 for f in self.files)

    @property
    def missing_files(self) -> list[RemoteFile]:
        return [f for f in self.files if not f.present()]

    @property
    def missing_size(self) -> int:
        return sum(f.size or 0 for f in self.missing_files)

    @property
    def complete(self) -> bool:
        return not self.missing_files


# ------------------------------------------------------------------ lectura
def items_from_manifest(plugin_dir: Path, manifest: dict) -> list[DownloadItem]:
    plugin_dir = Path(plugin_dir).resolve()
    items = []
    for spec in manifest.get("downloads", []) or []:
        kind = spec.get("type", "url")
        target = (plugin_dir / spec["target"]).resolve()
        if kind == "huggingface":
            repo, rev = spec["repo"], spec.get("revision", "main")
            base = f"https://huggingface.co/{repo}/resolve/{rev}/"
            files = [RemoteFile(base + quote(f["path"]), target / f["path"], f.get("size"), f.get("sha256"))
                     for f in spec["files"]]
            page = spec.get("page") or f"https://huggingface.co/{repo}"
        elif kind == "url":
            files = [RemoteFile(spec["url"], target, spec.get("size"), spec.get("sha256"))]
            page = spec.get("page") or spec["url"]
        else:
            raise ValueError(f"Unknown download type: {kind!r}")
        items.append(DownloadItem(
            model_id=str(manifest.get("id", plugin_dir.name)), model_name=str(manifest.get("name", plugin_dir.name)),
            name=spec.get("name", target.name), page=page, license=spec.get("license", ""),
            license_url=spec.get("license_url", ""), requires_acceptance=bool(spec.get("requires_acceptance")),
            target=target, files=files, family=str(manifest.get("family", "")),
            family_name=str(manifest.get("family_name", "")), hardware=dict(manifest.get("hardware") or {}),
            order=int(manifest.get("order", 100))))
    return items


def group_by_model(items: list[DownloadItem]) -> dict[str, list[DownloadItem]]:
    groups: dict[str, list[DownloadItem]] = {}
    for it in sorted(items, key=lambda i: (i.order, i.model_name)):
        groups.setdefault(it.model_id, []).append(it)
    return groups


def installed_families(plugins_dir: Path = PLUGINS_DIR) -> set[str]:
    """Families (e.g. "df_arena") with at least one fully downloaded version."""
    complete: dict[str, bool] = {}
    for it in scan(plugins_dir, only_missing=False):
        if it.family:
            key = (it.family, it.model_id)
            complete[key] = complete.get(key, True) and it.complete
    return {fam for (fam, _), ok in complete.items() if ok}


def scan(plugins_dir: Path = PLUGINS_DIR, model_ids=None, only_missing: bool = True) -> list[DownloadItem]:
    """Downloads declared by the plugins (by default, only the incomplete ones)."""
    out = []
    if not plugins_dir.exists():
        return out
    for d in sorted(plugins_dir.iterdir()):
        mf = d / "manifest.json"
        if not d.is_dir() or d.name.startswith(("_", ".")) or not mf.exists():
            continue
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
            items = items_from_manifest(d, manifest)
        except Exception:
            continue
        if model_ids is not None and manifest.get("id") not in model_ids:
            continue
        out += [it for it in items if not only_missing or not it.complete]
    return out


def disk_free(path: Path) -> int:
    p = Path(path).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def fmt_bytes(n: float) -> str:
    """Decimal units (1 GB = 10^9 B), as shown by Hugging Face and GitHub."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def fmt_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------------------------------------------------------------- descarga
def _hash_file(path: Path, h, cancel=None):
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK * 4), b""):
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled()
            h.update(block)


def _fetch(f: RemoteFile, on_bytes: Callable[[int], None], cancel) -> None:
    """Downloads a file, resuming the .part if present. Raises network exceptions."""
    part = f.dest.with_name(f.dest.name + ".part")
    f.dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if f.size is not None and have > f.size:
        part.unlink()
        have = 0
    h = hashlib.sha256() if f.sha256 else None
    if not (f.size is not None and have == f.size):
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(f.url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:  # the server cannot resume: start over
                have = 0
            if h is not None and have:
                _hash_file(part, h, cancel)
            on_bytes(have)
            with open(part, "ab" if have else "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    if h is not None:
                        h.update(chunk)
                    on_bytes(len(chunk))
    elif h is not None:
        _hash_file(part, h, cancel)
        on_bytes(have)
    got = part.stat().st_size
    if f.size is not None and got != f.size:
        raise IOError(f"Incomplete download of {f.name}: {got} of {f.size} bytes")
    if h is not None and h.hexdigest() != f.sha256.lower():
        part.unlink()
        raise IntegrityError(f"SHA-256 mismatch for {f.name}: the downloaded file is not the expected one")
    part.replace(f.dest)


def download(items: list[DownloadItem], report: Callable[[dict], None] | None = None, cancel=None) -> int:
    """Downloads everything missing from `items`. Returns the bytes downloaded.

    Events sent to `report`:
      {"type": "file", "index", "count", "model", "item", "file", "size"}
      {"type": "progress", "done", "total", "speed", "eta"}
      {"type": "file_done", "file"}
    """
    report = report or (lambda e: None)
    pending = [(it, f) for it in items for f in it.missing_files]
    total = sum(f.size or 0 for _, f in pending)
    needed = total - sum((f.dest.with_name(f.dest.name + ".part").stat().st_size
                          if f.dest.with_name(f.dest.name + ".part").exists() else 0) for _, f in pending)
    if pending and needed > 0 and disk_free(pending[0][1].dest) < needed * 1.02:
        raise IOError(f"Not enough disk space: {fmt_bytes(needed)} needed and "
                      f"{fmt_bytes(disk_free(pending[0][1].dest))} available")
    state = {"done": 0, "base": 0, "t0": time.monotonic(), "last": 0.0, "net": 0}

    def emit(force=False):
        now = time.monotonic()
        if not force and now - state["last"] < REPORT_EVERY:
            return
        state["last"] = now
        elapsed = max(1e-3, now - state["t0"])
        speed = state["net"] / elapsed
        remaining = max(0, total - state["done"])
        eta = remaining / speed if speed > 1 and elapsed >= 2.0 else None  # stable estimate
        report({"type": "progress", "done": state["done"], "total": total, "speed": speed, "eta": eta})

    for i, (it, f) in enumerate(pending):
        report({"type": "file", "index": i, "count": len(pending), "model": it.model_name, "item": it.name,
                "file": f.name, "size": f.size})
        start_done = state["done"]
        for attempt in range(1, RETRIES + 1):
            state["done"] = start_done
            first = [True]

            def on_bytes(n):
                state["done"] += n
                if first[0]:          # bytes already in the .part do not count towards speed
                    first[0] = False
                else:
                    state["net"] += n
                emit()

            try:
                _fetch(f, on_bytes, cancel)
                break
            except (DownloadCancelled, IntegrityError):
                raise
            except (urllib.error.URLError, socket.timeout, ConnectionError, IncompleteRead, TimeoutError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                    raise IOError(f"{f.url} answered {e.code} {e.reason}") from e
                if isinstance(e, urllib.error.HTTPError) and e.code == 416:  # invalid .part: start over
                    f.dest.with_name(f.dest.name + ".part").unlink(missing_ok=True)
                if attempt == RETRIES:
                    raise IOError(f"Could not download {f.name} after {RETRIES} attempts: {e}") from e
                for _ in range(int(2 * attempt / 0.1)):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    time.sleep(0.1)
        state["done"] = start_done + (f.size or 0)
        report({"type": "file_done", "file": f.name})
        emit(force=True)
    return state["net"]
