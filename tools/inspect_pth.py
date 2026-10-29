"""Inspects a weights file and explains what it contains and how to load it in VeriVoz.

Usage:
    .venv\\Scripts\\python tools\\inspect_pth.py path\\to\\model.pth [--all]

Detects whether the file is TorchScript, a whole model or a state_dict (possibly
inside a dictionary with more data), lists the layers with their shapes and
infers the input of the first layer and the number of output classes.

WARNING: .pth files that are not TorchScript are opened with pickle
(weights_only=False), which can execute code. Only use it with trusted files.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _layer_kind(shape) -> str:
    if len(shape) == 2:
        return f"Linear(in={shape[1]}, out={shape[0]})"
    if len(shape) == 3:
        return f"Conv1d(in={shape[1]}, out={shape[0]}, kernel={shape[2]})"
    if len(shape) == 4:
        return f"Conv2d(in={shape[1]}, out={shape[0]}, kernel={shape[2]}x{shape[3]})"
    return f"tensor{tuple(shape)}"


def describe_state(state: dict, show_all: bool) -> None:
    tensors = {k: v for k, v in state.items() if hasattr(v, "shape")}
    n_params = sum(int(v.numel()) for v in tensors.values() if hasattr(v, "numel"))
    print(f"  {len(tensors)} tensors · {n_params:,} parameters")
    roots = Counter(k.split(".")[0] for k in tensors)
    print("  Top-level blocks: " + ", ".join(f"{k} ({n})" for k, n in roots.most_common()))
    if any(k.startswith("module.") for k in tensors):
        print("  ⚠ Keys start with 'module.' (trained with DataParallel). The template already strips it.")
    limit = None if show_all else 40
    items = list(tensors.items())
    print("\n  Layers (name · shape · dtype):")
    for k, v in items[:limit]:
        print(f"    {k:<64} {str(tuple(v.shape)):<22} {str(v.dtype).replace('torch.', '')}")
    if limit and len(items) > limit:
        print(f"    … {len(items) - limit} more (use --all to see them)")

    weights = [(k, v) for k, v in items if k.endswith("weight") and getattr(v, "ndim", 0) >= 2]
    if weights:
        k0, v0 = weights[0]
        k1, v1 = weights[-1]
        print("\n  Inferences:")
        print(f"    · First layer with weights: {k0} -> {_layer_kind(tuple(v0.shape))}")
        print(f"    · Last layer with weights:  {k1} -> {_layer_kind(tuple(v1.shape))}")
        n_out = int(v1.shape[0])
        if n_out == 1:
            print("    · Single output value: use OUTPUT = 'sigmoid' in detector.py "
                  "(and INVERT = True if that value means 'real').")
        elif n_out == 2:
            print("    · Two output classes: use OUTPUT = 'softmax' and set FAKE_INDEX "
                  "(1 if you trained 0=real/1=fake; 0 for the ASVspoof convention 0=spoof/1=bonafide).")
        else:
            print(f"    · {n_out} output values: check which index means 'fake'.")
        if len(v0.shape) == 2 and int(v0.shape[1]) > 1:
            print(f"    · The network expects a VECTOR of {int(v0.shape[1])} features, not the waveform: you will "
                  "have to compute them in preprocess() (embeddings, MFCC, statistics...).")
        elif len(v0.shape) == 3 and int(v0.shape[1]) == 1:
            print("    · The first layer is a 1-channel Conv1d: it probably takes the raw waveform "
                  "(batch, 1, samples). Add .unsqueeze(1) in preprocess/forward if needed.")
        elif len(v0.shape) == 4:
            print("    · The first layer is a Conv2d: it probably takes a spectrogram (batch, 1, freq, time).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help=".pth / .pt / .ckpt / .bin / .safetensors file")
    ap.add_argument("--all", action="store_true", help="show every layer")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    path = Path(args.path)
    if not path.is_file():
        print(f"Not found: {path}")
        return 1
    import torch
    import torch.nn as nn

    print(f"File: {path}  ({path.stat().st_size / 1e6:.1f} MB)\n")
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        print("Format: safetensors (plain state_dict)")
        describe_state(load_file(str(path)), args.all)
        print("\n→ Load it in load(): from safetensors.torch import load_file; "
              "self.model.load_state_dict(load_file(self.file('checkpoint')))")
        return 0
    try:
        m = torch.jit.load(str(path), map_location="cpu")
        print("Format: TorchScript ✔  (no need to define the architecture; the template loads it as is)")
        describe_state(m.state_dict(), args.all)
        return 0
    except Exception:
        pass
    obj = torch.load(str(path), map_location="cpu", weights_only=False)
    if isinstance(obj, nn.Module):
        print(f"Format: whole model saved with torch.save(model) · class {type(obj).__module__}.{type(obj).__name__}")
        print("  The template loads it as is, but the class must be importable under the same module "
              "name used when saving. If that fails, save only the state_dict.")
        describe_state(obj.state_dict(), args.all)
        return 0
    if not isinstance(obj, dict):
        print(f"Unknown format: {type(obj)}")
        return 1
    if all(hasattr(v, "shape") for v in obj.values()):
        print("Format: state_dict (layer -> tensor dictionary) ✔  · you need the nn.Module class in detector.py")
        describe_state(obj, args.all)
        return 0
    print("Format: dictionary with several entries (checkpoint):")
    nested = None
    for k, v in obj.items():
        kind = type(v).__name__
        extra = ""
        if hasattr(v, "shape"):
            extra = f" shape={tuple(v.shape)}"
        elif isinstance(v, (int, float, str, bool)):
            extra = f" = {v!r}"[:80]
        elif isinstance(v, dict):
            n_t = sum(1 for x in v.values() if hasattr(x, "shape"))
            extra = f" ({len(v)} keys, {n_t} tensors)"
            if n_t and nested is None:
                nested = k
        print(f"  · {k!r}: {kind}{extra}")
    if nested:
        print(f"\nModel weights inside the {nested!r} key:")
        describe_state(obj[nested], args.all)
        others = [k for k in obj if k != nested]
        if others:
            print(f"\n  ⚠ There is also {others}: if they are normalization statistics, thresholds, etc., use "
                  "them in load()/preprocess() (example: plugins/xlsr_mlp/detector.py uses 'media' and 'desv').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
