"""Model registry: discovers plugins in /plugins, imports, installs and removes them.

A plugin is a folder with:
    manifest.json   -> metadata and configuration (see docs/ADDING_MODELS.md)
    detector.py     -> class inheriting from verivoz.core.detector.BaseDetector
    (weights)       -> .pth/.bin/... inside the folder or referenced in "files"
"""
from __future__ import annotations

import importlib
import json
import math
import re
import shutil
import sys
import time
import types
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import downloads
from .detector import BaseDetector
from .paths import PLUGINS_DIR, TEMPLATE_DIR, TRASH_DIR

MANIFEST_NAME = "manifest.json"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,47}$")
REQUIRED_KEYS = ("id", "name", "entry_point")
MISSING_FILE = "File not found"


@dataclass
class ModelInfo:
    id: str
    name: str
    plugin_dir: Path
    manifest: dict
    version: str = "1.0.0"
    author: str = ""
    license: str = ""
    entry_point: str = "detector.py:Detector"
    sample_rate: int = 16000
    weight: float = 1.0
    default_threshold: float = 0.5
    window_seconds: float | None = 4.0
    forensic_window_seconds: float = 4.0
    forensic_hop_seconds: float = 1.0
    batch_size: int = 1
    order: int = 100
    family: str = ""          # versions of the same model (e.g. "df_arena"): only one is used at a time
    family_name: str = ""
    hardware: dict = field(default_factory=dict)   # approximate specs shown to the user
    files: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    downloads: list = field(default_factory=list)          # declared DownloadItems
    pending_downloads: list = field(default_factory=list)  # the ones not downloaded yet

    @property
    def ok(self) -> bool:
        """Usable: no errors and every file downloaded."""
        return not self.errors and not self.pending_downloads

    @property
    def needs_download(self) -> bool:
        return not self.errors and bool(self.pending_downloads)

    @property
    def pending_size(self) -> int:
        return sum(it.missing_size for it in self.pending_downloads)

    def description(self, lang: str = "es") -> str:
        desc = self.manifest.get("description", "")
        if isinstance(desc, dict):
            return desc.get(lang) or desc.get("es") or desc.get("en") or next(iter(desc.values()), "")
        return str(desc or "")

    def resolve_file(self, key: str) -> Path:
        if key not in self.files:
            raise KeyError(f"'{key}' is not declared in 'files' of the {self.id} manifest")
        p = Path(self.files[key])
        return p if p.is_absolute() else (self.plugin_dir / p).resolve()

    def missing_files(self) -> list[str]:
        return [k for k in self.files if not self.resolve_file(k).exists()]

    @property
    def entry_file(self) -> Path:
        return self.plugin_dir / self.entry_point.split(":", 1)[0]

    @property
    def entry_class(self) -> str:
        parts = self.entry_point.split(":", 1)
        return parts[1] if len(parts) == 2 else "Detector"


# ----------------------------------------------------------------- manifests
def _num(value, default, cast=float, minimum=None):
    if value is None:
        return default
    v = cast(value)
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError
    if minimum is not None and v < minimum:
        raise ValueError
    return v


