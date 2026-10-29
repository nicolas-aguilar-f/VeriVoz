"""Main window: header + pages (home, progress, results, settings)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..core import engine, i18n, registry
from ..core.audio import AudioInfo, collect_audio, probe
from ..core.i18n import tr
from . import icons, theme
from .pages.home import HomePage
from .pages.progress import ProgressPage
from .pages.results import ResultsPage
from .pages.settings import SettingsPage
from .widgets.common import Clickable, Toast
from .workers import run_task


def short_gpu_name(name: str | None) -> str:
    if not name:
        return ""
    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "GeForce "):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


class Header(QFrame):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setObjectName("Header")
        self.setFixedHeight(68)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 0, 16, 0)
        lay.setSpacing(12)
        # Logo + name: clicking them goes back to the start state
        brand = Clickable()
        brand.setToolTip(tr("header.home"))
        brand.clicked.connect(win.go_start)
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(38, light=True))
        bl.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addStretch(1)
        t = QLabel(APP_NAME)
        t.setObjectName("HeaderTitle")
        s = QLabel(tr("app.tagline"))
        s.setObjectName("HeaderSubtitle")
        col.addWidget(t)
        col.addWidget(s)
        col.addStretch(1)
        bl.addLayout(col)
        lay.addWidget(brand)
        lay.addStretch(1)

        self.chip = QLabel()
        self.chip.setObjectName("HeaderChip")
        lay.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(6)

        self.back = QToolButton()
        self.back.setObjectName("HeaderButton")
        self.back.setIcon(icons.icon("back", "#FFFFFF", 22))
        self.back.setIconSize(QSize(22, 22))
        self.back.setToolTip(tr("header.back"))
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(win.toggle_settings)
        lay.addWidget(self.back)

        self.gear = QToolButton()
        self.gear.setObjectName("HeaderButton")
        self.gear.setIcon(icons.icon("settings", "#FFFFFF", 24))
        self.gear.setIconSize(QSize(24, 24))
        self.gear.setToolTip(tr("header.settings"))
        self.gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear.clicked.connect(win.toggle_settings)
        lay.addWidget(self.gear)
        self.refresh_chip()

    def refresh_chip(self):
        env, dev = self.win.env, self.win.settings.device
        if env.get("cuda") and dev != "cpu":
            self.chip.setText(tr("header.gpu", name=short_gpu_name(env.get("gpu"))))
            self.chip.setToolTip(env.get("gpu") or "")
        else:
            self.chip.setText(tr("header.cpu"))
            self.chip.setToolTip("")

    def set_mode(self, page: str, busy: bool):
        self.back.setVisible(page == "settings")
        self.gear.setVisible(page != "settings")
        self.gear.setEnabled(not busy)
        self.gear.setToolTip(tr("header.busy") if busy else tr("header.settings"))


class MainWindow(QMainWindow):
    def __init__(self, settings, env: dict, models: list):
        super().__init__()
        self.settings = settings
        self.env = env
        self.models = models
        self.queue: list[AudioInfo] = []
        self.results: list = []
        self.selected = 0
        self.page = "home"
        self.prev_page = "home"
        self.task = None
        self.probe_task = None
        self.setWindowIcon(icons.app_icon())
        self.setWindowTitle(f"{APP_NAME} — {tr('app.tagline')}")
        self.resize(1260, 880)
        self.setMinimumSize(1000, 700)
        self._build()
        self.show_page("home")
        QTimer.singleShot(700, self._startup_downloads)

    # ------------------------------------------------------------------ build
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = Header(self)
        v.addWidget(self.header)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.home = HomePage(self)
        self.progress = ProgressPage(self)
        self.results_page = ResultsPage(self)
        self.settings_page = SettingsPage(self)
        for page in (self.home, self.progress, self.results_page, self.settings_page):
            self.stack.addWidget(page)
        self.setCentralWidget(root)
        self.toast_widget = Toast(root)

    def rebuild(self):
        """Rebuilds the interface (after a theme or language change) keeping the state."""
        self.results_page.cleanup()
        page = self.page
        old = self.takeCentralWidget()
        self._build()
        if old is not None:
            old.deleteLater()
        self.setWindowTitle(f"{APP_NAME} — {tr('app.tagline')}")
        self.show_page(page)

    # ------------------------------------------------------------- navigation
    @property
    def busy(self) -> bool:
        return self.task is not None and self.task.is_running()

    def show_page(self, name: str):
        if name == "settings" and self.page != "settings":
            self.prev_page = self.page
        if name != "results":
            self.results_page.cleanup()
        self.page = name
        widget = {"home": self.home, "progress": self.progress, "results": self.results_page,
                  "settings": self.settings_page}[name]
        if name == "home":
            self.home.refresh()
        elif name == "results":
            self.results_page.refresh()
        elif name == "settings":
            self.settings_page.refresh()
        self.stack.setCurrentWidget(widget)
        self.header.set_mode(name, self.busy)

    def toggle_settings(self):
        if self.page == "settings":
            target = self.prev_page if self.prev_page in ("home", "results") else "home"
            if target == "results" and not self.results:
                target = "home"
            self.show_page(target)
        elif not self.busy:
            self.show_page("settings")

    def toast(self, text: str, ms: int = 3200):
        self.toast_widget.show_message(text, ms)

    # ----------------------------------------------------------------- models
    def enabled_models(self) -> list:
        """Models taking part in the analysis. Only one per family (e.g. DF-Arena 1B/500M),
        so the same model is not counted twice in the average."""
        out, families = [], set()
        for m in self.models:
            if not (m.ok and self.settings.is_enabled(m)):
                continue
            if m.family:
                if m.family in families:
                    continue
                families.add(m.family)
            out.append(m)
        return out

    def reload_models(self):
        self.models = registry.discover()
        valid = {m.id for m in self.models}
        self.settings.disabled_models = [i for i in self.settings.disabled_models if i in valid]
        self.settings.save()

    def activate_model(self, model) -> bool:
        """Enables a model; if it belongs to a family, disables the other versions.
        Returns True if other models changed state."""
        dis = self.settings.disabled_models
        if model.id in dis:
            dis.remove(model.id)
        siblings = [m for m in self.models if model.family and m.family == model.family
                    and m.id != model.id and m.id not in dis]
        for m in siblings:
            dis.append(m.id)
        self.settings.save()
        return bool(siblings)

    def pending_models(self, only_enabled: bool = True) -> list:
        """Models still to download. Skips those whose family already has another version installed."""
        installed = {m.family for m in self.models if m.family and m.ok}
        return [m for m in self.models if m.needs_download and (not only_enabled or self.settings.is_enabled(m))
                and not (m.family and m.family in installed)]

    def pending_downloads(self, only_enabled: bool = True) -> list:
        return [it for m in self.pending_models(only_enabled) for it in m.pending_downloads]

    def _startup_downloads(self):
        """On startup: if an enabled model is missing files, offer to download them."""
        items = self.pending_downloads()
        if items and not self.busy:
            self.open_downloads(items)

    def open_downloads(self, items: list | None = None):
        from .dialogs import DownloadDialog

        items = items if items is not None else self.pending_downloads(only_enabled=False)
        if not items:
            return
        before = {m.id for m in self.models if m.needs_download}
        DownloadDialog(self, items).exec()
        self.reload_models()
        # A freshly downloaded version of a family becomes the active one (the first by order)
        fresh = [m for m in self.models if m.id in before and m.ok and m.family]
        for family in {m.family for m in fresh}:
            self.activate_model(min((m for m in fresh if m.family == family), key=lambda m: m.order))
        if self.page in ("home", "settings"):
            self.show_page(self.page)

    def device_name(self) -> str:
        dev = engine.resolve_device(self.settings.device) if self.env.get("torch") else "cpu"
        return "GPU" if dev == "cuda" else "CPU"

    # ----------------------------------------------------------------- queue
    def add_paths(self, paths: list[str]):
        if not paths:
            return
        self.settings.last_dir = os.path.dirname(paths[0]) if os.path.isfile(paths[0]) else paths[0]
        self.settings.save()
        self.home.set_loading(True)

        def job(paths, report, cancel):
            files = collect_audio(paths)
            infos, failed = [], []
            for f in files:
                if cancel.is_set():
                    break
                try:
                    infos.append(probe(f))
                except Exception:
                    failed.append(f)
            return infos, failed, len(files)

        self.probe_task = run_task(job, paths, on_done=self._on_probed,
                                   on_error=lambda tb: (self.home.set_loading(False), self.toast(tb.splitlines()[-1])))

    def _on_probed(self, res):
        infos, failed, total = res
        known = {os.path.normcase(q.path) for q in self.queue}
        new = [i for i in infos if os.path.normcase(i.path) not in known]
        self.queue.extend(new)
        self.home.set_loading(False)
        self.home.refresh()
        if total == 0:
            self.toast(tr("queue.none_found"))
        elif failed:
            self.toast(tr("queue.added", n=len(new)) + " · " + tr("queue.skipped", n=len(failed)))
        elif new:
            self.toast(tr("queue.added", n=len(new)))

    def remove_from_queue(self, path: str):
        self.queue = [q for q in self.queue if q.path != path]
        self.home.refresh()

    def clear_queue(self):
        self.queue = []
        self.home.refresh()

    # --------------------------------------------------------------- analysis
    def start_analysis(self, files: list[AudioInfo] | None = None, forensic: bool | None = None):
        files = list(files if files is not None else self.queue)
        if not files or self.busy:
            return
        models = self.enabled_models()
        if not models:
            QMessageBox.warning(self, APP_NAME, tr("error.no_models_enabled"))
            return
        forensic = self.settings.forensic if forensic is None else forensic
        thresholds = {m.id: self.settings.threshold(m) for m in models}
        self.progress.setup(models, len(files), forensic, self.device_name())
        self.task = run_task(engine.run_analysis, files, models, thresholds, self.settings.device, forensic,
                             aggregation=self.settings.aggregation,
                             on_progress=self.progress.on_event, on_done=self._on_analysis_done,
                             on_error=self._on_analysis_error, on_cancel=self._on_analysis_cancelled)
        self.show_page("progress")

    def cancel_analysis(self):
        if self.task is not None:
            self.task.cancel()
            self.progress.set_cancelling()

    def _finish_task(self):
        self.progress.stop()
        self.task = None

    def _on_analysis_done(self, results):
        self._finish_task()
        self.results = results
        self.selected = 0
        self.show_page("results")

    def _on_analysis_error(self, tb: str):
        self._finish_task()
        box = QMessageBox(QMessageBox.Icon.Critical, APP_NAME, tr("progress.failed"), parent=self)
        box.setDetailedText(tb)
        box.exec()
        self.show_page("home")

    def _on_analysis_cancelled(self):
        self._finish_task()
        self.toast(tr("progress.cancelled"))
        self.show_page("home")

    def reanalyze_forensic(self):
        files = [AudioInfo(r.path, r.name, r.duration, r.sample_rate, r.channels, r.format, r.size)
                 for r in self.results]
        self.settings.forensic = True
        self.settings.save()
        self.start_analysis(files, forensic=True)

    def new_analysis(self):
        self.results_page.cleanup()
        self.queue = []
        self.show_page("home")

    def go_start(self):
        """Header logo: back to the initial state (empty home, no results)."""
        if self.busy:
            self.toast(tr("header.busy"))
            return
        self.results_page.cleanup()
        self.queue = []
        self.results = []
        self.selected = 0
        self.show_page("home")

    # --------------------------------------------------------------- settings
    def set_theme(self, name: str):
        if name == self.settings.theme:
            return
        self.settings.theme = name
        self.settings.save()
        theme.set_theme(name)
        theme.apply(QApplication.instance())
        self.rebuild()

    def set_language(self, lang: str):
        if lang == self.settings.language:
            return
        self.settings.language = lang
        self.settings.save()
        i18n.set_language(lang)
        self.rebuild()

    def set_device(self, device: str):
        self.settings.device = device
        self.settings.save()
        self.header.refresh_chip()

    def set_aggregation(self, method: str):
        self.settings.aggregation = method
        self.settings.save()

    # ------------------------------------------------------------------ close
    def closeEvent(self, e):
        if self.busy:
            ans = QMessageBox.question(self, tr("confirm.quit_title"), tr("confirm.quit"))
            if ans != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.task.cancel()
            self.task.wait(30000)
        self.results_page.cleanup()
        e.accept()
