"""Validates a model plugin (same as the "Validate" button in Settings).

Usage:
    .venv\\Scripts\\python tools\\validate_model.py <id or folder> [--audio file.wav] [--device auto|cuda|cpu] [--quick]

Checks, in order:
  1. manifest.json (required keys, types, 'files' paths)
  2. that detector.py imports and its class inherits from BaseDetector and implements load() and predict()
  3. (unless --quick) that load() works on the chosen device
  4. that predict() returns a valid probability with 0.5 s, 3 s and 6 s test signals
  5. that predict_batch() is consistent with predict()
  6. (with --audio) the full score of a real audio file, exactly as in the interface
Exits with code 0 if everything is correct and 1 if something fails.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verivoz.core import engine, validation  # noqa: E402
from verivoz.core.paths import PLUGINS_DIR  # noqa: E402

COLORS = {"ok": "\033[32m✔", "warn": "\033[33m⚠", "fail": "\033[31m✖", "info": "\033[90m·"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin", help="model id (folder inside plugins/) or path to the plugin folder")
    ap.add_argument("--audio", help="real audio file to test the full score")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--quick", action="store_true", help="static checks only (does not load the model)")
    args = ap.parse_args()

    target = Path(args.plugin)
    if not target.is_dir():
        target = PLUGINS_DIR / args.plugin
    if not target.is_dir():
        print(f"✖ Plugin '{args.plugin}' not found (neither as a path nor in {PLUGINS_DIR})")
        return 1
    if os.name == "nt":
        os.system("")  # enables ANSI colors in the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    device = engine.resolve_device(args.device)

    def log(level: str, msg: str):
        print(f"{COLORS.get(level, '·')} {msg}\033[0m")

    ok = validation.validate(target, device=device, deep=not args.quick, audio_path=args.audio, log=log)
    print()
    print("\033[32m✔ VALID: you can now enable it in Settings › Installed models.\033[0m" if ok
          else "\033[31m✖ NOT VALID: fix the errors marked with ✖ and validate again.\033[0m")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