def parse_manifest(plugin_dir: Path) -> ModelInfo:
    plugin_dir = Path(plugin_dir).resolve()
    mpath = plugin_dir / MANIFEST_NAME
    info = ModelInfo(id=plugin_dir.name, name=plugin_dir.name, plugin_dir=plugin_dir, manifest={})
    if not mpath.exists():
        info.errors.append(f"Missing {MANIFEST_NAME}")
        return info
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the manifest must be a JSON object")
    except Exception as e:
        info.errors.append(f"{MANIFEST_NAME} is not valid JSON: {e}")
        return info
    info.manifest = data

    for key in REQUIRED_KEYS:
        if not data.get(key):
            info.errors.append(f"Missing required key '{key}'")
    info.id = str(data.get("id") or plugin_dir.name)
    info.name = str(data.get("name") or info.id)
    if not ID_PATTERN.match(info.id):
        info.errors.append("'id' only allows lowercase letters, digits, '_' and '-' (2-48 characters)")
    info.version = str(data.get("version", info.version))
    info.author = str(data.get("author", ""))
    info.license = str(data.get("license", ""))
    info.entry_point = str(data.get("entry_point") or info.entry_point)
    info.order = int(data.get("order", 100))
    info.family = str(data.get("family", "") or "")
    info.family_name = str(data.get("family_name", "") or info.family)
    info.hardware = data.get("hardware") if isinstance(data.get("hardware"), dict) else {}

    analysis = data.get("analysis", {}) or {}
    try:
        info.sample_rate = _num(data.get("sample_rate"), 16000, int, 1000)
        info.weight = _num(data.get("weight"), 1.0, float, 0.0)
        info.default_threshold = _num(data.get("default_threshold"), 0.5)
        if not 0.0 < info.default_threshold < 1.0:
            raise ValueError
        win = analysis.get("window_seconds", 4.0)
        info.window_seconds = None if win in (None, 0) else _num(win, 4.0, float, 0.1)
        info.forensic_window_seconds = _num(analysis.get("forensic_window_seconds"),
                                            info.window_seconds or 4.0, float, 0.1)
        info.forensic_hop_seconds = _num(analysis.get("forensic_hop_seconds"), 1.0, float, 0.05)
        info.batch_size = _num(analysis.get("batch_size"), 1, int, 1)
    except (TypeError, ValueError):
        info.errors.append("Invalid numeric values in sample_rate / weight / "
                           "default_threshold / analysis")

    files = data.get("files", {}) or {}
    if not isinstance(files, dict):
        info.errors.append("'files' must be an object {name: path}")
        files = {}
    info.files = {str(k): str(v) for k, v in files.items()}

    if ":" not in info.entry_point:
        info.errors.append("'entry_point' must have the format 'file.py:Class'")
    elif not info.entry_file.exists():
        info.errors.append(f"The detector file does not exist: {info.entry_file.name}")

    try:
        info.downloads = downloads.items_from_manifest(plugin_dir, data)
    except Exception as e:
        info.errors.append(f"invalid 'downloads': {e}")
    info.pending_downloads = [it for it in info.downloads if not it.complete]
    pending_targets = [it.target for it in info.pending_downloads]
    for key in info.missing_files():
        path = info.resolve_file(key)
        # If a pending download provides the file it is not an error: it just needs downloading
        if any(path == t or t in path.parents or path in t.parents for t in pending_targets):
            continue
        info.errors.append(f"{MISSING_FILE} '{key}': {path}")
    return info


def discover(plugins_dir: Path = PLUGINS_DIR) -> list[ModelInfo]:
    """Finds plugins, valid or not (folders with manifest.json not starting with _ or .)."""
    if not plugins_dir.exists():
        return []
    found, ids = [], set()
    for d in sorted(plugins_dir.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")) or not (d / MANIFEST_NAME).exists():
            continue
        info = parse_manifest(d)
        if info.id in ids:
            info.errors.append(f"ID duplicado: '{info.id}'")
        ids.add(info.id)
        found.append(info)
    found.sort(key=lambda m: (m.order, m.name.lower()))
    return found


# ------------------------------------------------------------------- import
def load_detector_class(info: ModelInfo) -> type[BaseDetector]:
    """Imports the detector as an isolated package (allows relative imports)."""
    pkg_name = "verivoz_plugin_" + re.sub(r"\W", "_", info.id)
    module_name = info.entry_file.stem
    for name in [n for n in sys.modules if n == pkg_name or n.startswith(pkg_name + ".")]:
        del sys.modules[name]
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(info.plugin_dir)]
    pkg.__file__ = str(info.plugin_dir / "__init__.py")
    sys.modules[pkg_name] = pkg
    plugin_path = str(info.plugin_dir)
    added = plugin_path not in sys.path
    if added:
        sys.path.insert(0, plugin_path)
    try:
        module = importlib.import_module(f"{pkg_name}.{module_name}")
    finally:
        if added and plugin_path in sys.path:
            sys.path.remove(plugin_path)
    cls = getattr(module, info.entry_class, None)
    if cls is None:
        raise AttributeError(f"{info.entry_file.name} does not define the class '{info.entry_class}'")
    if not (isinstance(cls, type) and issubclass(cls, BaseDetector)):
        raise TypeError(f"'{info.entry_class}' must inherit from verivoz.core.detector.BaseDetector")
    return cls


