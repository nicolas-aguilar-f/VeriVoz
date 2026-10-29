"""VeriVoz installer.

    python install.py [--plan] [--yes] [--cpu] [--no-models] [--accept-licenses]

Before changing anything it shows WHAT will be installed, FROM WHERE, its size
and its license, and asks for confirmation. Then it:
  1. creates the .venv virtual environment (for this folder only);
  2. installs PyTorch (with CUDA if there is an NVIDIA GPU) from download.pytorch.org;
  3. installs the other dependencies (requirements.txt) from pypi.org;
  4. downloads the models from their official sources (Hugging Face, GitHub) and
     checks their SHA-256.
It can be run again: it only does what is missing. Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TORCH_VERSION = "2.11.0"
TORCH_INDEX = "https://download.pytorch.org/whl/{variant}"
# Approximate download sizes (GB) shown to the user
TORCH_SIZE = {"cu128": 3.0, "cu126": 2.8, "cpu": 0.25}
DEPS_SIZE = 0.6
REQUIRED_IMPORTS = "import torch, PySide6, transformers, einops, numpy, scipy, soundfile, av"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from verivoz.core import downloads as dl  # noqa: E402  (standard library only)
import download_models as dm  # noqa: E402


def out(text: str = "") -> None:
    print(text, flush=True)


def detect_gpu() -> tuple[str, int] | None:
    """(name, major driver version) of the NVIDIA GPU, or None. Only used to pick the PyTorch build."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    name, _, driver = r.stdout.strip().splitlines()[0].partition(",")
    m = re.match(r"\s*(\d+)", driver)
    return name.strip(), int(m.group(1)) if m else 0


def choose_torch(gpu, force_cpu: bool) -> tuple[str, str]:
    if force_cpu:
        return "cpu", "CPU build (forced with --cpu)"
    if gpu is None:
        return "cpu", "no NVIDIA GPU detected: CPU build (analyses will be slower)"
    name, driver = gpu
    if driver >= 570:
        return "cu128", f"GPU {name} (driver {driver}): CUDA 12.8 build"
    if driver >= 528:
        return "cu126", f"GPU {name} (driver {driver}): CUDA 12.6 build"
    return "cpu", (f"GPU {name} with driver {driver}, too old for CUDA 12: CPU build. "
                   "Update the NVIDIA driver and run the installer again to use the GPU")


def env_status() -> str:
    """'ok' if the environment is complete, 'partial' if it exists but lacks packages, 'missing'."""
    if not VPY.exists():
        return "missing"
    r = subprocess.run([str(VPY), "-c", REQUIRED_IMPORTS], capture_output=True)
    return "ok" if r.returncode == 0 else "partial"


def run(cmd: list[str]) -> None:
    out("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="only show what would be done, without changing anything")
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask for general confirmation")
    ap.add_argument("--cpu", action="store_true", help="install the CPU build of PyTorch even if there is a GPU")
    ap.add_argument("--no-models", action="store_true", help="do not download models (you can get them from the app)")
    ap.add_argument("--accept-licenses", action="store_true",
                    help="also accept the licenses that require explicit acceptance (DF-Arena: non-commercial)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    out("=" * 72)
    out(" VeriVoz · installation")
    out("=" * 72)
    v = sys.version_info
    if not ((3, 10) <= (v.major, v.minor) <= (3, 13)):
        out(f"✖ Python {v.major}.{v.minor} is not supported. Install Python 3.11 (or 3.10-3.13) from "
            "https://www.python.org/downloads/ and run install.bat again.")
        return 1

    gpu = detect_gpu()
    variant, why = choose_torch(gpu, args.cpu)
    status = env_status()
    items = [] if args.no_models else dm.drop_installed_families(dl.scan())
    total_gb = 0.0

    out("\nThis is what will be done:\n")
    out("STEP 1 · Python environment")
    if status == "ok":
        out("  ✔ Already installed in .venv (nothing to download).")
    else:
        out(f"  • Virtual environment in {VENV}  (only affects this folder; your system Python is untouched)")
        out(f"  • PyTorch {TORCH_VERSION} — {why}")
        out(f"      Source: {TORCH_INDEX.format(variant=variant)}  ·  ≈ {TORCH_SIZE[variant]:.1f} GB")
        out("  • Dependencies from requirements.txt: PySide6 (interface), transformers, einops, numpy, scipy, "
            "soundfile, PyAV")
        out(f"      Source: https://pypi.org  ·  ≈ {DEPS_SIZE:.1f} GB")
        total_gb += TORCH_SIZE[variant] + DEPS_SIZE

    out("\nSTEP 2 · Models")
    if args.no_models:
        out("  • Skipped (--no-models). You can download them from the app.")
    elif not items:
        out("  ✔ All models are already downloaded.")
    else:
        dm.print_plan(items)

    if args.plan:
        out("\n(--plan: nothing was changed)")
        return 0
    items = dm.choose_variants(items, interactive=not args.yes)
    total_gb += sum(it.missing_size for it in items) / 1e9
    free = dl.disk_free(ROOT) / 1e9
    out(f"\nApproximate total download: {total_gb:.1f} GB · free space: {free:.0f} GB")
    if total_gb == 0:
        out("\n✔ Nothing to install. Run run.bat to open VeriVoz.")
        return 0
    if free < total_gb * 1.3 + 1:
        out("✖ Not enough disk space.")
        return 1
    if not args.yes and not dm.ask("\nContinue with the installation?", default=True):
        out("Cancelled. Nothing was installed.")
        return 1
    items = dm.accept_licenses(items, args.accept_licenses)

    try:
        if status != "ok":
            out("\n── STEP 1 · Python environment " + "─" * 40)
            if status == "missing":
                run([sys.executable, "-m", "venv", str(VENV)])
            run([str(VPY), "-m", "pip", "install", "--upgrade", "pip"])
            run([str(VPY), "-m", "pip", "install", f"torch=={TORCH_VERSION}",
                 "--index-url", TORCH_INDEX.format(variant=variant)])
            run([str(VPY), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
            r = subprocess.run([str(VPY), "-c", "import torch; print(torch.cuda.is_available())"],
                               capture_output=True, text=True)
            gpu_ok = r.stdout.strip() == "True"
            out(f"  ✔ Environment ready · GPU {'available' if gpu_ok else 'not available (the CPU will be used)'}")
    except subprocess.CalledProcessError as e:
        out(f"\n✖ Failed: {' '.join(e.cmd)}")
        out("  Check your connection and run install.bat again (it will continue where it stopped).")
        return 1

    if items:
        out("\n── STEP 2 · Models " + "─" * 52)
        if not dm.run(items):
            return 1

    out("\n" + "=" * 72)
    out(" ✔ Installation finished. Run run.bat to open VeriVoz.")
    if dm.drop_installed_families(dl.scan()):
        out("   (Some models were not downloaded; the app will offer to download them.)")
    out("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out("\nInterrupted. Run install.bat again: it will continue where it stopped.")
        sys.exit(1)
