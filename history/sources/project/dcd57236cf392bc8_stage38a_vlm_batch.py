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

MARKER = "<STAGE38A_RESPONSE>"


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True)
    p.add_argument("--fallback-binary", required=False)
    p.add_argument("--model", required=True)
    p.add_argument("--mmproj", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--payload-root", required=True)
    p.add_argument("--output-dir", required=True)
    return p.parse_args()


def read_manifest(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def clean_response(raw):
    # Strongest signal: explicit wrapper requested in the prompt.
    matches = re.findall(
        r"<OCR>\s*(.*?)\s*</OCR>",
        raw,
        flags=re.S | re.I,
    )

    if matches:
        text = matches[-1]
    else:
        tail = raw.split(MARKER, 1)[-1] if MARKER in raw else raw

        kept = []

        for line in tail.splitlines():
            s = line.strip()

            if not s:
                continue

            # Drop common llama.cpp / Vulkan diagnostics.
            if re.match(
                r"^(llama_|ggml_|mtmd_|main:|common_|load_|print_|sampler|build:|system_info:)",
                s,
                flags=re.I,
            ):
                continue

            if "tokens per second" in s.lower():
                continue

            if re.match(r"^[\[\(]?(prompt|eval|sample|load) time", s, flags=re.I):
                continue

            kept.append(line)

        text = "\n".join(kept).strip()

    # Remove accidental surrounding code fences.
    text = re.sub(r"^```(?:text)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def contains_hangul(text):
    return bool(re.search(r"[\u3131-\u318E\uAC00-\uD7A3]", text))


def hangul_count(text):
    return len(re.findall(r"[\u3131-\u318E\uAC00-\uD7A3]", text))


def run_one(binary, model, mmproj, image):
    env = dict(os.environ)
    env["MTMD_TEST_RESPONSE_MARKER"] = MARKER

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

    t0 = time.perf_counter()

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    elapsed = time.perf_counter() - t0
    raw = proc.stdout or ""
    text = clean_response(raw)

    return {
        "exit_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "raw": raw,
        "text": text,
        "cmd": cmd,
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

    return xs[lo] * (1 - frac) + xs[hi] * frac


def main():
    a = args()

    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw_dir = out / "raw_logs"
    review_dir = out / "review_images"

    raw_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(a.manifest)

    if len(manifest) != 120:
        raise RuntimeError(
            f"Expected 120 manifest rows, got {len(manifest)}"
        )

    payload_root = Path(a.payload_root)

    binaries = [a.binary]

    if a.fallback_binary and Path(a.fallback_binary).exists():
        binaries.append(a.fallback_binary)

    chosen_binary = None
    smoke = None

    first_image = payload_root / manifest[0]["image_file"]

    print("Smoke test image:", first_image)
    print()

    for binary in binaries:
        print("Trying binary:", binary)
        result = run_one(
            binary,
            a.model,
            a.mmproj,
            first_image,
        )

        smoke_name = (
            raw_dir
            / ("smoke_" + Path(binary).name + ".log")
        )

        smoke_name.write_text(
            result["raw"],
            encoding="utf-8",
        )

        if result["exit_code"] == 0 and result["text"]:
            chosen_binary = binary
            smoke = result
            print("Selected:", binary)
            print("Smoke OCR:", repr(result["text"]))
            break

        print(
            "Failed:",
            result["exit_code"],
            repr(result["text"][:200]),
        )

    if chosen_binary is None:
        raise RuntimeError(
            "Both llama-mtmd-cli and llama-cli smoke tests failed."
        )

    rows = []
    durations = []
    consecutive_failures = 0

    # First sample already ran as smoke; run all 120 again for a uniform benchmark.
    for i, item in enumerate(manifest, 1):
        image = payload_root / item["image_file"]

        if not image.exists():
            raise RuntimeError(f"Image missing: {image}")

        print(
            f"[{i:03d}/120] "
            f"{item['video_part']} "
            f"{item['timestamp']} "
            f"{image.name}",
            flush=True,
        )

        result = run_one(
            chosen_binary,
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
            consecutive_failures = 0
            durations.append(
                result["elapsed_seconds"]
            )
        else:
            consecutive_failures += 1

        # Keep diagnostics for first five, every 20th, and all failures.
        if (
            i <= 5
            or i % 20 == 0
            or status != "OK"
        ):
            (raw_dir / f"{i:03d}_{image.stem}.log").write_text(
                result["raw"],
                encoding="utf-8",
            )

        # 40 review images: every 3rd sample.
        if (i - 1) % 3 == 0:
            shutil.copy2(
                image,
                review_dir / image.name,
            )

        row = {
            "sample_index": item["sample_index"],
            "video_part": item["video_part"],
            "part_index": item["part_index"],
            "global_index": item["global_index"],
            "timestamp_seconds": item["timestamp_seconds"],
            "timestamp": item["timestamp"],
            "image_file": item["image_file"],
            "status": status,
            "exit_code": result["exit_code"],
            "elapsed_seconds": f"{result['elapsed_seconds']:.3f}",
            "contains_hangul": int(
                contains_hangul(result["text"])
            ),
            "hangul_chars": hangul_count(
                result["text"]
            ),
            "ocr_text": result["text"],
        }

        rows.append(row)

        print(
            "  ->",
            status,
            f"{result['elapsed_seconds']:.2f}s",
            repr(result["text"][:140]),
            flush=True,
        )

        if consecutive_failures >= 3:
            raise RuntimeError(
                "Three consecutive VLM inference failures; aborting."
            )

    fields = [
        "sample_index",
        "video_part",
        "part_index",
        "global_index",
        "timestamp_seconds",
        "timestamp",
        "image_file",
        "status",
        "exit_code",
        "elapsed_seconds",
        "contains_hangul",
        "hangul_chars",
        "ocr_text",
    ]

    with (out / "stage38a_results.tsv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
        )

        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["status"] == "OK"]
    hangul = [r for r in ok if int(r["contains_hangul"])]

    avg = statistics.mean(durations) if durations else None
    med = statistics.median(durations) if durations else None
    p95 = percentile(durations, 0.95)
    total = sum(durations)

    estimate_full = (
        avg * 2086
        if avg is not None
        else None
    )

    # GPU evidence from smoke/raw output.
    all_diag = "\n".join(
        p.read_text(
            encoding="utf-8",
            errors="replace",
        )
        for p in raw_dir.glob("smoke_*.log")
    )

    vulkan_seen = bool(
        re.search(
            r"ggml_vulkan|Vulkan",
            all_diag,
            flags=re.I,
        )
    )

    summary = {
        "stage": "38A",
        "backend": "llama.cpp Vulkan",
        "rocm_used": False,
        "pytorch_used": False,
        "model": "Qwen3-VL-2B-Instruct Q8_0",
        "chosen_binary": chosen_binary,
        "samples": len(rows),
        "ok": len(ok),
        "errors": len(rows) - len(ok),
        "hangul_positive": len(hangul),
        "vulkan_evidence_in_smoke_log": vulkan_seen,
        "timing": {
            "mean_seconds": avg,
            "median_seconds": med,
            "p95_seconds": p95,
            "sum_success_seconds": total,
            "estimated_2086_seconds_at_same_rate": estimate_full,
            "estimated_2086_minutes_at_same_rate": (
                estimate_full / 60
                if estimate_full is not None
                else None
            ),
        },
        "prompt": PROMPT,
    }

    (out / "stage38a_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fmt(v):
        return "n/a" if v is None else f"{v:.3f}"

    lines = [
        "Naruto PSP Stage 38A",
        "=" * 72,
        "",
        "STATUS: BC250_VULKAN_VLM_BENCHMARK_COMPLETE",
        "",
        "Backend:",
        "  llama.cpp Vulkan",
        "  ROCm: NO",
        "  PyTorch: NO",
        f"  binary: {chosen_binary}",
        "",
        "Model:",
        "  Qwen3-VL-2B-Instruct Q8_0",
        "",
        "Results:",
        f"  samples: {len(rows)}",
        f"  OK: {len(ok)}",
        f"  errors: {len(rows) - len(ok)}",
        f"  Hangul-positive OCR: {len(hangul)}",
        f"  Vulkan evidence in smoke log: {vulkan_seen}",
        "",
        "Timing per image:",
        f"  mean: {fmt(avg)} s",
        f"  median: {fmt(med)} s",
        f"  p95: {fmt(p95)} s",
        "",
        "Projected full Stage37B corpus (2086 images):",
        (
            "  n/a"
            if estimate_full is None
            else f"  {estimate_full / 60:.1f} minutes at the same rate"
        ),
        "",
        "Review:",
        "  stage38a_results.tsv",
        "  review_images/ contains every 3rd sample (40 images)",
        "  raw_logs/ contains smoke + selected diagnostic runs",
    ]

    (out / "stage38a_summary.txt").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE38A VLM BENCHMARK COMPLETE")
    print("=" * 72)
    print("OK:", len(ok), "/", len(rows))
    print("Hangul-positive:", len(hangul))
    print("Mean:", fmt(avg), "s/image")
    print(
        "Projected full:",
        "n/a"
        if estimate_full is None
        else f"{estimate_full / 60:.1f} min",
    )
    print("Vulkan evidence:", vulkan_seen)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("STAGE38A BATCH ERROR:", exc, file=sys.stderr)
        raise
