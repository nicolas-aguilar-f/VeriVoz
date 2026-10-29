"""Application startup: splash screen -> main window."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from ..core import i18n, registry
from ..core.settings import Settings
from . import icons, theme
from .main_window import MainWindow
from .splash import SplashScreen
from .workers import run_task

MIN_SPLASH_SECONDS = 2.2


def startup(report, cancel) -> tuple[dict, list]:
    """Runs in the background while the loading wave is shown."""
    env = {"torch": None, "cuda": False, "gpu": None, "vram": 0, "error": None}
    report(i18n.tr("splash.loading_engine"))
    try:
        import torch

        env["torch"] = torch.__version__.split("+")[0]
        env["cuda"] = bool(torch.cuda.is_available())
        if env["cuda"]:
            env["gpu"] = torch.cuda.get_device_name(0)
            env["vram"] = torch.cuda.get_device_properties(0).total_memory
    except Exception as e:  # the interface still works and reports it in Settings
        env["error"] = f"{type(e).__name__}: {e}"
    report(i18n.tr("splash.loading_libs"))
    try:
        import transformers  # noqa: F401  (preload: speeds up the first analysis)
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
    except Exception:
        pass
    report(i18n.tr("splash.scanning_models"))
    models = registry.discover()
    report(i18n.tr("splash.preparing_ui"))
    return env, models


def run() -> int:
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.App")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # The native "windows11" style ignores part of the stylesheet (e.g. QSpinBox text
    # disappears). Fusion honors the QSS and looks the same on every system.
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(icons.app_icon())

    settings = Settings.load()
    i18n.set_language(settings.language)
    theme.set_theme(settings.theme)
    theme.apply(app)

    splash = SplashScreen()
    splash.show()
    app.processEvents()
    state: dict = {"t0": time.monotonic()}

    def show_main(env, models):
        win = MainWindow(settings, env, models)
        state["win"] = win
        win.show()
        splash.close()

    def on_done(result):
        env, models = result
        wait = max(0.0, MIN_SPLASH_SECONDS - (time.monotonic() - state["t0"]))
        QTimer.singleShot(int(wait * 1000), lambda: show_main(env, models))

    def on_error(tb: str):
        print(tb, file=sys.stderr)
        on_done(({"torch": None, "cuda": False, "gpu": None, "vram": 0, "error": tb.strip().splitlines()[-1]},
                 registry.discover()))

    state["task"] = run_task(startup, on_progress=splash.set_status, on_done=on_done, on_error=on_error)
    return app.exec()
