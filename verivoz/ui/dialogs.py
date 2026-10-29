"""Dialogs: threshold calibration, add / remove / validate models, downloads, guide."""
from __future__ import annotations

import html
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QListWidget,
                               QPlainTextEdit, QProgressBar, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..core import engine, registry, validation
from ..core.audio import AUDIO_EXTENSIONS, collect_audio
from ..core.calibration import compute_threshold
from ..core.downloads import DownloadCancelled, disk_free, fmt_bytes, fmt_eta, group_by_model
from ..core.downloads import download as _download
from ..core.i18n import language, tr
from ..core.paths import DOCS_DIR, GUIDE_FILE
from . import theme
from .widgets.common import Card, ElidedLabel, button, card_header, label, separator
from .workers import run_task


def _scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setObjectName("ScrollContent")
    area.setWidget(widget)
    return area


def specs_text(hw: dict) -> str:
    """Approximate specs declared in the manifest: "1,150 M parameters · 6 GB VRAM · …"."""
    text = tr("hw.specs", params=f"{hw.get('params_m', '?'):,}".replace(",", "."),
              vram=hw.get("vram_gb", "?"), ram=hw.get("ram_gb", "?"))
    note = hw.get("note")
    if isinstance(note, dict):
        note = note.get(language()) or note.get("es") or ""
    return f"{text} · {note}" if note else text


def download_items(items, report, cancel):
    """Adapter for run_task: a cancelled download is handled like a cancelled analysis."""
    try:
        return _download(items, report=report, cancel=cancel)
    except DownloadCancelled:
        raise engine.Cancelled() from None


def open_folder(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_in_editor(path) -> None:
    """Opens a text file for editing. With openUrl, a .py file would be EXECUTED on Windows."""
    if sys.platform == "win32":
        try:
            os.startfile(str(path), "edit")
        except OSError:
            subprocess.Popen(["notepad.exe", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _audio_filter() -> str:
    exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
    return f"{tr('dialog.audio_filter')} ({exts});;{tr('dialog.all_files')} (*.*)"


class _BaseDialog(QDialog):
    def __init__(self, parent, title: str, size=(760, 560)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self.task = None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 22, 24, 20)
        self.root.setSpacing(14)

    def _stop_task(self):
        if self.task is not None and self.task.is_running():
            self.task.cancel()
            self.task.wait(30000)

    def reject(self):
        self._stop_task()
        super().reject()

    def accept(self):
        self._stop_task()
        super().accept()


# ============================================================== calibration
class _DropList(QListWidget):
    def __init__(self, on_paths):
        super().__init__()
        self.setObjectName("DropList")
        self.on_paths = on_paths
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.on_paths(paths)
            e.acceptProposedAction()


class AudioSetBox(QWidget):
    def __init__(self, title: str, color_key: str, win):
        super().__init__()
        self.win = win
        self.paths: list[str] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        t = label(title, "h3")
        t.setStyleSheet(f"color: {theme.hexc(color_key)};")
        head.addWidget(t)
        head.addStretch(1)
        self.count = label(tr("calib.count", n=0), "caption")
        head.addWidget(self.count)
        v.addLayout(head)
        self.list = _DropList(self.add)
        self.list.setMinimumHeight(150)
        self.list.setToolTip(tr("calib.drop_hint"))
        v.addWidget(self.list, 1)
        btns = QHBoxLayout()
        b1 = button(tr("calib.add_files"), None, "file", size="sm")
        b2 = button(tr("calib.add_folder"), None, "folder", size="sm")
        b3 = button(tr("calib.clear"), "ghost", "trash", size="sm")
        b1.clicked.connect(self._pick_files)
        b2.clicked.connect(self._pick_folder)
        b3.clicked.connect(self.clear)
        for b in (b1, b2):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(b3)
        v.addLayout(btns)
        self.list.addItem(tr("calib.drop_hint"))
        self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)

    def add(self, paths):
        known = set(self.paths)
        for p in collect_audio(paths):
            if p not in known:
                self.paths.append(p)
                known.add(p)
        self._refresh()

    def clear(self):
        self.paths = []
        self._refresh()

    def _refresh(self):
        self.list.clear()
        if not self.paths:
            self.list.addItem(tr("calib.drop_hint"))
            self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        for p in self.paths:
            self.list.addItem(Path(p).name)
            self.list.item(self.list.count() - 1).setToolTip(p)
        self.count.setText(tr("calib.count", n=len(self.paths)))

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("dialog.pick_files"), self.win.settings.last_dir, _audio_filter())
        if files:
            self.add(files)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("dialog.pick_folder"), self.win.settings.last_dir)
        if d:
            self.add([d])


