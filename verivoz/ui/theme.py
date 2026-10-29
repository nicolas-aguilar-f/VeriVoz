"""Blue/white palettes (light and dark), stylesheet and score color scale."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from ..core.paths import CACHE_DIR

PALETTES = {
    "light": {
        "bg": "#F3F6FB", "surface": "#FFFFFF", "surface_alt": "#F0F4FB", "surface_hover": "#E9F0FD",
        "border": "#DDE5F2", "border_strong": "#C3D0E6",
        "text": "#0E1B36", "text_muted": "#566684", "text_faint": "#8894AE",
        "primary": "#1D5BEA", "primary_hover": "#174DCB", "primary_pressed": "#123FA8",
        "primary_soft": "#E5EDFF", "primary_text": "#FFFFFF",
        "header_bg": "#1747C9", "header_bg2": "#2F74FF", "header_text": "#FFFFFF",
        "accent_a": "#1747C9", "accent_b": "#2F74FF",
        "danger": "#D33A3A", "danger_soft": "#FDEEEE", "danger_border": "#F2B9B9",
        "success": "#169A4E", "warning": "#B67C00",
        "track": "#E5EBF5", "shadow": "#1D3A7A", "wave_muted": "#B7C4DD",
    },
    "dark": {
        "bg": "#0A1120", "surface": "#101A2E", "surface_alt": "#15213A", "surface_hover": "#1A2947",
        "border": "#1F2D4A", "border_strong": "#2C3E64",
        "text": "#E7EEFC", "text_muted": "#97A7C7", "text_faint": "#66789E",
        "primary": "#3D7BFF", "primary_hover": "#5A8FFF", "primary_pressed": "#2D64D8",
        "primary_soft": "#172A50", "primary_text": "#FFFFFF",
        "header_bg": "#0D1A38", "header_bg2": "#16306B", "header_text": "#FFFFFF",
        "accent_a": "#2D64D8", "accent_b": "#6A9BFF",
        "danger": "#F05A5A", "danger_soft": "#2A1419", "danger_border": "#5E2630",
        "success": "#38C875", "warning": "#E6AA2A",
        "track": "#1B2843", "shadow": "#000000", "wave_muted": "#30436B",
    },
}

_state = {"name": "light"}


def set_theme(name: str) -> None:
    _state["name"] = name if name in PALETTES else "light"


def name() -> str:
    return _state["name"]


def is_dark() -> bool:
    return _state["name"] == "dark"


def hexc(key: str) -> str:
    return PALETTES[_state["name"]][key]


def c(key: str, alpha: float | None = None) -> QColor:
    col = QColor(hexc(key))
    if alpha is not None:
        col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


# ------------------------------------------------ green-yellow-red scale
GREEN = (22, 163, 74)
YELLOW = (234, 179, 8)
RED = (220, 38, 38)
YELLOW_AT, RED_AT = 45.0, 90.0


def score_rgb(score: float) -> tuple[int, int, int]:
    """Green (0) -> yellow (45) -> red (90-100), interpolated linearly."""
    s = max(0.0, min(100.0, float(score)))
    if s >= RED_AT:
        return RED
    a, b, t = (GREEN, YELLOW, s / YELLOW_AT) if s <= YELLOW_AT else (YELLOW, RED, (s - YELLOW_AT) / (RED_AT - YELLOW_AT))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def score_color(score: float, alpha: float = 1.0) -> QColor:
    r, g, b = score_rgb(score)
    col = QColor(r, g, b)
    col.setAlphaF(alpha)
    return col


def score_text_color(score: float) -> QColor:
    """Higher-contrast variant for text (darker in light mode, lighter in dark mode)."""
    r, g, b = score_rgb(score)
    if is_dark():
        k = 0.25
        return QColor(round(r + (255 - r) * k), round(g + (255 - g) * k), round(b + (255 - b) * k))
    k = 0.22
    return QColor(round(r * (1 - k)), round(g * (1 - k)), round(b * (1 - k)))


def rgba(col: QColor, alpha: float) -> str:
    return f"rgba({col.red()},{col.green()},{col.blue()},{alpha:.3f})"


def pill_style(col: QColor, text: QColor | None = None) -> str:
    text = text or col
    return (f"background:{rgba(col, 0.13)}; color:{text.name()}; border:1px solid {rgba(col, 0.35)};"
            f"border-radius:11px; padding:3px 10px; font-weight:600; font-size:12px;")


# -------------------------------------------------------------------- QSS
def palette() -> QPalette:
    """Base palette for what the stylesheet does not cover (system dialogs, menus...)."""
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg", QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface", QPalette.ColorRole.AlternateBase: "surface_alt",
        QPalette.ColorRole.Text: "text", QPalette.ColorRole.Button: "surface",
        QPalette.ColorRole.ButtonText: "text", QPalette.ColorRole.Highlight: "primary",
        QPalette.ColorRole.ToolTipBase: "surface", QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.PlaceholderText: "text_faint", QPalette.ColorRole.Link: "primary",
    }
    for role, key in roles.items():
        pal.setColor(role, c(key))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return pal


def apply(app) -> None:
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())


def _check_icon() -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "check.svg"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" '
           'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>')
    try:
        if not path.exists() or path.read_text() != svg:
            path.write_text(svg)
    except OSError:
        return ""
    return path.as_posix()


def stylesheet() -> str:
    p = PALETTES[_state["name"]]
    check = _check_icon()
    check_rule = f'image: url("{check}");' if check else ""
    return f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable Text", Arial, sans-serif; }}
QWidget#Root, QWidget#Page, QDialog {{ background: {p['bg']}; color: {p['text']}; }}
QWidget#ScrollContent, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QLabel {{ color: {p['text']}; background: transparent; }}
QLabel[role="display"] {{ font-size: 28px; font-weight: 700; }}
QLabel[role="title"] {{ font-size: 21px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="body"] {{ font-size: 13px; }}
QLabel[role="muted"] {{ color: {p['text_muted']}; font-size: 13px; }}
QLabel[role="caption"] {{ color: {p['text_faint']}; font-size: 12px; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; color: {p['text_muted']}; }}
QLabel[role="danger"] {{ color: {p['danger']}; font-size: 13px; }}
QLabel[role="warn"] {{ color: {p['warning']}; font-size: 12px; font-weight: 600; }}
QLabel[role="metakey"] {{ color: {p['text_faint']}; font-size: 12px; }}
QLabel[role="metaval"] {{ color: {p['text']}; font-size: 13px; }}

QFrame#Card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QFrame#SoftCard {{ background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#DangerCard {{ background: {p['surface']}; border: 1px solid {p['danger_border']}; border-radius: 14px; }}
QFrame#Separator {{ background: {p['border']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame#Row {{ background: transparent; border: none; border-radius: 10px; }}
QFrame#Row:hover {{ background: {p['surface_alt']}; }}
QFrame#IconBadge {{ background: {p['primary_soft']}; border: none; border-radius: 10px; }}
QFrame#Banner {{ background: {p['primary_soft']}; border: none; border-radius: 10px; }}

QFrame#Header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['header_bg']}, stop:1 {p['header_bg2']});
                 border: none; }}
QLabel#HeaderTitle {{ color: {p['header_text']}; font-size: 19px; font-weight: 700; }}
QLabel#HeaderSubtitle {{ color: rgba(255,255,255,0.78); font-size: 12px; }}
QLabel#HeaderChip {{ color: {p['header_text']}; background: rgba(255,255,255,0.14);
                     border: 1px solid rgba(255,255,255,0.24); border-radius: 12px; padding: 3px 11px; font-size: 12px; }}
QToolButton#HeaderButton {{ background: transparent; border: none; border-radius: 10px; padding: 7px; color: white; }}
QToolButton#HeaderButton:hover {{ background: rgba(255,255,255,0.16); }}
QToolButton#HeaderButton:pressed {{ background: rgba(255,255,255,0.28); }}

QPushButton {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
               border-radius: 9px; padding: 8px 16px; font-size: 13px; font-weight: 600; }}
QPushButton:hover {{ background: {p['surface_hover']}; border-color: {p['primary']}; }}
QPushButton:pressed {{ background: {p['primary_soft']}; }}
QPushButton:disabled {{ color: {p['text_faint']}; border-color: {p['border']}; background: {p['surface_alt']}; }}
QPushButton[variant="primary"] {{ background: {p['primary']}; color: {p['primary_text']}; border: 1px solid {p['primary']}; }}
QPushButton[variant="primary"]:hover {{ background: {p['primary_hover']}; border-color: {p['primary_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {p['primary_pressed']}; }}
QPushButton[variant="primary"]:disabled {{ background: {p['track']}; border-color: {p['track']}; color: {p['text_faint']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {p['primary']}; padding: 6px 10px; }}
QPushButton[variant="ghost"]:hover {{ background: {p['primary_soft']}; }}
QPushButton[variant="ghost"]:disabled {{ color: {p['text_faint']}; background: transparent; }}
QPushButton[variant="danger"] {{ background: transparent; color: {p['danger']}; border: 1px solid {p['danger_border']}; }}
QPushButton[variant="danger"]:hover {{ background: {p['danger_soft']}; border-color: {p['danger']}; }}
QPushButton[variant="danger-solid"] {{ background: {p['danger']}; color: white; border: 1px solid {p['danger']}; }}
QPushButton[variant="danger-solid"]:hover {{ background: {p['danger']}; border-color: {p['text']}; }}
QPushButton[variant="danger-solid"]:disabled {{ background: {p['track']}; border-color: {p['track']}; color: {p['text_faint']}; }}
QPushButton[size="lg"] {{ padding: 12px 30px; font-size: 15px; border-radius: 11px; }}
QPushButton[size="sm"] {{ padding: 5px 11px; font-size: 12px; border-radius: 7px; }}
QToolButton#IconButton {{ background: transparent; border: none; border-radius: 8px; padding: 5px; }}
QToolButton#IconButton:hover {{ background: {p['surface_hover']}; }}

QFrame#Segmented {{ background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QPushButton#SegButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
                         padding: 6px 16px; color: {p['text_muted']}; font-weight: 600; }}
QPushButton#SegButton:hover {{ color: {p['text']}; background: transparent; border-color: transparent; }}
QPushButton#SegButton:checked {{ background: {p['surface']}; color: {p['primary']}; border: 1px solid {p['border']}; }}
QPushButton#SegButton:disabled {{ color: {p['text_faint']}; background: transparent; border-color: transparent; }}

QProgressBar {{ background: {p['track']}; border: none; border-radius: 5px; min-height: 10px; max-height: 10px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent_a']}, stop:1 {p['accent_b']}); }}

QSlider::groove:horizontal {{ height: 6px; background: {p['track']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p['primary']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {p['surface']}; border: 2px solid {p['primary']};
                              width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: {p['primary_soft']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{
    background: {p['surface']}; border: 1px solid {p['border_strong']}; border-radius: 8px; padding: 6px 9px;
    color: {p['text']}; selection-background-color: {p['primary']}; selection-color: white; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 22px; }}
QAbstractSpinBox QLineEdit, QComboBox QLineEdit {{ background: transparent; border: none; padding: 0px;
    margin: 0px; min-height: 0px; }}
QTextBrowser#Guide {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px;
    padding: 8px 14px; font-size: 14px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p['primary']}; }}
QLineEdit:disabled {{ color: {p['text_faint']}; background: {p['surface_alt']}; }}
QPlainTextEdit#Log {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; background: {p['surface_alt']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    selection-background-color: {p['primary_soft']}; selection-color: {p['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}

QListWidget {{ background: transparent; border: none; outline: none; color: {p['text']}; }}
QListWidget#FileList::item {{ border-radius: 10px; margin: 2px 0px; padding: 0px; }}
QListWidget#FileList::item:selected {{ background: {p['primary_soft']}; }}
QListWidget#FileList::item:hover:!selected {{ background: {p['surface_alt']}; }}
QListWidget#DropList {{ background: {p['surface_alt']}; border: 1px dashed {p['border_strong']}; border-radius: 10px; padding: 4px; }}
QListWidget#DropList::item {{ padding: 3px 6px; border-radius: 6px; }}
QListWidget#DropList::item:selected {{ background: {p['primary_soft']}; color: {p['text']}; }}

QTableWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
                gridline-color: {p['border']}; color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface_alt']}; color: {p['text_muted']}; border: none;
                        border-bottom: 1px solid {p['border']}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p['surface_alt']}; border: none; }}

QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background: {p['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p['text_muted']}; padding: 9px 18px; border: none;
                border-bottom: 2px solid transparent; font-weight: 600; font-size: 13px; }}
QTabBar::tab:selected {{ color: {p['primary']}; border-bottom: 2px solid {p['primary']}; }}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

QCheckBox {{ color: {p['text']}; spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px; border: 1.5px solid {p['border_strong']};
                        background: {p['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {p['primary']}; }}
QCheckBox::indicator:checked {{ background: {p['primary']}; border-color: {p['primary']}; {check_rule} }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border_strong']}; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p['text_faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border_strong']}; border-radius: 4px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
            border-radius: 6px; padding: 6px 8px; font-size: 12px; }}
QMessageBox {{ background: {p['bg']}; }}
QMessageBox QLabel {{ color: {p['text']}; font-size: 13px; }}
QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item:selected {{ background: {p['primary_soft']}; }}
QLabel#Toast {{ background: rgba(14,27,54,0.94); color: white; border-radius: 10px; padding: 10px 16px; font-size: 13px; }}
"""
