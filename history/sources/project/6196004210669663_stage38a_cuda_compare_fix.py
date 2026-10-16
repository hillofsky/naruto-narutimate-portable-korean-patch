#!/usr/bin/env python3
from pathlib import Path
import argparse
import csv
import json
import re
import shutil
import statistics
import subprocess
import threading
import time


PROMPT = """???대?吏??寃뚯엫 ?곸긽?먯꽌 ?섎씪???먮쭑/????곸뿭?대떎.
?붾㈃???ㅼ젣濡?蹂댁씠??湲?먮쭔 ?뺥솗???꾩궗?섎씪.

洹쒖튃:
- ?쒓뎅?? ?쇰낯?? ?곸뼱, ?レ옄, 臾몄옣遺?몃? 蹂댁씠??洹몃?濡??곷뒗??
- 踰덉뿭, ?섏뿭, ?붿빟, 異붿륫, ?ㅻ챸???섏? ?딅뒗??
- 以꾨컮轅덉? ?붾㈃??蹂댁씠???濡?理쒕????좎??쒕떎.
- 湲?먭? ?꾪? ?놁쑝硫?[EMPTY]?쇨퀬 ?곷뒗??
- ?먮룆?????녿뒗 湲?먮쭔 [遺덈챸]?쇰줈 ?쒖떆?쒕떎.
- ?대?吏???녿뒗 臾몄옣??留뚮뱾?대궡吏 ?딅뒗??

諛섎뱶???꾨옒 ?뺤떇留?異쒕젰?쒕떎.
<OCR>
?붾㈃???ㅼ젣 ?띿뒪??</OCR>"""


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--mmproj", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--payload-root", required=True)
    p.add_argument("--bc250-results", required=True)
    p.add_argument("--output-dir", required=True)
    return p.parse_args()


def read_tsv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)


def clean_response(raw):
    matches = re.findall(
        r"<OCR>\s*(.*?)\s*</OCR>",
        raw,
        flags=re.S | re.I,
    )

    if matches:
        return matches[-1].strip()

    kept = []

    for line in raw.splitlines():
        s = line.strip()

        if not s:
            continue

        if re.match(
            r"^(llama_|ggml_|mtmd_|main:|common_|load_|print_|sampler|build:|system_info:)",
            s,
            flags=re.I,
        ):
            continue

        if "tokens per second" in s.lower():
            continue

        if re.match(
            r"^[\[\(]?(prompt|eval|sample|load) time",
            s,
            flags=re.I,
        ):
            continue

        kept.append(line)

    text = "\n".join(kept).strip()
    text = re.sub(r"^```(?:text)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    return text.strip()


def normalize_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
    ).strip()