class CalibrationDialog(_BaseDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win, tr("calib.title"), (900, 720))
        self.win = win
        self.models = [m for m in win.models if m.ok]
        self.suggested: dict = {}
        self.root.addWidget(card_header("sliders", tr("calib.title"), tr("calib.intro")))
        sets = QHBoxLayout()
        sets.setSpacing(16)
        self.real = AudioSetBox(tr("calib.real"), "success", win)
        self.fake = AudioSetBox(tr("calib.fake"), "danger", win)
        sets.addWidget(self.real)
        sets.addWidget(self.fake)
        self.root.addLayout(sets, 1)

        self.root.addWidget(label(tr("calib.models"), "h3"))
        mrow = QHBoxLayout()
        self.checks = {}
        for m in self.models:
            cb = QCheckBox(m.name)
            cb.setChecked(win.settings.is_enabled(m))
            self.checks[m.id] = cb
            mrow.addWidget(cb)
        mrow.addStretch(1)
        self.root.addLayout(mrow)

        run_row = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        run_row.addWidget(self.bar, 1)
        self.run_btn = button(tr("calib.run"), "primary", "scan")
        self.run_btn.clicked.connect(self.run)
        run_row.addWidget(self.run_btn)
        self.root.addLayout(run_row)
        self.status = label("", "muted", wrap=True)
        self.root.addWidget(self.status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("calib.col_model"), tr("calib.col_current"), tr("calib.col_suggested"),
                                              tr("calib.col_eer"), tr("calib.col_acc")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(150)
        self.table.hide()
        self.root.addWidget(self.table)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.apply_btn = button(tr("calib.apply"), "primary", "check")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = button(tr("common.close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        bottom.addWidget(self.apply_btn)
        self.root.addLayout(bottom)

    def run(self):
        models = [m for m in self.models if self.checks[m.id].isChecked()]
        if not self.real.paths or not self.fake.paths:
            self.status.setText(tr("calib.need_both"))
            return
        if not models:
            return
        self.run_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.status.setText(tr("calib.running"))
        self.bar.setValue(0)
        paths = self.real.paths + self.fake.paths
        self._run_models = models
        self.task = run_task(engine.score_files, paths, models, self.win.settings.device,
                             aggregation=self.win.settings.aggregation,
                             on_progress=self._on_event, on_done=self._on_done, on_error=self._on_error)

    def _on_event(self, e):
        if e.get("type") == "progress":
            self.bar.setValue(int(e["value"] * 1000))
        elif e.get("type") == "stage":
            self.status.setText(tr("progress.model", i=e["index"] + 1, n=e["count"], name=e["model"]) + " · " +
                                (tr("progress.loading", device=self.win.device_name()) if e["phase"] == "loading"
                                 else tr("progress.running")))
        elif e.get("type") == "file":
            self.status.setText(tr("progress.file", i=e["index"] + 1, n=e["count"], name=Path(e["name"]).name))

    def _on_error(self, tb: str):
        self.run_btn.setEnabled(True)
        self.status.setText(tb.strip().splitlines()[-1])

    def _on_done(self, probs: dict):
        self.run_btn.setEnabled(True)
        self.bar.setValue(1000)
        n_real = len(self.real.paths)
        self.suggested = {}
        self.table.setRowCount(0)
        for m in self._run_models:
            p = probs.get(m.id, [])
            row = self.table.rowCount()
            self.table.insertRow(row)
            cur = self.win.settings.threshold(m)
            cells = [m.name, f"{cur:.2f}"]
            try:
                res = compute_threshold(p[:n_real], p[n_real:])
                self.suggested[m.id] = res
                cells += [f"{res['threshold']:.2f}", f"{res['eer']:.1f} %", f"{res['balanced_accuracy']:.1f} %"]
            except ValueError:
                cells += [tr("calib.failed_model"), "–", "–"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, c, item)
        self.table.show()
        self.status.setText(tr("calib.done"))
        self.apply_btn.setEnabled(bool(self.suggested))

    def apply(self):
        s = self.win.settings
        now = datetime.now().isoformat(timespec="seconds")
        for mid, res in self.suggested.items():
            s.thresholds[mid] = res["threshold"]
            s.calibration[mid] = {"date": now, **res}
        s.save()
        self.win.toast(tr("calib.applied"))
        self.accept()


# ================================================================ add model
class AddModelDialog(_BaseDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win, tr("add.title"), (820, 760))
        self.win = win
        self.created = None
        self.root.addWidget(card_header("plus", tr("add.title"), "", danger=False))
        tabs = QTabWidget()
        tabs.addTab(_scrollable(self._create_tab()), tr("add.tab_create"))
        tabs.addTab(_scrollable(self._import_tab()), tr("add.tab_import"))
        self.root.addWidget(tabs, 1)
        bottom = QHBoxLayout()
        guide = button(tr("settings.open_guide"), "ghost", "book")
        guide.clicked.connect(lambda: GuideDialog(self).exec())
        bottom.addWidget(guide)
        bottom.addStretch(1)
        close = button(tr("common.close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        self.root.addLayout(bottom)

    # -------------------------------------------------- create from .pth
    def _create_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("add.create_intro"), "muted", wrap=True))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("My detector")
        self.mid = QLineEdit()
        self.mid.setPlaceholderText("my_detector")
        self._id_touched = False
        self.name.textChanged.connect(self._auto_id)
        self.mid.textEdited.connect(lambda _: setattr(self, "_id_touched", True))
        self.weights = QLineEdit()
        self.weights.setPlaceholderText("C:/path/to/my_model.pth")
        browse = button(tr("add.browse"), None, "folder", size="sm")
        browse.clicked.connect(self._pick_weights)
        wrow = QHBoxLayout()
        wrow.addWidget(self.weights, 1)
        wrow.addWidget(browse)
        self.sr = QSpinBox()
        self.sr.setRange(8000, 96000)
        self.sr.setSingleStep(1000)
        self.sr.setValue(16000)
        self.win_s = QDoubleSpinBox()
        self.win_s.setRange(0.5, 60.0)
        self.win_s.setSingleStep(0.5)
        self.win_s.setValue(4.0)
        self.desc = QLineEdit()
        self.copy = QCheckBox(tr("add.copy_weights"))
        self.copy.setChecked(True)
        rows = [(tr("add.name"), self.name), (tr("add.id"), self.mid), (tr("add.weights"), wrow),
                (tr("add.sample_rate"), self.sr), (tr("add.window"), self.win_s), (tr("add.description"), self.desc)]
        for i, (k, field) in enumerate(rows):
            g.addWidget(label(k, "body"), i, 0)
            if isinstance(field, QHBoxLayout):
                g.addLayout(field, i, 1)
            else:
                g.addWidget(field, i, 1)
        g.addWidget(self.copy, len(rows), 1)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        self.create_btn = button(tr("add.create"), "primary", "plus")
        self.create_btn.clicked.connect(self._create)
        v.addWidget(self.create_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.create_msg = label("", "danger", wrap=True)
        self.create_msg.hide()
        v.addWidget(self.create_msg)

        self.next_card = Card(name="SoftCard", padding=16, spacing=8, shadow=False)
        self.next_title = label("", "h3")
        self.next_title.setWordWrap(True)
        self.next_card.add(self.next_title)
        self.next_card.add(label(tr("add.next_steps"), "muted", wrap=True))
        nb = QHBoxLayout()
        for text, icon_name, fn in ((tr("add.open_folder"), "folder", self._open_folder),
                                    (tr("add.open_detector"), "file", self._open_detector),
                                    (tr("settings.validate"), "shield", self._validate_created)):
            b = button(text, "primary" if icon_name == "shield" else None, icon_name, size="sm")
            b.clicked.connect(fn)
            nb.addWidget(b)
        nb.addStretch(1)
        self.next_card.add_layout(nb)
        self.next_card.hide()
        v.addWidget(self.next_card)
        v.addStretch(1)
        return w

    def _auto_id(self, text: str):
        if not self._id_touched:
            self.mid.setText(registry.slugify(text) if text else "")

    def _pick_weights(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("add.weights"), self.win.settings.last_dir,
                                           f"{tr('add.weights_filter')} (*.pth *.pt *.ckpt *.bin *.safetensors);;"
                                           f"{tr('dialog.all_files')} (*.*)")
        if f:
            self.weights.setText(f)
            if not self.name.text():
                self.name.setText(Path(f).stem.replace("_", " ").title())

    def _create(self):
        name, mid, weights = self.name.text().strip(), self.mid.text().strip(), self.weights.text().strip()
        self.create_msg.hide()
        if not name or not mid or not weights or not Path(weights).is_file():
            self.create_msg.setText(tr("add.missing_fields"))
            self.create_msg.show()
            return
        try:
            info = registry.scaffold_plugin(name, mid, Path(weights), self.sr.value(), self.win_s.value(),
                                            self.desc.text().strip(), copy_weights=self.copy.isChecked())
        except Exception as e:
            self.create_msg.setText(str(e))
            self.create_msg.show()
            return
        self.created = info
        s = self.win.settings
        if info.id not in s.disabled_models:
            s.disabled_models.append(info.id)
        s.save()
        self.win.reload_models()
        self.next_title.setText(tr("add.created", id=info.id, path=info.plugin_dir))
        self.next_card.show()
        self.create_btn.setEnabled(False)

    def _open_folder(self):
        if self.created:
            open_folder(self.created.plugin_dir)

    def _open_detector(self):
        if self.created:
            open_in_editor(self.created.plugin_dir / "detector.py")

    def _validate_created(self):
        if self.created:
            ValidationDialog(self.win, registry.parse_manifest(self.created.plugin_dir), self).exec()

    # -------------------------------------------------- import plugin
    def _import_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("add.import_intro"), "muted", wrap=True))
        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("C:/path/to/my_plugin")
        self.folder.textChanged.connect(self._check_folder)
        b = button(tr("add.browse"), None, "folder", size="sm")
        b.clicked.connect(self._pick_folder)
        row.addWidget(label(tr("add.folder"), "body"))
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        v.addLayout(row)
        self.folder_status = label("", "muted", wrap=True)
        v.addWidget(self.folder_status)
        self.import_btn = button(tr("add.import"), "primary", "download")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import)
        v.addWidget(self.import_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.import_bar = QProgressBar()
        self.import_bar.setRange(0, 0)
        self.import_bar.hide()
        v.addWidget(self.import_bar)
        v.addStretch(1)
        return w

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("add.folder"), self.win.settings.last_dir)
        if d:
            self.folder.setText(d)

    def _check_folder(self, text: str):
        p = Path(text.strip())
        if not text.strip() or not p.is_dir():
            self.folder_status.setText("")
            self.import_btn.setEnabled(False)
            return
        info = registry.parse_manifest(p)
        if info.errors:
            self.folder_status.setProperty("role", "danger")
            self.folder_status.setText(tr("add.manifest_err") + "\n• " + "\n• ".join(info.errors))
        else:
            self.folder_status.setProperty("role", "muted")
            self.folder_status.setText("✔ " + tr("add.manifest_ok", name=info.name, id=info.id))
        self.folder_status.style().unpolish(self.folder_status)
        self.folder_status.style().polish(self.folder_status)
        hard = [e for e in info.errors if not e.startswith(registry.MISSING_FILE)]
        self.import_btn.setEnabled(not hard)

    def _import(self):
        src = Path(self.folder.text().strip())
        self.import_btn.setEnabled(False)
        self.import_bar.show()
        self.folder_status.setText(tr("add.copying"))
        self.task = run_task(lambda src, report, cancel: registry.import_plugin_folder(src), src,
                             on_done=self._imported, on_error=self._import_failed)

    def _imported(self, info):
        self.import_bar.hide()
        s = self.win.settings
        if info.id not in s.disabled_models:
            s.disabled_models.append(info.id)
        s.save()
        self.win.reload_models()
        self.folder_status.setText(tr("add.imported", id=info.id))
        ValidationDialog(self.win, info, self).exec()

    def _import_failed(self, tb: str):
        self.import_bar.hide()
        self.import_btn.setEnabled(True)
        self.folder_status.setProperty("role", "danger")
        self.folder_status.setText(tb.strip().splitlines()[-1])
        self.folder_status.style().unpolish(self.folder_status)
        self.folder_status.style().polish(self.folder_status)


# ================================================================ downloads
class DownloadDialog(_BaseDialog):
    """Shows what will be downloaded (source, size, license), asks for consent and downloads it."""

    def __init__(self, win, items: list, parent=None):
        super().__init__(parent or win, tr("dl.title"), (900, 720))
        self.win = win
        self.items = items
        self.done_ok = False
        self.root.addWidget(card_header("download", tr("dl.title"), tr("dl.intro")))

        groups = group_by_model(items)
        families: dict[str, int] = {}
        for its in groups.values():
            if its[0].family:
                families[its[0].family] = families.get(its[0].family, 0) + 1

        box = QWidget()
        box.setObjectName("ScrollContent")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        self.groups: list[tuple[QCheckBox, list]] = []
        link = theme.hexc("primary")
        shown_family_note = set()
        for mid, its in groups.items():
            first = its[0]
            if first.family and families.get(first.family, 0) > 1 and first.family not in shown_family_note:
                shown_family_note.add(first.family)
                note = label(tr("hw.family_choose", family=first.family_name or first.family), "muted", wrap=True)
                lay.addWidget(note)
            card = Card(name="SoftCard", padding=14, spacing=4, shadow=False)
            head = QHBoxLayout()
            needs_accept = any(it.requires_acceptance for it in its)
            cb = QCheckBox(first.model_name)
            cb.setStyleSheet("font-weight: 700; font-size: 14px;")
            cb.setChecked(not needs_accept)
            cb.toggled.connect(self._update_summary)
            self.groups.append((cb, its))
            head.addWidget(cb)
            head.addStretch(1)
            head.addWidget(label(fmt_bytes(sum(it.missing_size for it in its)), "h3"))
            card.add_layout(head)
            if first.hardware:
                card.add(label(specs_text(first.hardware), "body", wrap=True))
            for it in its:
                lic = html.escape(it.license or "—")
                if it.license_url:
                    lic = f'<a style="color:{link}" href="{html.escape(it.license_url)}">{lic}</a>'
                row = label(f'• {html.escape(it.name)} — <a style="color:{link}" href="{html.escape(it.page)}">'
                            f'{html.escape(it.source)}</a> · {fmt_bytes(it.missing_size)} · '
                            f'{tr("dl.license")}: {lic}', "caption")
                row.setWordWrap(True)
                row.setOpenExternalLinks(True)
                card.add(row)
            if needs_accept:
                card.add(label("⚠ " + tr("dl.accept_notice"), "warn", wrap=True))
            card.add(ElidedLabel(f'{tr("dl.dest")}: {first.target.parent}', "caption"))
            lay.addWidget(card)
        lay.addStretch(1)
        self.root.addWidget(_scrollable(box), 1)

        self.summary = label("", "muted")
        self.root.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.root.addWidget(self.bar)
        self.status = label("", "caption", wrap=True)
        self.root.addWidget(self.status)
        bottom = QHBoxLayout()
        bottom.addWidget(label(tr("dl.resume_note"), "caption"), 1)
        self.later_btn = button(tr("dl.later"))
        self.later_btn.clicked.connect(self.reject)
        self.go_btn = button(tr("dl.start"), "primary", "download")
        self.go_btn.clicked.connect(self._start)
        bottom.addWidget(self.later_btn)
        bottom.addWidget(self.go_btn)
        self.root.addLayout(bottom)
        self._update_summary()

    def _selected(self) -> list:
        return [it for cb, its in self.groups if cb.isChecked() for it in its]

    def _update_summary(self, *_):
        sel = self._selected()
        size = sum(it.missing_size for it in sel)
        free = disk_free(self.items[0].target) if self.items else 0
        text = tr("dl.summary", sel=fmt_bytes(size), free=fmt_bytes(free))
        if size > free:
            text += " · " + tr("dl.no_space")
        self.summary.setText(text)
        self.go_btn.setEnabled(bool(sel) and size <= free)

    def _start(self):
        if self.task is not None and self.task.is_running():
            self.task.cancel()
            self.go_btn.setEnabled(False)
            return
        sel = self._selected()
        for cb, _ in self.groups:
            cb.setEnabled(False)
        self.bar.setValue(0)
        self.bar.show()
        self.later_btn.setEnabled(False)
        self.go_btn.setText(tr("dl.cancel"))
        self.task = run_task(download_items, sel, on_progress=self._on_event, on_done=self._done,
                             on_error=self._failed, on_cancel=self._cancelled)

    def _on_event(self, e: dict):
        if e["type"] == "file":
            self.status.setText(tr("dl.file", file=e["file"], i=e["index"] + 1, n=e["count"], model=e["model"]))
            self._file_text = self.status.text()
        elif e["type"] == "progress" and e["total"]:
            self.bar.setValue(int(1000 * min(1.0, e["done"] / e["total"])))
            eta = fmt_eta(e["eta"]) if e.get("eta") is not None else "…"
            self.status.setText(getattr(self, "_file_text", "") + "\n" + tr(
                "dl.progress", done=fmt_bytes(e["done"]), total=fmt_bytes(e["total"]),
                speed=fmt_bytes(e["speed"]), eta=eta))

    def _finish(self):
        self.go_btn.setText(tr("dl.start"))
        self.later_btn.setEnabled(True)
        for cb, _ in self.groups:
            cb.setEnabled(True)
        self.go_btn.setEnabled(True)

    def _done(self, _):
        self.done_ok = True
        self.bar.setValue(1000)
        self.win.toast(tr("dl.done"))
        self.accept()

    def _failed(self, tb: str):
        self._finish()
        self.status.setText(tr("dl.error", err=tb.strip().splitlines()[-1]))
        self.status.setProperty("role", "danger")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _cancelled(self):
        self._finish()
        self.status.setText(tr("dl.cancelled"))


# ==================================================================== guide
class GuideDialog(_BaseDialog):
    """Shows docs/ADDING_MODELS.md inside the application."""

    def __init__(self, parent):
        super().__init__(parent, tr("settings.open_guide"), (1000, 780))
        self.root.addWidget(card_header("book", tr("settings.open_guide"), str(GUIDE_FILE)))
        browser = QTextBrowser()
        browser.setObjectName("Guide")
        browser.setOpenExternalLinks(True)
        browser.document().setDocumentMargin(12)
        try:
            browser.setMarkdown(GUIDE_FILE.read_text(encoding="utf-8"))
            self._style_code(browser.document())
        except OSError as e:
            browser.setPlainText(f"{GUIDE_FILE}\n\n{e}")
        self.root.addWidget(browser, 1)
        bottom = QHBoxLayout()
        folder = button(tr("guide.open_folder"), None, "folder", size="sm")
        folder.clicked.connect(lambda: open_folder(DOCS_DIR))
        bottom.addWidget(folder)
        bottom.addStretch(1)
        close = button(tr("common.close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        self.root.addLayout(bottom)

    @staticmethod
    def _style_code(doc) -> None:
        """The Markdown importer uses the system fixed font, which may lack some glyphs:
        force a specific monospace font and the accent color for code."""
        mono = QTextCharFormat()
        mono.setFontFamilies(["Cascadia Mono", "Consolas", "Courier New"])
        mono.setForeground(theme.c("primary_pressed") if not theme.is_dark() else theme.c("primary_hover"))
        spans = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().fontFixedPitch():
                    spans.append((frag.position(), frag.length()))
                it += 1
            block = block.next()
        cursor = QTextCursor(doc)
        for pos, length in spans:
            cursor.setPosition(pos)
            cursor.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(mono)


# ============================================================= remove model
class RemoveModelDialog(_BaseDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win, tr("remove.title"), (620, 420))
        self.win = win
        self.root.addWidget(card_header("trash", tr("remove.title"), tr("remove.warning"), danger=True))
        if not win.models:
            self.root.addWidget(label(tr("remove.none"), "muted"))
        g = QGridLayout()
        g.setVerticalSpacing(10)
        self.combo = QComboBox()
        for m in win.models:
            self.combo.addItem(f"{m.name}  ({m.id})", m.id)
        self.combo.currentIndexChanged.connect(self._update)
        g.addWidget(label(tr("remove.model"), "body"), 0, 0)
        g.addWidget(self.combo, 0, 1)
        g.setColumnStretch(1, 1)
        self.root.addLayout(g)
        self.permanent = QCheckBox(tr("remove.permanent"))
        self.root.addWidget(self.permanent)
        self.root.addWidget(separator())
        self.confirm_lbl = label("", "body")
        self.root.addWidget(self.confirm_lbl)
        self.confirm = QLineEdit()
        self.confirm.textChanged.connect(self._update)
        self.root.addWidget(self.confirm)
        self.root.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        cancel = button(tr("common.cancel"))
        cancel.clicked.connect(self.reject)
        self.remove_btn = button(tr("remove.button"), "danger-solid", "trash")
        self.remove_btn.clicked.connect(self._remove)
        bottom.addWidget(cancel)
        bottom.addWidget(self.remove_btn)
        self.root.addLayout(bottom)
        self._update()

    def _current(self):
        mid = self.combo.currentData()
        return next((m for m in self.win.models if m.id == mid), None)

    def _update(self, *_):
        m = self._current()
        self.confirm_lbl.setText(tr("remove.confirm", id=m.id) if m else "")
        self.remove_btn.setEnabled(bool(m) and self.confirm.text().strip() == m.id)

    def _remove(self):
        m = self._current()
        if not m:
            return
        try:
            dest = registry.remove_plugin(m, permanent=self.permanent.isChecked())
        except Exception as e:
            self.confirm_lbl.setText(str(e))
            return
        s = self.win.settings
        s.thresholds.pop(m.id, None)
        s.calibration.pop(m.id, None)
        s.save()
        self.win.reload_models()
        self.win.toast(tr("remove.done_trash", path=dest) if dest else tr("remove.done"), 5000)
        self.accept()


# =========================================================== validate model
class ValidationDialog(_BaseDialog):
    SYMBOLS = {"ok": ("✔", "success"), "warn": ("⚠", "warning"), "fail": ("✖", "danger"), "info": ("·", "text_muted")}

    def __init__(self, win, model, parent=None):
        super().__init__(parent or win, tr("validate.title", name=model.name), (820, 560))
        self.win = win
        self.model = model
        self.audio_path: str | None = None
        self.passed = False
        self.root.addWidget(card_header("shield", tr("validate.title", name=model.name), str(model.plugin_dir)))
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.root.addWidget(self.log, 1)
        self.status = label("", "h3")
        self.root.addWidget(self.status)
        bottom = QHBoxLayout()
        self.audio_btn = button(tr("validate.test_audio"), None, "music", size="sm")
        self.audio_btn.clicked.connect(self._pick_audio)
        self.again_btn = button(tr("validate.run"), None, "refresh", size="sm")
        self.again_btn.clicked.connect(self.run)
        bottom.addWidget(self.audio_btn)
        bottom.addWidget(self.again_btn)
        bottom.addStretch(1)
        self.enable_btn = button(tr("validate.enable"), "primary", "check")
        self.enable_btn.hide()
        self.enable_btn.clicked.connect(self._enable)
        close = button(tr("common.close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        bottom.addWidget(self.enable_btn)
        self.root.addLayout(bottom)
        self.run()

    def _append(self, entry):
        level, msg = entry
        sym, color = self.SYMBOLS.get(level, ("·", "text_muted"))
        text = html.escape(msg).replace("\n", "<br>")
        self.log.appendHtml(f'<span style="color:{theme.hexc(color)}">{sym}</span> '
                            f'<span style="color:{theme.hexc("text" if level != "info" else "text_muted")}">{text}</span>')

    def run(self):
        self.log.clear()
        self.status.setText(tr("validate.running"))
        self.status.setStyleSheet("")
        self.enable_btn.hide()
        self.again_btn.setEnabled(False)
        self.audio_btn.setEnabled(False)
        info = registry.parse_manifest(self.model.plugin_dir)
        device = engine.resolve_device(self.win.settings.device)

        def job(info, device, audio, report, cancel):
            return validation.validate(info, device=device, deep=True, audio_path=audio,
                                       log=lambda lvl, msg: report((lvl, msg)))

        self.task = run_task(job, info, device, self.audio_path, on_progress=self._append,
                             on_done=self._done, on_error=self._error)

    def _done(self, passed: bool):
        self.passed = bool(passed)
        self.again_btn.setEnabled(True)
        self.audio_btn.setEnabled(True)
        color = theme.hexc("success") if passed else theme.hexc("danger")
        self.status.setText(tr("validate.passed") if passed else tr("validate.failed"))
        self.status.setStyleSheet(f"color: {color};")
        self.enable_btn.setVisible(passed and self.model.id in self.win.settings.disabled_models)

    def _error(self, tb: str):
        self._append(("fail", tb))
        self._done(False)

    def _pick_audio(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("dialog.pick_files"), self.win.settings.last_dir, _audio_filter())
        if f:
            self.audio_path = f
            self.run()

    def _enable(self):
        s = self.win.settings
        if self.model.id in s.disabled_models:
            s.disabled_models.remove(self.model.id)
        s.save()
        self.enable_btn.hide()
        self.win.toast(f"{self.model.name}: ✔")
