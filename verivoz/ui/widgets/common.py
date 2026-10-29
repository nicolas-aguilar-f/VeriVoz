"""Reusable pieces: cards, switches, segmented controls, toasts..."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .. import icons, theme


def label(text: str = "", role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


class Clickable(QWidget):
    """Container that emits `clicked` when left-clicked."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class ElidedLabel(QLabel):
    """Single-line label that elides the text with "…" when it does not fit."""

    def __init__(self, text: str = "", role: str | None = None, mode=Qt.TextElideMode.ElideMiddle):
        super().__init__()
        self._full = text
        self._mode = mode
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text: str):
        self._full = text
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._full

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._full) + 2, fm.height() + 2)

    def minimumSizeHint(self):
        return QSize(20, self.fontMetrics().height() + 2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        fm = self.fontMetrics()
        p.drawText(self.rect(), int(self.alignment() | Qt.AlignmentFlag.AlignVCenter),
                   fm.elidedText(self._full, self._mode, self.width()))


def pill(text: str, color: QColor, text_color: QColor | None = None) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(theme.pill_style(color, text_color))
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


def button(text: str = "", variant: str | None = None, icon_name: str | None = None,
           size: str | None = None, icon_color=None) -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if size:
        btn.setProperty("size", size)
    if icon_name:
        if icon_color is None:
            icon_color = {"primary": "#FFFFFF", "danger-solid": "#FFFFFF", "danger": theme.hexc("danger"),
                          "ghost": theme.hexc("primary")}.get(variant or "", theme.hexc("text"))
        btn.setIcon(icons.icon(icon_name, icon_color, 18))
        btn.setIconSize(QSize(17, 17) if size != "lg" else QSize(20, 20))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def icon_button(icon_name: str, tooltip: str = "", color=None, size: int = 18) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("IconButton")
    btn.setIcon(icons.icon(icon_name, color or theme.hexc("text_muted"), size))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    return line


def icon_badge(icon_name: str, size: int = 38, color=None, bg: str | None = None) -> QFrame:
    badge = QFrame()
    badge.setObjectName("IconBadge")
    badge.setFixedSize(size, size)
    if bg:
        badge.setStyleSheet(f"QFrame#IconBadge {{ background: {bg}; }}")
    lay = QHBoxLayout(badge)
    lay.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(icon_name, color or theme.hexc("primary"), int(size * 0.5)))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    return badge


class Card(QFrame):
    def __init__(self, parent=None, name: str = "Card", padding: int = 22, spacing: int = 14, shadow: bool = True):
        super().__init__(parent)
        self.setObjectName(name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)
        if shadow:
            eff = QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(28)
            eff.setOffset(0, 4)
            eff.setColor(theme.c("shadow", 0.10 if not theme.is_dark() else 0.45))
            self.setGraphicsEffect(eff)

    def add(self, widget, stretch: int = 0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body.addLayout(layout)
        return layout


def card_header(icon_name: str, title: str, caption: str = "", danger: bool = False) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    color = theme.hexc("danger") if danger else theme.hexc("primary")
    bg = theme.hexc("danger_soft") if danger else None
    lay.addWidget(icon_badge(icon_name, 36, color, bg), 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = label(title, "h2")
    if danger:
        t.setStyleSheet(f"color: {theme.hexc('danger')};")
    col.addWidget(t)
    if caption:
        col.addWidget(label(caption, "muted", wrap=True))
    lay.addLayout(col, 1)
    return w


class ScrollPage(QScrollArea):
    """Scroll area with a centered column of maximum width."""

    def __init__(self, max_width: int = 900, margins=(28, 26, 28, 34), spacing: int = 18):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QWidget()
        outer.setObjectName("ScrollContent")
        h = QHBoxLayout(outer)
        h.setContentsMargins(*margins)
        h.addStretch(1)
        self.column = QWidget()
        self.column.setObjectName("ScrollContent")
        self.column.setMaximumWidth(max_width)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout_ = QVBoxLayout(self.column)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(spacing)
        h.addWidget(self.column, 100)
        h.addStretch(1)
        self.setWidget(outer)

    def add(self, widget, stretch: int = 0, align=None):
        if align is not None:
            self.layout_.addWidget(widget, stretch, align)
        else:
            self.layout_.addWidget(widget, stretch)
        return widget

    def add_stretch(self):
        self.layout_.addStretch(1)


class ToggleSwitch(QAbstractButton):
    """Animated iOS-style switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = float(v)
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        off, on = theme.c("border_strong"), theme.c("primary")
        track = QColor(
            round(off.red() + (on.red() - off.red()) * self._pos),
            round(off.green() + (on.green() - off.green()) * self._pos),
            round(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class Segmented(QFrame):
    """Segmented control: several mutually exclusive options."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("SegButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(key == current)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)

    def set_enabled(self, key: str, enabled: bool, tooltip: str = ""):
        if key in self.buttons:
            self.buttons[key].setEnabled(enabled)
            self.buttons[key].setToolTip(tooltip)


class MiniBar(QWidget):
    """Horizontal 0-100 score bar using the color scale."""

    def __init__(self, score: float | None, parent=None):
        super().__init__(parent)
        self.score = score
        self.setFixedHeight(10)
        self.setMinimumWidth(120)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("track"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.score is not None:
            w = max(r.height(), r.width() * self.score / 100.0)
            p.setBrush(theme.score_color(self.score))
            p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), r.height() / 2, r.height() / 2)
        # threshold mark (50)
        x = r.left() + r.width() * 0.5
        p.setBrush(theme.c("text_faint", 0.8))
        p.drawRect(QRectF(x - 0.75, r.top() - 0, 1.5, r.height()))


class Toast(QLabel):
    """Temporary floating message at the bottom of the window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_message(self, text: str, ms: int = 3200):
        self.setText(text)
        parent = self.parentWidget()
        self.setMaximumWidth(min(560, parent.width() - 40))
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(350)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self):
        try:
            self._anim.finished.disconnect(self._hide_once)
        except (RuntimeError, TypeError):
            pass
        if self._effect.opacity() < 0.05:
            self.hide()
