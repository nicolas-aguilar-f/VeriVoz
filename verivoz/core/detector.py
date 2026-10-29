"""Public API for models (plugins).

Every model used in VeriVoz must ship a Python file with a class that inherits
from `BaseDetector` and implements `load()` and `predict()`.
See docs/ADDING_MODELS.md for the full guide.

Lifecycle the application follows with each model (one at a time):

    det = MyDetector(info, device)   # do not load anything heavy here
    det.load()                       # load the weights onto self.device
    det.predict(wave) / det.predict_batch([waves])   # for each window
    det.unload()                     # free (GPU) memory before the next model
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .registry import ModelInfo


class BaseDetector:
    """Base class of a synthetic-audio detector.

    Attributes available to subclasses:
        self.info         -> ModelInfo with the parsed manifest
        self.manifest     -> dict with the original manifest.json
        self.plugin_dir   -> Path of the plugin folder
        self.device       -> "cuda" or "cpu" (chosen by the user in Settings)
        self.sample_rate  -> rate (Hz) of the waveform passed to predict()
    """

    _BASE_ATTRS = {"info", "manifest", "plugin_dir", "device", "sample_rate"}

    def __init__(self, info: "ModelInfo", device: str = "cpu"):
        self.info = info
        self.manifest = info.manifest
        self.plugin_dir: Path = info.plugin_dir
        self.device = device
        self.sample_rate = int(info.sample_rate)

    # ---------------------------------------------------------------- helpers
    def file(self, key: str) -> Path:
        """Absolute path of a file declared in the manifest's `files`."""
        path = self.info.resolve_file(key)
        if not path.exists():
            raise FileNotFoundError(f"File '{key}' does not exist: {path}")
        return path

    # --------------------------------------------------------------- required
    def load(self) -> None:
        """Loads the weights and prepares the model on `self.device`."""
        raise NotImplementedError("The detector must implement load()")

    def predict(self, wave: np.ndarray) -> float:
        """Receives a mono float32 waveform in [-1, 1] at `self.sample_rate` Hz.

        Returns the PROBABILITY THAT IT IS FAKE (AI / manipulated), between 0 and 1.
        """
        raise NotImplementedError("The detector must implement predict()")

    # --------------------------------------------------------------- optional
    def predict_batch(self, waves: list[np.ndarray]) -> list[float]:
        """Batched version (optional). By default it calls predict() in a loop."""
        return [float(self.predict(w)) for w in waves]

    def unload(self) -> None:
        """Frees memory. By default deletes every attribute created in load()."""
        for name in list(vars(self)):
            if name not in self._BASE_ATTRS:
                delattr(self, name)
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
