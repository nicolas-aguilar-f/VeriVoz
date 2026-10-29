"""DF-Arena adapter (Hugging Face, trust_remote_code) for VeriVoz.

Works for the 1B and 500M versions: only the weights and the XLS-R backbone
configuration requested by its code change (see "hf_config_redirects" in the manifest).

The model expects waveforms of 64,600 samples (~4 s) at 16 kHz. Shorter windows
are padded by repeating the signal, like its feature extractor does.
Output: logits [spoof, bonafide] -> we return softmax[spoof].
"""
from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import torch

from verivoz.core.detector import BaseDetector

N_SAMPLES = 64600


def _pad(wave: np.ndarray, n: int = N_SAMPLES) -> np.ndarray:
    if len(wave) >= n:
        return wave[:n]
    return np.tile(wave, n // max(1, len(wave)) + 1)[:n]


@contextmanager
def _local_wav2vec2_configs(redirects: dict[str, str]):
    """backbone.py asks Hugging Face for the XLS-R configuration on every load
    (e.g. "facebook/wav2vec2-xls-r-1b"). It is redirected to the copy downloaded into
    weights/ so it works offline."""
    from transformers import Wav2Vec2Config

    original = Wav2Vec2Config.from_pretrained.__func__

    def from_local(cls, name, *args, **kwargs):
        return original(cls, redirects.get(name, name), *args, **kwargs)

    Wav2Vec2Config.from_pretrained = classmethod(from_local)
    try:
        yield
    finally:
        Wav2Vec2Config.from_pretrained = classmethod(original)


class DFArenaDetector(BaseDetector):
    def load(self) -> None:
        from transformers import AutoModel
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
        redirects = {repo: str(self.file(key))
                     for repo, key in self.manifest.get("hf_config_redirects", {}).items()}
        with _local_wav2vec2_configs(redirects):
            self.model = AutoModel.from_pretrained(str(self.file("model_dir")), trust_remote_code=True)
        self.model.to(self.device).eval()
        self.spoof_index = int(self.model.config.label2id.get("spoof", 0))

    @torch.inference_mode()
    def predict(self, wave: np.ndarray) -> float:
        x = torch.from_numpy(_pad(wave).astype(np.float32)).to(self.device)
        logits = self.model(x)["logits"]
        return torch.softmax(logits.float(), dim=-1)[0, self.spoof_index].item()
