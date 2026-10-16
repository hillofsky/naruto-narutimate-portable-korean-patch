#!/usr/bin/env python3
from pathlib import Path
import argparse
import base64
import csv
import json
import mimetypes
import os
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request


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
    p.add_argument("--server-url", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--payload-root", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--backend", required=True)
    p.add_argument("--device", required=True)
    p.add_argument("--startup-seconds", type=float, default=None)
    p.add_argument("--nvidia-smi", action="store_true")
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


def http_json(url, body=None, timeout=180):
    if body is None:
        req = urllib.request.Request(url)
    else:
        raw = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer no-key",
            },
            method="POST",
        )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_model_id(server_url):
    data = http_json(server_url.rstrip("/") + "/v1/models", timeout=20)
    items = data.get("data") or []
    if not items:
        raise RuntimeError("/v1/models returned no models")
    return items[0].get("id") or "qwen3-vl"


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    raw = path.read_bytes()
    return "data:{};base64,{}".format(
        mime,
        base64.b64encode(raw).decode("ascii"),
    )


def extract_text(content):
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    pieces.append(item["text"])
                elif isinstance(item.get("content"), str):
                    pieces.append(item["content"])
        return "\n".join(pieces).strip()

    return str(content or "").strip()


def clean_ocr(text):
    m = re.findall(
        r"<OCR>\s*(.*?)\s*</OCR>",
        text,
        flags=re.S | re.I,
    )
    if m:
        return m[-1].strip()
    return text.strip()


def percentile(values, p):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    f = pos - lo
    return xs[lo] * (1 - f) + xs[hi] * f


