"""Persistent user settings (user_data/settings.json)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .paths import SETTINGS_FILE


@dataclass
class Settings:
    theme: str = "light"            # "light" | "dark"
    language: str = "en"            # "en" | "es"
    device: str = "auto"            # "auto" | "cuda" | "cpu"
    aggregation: str = "sensitive"  # "sensitive" | "mean" | "max" (see scoring.aggregate)
    forensic: bool = False          # last state of the forensic-analysis switch
    thresholds: dict = field(default_factory=dict)      # {model_id: threshold}
    calibration: dict = field(default_factory=dict)     # {model_id: info about the last calibration}
    disabled_models: list = field(default_factory=list)
    last_dir: str = ""

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            s = cls(**known)
        except Exception:
            s = cls()
        if s.theme not in ("light", "dark"):
            s.theme = "light"
        if s.language not in ("en", "es"):
            s.language = "en"
        if s.device not in ("auto", "cuda", "cpu"):
            s.device = "auto"
        if s.aggregation not in ("sensitive", "mean", "max"):
            s.aggregation = "sensitive"
        return s

    def save(self) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    def threshold(self, model) -> float:
        return float(self.thresholds.get(model.id, model.default_threshold))

    def is_enabled(self, model) -> bool:
        return model.id not in self.disabled_models
