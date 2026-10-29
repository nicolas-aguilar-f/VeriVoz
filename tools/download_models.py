"""Downloads the model files (same as the app's "Download models" dialog).

Usage:
    python tools\\download_models.py [--yes] [--accept-licenses] [--models df_arena_1b,xlsr_mlp] [--list]

Before downloading it shows what will be fetched, from where, its size, its
license and the approximate specs of each model, and asks for confirmation.
If a model has several versions (DF-Arena 1B / 500M) it asks which one you want.
Models with a restrictive license (DF-Arena's non-commercial one) must be
accepted explicitly.
Downloads resume if interrupted and are verified with SHA-256.
Standard library only: works with any Python 3.10+.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verivoz.core import downloads as dl  # noqa: E402


def _out(text: str = "") -> None:
    print(text, flush=True)


def ask(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{question} {suffix} ").strip().lower().lstrip("\ufeff")
    except EOFError:
        return False  # no answer (closed input) is never taken as consent
    if not ans:
        return default
    return ans in ("y", "yes")


def specs(hw: dict) -> str:
    text = (f"≈ {hw.get('params_m', '?')} M parameters · {hw.get('vram_gb', '?')} GB VRAM · "
            f"{hw.get('ram_gb', '?')} GB RAM")
    note = hw.get("note")
    if isinstance(note, dict):
        note = note.get("en") or ""
    return f"{text} · {note}" if note else text


def print_plan(items: list[dl.DownloadItem]) -> int:
    """Lists what will be downloaded, grouped by model. Returns the total bytes."""
    total = 0
    for mid, its in dl.group_by_model(items).items():
        first = its[0]
        size = sum(it.missing_size for it in its)
        total += size
        _out(f"  • {first.model_name} — {dl.fmt_bytes(size)}")
        if first.hardware:
            _out(f"      {specs(first.hardware)}")
        for it in its:
            lic = it.license + (f" ({it.license_url})" if it.license_url else "")
            _out(f"      - {it.name}: {it.source} · {dl.fmt_bytes(it.missing_size)} · license: {lic}")
        if any(it.requires_acceptance for it in its):
            _out("      ⚠ The license must be accepted before downloading.")
        _out(f"      Destination: {first.target.parent}")
    return total


def drop_installed_families(items: list[dl.DownloadItem]) -> list[dl.DownloadItem]:
    """Do not offer other versions of a family that already has one installed."""
    done = dl.installed_families()
    return [it for it in items if not (it.family and it.family in done)]


def choose_variants(items: list[dl.DownloadItem], interactive: bool) -> list[dl.DownloadItem]:
    """If a model has several versions, asks which one to download.
    Without interaction (--yes) it does not choose for the user: they are skipped."""
    groups = dl.group_by_model(items)
    fams: dict[str, list[str]] = {}
    for mid, its in groups.items():
        if its[0].family:
            fams.setdefault(its[0].family, []).append(mid)
    keep_all = set(groups)
    for fam, mids in fams.items():
        if len(mids) < 2:
            continue
        name = groups[mids[0]][0].family_name or fam
        keep_all -= set(mids)
        if not interactive:
            _out(f"\n{name}: several versions available; skipped. Download it from the app or with --models.")
            continue
        _out(f"\n{name} comes in several versions (only one is used at a time):")
        for i, m in enumerate(mids, 1):
            its = groups[m]
            hw = f" · {specs(its[0].hardware)}" if its[0].hardware else ""
            _out(f"  [{i}] {its[0].model_name} — {dl.fmt_bytes(sum(it.missing_size for it in its))}{hw}")
        _out("  [A] all · [0] none (you can download it later from the app)")
        while True:
            try:
                ans = input("  Which one do you want? ").strip().lower().lstrip("\ufeff")
            except EOFError:
                ans = "0"
            if ans in ("a", "all"):
                keep_all |= set(mids)
                break
            if ans == "0":
                break
            if ans.isdigit() and 1 <= int(ans) <= len(mids):
                keep_all.add(mids[int(ans) - 1])
                break
            _out(f"  Type a number from 1 to {len(mids)}, A or 0.")
    return [it for it in items if it.model_id in keep_all]


def accept_licenses(items: list[dl.DownloadItem], assume: bool) -> list[dl.DownloadItem]:
    """Asks to accept the licenses that require it (once per model). Returns what was accepted."""
    chosen = []
    for mid, its in dl.group_by_model(items).items():
        need = [it for it in its if it.requires_acceptance]
        if not need or assume:
            chosen += its
            continue
        it = need[0]
        _out()
        _out(f"⚠ {it.model_name} is distributed under this license: {it.license}.")
        _out(f"  Full text: {it.license_url}")
        if ask(f"  Do you accept the {it.model_name} license and want to download it?", default=False):
            chosen += its
        else:
            _out(f"  Skipping {it.model_name}. You can download it later from the app.")
    return chosen


def console_progress():
    def report(e: dict):
        if e["type"] == "file":
            size = dl.fmt_bytes(e["size"]) if e.get("size") else "?"
            sys.stdout.write(f"\n  [{e['index'] + 1}/{e['count']}] {e['model']} · {e['file']} ({size})\n")
            sys.stdout.flush()
        elif e["type"] == "progress" and e["total"]:
            frac = min(1.0, e["done"] / e["total"])
            bar = "#" * int(frac * 30) + "." * (30 - int(frac * 30))
            eta = dl.fmt_eta(e["eta"]) if e.get("eta") is not None else "--:--"
            sys.stdout.write(f"\r      [{bar}] {frac * 100:5.1f}%  {dl.fmt_bytes(e['done'])} / "
                             f"{dl.fmt_bytes(e['total'])}  {dl.fmt_bytes(e['speed'])}/s  {eta} left   ")
            sys.stdout.flush()

    return report


def run(items: list[dl.DownloadItem]) -> bool:
    if not items:
        return True
    try:
        dl.download(items, report=console_progress())
    except KeyboardInterrupt:
        _out("\n\nDownload interrupted. Run the command again to resume where it stopped.")
        return False
    except Exception as e:
        _out(f"\n\n✖ Download error: {e}")
        _out("  Run the command again: it will resume where it stopped.")
        return False
    _out("\n\n✔ Downloads finished and verified (SHA-256).")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", "-y", action="store_true",
                    help="do not ask for confirmation (models with several versions are skipped: use --models)")
    ap.add_argument("--accept-licenses", action="store_true",
                    help="also accept the licenses that require explicit acceptance")
    ap.add_argument("--models", help="comma-separated ids (default: all)")
    ap.add_argument("--list", action="store_true", help="only show what is missing, without downloading")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ids = set(args.models.split(",")) if args.models else None
    items = dl.scan(model_ids=ids)
    if ids is None:
        items = drop_installed_families(items)
    if not items:
        _out("✔ All models are downloaded.")
        return 0
    _out("Models to download:\n")
    print_plan(items)
    if args.list:
        return 0
    if ids is None:  # with --models the user has already chosen the versions
        items = choose_variants(items, interactive=not args.yes)
    total = sum(it.missing_size for it in items)
    _out(f"\n  Total to download: {dl.fmt_bytes(total)} · free space: {dl.fmt_bytes(dl.disk_free(ROOT))}")
    if not items or (not args.yes and not ask("\nContinue with the download?", default=True)):
        _out("Cancelled. Nothing was downloaded.")
        return 1
    items = accept_licenses(items, args.accept_licenses)
    return 0 if run(items) else 1


if __name__ == "__main__":
    sys.exit(main())