def query_vram_mib():
    try:
        p = subprocess.run(
            [
                "nvidia-smi.exe",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )

        if p.returncode != 0:
            return None

        return int(
            p.stdout.strip().splitlines()[0].strip()
        )
    except Exception:
        return None


class VramSampler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.values = []

    def start(self):
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            v = query_vram_mib()

            if v is not None:
                self.values.append(v)

            self.stop_event.wait(0.20)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        return max(self.values) if self.values else None


def run_one(binary, model, mmproj, image):
    cmd = [
        binary,
        "-m", model,
        "--mmproj", mmproj,
        "--image", str(image),
        "-p", PROMPT,
        "-ngl", "99",
        "-c", "4096", "-b", "1024", "-ub", "1024", "--image-max-tokens", "512",
        "--temp", "0",
        "--top-k", "1",
        "--top-p", "1",
        "-n", "160", "--single-turn",
    ]

    sampler = VramSampler()
    sampler.start()

    t0 = time.perf_counter()

    p = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    elapsed = time.perf_counter() - t0
    peak = sampler.stop()

    raw = p.stdout or ""

    return {
        "exit_code": p.returncode,
        "elapsed_seconds": elapsed,
        "peak_vram_mib": peak,
        "raw": raw,
        "text": clean_response(raw),
    }


def percentile(values, q):
    if not values:
        return None

    xs = sorted(values)

    if len(xs) == 1:
        return xs[0]

    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    f = pos - lo

    return xs[lo] * (1 - f) + xs[hi] * f


def main():
    a = parse_args()

    out = Path(a.output_dir)
    raw_dir = out / "raw_logs"
    review_dir = out / "review_images"

    raw_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_tsv(a.manifest)
    bc = read_tsv(a.bc250_results)

    if len(manifest) != 120:
        raise RuntimeError(
            f"Expected 120 samples, got {len(manifest)}"
        )

    bc_by = {
        int(r["sample_index"]): r
        for r in bc
    }

    payload = Path(a.payload_root)

    rows = []
    durations = []
    peaks = []

    for i, item in enumerate(manifest, 1):
        image = payload / item["image_file"]

        print(
            f"[{i:03d}/120] {item['video_part']} "
            f"{item['timestamp']} {image.name}",
            flush=True,
        )

        r = run_one(
            a.binary,
            a.model,
            a.mmproj,
            image,
        )

        status = "OK"

        if r["exit_code"] != 0:
            status = "ERROR_EXIT"
        elif not r["text"]:
            status = "EMPTY_OUTPUT"

        if status == "OK":
            durations.append(
                r["elapsed_seconds"]
            )

        if r["peak_vram_mib"] is not None:
            peaks.append(
                r["peak_vram_mib"]
            )

        if i <= 5 or i % 20 == 0 or status != "OK":
            (
                raw_dir
                / f"{i:03d}_{image.stem}.log"
            ).write_text(
                r["raw"],
                encoding="utf-8",
            )

        if (i - 1) % 3 == 0:
            shutil.copy2(
                image,
                review_dir / image.name,
            )

        prev = bc_by.get(
            int(item["sample_index"]),
            {},
        )

        cuda_text = normalize_text(r["text"])
        bc_text = normalize_text(
            prev.get("ocr_text", "")
        )

        rows.append({
            "sample_index": item["sample_index"],
            "video_part": item["video_part"],
            "part_index": item["part_index"],
            "global_index": item["global_index"],
            "timestamp": item["timestamp"],
            "status": status,
            "exit_code": r["exit_code"],
            "elapsed_seconds": f"{r['elapsed_seconds']:.3f}",
            "peak_vram_mib": (
                r["peak_vram_mib"]
                if r["peak_vram_mib"] is not None
                else ""
            ),
            "cuda_ocr_text": cuda_text,
            "bc250_ocr_text": bc_text,
            "exact_same_as_bc250": int(
                cuda_text == bc_text
            ),
        })

        print(
            "  ->",
            status,
            f"{r['elapsed_seconds']:.2f}s",
            (
                f"VRAM={r['peak_vram_mib']}MiB"
                if r["peak_vram_mib"] is not None
                else "VRAM=n/a"
            ),
            repr(cuda_text[:100]),
            flush=True,
        )

    write_tsv(
        out / "stage38a_cuda_results.tsv",
        rows,
        [
            "sample_index",
            "video_part",
            "part_index",
            "global_index",
            "timestamp",
            "status",
            "exit_code",
            "elapsed_seconds",
            "peak_vram_mib",
            "cuda_ocr_text",
        ],
    )

    write_tsv(
        out / "stage38a_cuda_compare.tsv",
        rows,
        [
            "sample_index",
            "video_part",
            "part_index",
            "global_index",
            "timestamp",
            "cuda_ocr_text",
            "bc250_ocr_text",
            "exact_same_as_bc250",
            "elapsed_seconds",
            "peak_vram_mib",
        ],
    )

    bc_times = []

    for r in bc:
        try:
            if r.get("status") == "OK":
                bc_times.append(
                    float(r["elapsed_seconds"])
                )
        except Exception:
            pass

    cuda_mean = statistics.mean(durations) if durations else None
    cuda_median = statistics.median(durations) if durations else None
    cuda_p95 = percentile(durations, 0.95)
    bc_mean = statistics.mean(bc_times) if bc_times else None
    speedup = (
        bc_mean / cuda_mean
        if bc_mean and cuda_mean
        else None
    )

    exact = sum(
        int(r["exact_same_as_bc250"])
        for r in rows
    )

    peak = max(peaks) if peaks else None
    projected = cuda_mean * 2086 if cuda_mean else None

    summary = {
        "stage": "38A-CUDA-FIX",
        "backend": "llama.cpp CUDA",
        "binary": a.binary,
        "samples": len(rows),
        "ok": sum(1 for r in rows if r["status"] == "OK"),
        "cuda_mean_seconds": cuda_mean,
        "cuda_median_seconds": cuda_median,
        "cuda_p95_seconds": cuda_p95,
        "bc250_mean_seconds": bc_mean,
        "speedup_vs_bc250": speedup,
        "exact_same_ocr_count": exact,
        "exact_same_ocr_ratio": exact / len(rows),
        "max_observed_vram_mib": peak,
        "projected_2086_minutes": (
            projected / 60
            if projected is not None
            else None
        ),
    }

    (
        out / "stage38a_cuda_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def f(v):
        return "n/a" if v is None else f"{v:.3f}"

    lines = [
        "Naruto PSP Stage 38A-CUDA FIX",
        "=" * 72,
        "",
        f"Binary: {a.binary}",
        "",
        f"OK: {summary['ok']}/{len(rows)}",
        f"CUDA mean: {f(cuda_mean)} s/image",
        f"CUDA median: {f(cuda_median)} s/image",
        f"CUDA p95: {f(cuda_p95)} s/image",
        f"BC250 mean: {f(bc_mean)} s/image",
        (
            "Speedup: n/a"
            if speedup is None
            else f"Speedup vs BC250: {speedup:.2f}x"
        ),
        (
            "Max observed VRAM: n/a"
            if peak is None
            else f"Max observed VRAM: {peak} MiB"
        ),
        (
            f"Exact same OCR text: "
            f"{exact}/{len(rows)} "
            f"({100*exact/len(rows):.1f}%)"
        ),
        (
            "Projected 2086: n/a"
            if projected is None
            else f"Projected 2086: {projected/60:.1f} min"
        ),
    ]

    (
        out / "stage38a_cuda_summary.txt"
    ).write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE38A-CUDA FIX COMPLETE")
    print("=" * 72)
    print("CUDA mean:", f(cuda_mean), "s/image")
    print("BC250 mean:", f(bc_mean), "s/image")
    print(
        "Speedup:",
        "n/a" if speedup is None else f"{speedup:.2f}x",
    )
    print(
        "Max VRAM:",
        "n/a" if peak is None else f"{peak} MiB",
    )


if __name__ == "__main__":
    main()


