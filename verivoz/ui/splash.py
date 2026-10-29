"""Splash screen: animated sound wave while PyTorch and the models load."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

from .. import APP_NAME, APP_VERSION
from ..core.i18n import tr
from .widgets.wave import WaveAnimation


class _Panel(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 22, 22)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, QColor("#2F74FF"))
        g.setColorAt(0.55, QColor("#1D5BEA"))
        g.setColorAt(1.0, QColor("#123FA8"))
        p.fillPath(path, g)
        # subtle highlight
        glow = QLinearGradient(r.topLeft(), r.bottomLeft())
        glow.setColorAt(0.0, QColor(255, 255, 255, 34))
        glow.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillPath(path, glow)


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(600, 400)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        panel = _Panel()
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(10, 30, 80, 120))
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(36, 40, 36, 28)
        lay.setSpacing(6)
        self.wave = WaveAnimation(bars=46, color=QColor("#FFFFFF"))
        self.wave.setFixedHeight(130)
        lay.addWidget(self.wave)
        lay.addSpacing(16)
        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: white; font-size: 34px; font-weight: 700; background: transparent;")
        lay.addWidget(title)
        sub = QLabel(tr("app.tagline"))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: rgba(255,255,255,0.82); font-size: 14px; background: transparent;")
        lay.addWidget(sub)
        lay.addStretch(1)
        self.status = QLabel(tr("splash.loading_engine"))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: rgba(255,255,255,0.9); font-size: 13px; background: transparent;")
        lay.addWidget(self.status)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11px; background: transparent;")
        lay.addWidget(ver)

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def set_status(self, text: str):
        self.status.setText(text)