def create_detector(info: ModelInfo, device: str) -> BaseDetector:
    if info.errors:
        raise RuntimeError("; ".join(info.errors))
    if info.pending_downloads:
        raise RuntimeError("Files not downloaded yet: " + ", ".join(it.name for it in info.pending_downloads))
    return load_detector_class(info)(info, device)


# ---------------------------------------------------------- install / remove
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return (text or "model")[:48]


def _write_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def import_plugin_folder(src: Path, plugins_dir: Path = PLUGINS_DIR) -> ModelInfo:
    """Copies an existing plugin folder into /plugins."""
    src = Path(src).resolve()
    info = parse_manifest(src)
    hard = [e for e in info.errors if not e.startswith(MISSING_FILE)]
    if hard:
        raise ValueError("\n".join(hard))
    dest = plugins_dir / info.id
    if dest.exists():
        raise FileExistsError(f"A model with id '{info.id}' already exists")
    if plugins_dir in src.parents or src == dest:
        raise ValueError("The folder is already inside /plugins")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Relative paths that pointed outside the original folder become absolute
    data = dict(info.manifest)
    files = {}
    for k, v in (data.get("files") or {}).items():
        p = Path(v)
        if not p.is_absolute():
            target = (src / p).resolve()
            if src not in target.parents:
                v = str(target)
        files[k] = v
    if files:
        data["files"] = files
        _write_manifest(dest / MANIFEST_NAME, data)
    return parse_manifest(dest)


def scaffold_plugin(name: str, model_id: str, weights: Path | None, sample_rate: int = 16000,
                    window_seconds: float = 4.0, description: str = "", author: str = "",
                    copy_weights: bool = True, plugins_dir: Path = PLUGINS_DIR) -> ModelInfo:
    """Creates a new plugin from the template (/plugins/_template)."""
    model_id = model_id.strip().lower()
    if not ID_PATTERN.match(model_id):
        raise ValueError("Invalid id: use lowercase letters, digits, '_' or '-' (2-48 characters)")
    dest = plugins_dir / model_id
    if dest.exists():
        raise FileExistsError(f"A model with id '{model_id}' already exists")
    shutil.copytree(TEMPLATE_DIR, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "README.md"))
    data = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    data.update({"id": model_id, "name": name.strip() or model_id, "author": author,
                 "sample_rate": int(sample_rate)})
    data["description"] = {"es": description, "en": description}
    data.setdefault("analysis", {})
    data["analysis"].update({"window_seconds": float(window_seconds),
                             "forensic_window_seconds": float(window_seconds)})
    if weights:
        weights = Path(weights).resolve()
        if copy_weights:
            (dest / "weights").mkdir(exist_ok=True)
            shutil.copy2(weights, dest / "weights" / weights.name)
            data["files"] = {"checkpoint": f"weights/{weights.name}"}
        else:
            data["files"] = {"checkpoint": str(weights)}
    _write_manifest(dest / MANIFEST_NAME, data)
    return parse_manifest(dest)


def remove_plugin(info: ModelInfo, permanent: bool = False) -> Path | None:
    """Removes the plugin folder. By default it is moved to user_data/deleted.

    Files referenced OUTSIDE the plugin folder are never touched.
    """
    src = info.plugin_dir
    if PLUGINS_DIR.resolve() not in src.resolve().parents:
        raise ValueError("Only plugins inside /plugins can be removed")
    if permanent:
        shutil.rmtree(src)
        return None
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = TRASH_DIR / f"{info.id}_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.move(str(src), str(dest))
    return dest
