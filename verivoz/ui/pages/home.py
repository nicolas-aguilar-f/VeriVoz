"""Home page: drop zone, audio queue, options and Analyze button."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ...core.audio import AUDIO_EXTENSIONS, AudioInfo, fmt_size, fmt_time
from ...core.downloads import fmt_bytes
from ...core.i18n import tr
from .. import theme
from ..widgets.common import (Card, ElidedLabel, ScrollPage, ToggleSwitch, button, icon_badge, icon_button,
                              label, separator)
from ..widgets.dropzone import DropZone


def describe(info: AudioInfo) -> str:
    ch = {1: tr("meta.mono"), 2: tr("meta.stereo")}.get(info.channels, tr("meta.n_channels", n=info.channels))
    parts = [fmt_time(info.duration), f"{info.sample_rate / 1000:g} kHz" if info.sample_rate else "", ch,
             info.format, fmt_size(info.size)]
    return " · ".join(p for p in parts if p)


class FileRow(QFrame):
    def __init__(self, info: AudioInfo, on_remove):
        super().__init__()
        self.setObjectName("Row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 7, 6, 7)
        lay.setSpacing(12)
        lay.addWidget(icon_badge("music", 34))
        col = QVBoxLayout()
        col.setSpacing(1)
        name = ElidedLabel(info.name, "h3")
        meta = ElidedLabel(describe(info), "caption", Qt.TextElideMode.ElideRight)
        name.setToolTip(info.path)
        col.addWidget(name)
        col.addWidget(meta)
        lay.addLayout(col, 1)
        rm = icon_button("x", tr("queue.remove"))
        rm.clicked.connect(lambda: on_remove(info.path))
        lay.addWidget(rm)


class HomePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = ScrollPage(max_width=880, spacing=18)
        outer.addWidget(self.scroll)

        hero = QWidget()
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(0, 6, 0, 2)
        hl.setSpacing(6)
        title = label(tr("home.title"), "display")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = label(tr("home.subtitle"), "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(title)
        hl.addWidget(sub)
        self.scroll.add(hero)

        # notice: enabled models not downloaded yet
        self.dl_banner = QFrame()
        self.dl_banner.setObjectName("Banner")
        bl = QHBoxLayout(self.dl_banner)
        bl.setContentsMargins(14, 10, 12, 10)
        bl.setSpacing(12)
        bl.addWidget(icon_badge("download", 34, theme.hexc("primary"), theme.hexc("surface")))
        self.dl_text = label("", "body", wrap=True)
        bl.addWidget(self.dl_text, 1)
        dl_btn = button(tr("home.download"), "primary", "download", size="sm")
        dl_btn.clicked.connect(lambda: win.open_downloads(win.pending_downloads()))
        bl.addWidget(dl_btn)
        self.scroll.add(self.dl_banner)

        self.drop = DropZone()
        self.drop.files_dropped.connect(win.add_paths)
        self.drop.browse_files.connect(self.pick_files)
        self.drop.browse_folder.connect(self.pick_folder)
        self.scroll.add(self.drop)

        # file queue
        self.queue_card = Card(padding=14, spacing=4)
        head = QHBoxLayout()
        head.setContentsMargins(8, 2, 0, 6)
        self.queue_title = label("", "h3")
        head.addWidget(self.queue_title)
        head.addStretch(1)
        self.loading = label(tr("queue.reading"), "caption")
        head.addWidget(self.loading)
        self.clear_btn = button(tr("queue.clear"), "ghost", "trash", size="sm")
        self.clear_btn.clicked.connect(win.clear_queue)
        head.addWidget(self.clear_btn)
        self.queue_card.add_layout(head)
        self.queue_box = QVBoxLayout()
        self.queue_box.setSpacing(0)
        self.queue_card.add_layout(self.queue_box)
        self.scroll.add(self.queue_card)

        # options
        opts = Card(padding=18, spacing=14)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(icon_badge("wave", 40), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(tr("forensic.title"), "h3"))
        col.addWidget(label(tr("forensic.desc"), "muted", wrap=True))
        row.addLayout(col, 1)
        self.forensic = ToggleSwitch(win.settings.forensic)
        self.forensic.toggled.connect(self._on_forensic)
        row.addWidget(self.forensic, 0, Qt.AlignmentFlag.AlignVCenter)
        opts.add_layout(row)
        opts.add(separator())
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(icon_badge("layers", 40), 0, Qt.AlignmentFlag.AlignTop)
        col2 = QVBoxLayout()
        col2.setSpacing(3)
        col2.addWidget(label(tr("home.models"), "h3"))
        self.models_lbl = label("", "muted", wrap=True)
        col2.addWidget(self.models_lbl)
        col2.addWidget(label(tr("home.sequential"), "caption", wrap=True))
        row2.addLayout(col2, 1)
        opts.add_layout(row2)
        self.scroll.add(opts)

        self.analyze_btn = button(tr("home.analyze"), "primary", "scan", size="lg")
        self.analyze_btn.setMinimumWidth(280)
        self.analyze_btn.clicked.connect(lambda: win.start_analysis())
        self.scroll.add(self.analyze_btn, align=Qt.AlignmentFlag.AlignHCenter)
        self.scroll.add_stretch()
        self.set_loading(False)

    # ---------------------------------------------------------------- actions
    def _filter(self) -> str:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        return f"{tr('dialog.audio_filter')} ({exts});;{tr('dialog.all_files')} (*.*)"

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("dialog.pick_files"), self.win.settings.last_dir, self._filter())
        if files:
            self.win.add_paths(files)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.pick_folder"), self.win.settings.last_dir)
        if folder:
            self.win.add_paths([folder])

    def _on_forensic(self, on: bool):
        self.win.settings.forensic = on
        self.win.settings.save()

    def set_loading(self, on: bool):
        self.loading.setVisible(on)
        if on:
            self.queue_card.setVisible(True)

    def refresh(self):
        while self.queue_box.count():
            item = self.queue_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        q = self.win.queue
        for info in q:
            self.queue_box.addWidget(FileRow(info, self.win.remove_from_queue))
        self.queue_card.setVisible(bool(q) or self.loading.isVisible())
        self.clear_btn.setVisible(bool(q))
        self.queue_title.setText(tr("queue.count_one") if len(q) == 1 else tr("queue.count", n=len(q)))
        pending = self.win.pending_models()
        self.dl_banner.setVisible(bool(pending))
        if pending:
            # Versions of the same family are shown together: "DF-Arena (1B / 500M)"
            names, size, seen = [], 0, {}
            for m in pending:
                if m.family:
                    seen.setdefault(m.family, []).append(m)
                else:
                    names.append(m.name)
                    size += m.pending_size
            for variants in seen.values():
                fam = variants[0].family_name
                if len(variants) == 1:
                    names.append(variants[0].name)
                else:
                    names.append(f"{fam} ({' / '.join(v.name.replace(fam, '').strip() for v in variants)})")
                size += min(v.pending_size for v in variants)
            self.dl_text.setText(tr("home.missing", models=", ".join(names), size=fmt_bytes(size)))
        models = self.win.enabled_models()
        if models:
            self.models_lbl.setText("  ·  ".join(m.name for m in models))
            self.models_lbl.setProperty("role", "muted")
        else:
            self.models_lbl.setText(tr("home.models_none"))
            self.models_lbl.setProperty("role", "danger")
        self.models_lbl.style().unpolish(self.models_lbl)
        self.models_lbl.style().polish(self.models_lbl)
        self.analyze_btn.setEnabled(bool(q) and bool(models) and not self.win.busy)
        self.analyze_btn.setText(tr("home.analyze_n", n=len(q)) if len(q) > 1 else tr("home.analyze"))
        self.forensic.blockSignals(True)
        self.forensic.setChecked(self.win.settings.forensic)
        self.forensic._pos = 1.0 if self.win.settings.forensic else 0.0
        self.forensic.blockSignals(False)
