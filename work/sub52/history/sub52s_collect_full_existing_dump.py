#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52S: read-only full PPSSPP texture dump collection, stdlib only."""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import traceback
import zipfile
from collections import Counter

GAME_ID = "ULKS46086"
STAGE = "naruto_sub52s_full_existing_dump"
DEFAULT_ROOT = Path(r"D:\narutimate portable")
DEFAULT_DUMP = Path(r"C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\memstick\PSP\TEXTURES\ULKS46086\new")
FILENAME_RE = re.compile(r"^[0-9a-fA-F]{24,32}\.png$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def utc_iso(stamp: float) -> str:
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()


def filename_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def png_dimensions(p: Path):
    with p.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != PNG_MAGIC or head[12:16] != b"IHDR":
        raise ValueError("Invalid PNG header: " + str(p))
    w, h = struct.unpack(">II", head[16:24])
    if w < 1 or h < 1 or w > 8192 or h > 8192:
        raise ValueError("Suspicious PNG dimensions: " + str(p))
    return w, h


def as_tsv(items, keys):
    f = io.StringIO(newline="")
    writer = csv.DictWriter(f, fieldnames=keys, delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)
    return ("\ufeff" + f.getvalue()).encode("utf-8")


def choose_source(explicit: str):
    if explicit:
        return Path(explicit)
    if DEFAULT_DUMP.is_dir():
        return DEFAULT_DUMP
    home = Path.home()
    secondary = home / "Documents" / "Codex" / "2026-09-18" / "c-users-admin-downloads" / "work" / "ppsspp" / "memstick" / "PSP" / "TEXTURES" / GAME_ID / "new"
    return secondary


def make_zip(path, files, source, rows, summary, script_dir, error=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    inventory = as_tsv(rows, ["filename", "width", "height", "bytes", "sha256", "mtime_utc"])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as z:
        z.writestr("SUMMARY.json", json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"))
        z.writestr("DUMP_INVENTORY.tsv", inventory)
        z.writestr("README.txt", (
            "SUB52S existing texture dump export\n"
            "Source is read-only. This export DOES NOT prove the time or game screen where each image appeared.\n"
            "All textures/ entries are byte-identical copies of source PNG files.\n"
            "Source: " + str(source) + "\n"
        ).encode("utf-8"))
        for n in ("sub52s_collect_full_existing_dump.py", "run_naruto_sub52s_full_dump.ps1"):
            p = script_dir / n
            if p.is_file():
                z.write(p, "scripts/" + n)
        if error:
            z.writestr("FAILURE.txt", error)
        else:
            for p in files:
                z.write(p, "textures/" + p.name)
    # Ensure ZIP central directory and count are valid.
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise IOError("ZIP CRC failure at " + bad)
        if not error:
            dumped = sum(1 for n in z.namelist() if n.startswith("textures/") and n.lower().endswith(".png"))
            if dumped != len(files):
                raise IOError("ZIP texture count mismatch")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--source", default="")
    ap.add_argument("--log-dir", default="")
    args = ap.parse_args()
    root = Path(args.root)
    log_dir = Path(args.log_dir) if args.log_dir else root / "logs"
    report_dir = root / "analysis" / "sub" / "sub52s_full_existing_dump"
    source = choose_source(args.source)
    script_dir = Path(__file__).resolve().parent
    rows = []
    files = []
    summary = {"stage": STAGE, "game_id": GAME_ID, "read_only": True,
               "source": str(source), "ppsspp_launched": False,
               "iso_modified": False, "existing_dump_modified": False,
               "note": "File modified times are not proof of the original moment a texture was rendered."}
    try:
        if not source.is_dir():
            raise FileNotFoundError("Existing PPSSPP texture dump folder not found: " + str(source))
        print("[1/3] Inventorying " + str(source), flush=True)
        for p in sorted(source.glob("*.png"), key=lambda x: x.name.lower()):
            if not p.is_file():
                continue
            if not FILENAME_RE.fullmatch(p.name):
                # Ignore unrelated files; do not delete or modify them.
                continue
            w, h = png_dimensions(p)
            size = p.stat().st_size
            rows.append({"filename": p.name, "width": w, "height": h,
                         "bytes": size, "sha256": filename_sha256(p),
                         "mtime_utc": utc_iso(p.stat().st_mtime)})
            files.append(p)
        if not files:
            raise RuntimeError("No matching PNG textures found (0 files).")
        total = sum(r["bytes"] for r in rows)
        sizes = Counter((r["width"], r["height"]) for r in rows)
        summary.update({"status": "PASS", "png_count": len(files), "total_png_bytes": total,
                        "dimensions": {f"{w}x{h}": count for (w,h),count in sorted(sizes.items())},
                        "unique_sha256": len(set(r["sha256"] for r in rows)),
                        "all_original_png_in_zip": True,
                        "snapshot_time_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        # Disk check only for output ZIP, no deletion.
        log_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(log_dir).free
        summary["log_drive_free_bytes"] = free
        if free < total + 20 * 1024 * 1024:
            raise RuntimeError("Not enough space for ~%.1f MiB dump ZIP. Free %.1f MiB."
                               % (total/1048576, free/1048576))
        print(f"[2/3] Packaging {len(files)} PNGs ({total/1048576:.2f} MiB raw)", flush=True)
        success_path = log_dir / (STAGE + "_upload.zip")
        make_zip(success_path, files, source, rows, summary, script_dir)
        # Only short diagnostic files, do not replicate textures on disk.
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        (report_dir / "DUMP_INVENTORY.tsv").write_bytes(as_tsv(rows, ["filename", "width", "height", "bytes", "sha256", "mtime_utc"]))
        print("[3/3] ZIP verified: " + str(success_path), flush=True)
        print("PNG_COUNT=" + str(len(files)), flush=True)
        print("UPLOAD_ZIP=" + str(success_path), flush=True)
        return 0
    except Exception:
        err = traceback.format_exc()
        summary.update({"status": "FAIL", "exception": err})
        print(err, file=sys.stderr, flush=True)
        fail_path = log_dir / ("fail_" + STAGE + "_upload.zip")
        try:
            make_zip(fail_path, [], source, rows, summary, script_dir, error=err)
            print("UPLOAD_ZIP=" + str(fail_path), flush=True)
        except Exception as e:
            print("COULD_NOT_PACKAGE_FAILURE=" + str(e), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
