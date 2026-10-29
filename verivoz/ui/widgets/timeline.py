"""Forensic timeline: waveform colored by manipulation probability."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ...core.audio import fmt_time
from ...core.i18n import tr
from .. import theme

TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600]


class ForensicTimeline(QWidget):
    seek_requested = Signal(float)

    LABEL_W = 124
    TOTAL_H = 96
    ROW_H = 12
    ROW_GAP = 10
    AXIS_H = 26
    PAD_R = 4

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.r = result
        self.step = result.timeline_step
        self.total = np.asarray(result.timeline or [], dtype=float)
        self.rows = [(m.model_name, np.asarray(m.timeline, dtype=float)) for m in result.models if m.timeline]
        self.duration = max(0.01, float(result.duration or len(self.total) * self.step))
        env = result.envelope or ([0.0], [0.0])
        self.env_min = np.asarray(env[0], dtype=float)
        self.env_max = np.asarray(env[1], dtype=float)
        self._cache: QPixmap | None = None
        self._hover: float | None = None
        self._playhead: float | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(420)
        self.setFixedHeight(self._rows_bottom() + self.AXIS_H)

    # ------------------------------------------------------------- geometry
    def _rows_top(self) -> int:
        return self.TOTAL_H + 16

    def _rows_bottom(self) -> int:
        return self._rows_top() + len(self.rows) * (self.ROW_H + self.ROW_GAP)

    def _x0(self) -> float:
        return float(self.LABEL_W)

    def _pw(self) -> float:
        return max(10.0, self.width() - self.LABEL_W - self.PAD_R)

    def x_at(self, t: float) -> float:
        return self._x0() + self._pw() * max(0.0, min(1.0, t / self.duration))

    def time_at(self, x: float) -> float:
        return max(0.0, min(self.duration, (x - self._x0()) / self._pw() * self.duration))

    def _score_at(self, series: np.ndarray, t: float) -> float | None:
        if series is None or len(series) == 0:
            return None
        return float(series[min(len(series) - 1, max(0, int(t / self.step)))])

    def set_playhead(self, seconds: float | None):
        self._playhead = seconds
        self.update()

    # ----------------------------------------------------------------- render
    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def _render(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, pw = self._x0(), self._pw()
        npx = int(pw)
        centers_t = (np.arange(npx) + 0.5) / npx * self.duration

        def colors_for(series):
            idx = np.clip((centers_t / self.step).astype(int), 0, max(0, len(series) - 1))
            return series[idx] if len(series) else np.zeros(npx)

        label_font = QFont(self.font())
        label_font.setPixelSize(13)
        label_font.setWeight(QFont.Weight.DemiBold)
        small = QFont(self.font())
        small.setPixelSize(11)

        # ---------------------------------------------------- total row
        top, th = 0.0, float(self.TOTAL_H)
        rect = QRectF(x0, top, pw, th)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.fillPath(path, theme.c("surface_alt"))
        p.save()
        p.setClipPath(path)
        for seg in self.r.segments:
            sx, ex = self.x_at(seg["start"]), self.x_at(seg["end"])
            p.fillRect(QRectF(sx, top, max(2.0, ex - sx), th), theme.c("danger", 0.10))
        # waveform, column by column
        B = len(self.env_min)
        edges = np.minimum(B - 1, (np.arange(npx) * B / npx).astype(int))
        lo = np.minimum.reduceat(self.env_min, edges) if B > 1 else np.repeat(self.env_min, npx)
        hi = np.maximum.reduceat(self.env_max, edges) if B > 1 else np.repeat(self.env_max, npx)
        scores = colors_for(self.total)
        mid, amp = top + th / 2, th * 0.40
        last_key = None
        for i in range(npx):
            s = float(scores[i])
            key = int(s)
            if key != last_key:
                p.setPen(QPen(theme.score_color(s), 1.2))
                last_key = key
            y1, y2 = mid - hi[i] * amp, mid - lo[i] * amp
            if y2 - y1 < 1.0:
                y1, y2 = mid - 0.5, mid + 0.5
            x = x0 + i + 0.5
            p.drawLine(QPointF(x, y1), QPointF(x, y2))
        # score curve and threshold
        if len(self.total):
            base, span = top + th - 6, th - 12
            curve = QPainterPath()
            for i in range(0, npx, 2):
                pt = QPointF(x0 + i, base - float(scores[i]) / 100 * span)
                curve.lineTo(pt) if i else curve.moveTo(pt)
            p.setPen(QPen(theme.c("text", 0.55), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(curve)
            dash = QPen(theme.c("text_muted", 0.6), 1, Qt.PenStyle.DashLine)
            p.setPen(dash)
            y50 = base - 0.5 * span
            p.drawLine(QPointF(x0, y50), QPointF(x0 + pw, y50))
            p.setFont(small)
            tag = f"{tr('forensic.threshold')} 50"
            tw = QFontMetrics(small).horizontalAdvance(tag) + 10
            tag_rect = QRectF(x0 + 6, y50 - 8, tw, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("surface", 0.85))
            p.drawRoundedRect(tag_rect, 4, 4)
            p.setPen(theme.c("text_muted"))
            p.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag)
        p.restore()
        p.setFont(label_font)
        p.setPen(theme.c("text"))
        p.drawText(QRectF(0, top, self.LABEL_W - 14, th / 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                   tr("forensic.total"))
        if self.r.total is not None:
            p.setPen(theme.score_text_color(self.r.total))
            p.drawText(QRectF(0, top + th / 2 + 2, self.LABEL_W - 14, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, f"{self.r.total:.0f}/100")

        # ---------------------------------------------------- per-model rows
        fm = QFontMetrics(small)
        y = float(self._rows_top())
        for name, series in self.rows:
            rr = QRectF(x0, y, pw, self.ROW_H)
            rp = QPainterPath()
            rp.addRoundedRect(rr, self.ROW_H / 2, self.ROW_H / 2)
            p.save()
            p.setClipPath(rp)
            cols = colors_for(series)
            p.setPen(Qt.PenStyle.NoPen)
            start = 0
            for i in range(1, npx + 1):
                if i == npx or int(cols[i]) != int(cols[start]):
                    p.fillRect(QRectF(x0 + start, y, i - start + 0.6, self.ROW_H), theme.score_color(float(cols[start])))
                    start = i
            p.restore()
            p.setFont(small)
            p.setPen(theme.c("text_muted"))
            p.drawText(QRectF(0, y - 3, self.LABEL_W - 14, self.ROW_H + 6),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, self.LABEL_W - 18))
            y += self.ROW_H + self.ROW_GAP

        # ---------------------------------------------------- time axis
        ay = float(self._rows_bottom()) + 2
        step = next((s for s in TICK_STEPS if s / self.duration * pw >= 68), TICK_STEPS[-1])
        p.setFont(small)
        t = 0.0
        while t <= self.duration + 1e-6:
            x = self.x_at(t)
            p.setPen(QPen(theme.c("border_strong"), 1))
            p.drawLine(QPointF(x, ay), QPointF(x, ay + 5))
            p.setPen(theme.c("text_faint"))
            txt = fmt_time(t, precise=step < 1)
            tw = fm.horizontalAdvance(txt)
            tx = min(max(x - tw / 2, x0), x0 + pw - tw)
            p.drawText(QPointF(tx, ay + 18), txt)
            t += step
        p.end()
        return pm

    def paintEvent(self, _):
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if self._cache is None or getattr(self, "_cache_key", None) != key:
            self._cache = self._render()
            self._cache_key = key
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._cache)
        bottom = float(self._rows_bottom()) - self.ROW_GAP + 2

        if self._playhead is not None:
            x = self.x_at(self._playhead)
            p.setPen(QPen(theme.c("primary"), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, bottom))
            p.setBrush(theme.c("primary"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, 3), 4, 4)

        if self._hover is not None:
            x = self._hover
            t = self.time_at(x)
            p.setPen(QPen(theme.c("text_muted", 0.7), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, 0), QPointF(x, bottom))
            lines = [(tr("forensic.total"), self._score_at(self.total, t))]
            lines += [(name, self._score_at(series, t)) for name, series in self.rows]
            f = QFont(self.font())
            f.setPixelSize(12)
            fm = QFontMetrics(f)
            title = fmt_time(t, precise=True)
            bw = max(fm.horizontalAdvance(title), *(fm.horizontalAdvance(n) + 54 for n, _ in lines)) + 26
            bh = 26 + 19 * len(lines)
            bx = x + 12 if x + 12 + bw < self.width() else x - 12 - bw
            box = QRectF(bx, 6, bw, bh)
            p.setPen(QPen(theme.c("border_strong"), 1))
            p.setBrush(theme.c("surface"))
            p.drawRoundedRect(box, 8, 8)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(theme.c("text"))
            p.drawText(QRectF(bx + 12, 10, bw - 24, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
            f.setWeight(QFont.Weight.Normal)
            p.setFont(f)
            yy = 32.0
            for name, val in lines:
                col = theme.score_color(val) if val is not None else theme.c("text_faint")
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(QPointF(bx + 16, yy + 8), 4, 4)
                p.setPen(theme.c("text_muted"))
                p.drawText(QRectF(bx + 26, yy, bw - 70, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(name, Qt.TextElideMode.ElideRight, int(bw - 70)))
                p.setPen(theme.score_text_color(val) if val is not None else theme.c("text_faint"))
                p.drawText(QRectF(bx + bw - 46, yy, 34, 17), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f"{val:.0f}" if val is not None else "–")
                yy += 19

    # ------------------------------------------------------------- mouse
    def _in_plot(self, x: float, y: float) -> bool:
        return self._x0() <= x <= self._x0() + self._pw() and 0 <= y <= self._rows_bottom()

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._hover = pos.x() if self._in_plot(pos.x(), pos.y()) else None
        self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MouseButton.LeftButton and self._in_plot(pos.x(), pos.y()):
            self.seek_requested.emit(self.time_at(pos.x()))
