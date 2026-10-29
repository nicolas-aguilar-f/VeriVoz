"""Creates a model plugin from the template (same as Settings › Add model).

Usage:
    .venv\\Scripts\\python tools\\create_model.py --name "My model" --pth C:\\path\\model.pth
        [--id my_model] [--sr 16000] [--window 4] [--description "..."] [--no-copy]

Generates plugins/<id>/ with manifest.json, detector.py and weights/<your .pth>.
The model stays DISABLED until you validate it and enable it in Settings.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verivoz.core import registry  # noqa: E402
from verivoz.core.settings import Settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="name shown in the interface")
    ap.add_argument("--pth", required=True, help="weights file (.pth, .pt, .ckpt, .bin, .safetensors)")
    ap.add_argument("--id", help="identifier (lowercase, digits, _ or -). Derived from the name by default")
    ap.add_argument("--sr", type=int, default=16000, help="sample rate the model expects (Hz)")
    ap.add_argument("--window", type=float, default=4.0, help="seconds of audio per analysis window")
    ap.add_argument("--description", default="", help="short description")
    ap.add_argument("--author", default="")
    ap.add_argument("--no-copy", action="store_true", help="reference the .pth where it is instead of copying it")
    args = ap.parse_args()

    weights = Path(args.pth)
    if not weights.is_file():
        print(f"✖ The weights file does not exist: {weights}")
        return 1
    model_id = args.id or registry.slugify(args.name)
    try:
        info = registry.scaffold_plugin(args.name, model_id, weights, args.sr, args.window,
                                        args.description, args.author, copy_weights=not args.no_copy)
    except Exception as e:
        print(f"✖ {e}")
        return 1
    s = Settings.load()
    if info.id not in s.disabled_models:
        s.disabled_models.append(info.id)
        s.save()
    print(f"✔ Plugin created in {info.plugin_dir}")
    print(f"""
Next steps:
  1. Inspect your weights:   .venv\\Scripts\\python tools\\inspect_pth.py "{weights}"
  2. Edit {info.plugin_dir / 'detector.py'}
       - paste your architecture into the MyNet class
       - adjust FAKE_INDEX / OUTPUT / INVERT and preprocess()
  3. Validate:               .venv\\Scripts\\python tools\\validate_model.py {info.id} --audio some_audio.wav
  4. Open VeriVoz › Settings › Installed models and enable it.
Full guide: docs\\ADDING_MODELS.md""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
