"""Drag-and-drop box for audio files (or pick files / a folder)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ...core.audio import is_audio
from ...core.i18n import tr
from .. import icons, theme
from .common import button, label


class DropZone(QFrame):
    files_dropped = Signal(list)
    browse_files = Signal()
    browse_folder = Signal()

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._hover = False
        self._drag = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(170 if compact else 250)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 26, 24, 24)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setPixmap(icons.pixmap("upload", theme.hexc("primary"), 42 if not compact else 32, 1.8))
        lay.addWidget(self.icon)
        self.title = label(tr("drop.title"), "h2")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        orl = label(tr("drop.or"), "caption")
        orl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(orl)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.btn_files = button(tr("drop.files"), "primary", "file")
        self.btn_folder = button(tr("drop.folder"), None, "folder")
        self.btn_files.clicked.connect(self.browse_files.emit)
        self.btn_folder.clicked.connect(self.browse_folder.emit)
        row.addWidget(self.btn_files)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        lay.addLayout(row)
        fmt = label(tr("drop.formats"), "caption")
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(4)
        lay.addWidget(fmt)
        lay.addStretch(1)

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        active = self._drag or self._hover
        p.fillPath(path, theme.c("primary_soft") if self._drag else
                   (theme.c("surface_hover") if self._hover else theme.c("surface")))
        pen = QPen(theme.c("primary") if active else theme.c("border_strong"), 2 if self._drag else 1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.drawPath(path)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.browse_files.emit()
        super().mouseReleaseEvent(e)

    # ---------------------------------------------------------- drag & drop
    @staticmethod
    def _paths(mime) -> list[str]:
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                out.append(url.toLocalFile())
        return out

    def dragEnterEvent(self, e):
        paths = self._paths(e.mimeData())
        from pathlib import Path

        if any(Path(p).is_dir() or is_audio(p) for p in paths):
            e.acceptProposedAction()
            self._drag = True
            self.title.setText(tr("drop.release"))
            self.update()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drag = False
        self.title.setText(tr("drop.title"))
        self.update()

    def dropEvent(self, e):
        self._drag = False
        self.title.setText(tr("drop.title"))
        self.update()
        paths = self._paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.files_dropped.emit(paths)
