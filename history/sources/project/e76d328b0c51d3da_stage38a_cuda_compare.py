#!/usr/bin/env python3
from pathlib import Path
import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time


PROMPT = """이 이미지는 게임 영상에서 잘라낸 자막/대사 영역이다.
화면에 실제로 보이는 글자만 정확히 전사하라.

규칙:
- 한국어, 일본어, 영어, 숫자, 문장부호를 보이는 그대로 적는다.
- 번역, 의역, 요약, 추측, 설명을 하지 않는다.
- 줄바꿈은 화면에 보이는 대로 최대한 유지한다.
- 글자가 전혀 없으면 [EMPTY]라고 적는다.
- 판독할 수 없는 글자만 [불명]으로 표시한다.
- 이미지에 없는 문장을 만들어내지 않는다.

반드시 아래 형식만 출력한다.
<OCR>
화면의 실제 텍스트
</OCR>"""


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
        text = matches[-1]
    else:
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

    text = re.sub(
        r"^```(?:text)?\s*",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return text.strip()


def normalize_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


def contains_hangul(text):
    return bool(
        re.search(
            r"[\u3131-\u318E\uAC00-\uD7A3]",
            text,
        )
    )


def query_vram_mib():
    try:
        proc = subprocess.run(
            [
                "nvidia-smi.exe",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )

        if proc.returncode != 0:
            return None

        line = proc.stdout.strip().splitlines()[0]
        return int(line.strip())
    except Exception:
        return None


class VramSampler:
    def __init__(self):
        self.stop_event = threading.Event()
        self.values = []
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )

    def _run(self):
        while not self.stop_event.is_set():
            value = query_vram_mib()

            if value is not None:
                self.values.append(value)

            self.stop_event.wait(0.20)

    def start(self):
        self.thread.start()

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
        "-c", "4096",
        "--temp", "0",
        "--top-k", "1",
        "--top-p", "1",
        "-n", "160",
    ]

    sampler = VramSampler()
    sampler.start()

    t0 = time.perf_counter()

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    elapsed = time.perf_counter() - t0
    peak_vram = sampler.stop()

    raw = proc.stdout or ""
    text = clean_response(raw)

    return {
        "exit_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "peak_vram_mib": peak_vram,
        "raw": raw,
        "text": text,
    }


def percentile(values, p):
    if not values:
        return None

    xs = sorted(values)

    if len(xs) == 1:
        return xs[0]

    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo

    return (
        xs[lo] * (1 - frac)
        + xs[hi] * frac
    )


