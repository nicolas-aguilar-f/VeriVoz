"""Semicircular 0-100 gauge with a green -> yellow -> red gradient."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QBrush, QConicalGradient, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme


def _arc_gradient(center: QPointF) -> QConicalGradient:
    """Angle 180° (left) is 0 points and 0° (right) is 100.

    QConicalGradient runs counter-clockwise from 3 o'clock, so on the upper half
    the position is p = 0.5 * (1 - score/100).
    """
    g = QConicalGradient(center, 0)
    green, yellow, red = theme.score_color(0), theme.score_color(theme.YELLOW_AT), theme.score_color(100)
    g.setColorAt(0.0, red)
    g.setColorAt(0.5 * (1 - theme.RED_AT / 100), red)
    g.setColorAt(0.5 * (1 - theme.YELLOW_AT / 100), yellow)
    g.setColorAt(0.5, green)
    g.setColorAt(0.74, green)   # lower half: end colors for the
    g.setColorAt(0.76, red)     # rounded caps of the arc
    g.setColorAt(1.0, red)
    return g


class ScoreGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown = 0.0
        self._score: float | None = None
        self._label = ""
        self._sub = "/100"
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(310, 206)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1100)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._shown = float(v)
        self.update()

    def set_score(self, score: float | None, label: str, animate: bool = True):
        self._score = score
        self._label = label
        self._anim.stop()
        if score is None:
            self._shown = 0.0
            self.update()
            return
        if animate:
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(float(score))
            self._anim.start()
        else:
            self._shown = float(score)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        thick = 20.0
        radius = min((w - thick - 16) / 2, h - thick / 2 - 66)
        cx, cy = w / 2, thick / 2 + 8 + radius
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
        center = QPointF(cx, cy)

        # track
        p.setPen(QPen(theme.c("track"), thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 180 * 16, -180 * 16)
        grad = _arc_gradient(center)
        p.setOpacity(0.22)
        p.setPen(QPen(QBrush(grad), thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 180 * 16, -180 * 16)
        p.setOpacity(1.0)

        # threshold mark (50) and 0 / 100 labels
        p.setPen(QPen(theme.c("text_faint"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        inner = radius - thick / 2 - 5
        p.drawLine(QPointF(cx, cy - inner), QPointF(cx, cy - inner + 7))
        p.setPen(theme.c("text_faint"))
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QRectF(cx - radius - thick / 2, cy + thick / 2 + 2, thick, 14), Qt.AlignmentFlag.AlignCenter, "0")
        p.drawText(QRectF(cx + radius - thick / 2 - 6, cy + thick / 2 + 2, thick + 12, 14),
                   Qt.AlignmentFlag.AlignCenter, "100")

        value = self._shown
        if self._score is not None:
            span = 180.0 * value / 100.0
            if span > 0.2:
                p.setPen(QPen(QBrush(grad), thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(rect, 180 * 16, int(-span * 16))
            ang = math.pi * (1 - value / 100)
            kx, ky = cx + radius * math.cos(ang), cy - radius * math.sin(ang)
            p.setPen(QPen(theme.score_color(value), 4))
            p.setBrush(theme.c("surface"))
            p.drawEllipse(QPointF(kx, ky), thick * 0.46, thick * 0.46)

        # central number
        num_color = theme.score_text_color(value) if self._score is not None else theme.c("text_faint")
        f = QFont(self.font())
        f.setPixelSize(int(radius * 0.52))
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(num_color)
        text = f"{value:.0f}" if self._score is not None else "–"
        p.drawText(QRectF(cx - radius, cy - radius * 0.62, 2 * radius, radius * 0.6),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, text)
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(theme.c("text_faint"))
        p.drawText(QRectF(cx - radius, cy - 2, 2 * radius, 16), Qt.AlignmentFlag.AlignCenter, self._sub)

        # verdict
        if self._label:
            f.setPixelSize(17)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(num_color)
            p.drawText(QRectF(0, cy + 24, w, 26), Qt.AlignmentFlag.AlignCenter, self._label)
