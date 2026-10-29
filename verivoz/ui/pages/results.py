"""Results page: total gauge, per-model breakdown and forensic timeline."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QLinearGradient, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ... import APP_NAME, APP_VERSION
from ...core import scoring
from ...core.audio import fmt_size, fmt_time
from ...core.i18n import language, tr
from .. import icons, theme
from ..widgets.common import (Card, ElidedLabel, MiniBar, button, card_header, icon_button, label, pill,
                              separator)
from ..widgets.gauge import ScoreGauge
from ..widgets.timeline import ForensicTimeline


def verdict_text(score) -> str:
    return tr(f"verdict.{scoring.verdict(score)}")


# ----------------------------------------------------------------------- player
class AudioPlayer(QObject):
    position = Signal(float)
    playing = Signal(bool)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._State = QMediaPlayer.PlaybackState
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.positionChanged.connect(lambda ms: self.position.emit(ms / 1000.0))
        self.player.playbackStateChanged.connect(lambda s: self.playing.emit(s == self._State.PlayingState))

    def is_playing(self) -> bool:
        return self.player.playbackState() == self._State.PlayingState

    def play_from(self, seconds: float):
        self.player.setPosition(int(seconds * 1000))
        self.player.play()

    def toggle(self):
        if self.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.player.stop()


class LegendBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(150, 8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.topRight())
        for s in (0, theme.YELLOW_AT, theme.RED_AT, 100):
            g.setColorAt(s / 100, theme.score_color(s))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 4, 4)


# -------------------------------------------------------------------- model row
class ModelRow(QWidget):
    def __init__(self, m, info=None):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(2, 6, 2, 6)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(3)
        name = label(m.model_name, "h3")
        grid.addWidget(name, 0, 0)
        desc = info.description(language()) if info else ""
        if desc:
            d = ElidedLabel(desc, "caption", Qt.TextElideMode.ElideRight)
            grid.addWidget(d, 1, 0)
        if m.error:
            err = label(tr("breakdown.error", err=m.error), "danger", wrap=True)
            err.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(err, 2, 0, 1, 4)
            grid.addWidget(pill(tr("status.error"), theme.c("danger")), 0, 3, Qt.AlignmentFlag.AlignRight)
        elif m.score is not None:
            bar = MiniBar(m.score)
            bar.setMinimumWidth(180)
            grid.addWidget(bar, 0, 1)
            sc = label(f"{m.score:.0f}")
            sc.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {theme.score_text_color(m.score).name()};")
            sc.setMinimumWidth(38)
            sc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(sc, 0, 2)
            col = theme.score_color(100 if m.is_fake else 0)
            tag = pill(tr("breakdown.fake") if m.is_fake else tr("breakdown.real"), col,
                       theme.score_text_color(100 if m.is_fake else 0))
            grid.addWidget(tag, 0, 3, Qt.AlignmentFlag.AlignRight)
            details = tr("breakdown.details", prob=f"{m.prob:.3f}", thr=f"{m.threshold:.2f}",
                         peak=f"{m.peak:.3f}", n=m.n_windows, t=f"{m.elapsed:.1f} s")
            grid.addWidget(label(details, "caption"), 1 if not desc else 2, 0, 1, 4)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)


# ------------------------------------------------------------ suspicious segment
class SegmentRow(QFrame):
    clicked = Signal(float)

    def __init__(self, seg: dict):
        super().__init__()
        self.setObjectName("Row")
        self.seg = seg
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(12)
        lbl = label()
        lbl.setPixmap(icons.pixmap("play", theme.hexc("primary"), 14))
        lay.addWidget(lbl)
        t = label(f"{fmt_time(seg['start'], True)} – {fmt_time(seg['end'], True)}", "mono")
        t.setStyleSheet(f"color: {theme.hexc('text')}; font-weight: 600;")
        lay.addWidget(t)
        lay.addWidget(label(f"({seg['end'] - seg['start']:.1f} s)", "caption"))
        lay.addStretch(1)
        lay.addWidget(label(tr("forensic.segment_row", peak=f"{seg['peak']:.0f}", mean=f"{seg['mean']:.0f}"), "caption"))
        lay.addWidget(pill(f"{seg['peak']:.0f}", theme.score_color(seg["peak"]), theme.score_text_color(seg["peak"])))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(float(self.seg["start"]))
        super().mouseReleaseEvent(e)


# ------------------------------------------------------------------ file detail
class FileDetail(QWidget):
    def __init__(self, win, r):
        super().__init__()
        self.win, self.r = win, r
        self.player: AudioPlayer | None = None
        self.timeline: ForensicTimeline | None = None
        self.setObjectName("ScrollContent")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 0, 12, 28)
        v.setSpacing(16)
        v.addWidget(self._summary_card())
        if r.models:
            v.addWidget(self._breakdown_card())
        if r.timeline:
            v.addWidget(self._forensic_card())
        elif not r.error and r.models:
            v.addWidget(self._upsell_card())
        v.addStretch(1)

    # ------------------------------------------------------------ summary
    def _summary_card(self) -> QWidget:
        r = self.r
        card = Card(padding=22, spacing=10)
        h = QHBoxLayout()
        h.setSpacing(26)
        gauge = ScoreGauge()
        gauge.set_score(r.total, verdict_text(r.total) if r.total is not None else tr("verdict.unknown"))
        h.addWidget(gauge, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(ElidedLabel(r.name, "title"))
        col.addWidget(ElidedLabel(r.path, "caption"))
        pills = QHBoxLayout()
        pills.setSpacing(8)
        n_ok = len(r.ok_models)
        if n_ok:
            k = r.n_fake
            col_ = theme.score_color(100 if k else 0)
            pills.addWidget(pill(tr("results.detections", k=k, n=n_ok), col_, theme.score_text_color(100 if k else 0)))
        if r.segments:
            pills.addWidget(pill("⚠ " + tr("results.segments_pill", n=len(r.segments)), theme.c("danger")))
        mode = tr("mode.forensic") if r.forensic else tr("mode.standard")
        pills.addWidget(pill(mode, theme.c("primary")))
        pills.addStretch(1)
        col.addLayout(pills)
        if r.error:
            col.addWidget(label(f"{tr('results.file_error')}: {r.error}", "danger", wrap=True))
        else:
            verdict = scoring.verdict(r.total)
            if r.segments and verdict in ("authentic", "likely_authentic"):
                verdict = "segments"
            desc = tr(f"verdict_desc.{verdict}")
            if desc:
                col.addWidget(label(desc, "muted", wrap=True))
        col.addSpacing(4)
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(8)
        ch = {1: tr("meta.mono"), 2: tr("meta.stereo")}.get(r.channels, str(r.channels))
        try:
            when = datetime.fromisoformat(r.analyzed_at).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            when = r.analyzed_at
        items = [
            (tr("meta.duration"), fmt_time(r.duration, precise=r.duration < 60)),
            (tr("meta.format"), r.format),
            (tr("meta.sample_rate"), f"{r.sample_rate:,} Hz".replace(",", ".")),
            (tr("meta.channels"), ch),
            (tr("meta.size"), fmt_size(r.size)),
            (tr("meta.device"), "GPU (CUDA)" if r.device == "cuda" else "CPU"),
            (tr("meta.analyzed"), when),
        ]
        for i, (k, val) in enumerate(items):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(label(k, "metakey"))
            cell.addWidget(ElidedLabel(str(val), "metaval", Qt.TextElideMode.ElideRight))
            grid.addLayout(cell, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        col.addLayout(grid)
        sha = QHBoxLayout()
        sha.setSpacing(6)
        sha.addWidget(label(tr("meta.sha256"), "metakey"))
        sha.addWidget(ElidedLabel(r.sha256 or "–", "mono"), 1)
        cp = icon_button("copy", tr("results.copy"), size=16)
        cp.clicked.connect(self._copy_sha)
        sha.addWidget(cp)
        col.addLayout(sha)
        h.addLayout(col, 1)
        card.add_layout(h)
        return card

    def _copy_sha(self):
        QApplication.clipboard().setText(self.r.sha256)
        self.win.toast(tr("results.copied"))

    # ------------------------------------------------------------ breakdown
    def _breakdown_card(self) -> QWidget:
        card = Card(padding=20, spacing=8)
        card.add(card_header("layers", tr("breakdown.title"), tr("breakdown.caption")))
        infos = {m.id: m for m in self.win.models}
        for m in self.r.models:
            card.add(separator())
            card.add(ModelRow(m, infos.get(m.model_id)))
        return card

    # ------------------------------------------------------------ forensic
    def _forensic_card(self) -> QWidget:
        r = self.r
        card = Card(padding=20, spacing=12, shadow=False)
        top = QHBoxLayout()
        top.addWidget(card_header("wave", tr("forensic.card_title"), tr("forensic.card_caption")), 1)
        self.play_btn = button(tr("forensic.play"), "primary", "play", size="sm")
        self.play_btn.clicked.connect(self._toggle_play)
        top.addWidget(self.play_btn, 0, Qt.AlignmentFlag.AlignTop)
        card.add_layout(top)

        legend = QHBoxLayout()
        legend.setSpacing(8)
        legend.addSpacing(ForensicTimeline.LABEL_W)
        legend.addWidget(label(f"{tr('forensic.legend_real')} 0", "caption"))
        legend.addWidget(LegendBar())
        legend.addWidget(label(f"100 {tr('forensic.legend_fake')}", "caption"))
        legend.addStretch(1)
        self.time_lbl = label(f"00:00.0 / {fmt_time(r.duration, True)}", "mono")
        legend.addWidget(self.time_lbl)
        card.add_layout(legend)

        self.timeline = ForensicTimeline(r)
        self.timeline.seek_requested.connect(self._play_from)
        card.add(self.timeline)

        card.add(separator())
        card.add(label(tr("forensic.segments"), "h3"))
        if r.segments:
            for seg in r.segments:
                row = SegmentRow(seg)
                row.clicked.connect(self._play_from)
                card.add(row)
        else:
            ok = label(tr("forensic.no_segments"), "muted")
            card.add(ok)
        return card

    def _upsell_card(self) -> QWidget:
        card = Card(name="SoftCard", padding=18, spacing=10, shadow=False)
        h = QHBoxLayout()
        h.setSpacing(14)
        h.addWidget(card_header("wave", tr("forensic.upsell_title"), tr("forensic.upsell_text")), 1)
        btn = button(tr("forensic.upsell_button"), "primary", "scan")
        btn.clicked.connect(self.win.reanalyze_forensic)
        h.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card.add_layout(h)
        return card

    # ------------------------------------------------------------ audio
    def _ensure_player(self) -> bool:
        if self.player is not None:
            return True
        try:
            self.player = AudioPlayer(self.r.path, self)
        except Exception:
            self.player = None
            self.win.toast(tr("player.unavailable"))
            return False
        self.player.position.connect(self._on_position)
        self.player.playing.connect(self._on_playing)
        return True

    def _play_from(self, seconds: float):
        if self._ensure_player():
            self.player.play_from(seconds)

    def _toggle_play(self):
        if self._ensure_player():
            self.player.toggle()

    def _on_position(self, s: float):
        if self.timeline is not None:
            self.timeline.set_playhead(s)
        self.time_lbl.setText(f"{fmt_time(s, True)} / {fmt_time(self.r.duration, True)}")

    def _on_playing(self, playing: bool):
        self.play_btn.setText(tr("forensic.pause") if playing else tr("forensic.play"))
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", "#FFFFFF", 18))

    def cleanup(self):
        if self.player is not None:
            self.player.stop()


# ------------------------------------------------------------- side list
class FileListItem(QWidget):
    def __init__(self, r):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(ElidedLabel(r.name, "h3"))
        sub = verdict_text(r.total) if not r.error else tr("status.error")
        if r.segments:
            sub += "  ·  ⚠ " + tr("results.segments_pill", n=len(r.segments))
        col.addWidget(ElidedLabel(sub, "caption", Qt.TextElideMode.ElideRight))
        lay.addLayout(col, 1)
        if r.total is not None:
            sc = pill(f"{r.total:.0f}", theme.score_color(r.total), theme.score_text_color(r.total))
        else:
            sc = pill("–", theme.c("danger"))
        lay.addWidget(sc)


class ResultsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.detail: FileDetail | None = None
        self.setObjectName("Page")
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 22, 16, 0)
        v.setSpacing(16)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(tr("results.title"), "title"))
        self.summary = label("", "muted")
        col.addWidget(self.summary)
        top.addLayout(col, 1)
        exp = button(tr("results.export"), None, "download")
        exp.clicked.connect(self.export)
        top.addWidget(exp)
        new = button(tr("results.new"), "primary", "plus")
        new.clicked.connect(win.new_analysis)
        top.addWidget(new)
        top.addSpacing(12)
        v.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(18)
        self.sidebar = Card(padding=10, spacing=6, shadow=False)
        self.sidebar.setFixedWidth(290)
        files_lbl = label(tr("results.files").upper(), "caption")
        files_lbl.setContentsMargins(8, 4, 0, 0)
        self.sidebar.add(files_lbl)
        self.list = QListWidget()
        self.list.setObjectName("FileList")
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentRowChanged.connect(self._select)
        self.sidebar.add(self.list, 1)
        body.addWidget(self.sidebar, 0, Qt.AlignmentFlag.AlignTop)
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self.scroll, 1)
        v.addLayout(body, 1)

    def refresh(self):
        res = self.win.results
        k = sum(1 for r in res if r.total is not None and r.total >= scoring.DECISION)
        self.summary.setText(tr("results.summary", n=len(res), k=k))
        self.list.blockSignals(True)
        self.list.clear()
        for r in res:
            item = QListWidgetItem()
            w = FileListItem(r)
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            self.list.setItemWidget(item, w)
        self.list.blockSignals(False)
        self.sidebar.setVisible(len(res) > 1)
        if res:
            row = min(self.win.selected, len(res) - 1)
            self.list.setCurrentRow(row)
            self._select(row)

    def _select(self, row: int):
        if row < 0 or row >= len(self.win.results):
            return
        self.win.selected = row
        self.cleanup()
        self.detail = FileDetail(self.win, self.win.results[row])
        self.scroll.setWidget(self.detail)
        self.scroll.verticalScrollBar().setValue(0)

    def cleanup(self):
        if self.detail is not None:
            self.detail.cleanup()

    def export(self):
        if not self.win.results:
            return
        default = Path(self.win.settings.last_dir or ".") / f"verivoz_{datetime.now():%Y%m%d_%H%M%S}.json"
        path, _ = QFileDialog.getSaveFileName(self, tr("results.export"), str(default), "JSON (*.json)")
        if not path:
            return
        data = {
            "app": APP_NAME, "version": APP_VERSION, "exported_at": datetime.now().isoformat(timespec="seconds"),
            "scale": "0 = real, 100 = fake; decision threshold = 50",
            "results": [r.to_dict() for r in self.win.results],
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.win.toast(tr("results.export_done", path=path))
