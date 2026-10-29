"""XLSR-MLP adapter for VeriVoz.

Reproduces the preprocessing of extract_features.py exactly
(https://github.com/nicolas-aguilar-f/XLSR-MLP):
  1. Neutralization noise at 36 dB SNR (fixed seed -> reproducible results).
  2. facebook/wav2vec2-xls-r-300m embeddings (last layer).
  3. Per-frame mean + standard deviation with the attention mask -> 2048 vector.
  4. Normalization with the mean/std stored in the checkpoint and a 2048->256->2 MLP.
Labels: 0 = real, 1 = synthetic -> we return softmax[1].
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from verivoz.core.detector import BaseDetector

SNR_DB = 36.0
SEED = 1234


class MLPClassifier(nn.Module):
    def __init__(self, input_dim=2048, hidden_dim=256, n_classes=2):
        super().__init__()
        # The attribute must be called "red": it matches the keys of the checkpoint
        self.red = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.LeakyReLU(0.01),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, n_classes),
        )

    def forward(self, x):
        return self.red(x)


class XLSRMLPDetector(BaseDetector):
    def load(self) -> None:
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2Model
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
        # Checkpoint keys (Spanish, from training): modelo, media, desv, umbral
        ckpt = torch.load(self.file("checkpoint"), map_location="cpu", weights_only=False)
        self.mlp = MLPClassifier()
        self.mlp.load_state_dict(ckpt["modelo"])
        self.mlp.to(self.device).eval()
        self.mean = torch.as_tensor(ckpt["media"], dtype=torch.float32, device=self.device)
        self.std = torch.as_tensor(ckpt["desv"], dtype=torch.float32, device=self.device)
        self.trained_threshold = float(ckpt.get("umbral", 0.5))

        # facebook/wav2vec2-xls-r-300m downloaded into weights/ (works offline)
        backbone = str(self.file("backbone"))
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(backbone)
        self.ssl = Wav2Vec2Model.from_pretrained(backbone)
        self.ssl.to(self.device).eval()

    @staticmethod
    def _neutralize(wave: torch.Tensor, gen: torch.Generator) -> torch.Tensor:
        rms = wave.pow(2).mean().sqrt() + 1e-12
        noise = torch.randn(wave.shape, generator=gen)
        noise = noise / (noise.pow(2).mean().sqrt() + 1e-12)
        return wave + noise * rms * 10.0 ** (-SNR_DB / 20.0)

    @torch.inference_mode()
    def predict_batch(self, waves: list[np.ndarray]) -> list[float]:
        # One seed per waveform: the same audio gets the same noise whether batched or not
        noisy = [self._neutralize(torch.from_numpy(np.asarray(w, dtype=np.float32)),
                                  torch.Generator().manual_seed(SEED)).numpy()
                 for w in waves]
        inputs = self.processor(noisy, sampling_rate=self.sample_rate, return_tensors="pt",
                                padding=True, return_attention_mask=True)
        values = inputs.input_values.to(self.device)
        mask = inputs.attention_mask.to(self.device)
        frames = self.ssl(values, attention_mask=mask).last_hidden_state
        m = self.ssl._get_feature_vector_attention_mask(frames.shape[1], mask).unsqueeze(-1).float()
        n = m.sum(dim=1).clamp(min=1.0)
        mean = (frames * m).sum(dim=1) / n
        std = (((frames - mean.unsqueeze(1)) ** 2 * m).sum(dim=1) / n).clamp(min=1e-8).sqrt()
        x = (torch.cat([mean, std], dim=1) - self.mean) / self.std
        return torch.softmax(self.mlp(x), dim=1)[:, 1].float().cpu().tolist()

    def predict(self, wave: np.ndarray) -> float:
        return self.predict_batch([wave])[0]
