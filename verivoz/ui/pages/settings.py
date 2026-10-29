"""Settings page."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ... import APP_NAME, APP_VERSION
from ...core.downloads import fmt_bytes
from ...core.i18n import LANGUAGES, language, tr
from ...core.paths import PLUGINS_DIR
from .. import icons, theme
from ..widgets.common import (Card, ElidedLabel, ScrollPage, Segmented, ToggleSwitch, button, card_header,
                              icon_button, label, pill, separator)


def _setting_row(title: str, desc: str, control: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(label(title, "h3"))
    if desc:
        col.addWidget(label(desc, "muted", wrap=True))
    row.addLayout(col, 1)
    row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class ThresholdRow(QWidget):
    def __init__(self, win, model):
        super().__init__()
        self.win, self.model = win, model
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(14)
        name_col = QVBoxLayout()
        name_col.setSpacing(1)
        name_col.addWidget(label(model.name, "h3"))
        cal = win.settings.calibration.get(model.id)
        if cal:
            try:
                date = datetime.fromisoformat(cal["date"]).strftime("%d/%m/%Y")
            except (KeyError, ValueError):
                date = "?"
            name_col.addWidget(label(tr("settings.calibrated_on", date=date, eer=cal.get("eer", "?"),
                                        n_real=cal.get("n_real", "?"), n_fake=cal.get("n_fake", "?")), "caption"))
        top.addLayout(name_col, 2)
        value = win.settings.threshold(model)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 99)
        self.slider.setValue(round(value * 100))
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(self.slider, 3)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.01, 0.99)
        self.spin.setSingleStep(0.01)
        self.spin.setDecimals(2)
        self.spin.setValue(value)
        self.spin.setFixedWidth(76)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Zero-width arrows instead of NoButtons: with a stylesheet, NoButtons leaves
        # the inner text field 1 px wide and the number is not visible.
        self.spin.setStyleSheet("QDoubleSpinBox { padding: 0px 4px; font-weight: 600; }"
                                "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button "
                                "{ width: 0px; border: none; }")
        top.addWidget(self.spin)
        reset = icon_button("refresh", tr("settings.threshold_reset"))
        reset.clicked.connect(lambda: self.set_value(model.default_threshold))
        top.addWidget(reset)
        v.addLayout(top)
        self.slider.valueChanged.connect(lambda x: self.set_value(x / 100, from_slider=True))
        self.spin.valueChanged.connect(lambda x: self.set_value(x))
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(win.settings.save)

    def set_value(self, value: float, from_slider: bool = False):
        value = round(min(0.99, max(0.01, value)), 2)
        for w, v in ((self.slider, round(value * 100)), (self.spin, value)):
            if not (from_slider and w is self.slider):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        th = self.win.settings.thresholds
        if abs(value - self.model.default_threshold) < 1e-9:
            th.pop(self.model.id, None)
        else:
            th[self.model.id] = value
        self._save_timer.start()


class ModelManageRow(QWidget):
    def __init__(self, page, model):
        super().__init__()
        win = page.win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(14)
        usable = not model.errors  # a model still to download can be enabled/disabled
        checked = usable and win.settings.is_enabled(model)
        if checked and model.family:  # within a family only the version in use is shown as enabled
            active = {m.id for m in win.enabled_models()}
            family_active = any(m.family == model.family and m.id in active for m in win.models)
            checked = model.id in active or not family_active
        toggle = ToggleSwitch(checked)
        toggle.setEnabled(usable)
        toggle.toggled.connect(lambda on: page.set_model_enabled(model, on))
        lay.addWidget(toggle, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(model.name, "h3"))
        head.addWidget(label(f"v{model.version}", "caption"))
        head.addStretch(1)
        col.addLayout(head)
        desc = model.description(language())
        if desc:
            col.addWidget(label(desc, "muted", wrap=True))
        if model.hardware:
            from ..dialogs import specs_text

            col.addWidget(label(specs_text(model.hardware), "caption", wrap=True))
        col.addWidget(ElidedLabel(str(model.plugin_dir), "caption"))
        if model.license:
            col.addWidget(label(model.license, "caption", wrap=True))
        for err in model.errors:
            col.addWidget(label("✖ " + err, "danger", wrap=True))
        lay.addLayout(col, 1)
        if model.needs_download:
            status = pill(tr("settings.model_pending"), theme.c("warning"))
            act = button(tr("settings.download", size=fmt_bytes(model.pending_size)), "primary", "download", size="sm")
            act.clicked.connect(lambda: page.win.open_downloads(model.pending_downloads))
        else:
            status = pill(tr("settings.model_ok") if model.ok else tr("settings.model_error"),
                          theme.c("success") if model.ok else theme.c("danger"))
            act = button(tr("settings.validate"), None, "shield", size="sm")
            act.clicked.connect(lambda: page.validate_model(model))
        lay.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(act, 0, Qt.AlignmentFlag.AlignTop)


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Page")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.scroll: ScrollPage | None = None
        self._build()

    def refresh(self):
        pos = self.scroll.verticalScrollBar().value() if self.scroll else 0
        old = self.scroll
        self._build()
        if old is not None:
            self.v.removeWidget(old)
            old.hide()  # deleteLater is not immediate: without this it overlaps for a moment
            old.deleteLater()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))

    def _build(self):
        win, s = self.win, self.win.settings
        page = ScrollPage(max_width=900, spacing=18)
        self.scroll = page
        self.v.addWidget(page)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(tr("settings.title"), "display"))
        head.addWidget(label(tr("settings.subtitle"), "muted"))
        hw = QWidget()
        hw.setLayout(head)
        page.add(hw)

        # appearance + language
        card = Card(padding=22, spacing=14)
        card.add(card_header("palette", tr("settings.appearance")))
        seg = Segmented([("light", tr("theme.light")), ("dark", tr("theme.dark"))], s.theme)
        seg.changed.connect(win.set_theme)
        card.add_layout(_setting_row(tr("settings.theme"), tr("settings.theme_desc"), seg))
        card.add(separator())
        lang = Segmented(list(LANGUAGES.items()), s.language)
        lang.changed.connect(win.set_language)
        card.add_layout(_setting_row(tr("settings.language"), tr("settings.language_desc"), lang))
        page.add(card)

        # processing
        card = Card(padding=22, spacing=12)
        card.add(card_header("cpu", tr("settings.processing")))
        dev = Segmented([("auto", tr("device.auto")), ("cuda", tr("device.cuda")), ("cpu", tr("device.cpu"))], s.device)
        env = win.env
        if not env.get("cuda"):
            dev.set_enabled("cuda", False, tr("settings.gpu_missing", torch=env.get("torch") or "-"))
        dev.changed.connect(win.set_device)
        card.add_layout(_setting_row(tr("settings.device"), tr("settings.device_desc"), dev))
        if env.get("error"):
            info = tr("settings.torch_missing", err=env["error"])
        elif env.get("cuda"):
            info = tr("settings.gpu_found", name=env.get("gpu"), mem=f"{env.get('vram', 0) / 1024 ** 3:.0f}",
                      torch=env.get("torch"))
        else:
            info = tr("settings.gpu_missing", torch=env.get("torch"))
        card.add(label(info, "caption", wrap=True))
        card.add(separator())
        agg = Segmented([("sensitive", tr("agg.sensitive")), ("mean", tr("agg.mean")), ("max", tr("agg.max"))],
                        s.aggregation)
        agg.changed.connect(win.set_aggregation)
        card.add_layout(_setting_row(tr("settings.aggregation"), tr("settings.aggregation_desc"), agg))
        page.add(card)

        # decision threshold
        card = Card(padding=22, spacing=10)
        card.add(card_header("sliders", tr("settings.threshold"), tr("settings.threshold_desc")))
        warn = QHBoxLayout()
        warn.setSpacing(6)
        ic = label()
        ic.setPixmap(icons.pixmap("alert", theme.hexc("warning"), 16))
        warn.addWidget(ic)
        warn.addWidget(label(tr("settings.threshold_warn"), "warn"))
        warn.addStretch(1)
        card.add_layout(warn)
        ok_models = [m for m in win.models if m.ok]
        for m in ok_models:
            card.add(separator())
            card.add(ThresholdRow(win, m))
        btns = QHBoxLayout()
        btns.setSpacing(10)
        cal = button(tr("settings.calibrate"), "primary", "sliders")
        cal.clicked.connect(self.open_calibration)
        cal.setEnabled(bool(ok_models))
        btns.addWidget(cal)
        reset = button(tr("settings.threshold_reset_all"), "ghost", "refresh")
        reset.clicked.connect(self.reset_thresholds)
        btns.addWidget(reset)
        btns.addStretch(1)
        card.body.addSpacing(4)
        card.add_layout(btns)
        page.add(card)

        # installed models
        card = Card(padding=22, spacing=8)
        card.add(card_header("layers", tr("settings.models"), tr("settings.models_desc")))
        if any(m.family for m in win.models):
            card.add(label(tr("settings.family_note"), "caption", wrap=True))
        for m in win.models:
            card.add(separator())
            card.add(ModelManageRow(self, m))
        page.add(card)

        # add model
        card = Card(padding=22, spacing=12)
        card.add(card_header("plus", tr("settings.add_section"), tr("settings.add_model_desc")))
        tools = QHBoxLayout()
        tools.setSpacing(8)
        add_btn = button(tr("settings.add_model"), "primary", "plus")
        add_btn.clicked.connect(self.open_add_model)
        b1 = button(tr("settings.open_guide"), None, "book")
        b1.clicked.connect(self.open_guide)
        b2 = button(tr("settings.open_plugins"), None, "folder")
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(PLUGINS_DIR))))
        b3 = button(tr("settings.reload"), "ghost", "refresh")
        b3.clicked.connect(self.reload_models)
        for b in (add_btn, b1, b2, b3):
            tools.addWidget(b)
        tools.addStretch(1)
        card.add_layout(tools)
        page.add(card)

        # danger zone
        card = Card(name="DangerCard", padding=22, spacing=12)
        card.add(card_header("alert", tr("settings.danger"), tr("settings.danger_desc"), danger=True))
        rm_btn = button(tr("settings.remove_model"), "danger", "trash")
        rm_btn.clicked.connect(self.open_remove_model)
        card.add(separator())
        card.add_layout(_setting_row(tr("settings.remove_model").rstrip("…"), tr("settings.remove_model_desc"), rm_btn))
        page.add(card)

        about = label(tr("settings.about", app=APP_NAME, version=APP_VERSION), "caption", wrap=True)
        about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.add(about)
        page.add_stretch()

    # ----------------------------------------------------------------- actions
    def set_model_enabled(self, model, on: bool):
        if on:
            changed = self.win.activate_model(model)
        else:
            changed = False
            if model.id not in self.win.settings.disabled_models:
                self.win.settings.disabled_models.append(model.id)
            self.win.settings.save()
        if changed:
            QTimer.singleShot(0, self.refresh)

    def reset_thresholds(self):
        self.win.settings.thresholds.clear()
        self.win.settings.calibration.clear()
        self.win.settings.save()
        self.refresh()

    def reload_models(self):
        self.win.reload_models()
        self.refresh()
        self.win.toast(tr("settings.reloaded", n=len(self.win.models)))

    def open_calibration(self):
        from ..dialogs import CalibrationDialog

        if CalibrationDialog(self.win, self).exec():
            self.refresh()

    def open_guide(self):
        from ..dialogs import GuideDialog

        GuideDialog(self.win).exec()

    def open_add_model(self):
        from ..dialogs import AddModelDialog

        AddModelDialog(self.win, self).exec()
        self.win.reload_models()
        self.refresh()

    def open_remove_model(self):
        from ..dialogs import RemoveModelDialog

        if RemoveModelDialog(self.win, self).exec():
            self.refresh()

    def validate_model(self, model):
        from ..dialogs import ValidationDialog

        ValidationDialog(self.win, model, self).exec()
        self.win.reload_models()
        self.refresh()
