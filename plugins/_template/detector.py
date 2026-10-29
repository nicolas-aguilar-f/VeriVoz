"""Detector template for VeriVoz.

This folder (_template) is NOT loaded as a model: the registry ignores folders
starting with "_". Use it as a starting point:

    Settings › Add model › Add model… › Create from a .pth
    (or)  python tools/create_model.py --name "My model" --pth path/to/model.pth

You only need to touch the sections marked with  >>> EDIT <<<.
Full guide: docs/ADDING_MODELS.md

CONTRACT
    predict(wave) receives: numpy float32, mono, values in [-1, 1], at manifest["sample_rate"] Hz,
                            lasting manifest["analysis"]["window_seconds"] (or less if the audio is short).
    predict(wave) returns:  float between 0 and 1 = PROBABILITY THAT THE AUDIO IS FAKE (AI / manipulated).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from verivoz.core.detector import BaseDetector


# =============================================================================
# >>> EDIT 1/3 <<<  ARCHITECTURE
# Paste here the SAME nn.Module class you used for training. Layer names must
# match the keys of your .pth state_dict
# (check them with:  python tools/inspect_pth.py path/to/model.pth).
# If your .pth is TorchScript (torch.jit.save) you do not need anything here.
# =============================================================================
class MyNet(nn.Module):
    def __init__(self):
        super().__init__()
        raise NotImplementedError(
            "Paste your model architecture into detector.py (class MyNet). "
            "See docs/ADDING_MODELS.md, step 3."
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, samples) -> logits (batch, n_classes)
        raise NotImplementedError


class Detector(BaseDetector):
    # =========================================================================
    # >>> EDIT 2/3 <<<  MODEL OUTPUT
    # FAKE_INDEX: position of the "fake/spoof" class in the network output.
    #   - If you trained with 0 = real, 1 = fake  -> FAKE_INDEX = 1
    #   - If you use the ASVspoof convention (0 = spoof, 1 = bonafide) -> FAKE_INDEX = 0
    # OUTPUT: "softmax" (2+ logits), "sigmoid" (1 logit) or "probability"
    #   (the network already returns a probability).
    # INVERT: True if your single output value means "real" (e.g. a bonafide score).
    # =========================================================================
    FAKE_INDEX = 1
    OUTPUT = "softmax"
    INVERT = False

    def build_model(self) -> nn.Module:
        """Instantiates the architecture (only used when the .pth is a state_dict)."""
        return MyNet()

    # ------------------------------------------------------------------ load
    @staticmethod
    def _try_torchscript(path) -> nn.Module | None:
        try:
            return torch.jit.load(str(path), map_location="cpu")
        except Exception:
            return None

    def load(self) -> None:
        path = self.file("checkpoint")
        self.model = self._try_torchscript(path)  # 1) TorchScript: no class needed
        if self.model is None:
            # Pickle can execute code: only load weights you trust
            ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
            if isinstance(ckpt, nn.Module):  # 2) whole model saved with torch.save(model)
                self.model = ckpt
            else:  # 3) state_dict (the most common case), maybe inside a dict
                state = ckpt
                if isinstance(ckpt, dict):
                    for key in ("state_dict", "model_state_dict", "model", "modelo", "net", "weights"):
                        if key in ckpt and isinstance(ckpt[key], dict):
                            state = ckpt[key]
                            break
                self.model = self.build_model()
                self._load_state(self.model, state)
        self.model.to(self.device).eval()

    @staticmethod
    def _load_state(model: nn.Module, state: dict) -> None:
        """Loads the state_dict; if it does not fit, tries removing DataParallel/Lightning prefixes."""
        variants = [
            state,
            {k.removeprefix("module."): v for k, v in state.items()},
            {k.removeprefix("module.").removeprefix("model."): v for k, v in state.items()},
        ]
        error = None
        for variant in variants:
            try:
                model.load_state_dict(variant, strict=True)
                return
            except RuntimeError as e:
                error = error or e
        raise error

    # ------------------------------------------------------------ preprocess
    def preprocess(self, wave: np.ndarray) -> torch.Tensor:
        # =====================================================================
        # >>> EDIT 3/3 <<<  PREPROCESSING
        # Reproduce EXACTLY what you did during training: normalization,
        # cropping/padding to a fixed length, spectrograms, etc.
        # Example: pad by repetition up to 4 s (64,000 samples at 16 kHz).
        # =====================================================================
        n = int(round(self.info.window_seconds * self.sample_rate)) if self.info.window_seconds else len(wave)
        if len(wave) < n:
            wave = np.tile(wave, n // max(1, len(wave)) + 1)
        return torch.from_numpy(np.ascontiguousarray(wave[:n], dtype=np.float32))

    # --------------------------------------------------------------- predict
    @torch.inference_mode()
    def predict_batch(self, waves: list[np.ndarray]) -> list[float]:
        x = torch.stack([self.preprocess(w) for w in waves]).to(self.device)
        out = self.model(x)
        if isinstance(out, (tuple, list)):
            out = out[0]
        if isinstance(out, dict):
            out = out.get("logits", next(iter(out.values())))
        out = out.float()
        if self.OUTPUT == "softmax":
            prob = torch.softmax(out, dim=-1)[:, self.FAKE_INDEX]
        elif self.OUTPUT == "sigmoid":
            prob = torch.sigmoid(out.reshape(len(waves), -1)[:, 0])
        else:
            prob = out.reshape(len(waves), -1)[:, 0].clamp(0, 1)
        if self.INVERT:
            prob = 1.0 - prob
        return prob.cpu().tolist()

    def predict(self, wave: np.ndarray) -> float:
        return self.predict_batch([wave])[0]
