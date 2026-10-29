"""Project paths."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = ROOT / "plugins"
TEMPLATE_DIR = PLUGINS_DIR / "_template"
USER_DIR = ROOT / "user_data"
TRASH_DIR = USER_DIR / "deleted"
CACHE_DIR = USER_DIR / ".cache"
SETTINGS_FILE = USER_DIR / "settings.json"
DOCS_DIR = ROOT / "docs"
GUIDE_FILE = DOCS_DIR / "ADDING_MODELS.md"