class NvidiaSampler:
    def __init__(self, enabled):
        self.enabled = enabled
        self.stop_event = threading.Event()
        self.rows = []

    def start(self):
        if not self.enabled:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                p = subprocess.run(
                    [
                        "nvidia-smi.exe",
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2,
                )
                if p.returncode == 0 and p.stdout.strip():
                    first = p.stdout.strip().splitlines()[0]
                    a, b = [x.strip() for x in first.split(",", 1)]
                    self.rows.append(
                        (time.time(), int(a), int(b))
                    )
            except Exception:
                pass

            self.stop_event.wait(0.20)

    def stop(self):
        if not self.enabled:
            return
        self.stop_event.set()
        self.thread.join(timeout=3)

    def summary(self):
        if not self.rows:
            return {
                "gpu_util_mean_percent": None,
                "gpu_util_peak_percent": None,
                "vram_peak_mib": None,
            }
        util = [r[1] for r in self.rows]
        mem = [r[2] for r in self.rows]
        return {
            "gpu_util_mean_percent": statistics.mean(util),
            "gpu_util_peak_percent": max(util),
            "vram_peak_mib": max(mem),
        }


def main():
    a = parse_args()

    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    payload_root = Path(a.payload_root)
    manifest = read_tsv(a.manifest)

    if len(manifest) != 30:
        raise RuntimeError(
            f"Persistent benchmark requires 30 images, got {len(manifest)}"
        )

    server_url = a.server_url.rstrip("/")
    model_id = get_model_id(server_url)

    print("Backend:", a.backend)
    print("Device:", a.device)
    print("Model ID:", model_id)
    print("Samples:", len(manifest))
    print()

    sampler = NvidiaSampler(a.nvidia_smi)
    sampler.start()

    rows = []
    latencies = []

    for i, item in enumerate(manifest, 1):
        image = payload_root / item["image_file"]

        if not image.exists():
            raise RuntimeError(f"Image missing: {image}")

        body = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri(image),
                            },
                        },
                        {
                            "type": "text",
                            "text": PROMPT,
                        },
                    ],
                }
            ],
            "temperature": 0,
            "top_p": 1.0,
            "top_k": 1,
            "max_tokens": 160,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
        }

        print(
            f"[{i:02d}/30] "
            f"{item['video_part']} "
            f"{item['timestamp']} "
            f"{image.name}",
            flush=True,
        )

        t0 = time.perf_counter()

        try:
            data = http_json(
                server_url + "/v1/chat/completions",
                body=body,
                timeout=180,
            )
            elapsed = time.perf_counter() - t0
            content = data["choices"][0]["message"]["content"]
            raw_text = extract_text(content)
            ocr_text = clean_ocr(raw_text)
            status = "OK"
            error = ""

            timings = data.get("timings") or {}
            prompt_ms = timings.get("prompt_ms")
            predicted_ms = timings.get("predicted_ms")
            prompt_n = timings.get("prompt_n")
            predicted_n = timings.get("predicted_n")

            latencies.append(elapsed)

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            status = "ERROR"
            error = repr(exc)
            raw_text = ""
            ocr_text = ""
            prompt_ms = predicted_ms = prompt_n = predicted_n = None

        rows.append({
            "persistent_index": item["persistent_index"],
            "original_sample": item["original_sample"],
            "video_part": item["video_part"],
            "part_index": item["part_index"],
            "global_index": item["global_index"],
            "timestamp": item["timestamp"],
            "image_file": item["image_file"],
            "status": status,
            "wall_seconds": f"{elapsed:.4f}",
            "prompt_ms": "" if prompt_ms is None else prompt_ms,
            "predicted_ms": "" if predicted_ms is None else predicted_ms,
            "prompt_n": "" if prompt_n is None else prompt_n,
            "predicted_n": "" if predicted_n is None else predicted_n,
            "ocr_text": ocr_text,
            "error": error,
        })

        print(
            "  ->",
            status,
            f"{elapsed:.3f}s",
            repr(ocr_text[:100]),
            flush=True,
        )

        if status != "OK":
            raise RuntimeError(
                f"Request {i} failed: {error}"
            )

    sampler.stop()
    gpu = sampler.summary()

    fields = [
        "persistent_index",
        "original_sample",
        "video_part",
        "part_index",
        "global_index",
        "timestamp",
        "image_file",
        "status",
        "wall_seconds",
        "prompt_ms",
        "predicted_ms",
        "prompt_n",
        "predicted_n",
        "ocr_text",
        "error",
    ]

    write_tsv(
        out / "persistent30_results.tsv",
        rows,
        fields,
    )

    first = latencies[0] if latencies else None
    warm = latencies[1:] if len(latencies) > 1 else []

    summary = {
        "backend": a.backend,
        "device": a.device,
        "server_url": server_url,
        "model_id": model_id,
        "samples": len(rows),
        "server_startup_seconds": a.startup_seconds,
        "first_request_seconds": first,
        "warm_requests": len(warm),
        "warm_mean_seconds": (
            statistics.mean(warm) if warm else None
        ),
        "warm_median_seconds": (
            statistics.median(warm) if warm else None
        ),
        "warm_p95_seconds": (
            percentile(warm, 0.95) if warm else None
        ),
        "warm_images_per_second": (
            1.0 / statistics.mean(warm)
            if warm and statistics.mean(warm) > 0
            else None
        ),
        "all_mean_seconds": (
            statistics.mean(latencies) if latencies else None
        ),
        "gpu_sampling": gpu,
        "prompt": PROMPT,
    }

    (out / "persistent30_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def f(v, digits=3):
        if v is None:
            return "n/a"
        return f"{v:.{digits}f}"

    lines = [
        "Naruto PSP Stage38A Persistent-30",
        "=" * 72,
        "",
        f"Backend: {a.backend}",
        f"Device: {a.device}",
        f"Model ID: {model_id}",
        "",
        f"Samples: {len(rows)}",
        f"Server startup: {f(a.startup_seconds)} s",
        f"First request: {f(first)} s",
        "",
        "Warm requests (2-30):",
        f"  count: {len(warm)}",
        f"  mean: {f(summary['warm_mean_seconds'])} s/image",
        f"  median: {f(summary['warm_median_seconds'])} s/image",
        f"  p95: {f(summary['warm_p95_seconds'])} s/image",
        f"  throughput: {f(summary['warm_images_per_second'])} image/s",
        "",
        "GPU sampling:",
        f"  mean utilization: {f(gpu['gpu_util_mean_percent'], 1)} %",
        f"  peak utilization: {f(gpu['gpu_util_peak_percent'], 1)} %",
        (
            "  peak VRAM: n/a"
            if gpu["vram_peak_mib"] is None
            else f"  peak VRAM: {gpu['vram_peak_mib']} MiB"
        ),
    ]

    (out / "persistent30_summary.txt").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("PERSISTENT-30 COMPLETE")
    print("=" * 72)
    print("First:", f(first), "s")
    print("Warm mean:", f(summary["warm_mean_seconds"]), "s/image")
    print("Warm median:", f(summary["warm_median_seconds"]), "s/image")
    print("Warm p95:", f(summary["warm_p95_seconds"]), "s/image")
    print("Throughput:", f(summary["warm_images_per_second"]), "image/s")
    if gpu["vram_peak_mib"] is not None:
        print("Peak VRAM:", gpu["vram_peak_mib"], "MiB")


if __name__ == "__main__":
    main()