def main():
    a = parse_args()

    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_dir = out / "raw_logs"
    review_dir = out / "review_images"

    raw_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_tsv(a.manifest)
    bc_rows = read_tsv(a.bc250_results)

    if len(manifest) != 120:
        raise RuntimeError(
            f"manifest expected 120 rows, got {len(manifest)}"
        )

    bc_by_sample = {
        int(row["sample_index"]): row
        for row in bc_rows
    }

    payload = Path(a.payload_root)
    rows = []
    durations = []
    peak_vrams = []

    for i, item in enumerate(manifest, 1):
        image = payload / item["image_file"]

        if not image.exists():
            raise RuntimeError(
                f"image missing: {image}"
            )

        print(
            f"[{i:03d}/120] "
            f"{item['video_part']} "
            f"{item['timestamp']} "
            f"{image.name}",
            flush=True,
        )

        result = run_one(
            a.binary,
            a.model,
            a.mmproj,
            image,
        )

        status = "OK"

        if result["exit_code"] != 0:
            status = "ERROR_EXIT"
        elif not result["text"]:
            status = "EMPTY_OUTPUT"

        if status == "OK":
            durations.append(
                result["elapsed_seconds"]
            )

        if result["peak_vram_mib"] is not None:
            peak_vrams.append(
                result["peak_vram_mib"]
            )

        if (
            i <= 5
            or i % 20 == 0
            or status != "OK"
        ):
            (
                raw_dir
                / f"{i:03d}_{image.stem}.log"
            ).write_text(
                result["raw"],
                encoding="utf-8",
            )

        if (i - 1) % 3 == 0:
            shutil.copy2(
                image,
                review_dir / image.name,
            )

        bc = bc_by_sample.get(
            int(item["sample_index"]),
            {},
        )

        cuda_text = normalize_text(
            result["text"]
        )

        bc_text = normalize_text(
            bc.get("ocr_text", "")
        )

        exact = (
            cuda_text == bc_text
        )

        rows.append({
            "sample_index":
                item["sample_index"],
            "video_part":
                item["video_part"],
            "part_index":
                item["part_index"],
            "global_index":
                item["global_index"],
            "timestamp":
                item["timestamp"],
            "image_file":
                item["image_file"],
            "status":
                status,
            "exit_code":
                result["exit_code"],
            "elapsed_seconds":
                f"{result['elapsed_seconds']:.3f}",
            "peak_vram_mib":
                (
                    result["peak_vram_mib"]
                    if result["peak_vram_mib"]
                    is not None
                    else ""
                ),
            "contains_hangul":
                int(
                    contains_hangul(
                        cuda_text
                    )
                ),
            "cuda_ocr_text":
                cuda_text,
            "bc250_ocr_text":
                bc_text,
            "exact_same_as_bc250":
                int(exact),
        })

        print(
            "  ->",
            status,
            f"{result['elapsed_seconds']:.2f}s",
            (
                f"peakVRAM={result['peak_vram_mib']}MiB"
                if result["peak_vram_mib"] is not None
                else "peakVRAM=n/a"
            ),
            repr(cuda_text[:120]),
            flush=True,
        )

    result_fields = [
        "sample_index",
        "video_part",
        "part_index",
        "global_index",
        "timestamp",
        "image_file",
        "status",
        "exit_code",
        "elapsed_seconds",
        "peak_vram_mib",
        "contains_hangul",
        "cuda_ocr_text",
    ]

    write_tsv(
        out / "stage38a_cuda_results.tsv",
        [
            {
                k: row[k]
                for k in result_fields
            }
            for row in rows
        ],
        result_fields,
    )

    compare_fields = [
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
    ]

    write_tsv(
        out / "stage38a_cuda_compare.tsv",
        rows,
        compare_fields,
    )

    ok = [
        r
        for r in rows
        if r["status"] == "OK"
    ]

    exact_count = sum(
        int(r["exact_same_as_bc250"])
        for r in rows
    )

    bc_times = []

    for row in bc_rows:
        try:
            if row.get("status") == "OK":
                bc_times.append(
                    float(
                        row["elapsed_seconds"]
                    )
                )
        except Exception:
            pass

    cuda_mean = (
        statistics.mean(durations)
        if durations
        else None
    )

    cuda_median = (
        statistics.median(durations)
        if durations
        else None
    )

    cuda_p95 = percentile(
        durations,
        0.95,
    )

    bc_mean = (
        statistics.mean(bc_times)
        if bc_times
        else None
    )

    speedup = (
        bc_mean / cuda_mean
        if bc_mean
        and cuda_mean
        and cuda_mean > 0
        else None
    )

    full_seconds = (
        cuda_mean * 2086
        if cuda_mean is not None
        else None
    )

    peak_max = (
        max(peak_vrams)
        if peak_vrams
        else None
    )

    summary = {
        "stage": "38A-CUDA",
        "device": "RTX 3070 Laptop",
        "backend": "llama.cpp CUDA",
        "same_model_as_bc250": True,
        "model": "Qwen3-VL-2B-Instruct Q8_0",
        "samples": len(rows),
        "ok": len(ok),
        "errors": len(rows) - len(ok),
        "exact_same_text_as_bc250": exact_count,
        "exact_same_ratio": exact_count / len(rows),
        "cuda_timing": {
            "mean_seconds": cuda_mean,
            "median_seconds": cuda_median,
            "p95_seconds": cuda_p95,
        },
        "bc250_timing_from_previous_run": {
            "mean_seconds": bc_mean,
        },
        "speedup_vs_bc250": speedup,
        "peak_vram_mib_max_observed": peak_max,
        "projected_2086_seconds": full_seconds,
        "projected_2086_minutes": (
            full_seconds / 60
            if full_seconds is not None
            else None
        ),
    }

    (
        out
        / "stage38a_cuda_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fmt(v, digits=3):
        if v is None:
            return "n/a"
        return f"{v:.{digits}f}"

    lines = [
        "Naruto PSP Stage 38A-CUDA",
        "=" * 72,
        "",
        "STATUS: CUDA_COMPARISON_COMPLETE",
        "",
        "Device:",
        "  RTX 3070 Laptop",
        "Backend:",
        "  llama.cpp CUDA",
        "",
        "Comparison conditions:",
        "  same 120 images as BC250",
        "  same Qwen3-VL-2B-Instruct Q8_0",
        "  same mmproj",
        "  same prompt",
        "  temp=0, n_gpu_layers=99",
        "",
        "CUDA results:",
        f"  OK: {len(ok)}/{len(rows)}",
        f"  mean: {fmt(cuda_mean)} s/image",
        f"  median: {fmt(cuda_median)} s/image",
        f"  p95: {fmt(cuda_p95)} s/image",
        (
            "  max observed VRAM: n/a"
            if peak_max is None
            else f"  max observed VRAM: {peak_max} MiB"
        ),
        "",
        "BC250 comparison:",
        f"  BC250 mean: {fmt(bc_mean)} s/image",
        (
            "  speedup: n/a"
            if speedup is None
            else f"  CUDA speedup: {speedup:.2f}x"
        ),
        (
            f"  exact same OCR text: "
            f"{exact_count}/{len(rows)} "
            f"({100.0 * exact_count / len(rows):.1f}%)"
        ),
        "",
        "Projected 2086 images:",
        (
            "  n/a"
            if full_seconds is None
            else f"  {full_seconds / 60:.1f} minutes"
        ),
        "",
        "Files:",
        "  stage38a_cuda_results.tsv",
        "  stage38a_cuda_compare.tsv",
        "  review_images/",
    ]

    (
        out
        / "stage38a_cuda_summary.txt"
    ).write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE38A-CUDA COMPLETE")
    print("=" * 72)
    print(
        "CUDA mean:",
        fmt(cuda_mean),
        "s/image",
    )
    print(
        "BC250 mean:",
        fmt(bc_mean),
        "s/image",
    )
    print(
        "Speedup:",
        "n/a"
        if speedup is None
        else f"{speedup:.2f}x",
    )
    print(
        "Exact OCR same:",
        f"{exact_count}/{len(rows)}",
    )
    print(
        "Max VRAM:",
        "n/a"
        if peak_max is None
        else f"{peak_max} MiB",
    )
    print(
        "Projected full:",
        "n/a"
        if full_seconds is None
        else f"{full_seconds / 60:.1f} min",
    )


if __name__ == "__main__":
    main()
