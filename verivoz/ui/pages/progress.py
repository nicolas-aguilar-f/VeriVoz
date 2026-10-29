"""Progress page: models running one after another."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ...core.audio import fmt_time
from ...core.i18n import tr
from .. import icons, theme
from ..widgets.common import Card, ElidedLabel, button, label, separator
from ..widgets.wave import WaveAnimation

STATUS_ICON = {"pending": ("clock", "text_faint"), "loading": ("download", "primary"),
               "running": ("wave", "primary"), "unloading": ("refresh", "primary"),
               "done": ("check", "success"), "error": ("x", "danger")}


class StepRow(QWidget):
    def __init__(self, index: int, name: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        lay.addWidget(self.icon)
        self.name = label(f"{index + 1}. {name}", "body")
        lay.addWidget(self.name, 1)
        self.status = label("", "caption")
        lay.addWidget(self.status)
        self.set_status("pending")

    def set_status(self, status: str, tooltip: str = ""):
        icon_name, color = STATUS_ICON.get(status, STATUS_ICON["pending"])
        self.icon.setPixmap(icons.pixmap(icon_name, theme.hexc(color), 20))
        self.status.setText(tr(f"status.{status}"))
        self.status.setStyleSheet(f"color: {theme.hexc(color)}; font-weight: 600;" if status != "pending" else "")
        self.setToolTip(tooltip)


class ProgressPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Page")
        self.steps: list[StepRow] = []
        self.device = "GPU"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = Card(padding=30, spacing=12)
        card.setFixedWidth(640)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

        self.wave = WaveAnimation(bars=48, color=theme.c("accent_a"), color2=theme.c("accent_b"))
        self.wave.setFixedHeight(92)
        card.add(self.wave)
        title = label(tr("progress.title"), "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(title)
        self.stage = label("", "h3")
        self.stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(self.stage)
        self.detail = ElidedLabel("", "muted")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(self.detail)
        card.body.addSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        card.add(self.bar)
        info = QHBoxLayout()
        self.percent = label("0 %", "caption")
        self.elapsed = label("", "caption")
        info.addWidget(self.percent)
        info.addStretch(1)
        info.addWidget(self.elapsed)
        card.add_layout(info)
        card.add(separator())
        self.steps_box = QVBoxLayout()
        self.steps_box.setSpacing(2)
        card.add_layout(self.steps_box)
        note = label(tr("progress.note"), "caption", wrap=True)
        card.add(note)
        self.cancel_btn = button(tr("progress.cancel"), "danger", "x")
        self.cancel_btn.clicked.connect(win.cancel_analysis)
        card.body.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)

    def setup(self, models, n_files: int, forensic: bool, device: str):
        self.device = device
        for s in self.steps:
            s.deleteLater()
        self.steps = []
        for i, m in enumerate(models):
            row = StepRow(i, m.name)
            self.steps.append(row)
            self.steps_box.addWidget(row)
        self.bar.setValue(0)
        self.percent.setText("0 %")
        self.stage.setText("")
        self.detail.setText(tr("progress.hashing"))
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText(tr("progress.cancel"))
        self._t0 = time.monotonic()
        self._tick()
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def set_cancelling(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText(tr("progress.cancelling"))

    def _tick(self):
        self.elapsed.setText(tr("progress.elapsed", t=fmt_time(time.monotonic() - self._t0)))

    def on_event(self, e: dict):
        kind = e.get("type")
        if kind == "progress":
            v = max(0.0, min(1.0, float(e["value"])))
            self.bar.setValue(int(v * 1000))
            self.percent.setText(f"{v * 100:.0f} %")
        elif kind == "phase" and e.get("phase") == "hashing":
            self.detail.setText(tr("progress.hashing"))
        elif kind == "stage":
            i, n = e["index"], e["count"]
            self.stage.setText(tr("progress.model", i=i + 1, n=n, name=e["model"]))
            phase = e["phase"]
            if phase == "loading":
                self.detail.setText(tr("progress.loading", device=self.device))
            elif phase == "unloading":
                self.detail.setText(tr("progress.unloading"))
            else:
                self.detail.setText(tr("progress.running"))
            if i < len(self.steps):
                self.steps[i].set_status(phase)
        elif kind == "file":
            self.detail.setText(tr("progress.file", i=e["index"] + 1, n=e["count"], name=e["name"]))
        elif kind == "model_status":
            i = e["index"]
            if i < len(self.steps):
                self.steps[i].set_status(e["status"], e.get("message", ""))
