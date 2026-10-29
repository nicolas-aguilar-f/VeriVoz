"""Sound-wave animation (splash screen and progress)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget


class WaveAnimation(QWidget):
    def __init__(self, parent=None, bars: int = 42, color: QColor | None = None,
                 color2: QColor | None = None, speed: float = 1.0):
        super().__init__(parent)
        self.bars = bars
        self.color = color or QColor("#FFFFFF")
        self.color2 = color2
        self.speed = speed
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_colors(self, color: QColor, color2: QColor | None = None):
        self.color, self.color2 = color, color2
        self.update()

    def showEvent(self, e):
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = (time.monotonic() - self._t0) * self.speed
        n = self.bars
        slot = w / n
        bw = max(2.0, slot * 0.52)
        if self.color2 is not None:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0, self.color)
            grad.setColorAt(1, self.color2)
            brush = grad
        else:
            brush = None
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            x = i / (n - 1)
            env = 0.18 + 0.82 * math.sin(math.pi * x) ** 1.2
            a = 0.5 + 0.5 * math.sin(t * 3.4 + x * 11.0)
            b = 0.55 + 0.45 * math.sin(t * 1.9 - x * 7.0 + 1.3)
            c = 0.75 + 0.25 * math.sin(t * 5.3 + x * 23.0)
            amp = max(0.07, env * a * b * c * 1.25)
            bh = min(h, amp * h)
            cx = slot * (i + 0.5)
            col = QColor(self.color)
            col.setAlphaF(0.45 + 0.55 * min(1.0, amp))
            if brush is not None:
                p.setBrush(brush)
                p.setOpacity(0.45 + 0.55 * min(1.0, amp))
            else:
                p.setBrush(col)
            p.drawRoundedRect(QRectF(cx - bw / 2, (h - bh) / 2, bw, bh), bw / 2, bw / 2)
        p.setOpacity(1.0)
