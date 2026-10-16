$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage37"
$videoDir = Join-Path $stage "video"
$framesDir = Join-Path $stage "frames"
$cropsDir = Join-Path $stage "crops"
$toolsDir = Join-Path $base "tools"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path `
    $stage,$videoDir,$framesDir,$cropsDir,$toolsDir,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage37_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
}

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    if (Test-Path -LiteralPath $runLog) {
        Copy-Item -LiteralPath $runLog -Destination $failDir -Force
    }

    Get-ChildItem -LiteralPath $stage -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -in @(".txt",".tsv",".json",".jpg",".png",".py")
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
        }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 37 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

function RunPython {
    param(
        [string]$Label,
        [string[]]$PythonArgs
    )

    Log ""
    Log "===== $Label ====="

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python @PythonArgs 2>&1 |
        ForEach-Object { Log "$_" }

    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    return $code
}

try {
    Log "Naruto PSP Stage 37"
    Log "YouTube dialogue-completion frame extractor"
    Log "Started: $(Get-Date)"

    # ========================================================
    # Python dependencies
    # ========================================================

    Log ""
    Log "[0/4] Python dependencies"

    & python -c "import cv2, numpy" 2>$null

    if ($LASTEXITCODE -ne 0) {
        Log "OpenCV / NumPy 설치 중..."
        Log "Python 3.9 호환 버전 고정"

        $code = RunPython `
            "pip install opencv/numpy" `
            @(
                "-m","pip","install",
                "--user",
                "numpy==1.26.4",
                "opencv-python-headless==4.10.0.84"
            )

        if ($code -ne 0) {
            throw "OpenCV/NumPy 설치 실패"
        }
    }
    else {
        Log "OpenCV / NumPy: OK"
    }

    # ========================================================
    # yt-dlp standalone
    # ========================================================

    $yt = Join-Path $toolsDir "yt-dlp.exe"

    if (-not (Test-Path -LiteralPath $yt)) {
        Log ""
        Log "yt-dlp.exe 다운로드 중..."

        $url = "httpLOCAL_PATH"

        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue

        if ($curl) {
            & curl.exe `
                -L `
                --fail `
                --retry 3 `
                --connect-timeout 20 `
                -o $yt `
                $url

            if ($LASTEXITCODE -ne 0) {
                Remove-Item -LiteralPath $yt -Force -ErrorAction SilentlyContinue
            }
        }

        if (-not (Test-Path -LiteralPath $yt)) {
            try {
                [Net.ServicePointManager]::SecurityProtocol = `
                    [Net.SecurityProtocolType]::Tls12

                Invoke-WebRequest `
                    -Uri $url `
                    -OutFile $yt `
                    -UseBasicParsing
            }
            catch {
                throw "yt-dlp.exe 다운로드 실패: $($_.Exception.Message)"
            }
        }
    }

    if (-not (Test-Path -LiteralPath $yt)) {
        throw "yt-dlp.exe 없음"
    }

    Log "yt-dlp: $yt"

    # ========================================================
    # Source video
    # ========================================================

    $source = Get-ChildItem `
        -LiteralPath $videoDir `
        -File `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "source_video.*" -and
            $_.Extension -in @(".mp4",".mkv",".webm")
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $source) {
        Log ""
        Log "[1/4] YouTube 영상 다운로드"
        Log "URL: httpLOCAL_PATH"
        Log "프레임 추출 목적이라 오디오는 받지 않습니다."

        $outputTemplate = Join-Path $videoDir "source_video.%(ext)s"

        $oldPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"

        & $yt `
            --no-playlist `
            --windows-filenames `
            --no-part `
            -f "bestvideo[height<=1080][ext=mp4]/best[height<=1080][ext=mp4]/best[height<=1080]/best" `
            -o $outputTemplate `
            "httpLOCAL_PATH" 2>&1 |
            ForEach-Object { Log "$_" }

        $ytCode = $LASTEXITCODE
        $ErrorActionPreference = $oldPref

        if ($ytCode -ne 0) {
            throw @"
YouTube 다운로드 실패.

직접 받은 영상을 아래 위치에 넣고 Stage37을 다시 실행해도 됩니다.
$videoDir\source_video.mp4
"@
        }

        $source = Get-ChildItem `
            -LiteralPath $videoDir `
            -File |
            Where-Object {
                $_.Name -like "source_video.*" -and
                $_.Extension -in @(".mp4",".mkv",".webm")
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }
    else {
        Log ""
        Log "[1/4] 기존 영상 재사용"
        Log $source.FullName
    }

    if (-not $source) {
        throw "source_video 파일을 찾지 못했습니다."
    }

    # ========================================================
    # Analyzer
    # ========================================================

    $analyzer = Join-Path $stage "stage37_extract_completed_dialogues.py"

    $analyzerCode = @'
from pathlib import Path
from collections import deque
import csv
import hashlib
import json
import math
import os
import sys
import time
import traceback

import cv2
import numpy as np


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage37"
VIDEO_DIR = OUT / "video"
FRAMES_DIR = OUT / "frames"
CROPS_DIR = OUT / "crops"

SAMPLE_FPS = 10.0
REFERENCE_H = 720

# Completion detector.
MIN_ACTIVE_INK_RATIO = 0.00065
STABLE_CHANGE_RATIO = 0.0018
TYPING_CHANGE_RATIO = 0.0040
STABLE_INK_DELTA_RATIO = 0.0012
MIN_STABLE_SECONDS = 0.75
MAX_STABLE_WAIT_SECONDS = 3.0

# Candidate cleanup.
PARTIAL_LOOKAHEAD_SECONDS = 6.0
PARTIAL_CONTAINMENT = 0.72
DUPLICATE_SECONDS = 15.0
DUPLICATE_XOR_RATIO = 0.012

# Auto ROI search in lower screen.
ROI_X0 = 0.035
ROI_X1 = 0.965
ROI_Y_STARTS = [0.52, 0.56, 0.60, 0.64, 0.68]
ROI_HEIGHT = 0.30

CONTACT_SHEET_COUNT = 24


def hms(seconds):
    ms = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)
    s = whole % 60
    m = (whole // 60) % 60
    h = whole // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def safe_ts(seconds):
    return hms(seconds).replace(":", "-").replace(".", "_")


def write_tsv(path, rows, fields):
    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)


def source_video():
    files = []

    for ext in ("*.mp4", "*.mkv", "*.webm"):
        files.extend(VIDEO_DIR.glob("source_video" + ext[1:]))

    files = [
        p for p in files
        if p.is_file()
    ]

    if not files:
        raise RuntimeError(
            f"source_video 없음: {VIDEO_DIR}"
        )

    files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return files[0]


def open_video(path):
    cap = cv2.VideoCapture(str(path))

    if not cap.isOpened():
        raise RuntimeError(
            f"OpenCV video open 실패: {path}"
        )

    fps = float(
        cap.get(cv2.CAP_PROP_FPS)
    )

    frame_count = int(
        cap.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    width = int(
        cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    height = int(
        cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(
            "invalid video metadata: "
            f"fps={fps} size={width}x{height}"
        )

    duration = (
        frame_count / fps
        if frame_count > 0
        else 0
    )

    return (
        cap,
        fps,
        frame_count,
        width,
        height,
        duration,
    )


def largest_segment(mask):
    best = None
    start = None

    for i, v in enumerate(
        list(mask) + [False]
    ):
        if v and start is None:
            start = i

        elif not v and start is not None:
            end = i

            if best is None or end - start > best[1] - best[0]:
                best = (start, end)

            start = None

    return best


def read_frame_at(cap, frame_index):
    cap.set(
        cv2.CAP_PROP_POS_FRAMES,
        int(frame_index),
    )

    ok, frame = cap.read()

    if not ok or frame is None:
        return None

    return frame


def sample_calibration_frames(
    cap,
    frame_count,
    fps,
    duration,
):
    if frame_count <= 0:
        targets = [
            int(fps * t)
            for t in (5, 15, 30, 60, 120)
        ]
    else:
        # Spread samples through the video, skipping the very first/last.
        count = 24

        targets = [
            int(
                frame_count
                * (
                    0.03
                    + 0.94
                    * i
                    / max(1, count - 1)
                )
            )
            for i in range(count)
        ]

    frames = []

    for idx in targets:
        if frame_count > 0:
            idx = min(
                max(0, idx),
                frame_count - 1,
            )

        frame = read_frame_at(
            cap,
            idx,
        )

        if frame is not None:
            frames.append(frame)

    cap.set(
        cv2.CAP_PROP_POS_FRAMES,
        0,
    )

    if not frames:
        raise RuntimeError(
            "calibration frame 추출 실패"
        )

    return frames


def detect_active_rect(frames):
    # Detect black letter/pillar bars from several frames.
    resized = []

    for frame in frames:
        h, w = frame.shape[:2]
        scale = min(
            1.0,
            640.0 / max(w, 1),
        )

        if scale != 1.0:
            f = cv2.resize(
                frame,
                (
                    int(round(w * scale)),
                    int(round(h * scale)),
                ),
                interpolation=cv2.INTER_AREA,
            )
        else:
            f = frame

        gray = cv2.cvtColor(
            f,
            cv2.COLOR_BGR2GRAY,
        )

        resized.append(gray)

    # All calibration frames share source dimensions, thus same resized dims.
    stack = np.stack(resized, axis=0)

    # A bar is dark in nearly every frame.
    nonblack = stack > 12

    col_activity = np.median(
        np.mean(nonblack, axis=1),
        axis=0,
    )

    row_activity = np.median(
        np.mean(nonblack, axis=2),
        axis=0,
    )

    cols = col_activity > 0.12
    rows = row_activity > 0.12

    cseg = largest_segment(cols)
    rseg = largest_segment(rows)

    rh, rw = resized[0].shape[:2]

    if cseg is None:
        cseg = (0, rw)

    if rseg is None:
        rseg = (0, rh)

    x0, x1 = cseg
    y0, y1 = rseg

    # Ignore tiny detected trims.
    if x0 < 0.015 * rw:
        x0 = 0

    if rw - x1 < 0.015 * rw:
        x1 = rw

    if y0 < 0.015 * rh:
        y0 = 0

    if rh - y1 < 0.015 * rh:
        y1 = rh

    # Return normalized active coordinates.
    return (
        x0 / rw,
        y0 / rh,
        x1 / rw,
        y1 / rh,
    )


def active_crop(frame, active_norm):
    h, w = frame.shape[:2]
    ax0, ay0, ax1, ay1 = active_norm

    x0 = int(round(ax0 * w))
    y0 = int(round(ay0 * h))
    x1 = int(round(ax1 * w))
    y1 = int(round(ay1 * h))

    x0 = max(0, min(w - 1, x0))
    y0 = max(0, min(h - 1, y0))
    x1 = max(x0 + 1, min(w, x1))
    y1 = max(y0 + 1, min(h, y1))

    return frame[y0:y1, x0:x1]


def light_panel_score(crop):
    if crop.size == 0:
        return 0.0

    small = cv2.resize(
        crop,
        (
            max(1, crop.shape[1] // 4),
            max(1, crop.shape[0] // 4),
        ),
        interpolation=cv2.INTER_AREA,
    )

    hsv = cv2.cvtColor(
        small,
        cv2.COLOR_BGR2HSV,
    )

    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    neutral_light = (
        (sat < 85)
        & (val > 125)
    )

    return float(
        np.mean(neutral_light)
    )


def detect_dialogue_roi(
    frames,
    active_norm,
):
    candidates = []

    for y0 in ROI_Y_STARTS:
        y1 = min(
            0.98,
            y0 + ROI_HEIGHT,
        )

        scores = []

        for frame in frames:
            active = active_crop(
                frame,
                active_norm,
            )

            ah, aw = active.shape[:2]

            x0 = int(
                round(
                    ROI_X0 * aw
                )
            )

            x1 = int(
                round(
                    ROI_X1 * aw
                )
            )

            yy0 = int(
                round(
                    y0 * ah
                )
            )

            yy1 = int(
                round(
                    y1 * ah
                )
            )

            crop = active[
                yy0:yy1,
                x0:x1,
            ]

            scores.append(
                light_panel_score(
                    crop
                )
            )

        score = float(
            np.median(
                scores
            )
        )

        candidates.append({
            "x0": ROI_X0,
            "y0": y0,
            "x1": ROI_X1,
            "y1": y1,
            "score": score,
        })

    candidates.sort(
        key=lambda x: -x["score"]
    )

    best = candidates[0]

    # If no light dialogue panel is obvious, use broad lower screen.
    if best["score"] < 0.12:
        best = {
            "x0": 0.035,
            "y0": 0.60,
            "x1": 0.965,
            "y1": 0.97,
            "score": best["score"],
            "fallback": True,
        }
    else:
        best["fallback"] = False

    return best, candidates


def crop_dialogue(
    frame,
    active_norm,
    roi_norm,
):
    h, w = frame.shape[:2]
    ax0, ay0, ax1, ay1 = active_norm

    active_x0 = int(round(ax0 * w))
    active_y0 = int(round(ay0 * h))
    active_x1 = int(round(ax1 * w))
    active_y1 = int(round(ay1 * h))

    aw = active_x1 - active_x0
    ah = active_y1 - active_y0

    x0 = active_x0 + int(
        round(
            roi_norm["x0"] * aw
        )
    )
    y0 = active_y0 + int(
        round(
            roi_norm["y0"] * ah
        )
    )
    x1 = active_x0 + int(
        round(
            roi_norm["x1"] * aw
        )
    )
    y1 = active_y0 + int(
        round(
            roi_norm["y1"] * ah
        )
    )

    x0 = max(0, min(w - 1, x0))
    y0 = max(0, min(h - 1, y0))
    x1 = max(x0 + 1, min(w, x1))
    y1 = max(y0 + 1, min(h, y1))

    return (
        frame[y0:y1, x0:x1],
        (x0, y0, x1, y1),
    )


def normalize_crop(crop):
    h, w = crop.shape[:2]

    if h <= 0 or w <= 0:
        raise RuntimeError(
            "empty ROI"
        )

    scale = REFERENCE_H / 720.0

    # Keep roughly 1000px wide at 720p regardless of source resolution.
    target_w = 1000
    target_h = max(
        80,
        int(
            round(
                target_w
                * h
                / w
            )
        ),
    )

    return cv2.resize(
        crop,
        (
            target_w,
            target_h,
        ),
        interpolation=cv2.INTER_AREA,
    )


def text_mask(crop):
    ref = normalize_crop(
        crop
    )

    gray = cv2.cvtColor(
        ref,
        cv2.COLOR_BGR2GRAY,
    )

    # Black-hat isolates dark text strokes over the light/translucent
    # dialogue panel and suppresses slow background illumination changes.
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (19, 19),
    )

    blackhat = cv2.morphologyEx(
        gray,
        cv2.MORPH_BLACKHAT,
        kernel,
    )

    # Otsu, but never use an extremely low threshold.
    otsu, mask = cv2.threshold(
        blackhat,
        0,
        255,
        cv2.THRESH_BINARY
        | cv2.THRESH_OTSU,
    )

    threshold_value = max(
        14.0,
        float(otsu),
    )

    _, mask = cv2.threshold(
        blackhat,
        threshold_value,
        255,
        cv2.THRESH_BINARY,
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        np.ones(
            (2, 2),
            dtype=np.uint8,
        ),
    )

    # Keep character-sized connected components.
    count, labels, stats, _ = (
        cv2.connectedComponentsWithStats(
            mask,
            connectivity=8,
        )
    )

    filtered = np.zeros_like(
        mask
    )

    ref_scale = (
        ref.shape[0]
        / max(
            1.0,
            crop.shape[0],
        )
    )

    for i in range(1, count):
        x, y, w, h, area = stats[i]

        if area < 4:
            continue

        if area > 850:
            continue

        if h < 2 or w < 1:
            continue

        if h > 55 or w > 95:
            continue

        filtered[
            labels == i
        ] = 255

    return filtered


def downsample_mask(mask):
    small = cv2.resize(
        mask,
        (250, 60),
        interpolation=cv2.INTER_AREA,
    )

    return (
        small > 64
    )


def mask_metrics(
    current,
    previous,
):
    area = float(
        current.size
    )

    ink = int(
        np.count_nonzero(
            current
        )
    )

    ink_ratio = (
        ink / area
    )

    if previous is None:
        return {
            "ink": ink,
            "ink_ratio": ink_ratio,
            "change_ratio": 1.0,
            "ink_delta_ratio": ink_ratio,
        }

    xor = cv2.bitwise_xor(
        current,
        previous,
    )

    change_ratio = (
        np.count_nonzero(
            xor
        )
        / area
    )

    prev_ink = int(
        np.count_nonzero(
            previous
        )
    )

    ink_delta_ratio = (
        abs(
            ink - prev_ink
        )
        / area
    )

    return {
        "ink": ink,
        "ink_ratio": ink_ratio,
        "change_ratio": change_ratio,
        "ink_delta_ratio": ink_delta_ratio,
    }


def candidate_mask_relation(
    a,
    b,
):
    ma = a["small_mask"]
    mb = b["small_mask"]

    ia = int(
        np.count_nonzero(
            ma
        )
    )

    ib = int(
        np.count_nonzero(
            mb
        )
    )

    inter = int(
        np.count_nonzero(
            ma & mb
        )
    )

    xor = int(
        np.count_nonzero(
            ma ^ mb
        )
    )

    area = float(
        ma.size
    )

    containment = (
        inter / max(1, ia)
    )

    return {
        "a_ink": ia,
        "b_ink": ib,
        "containment": containment,
        "xor_ratio": xor / area,
    }


def prune_candidates(candidates):
    if not candidates:
        return [], []

    keep = [True] * len(candidates)
    reasons = [""] * len(candidates)

    # Remove early partial typewriter pauses when a shortly-later crop
    # contains almost all previous ink plus noticeably more text.
    for i in range(len(candidates) - 1):
        if not keep[i]:
            continue

        a = candidates[i]

        for j in range(
            i + 1,
            min(
                len(candidates),
                i + 6,
            ),
        ):
            b = candidates[j]
            dt = b["timestamp"] - a["timestamp"]

            if dt > PARTIAL_LOOKAHEAD_SECONDS:
                break

            rel = candidate_mask_relation(
                a,
                b,
            )

            if (
                rel["containment"] >= PARTIAL_CONTAINMENT
                and rel["b_ink"] >= rel["a_ink"] * 1.05
            ):
                keep[i] = False
                reasons[i] = (
                    "partial_before_larger_same_text"
                )
                break

    # Remove near-identical repeats in a short window.
    last_kept = None

    for i, cand in enumerate(candidates):
        if not keep[i]:
            continue

        if last_kept is not None:
            prev = candidates[
                last_kept
            ]

            dt = (
                cand["timestamp"]
                - prev["timestamp"]
            )

            if dt <= DUPLICATE_SECONDS:
                rel = candidate_mask_relation(
                    prev,
                    cand,
                )

                if (
                    rel["xor_ratio"]
                    <= DUPLICATE_XOR_RATIO
                ):
                    keep[i] = False
                    reasons[i] = (
                        "near_duplicate"
                    )
                    continue

        last_kept = i

    accepted = []
    rejected = []

    for i, cand in enumerate(candidates):
        row = dict(cand)
        row["reject_reason"] = reasons[i]

        if keep[i]:
            accepted.append(row)
        else:
            rejected.append(row)

    return accepted, rejected


def scan_video(
    path,
    active_norm,
    roi_norm,
):
    (
        cap,
        fps,
        frame_count,
        width,
        height,
        duration,
    ) = open_video(path)

    stride = max(
        1,
        int(
            round(
                fps / SAMPLE_FPS
            )
        ),
    )

    effective_sample_fps = (
        fps / stride
    )

    stable_needed = max(
        1,
        int(
            math.ceil(
                MIN_STABLE_SECONDS
                * effective_sample_fps
            )
        ),
    )

    stable_force = max(
        stable_needed,
        int(
            math.ceil(
                MAX_STABLE_WAIT_SECONDS
                * effective_sample_fps
            )
        ),
    )

    print()
    print(
        f"Video: {width}x{height} "
        f"fps={fps:.3f} "
        f"frames={frame_count} "
        f"duration={hms(duration)}"
    )
    print(
        f"Sampling: every {stride} frames "
        f"({effective_sample_fps:.2f} fps)"
    )
    print(
        f"Stable: {stable_needed} samples "
        f"({MIN_STABLE_SECONDS:.2f}s)"
    )
    print()

    previous_mask = None

    stable_count = 0
    stable_start_time = None
    had_typing = False
    active_seen = False
    current_saved = False

    candidate_snapshot = None
    candidates = []

    frame_index = 0
    sample_index = 0
    last_progress = -1

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        if frame_index % stride != 0:
            frame_index += 1
            continue

        timestamp = (
            frame_index / fps
        )

        crop, roi_px = crop_dialogue(
            frame,
            active_norm,
            roi_norm,
        )

        mask = text_mask(
            crop
        )

        metrics = mask_metrics(
            mask,
            previous_mask,
        )

        active = (
            metrics["ink_ratio"]
            >= MIN_ACTIVE_INK_RATIO
        )

        stable = (
            active
            and previous_mask is not None
            and metrics["change_ratio"]
            <= STABLE_CHANGE_RATIO
            and metrics["ink_delta_ratio"]
            <= STABLE_INK_DELTA_RATIO
        )

        typing = (
            active
            and metrics["change_ratio"]
            >= TYPING_CHANGE_RATIO
        )

        if active and not active_seen:
            active_seen = True
            had_typing = True
            stable_count = 0
            current_saved = False

        if typing:
            # If a complete stable line existed and text now changes,
            # preserve the final stable snapshot.
            if (
                candidate_snapshot is not None
                and stable_count >= stable_needed
                and not current_saved
            ):
                candidates.append(
                    candidate_snapshot
                )
                current_saved = True

            stable_count = 0
            stable_start_time = None
            candidate_snapshot = None
            had_typing = True
            current_saved = False

        elif stable:
            if stable_count == 0:
                stable_start_time = timestamp

            stable_count += 1

            candidate_snapshot = {
                "raw_candidate_index":
                    len(candidates) + 1,
                "frame_index":
                    frame_index,
                "timestamp":
                    timestamp,
                "timestamp_text":
                    hms(timestamp),
                "stable_seconds":
                    stable_count
                    / effective_sample_fps,
                "ink_pixels":
                    metrics["ink"],
                "ink_ratio":
                    metrics["ink_ratio"],
                "change_ratio":
                    metrics["change_ratio"],
                "roi_x0":
                    roi_px[0],
                "roi_y0":
                    roi_px[1],
                "roi_x1":
                    roi_px[2],
                "roi_y1":
                    roi_px[3],
                "small_mask":
                    downsample_mask(
                        mask
                    ),
            }

            # Very long hold: save once even if there is no next change.
            if (
                stable_count >= stable_force
                and had_typing
                and not current_saved
            ):
                candidates.append(
                    candidate_snapshot
                )
                current_saved = True

        elif not active:
            if (
                candidate_snapshot is not None
                and stable_count >= stable_needed
                and had_typing
                and not current_saved
            ):
                candidates.append(
                    candidate_snapshot
                )

            stable_count = 0
            stable_start_time = None
            candidate_snapshot = None
            had_typing = False
            active_seen = False
            current_saved = False

        else:
            # Ambiguous small movement.
            if stable_count > 0:
                stable_count = max(
                    0,
                    stable_count - 1,
                )

        previous_mask = mask
        sample_index += 1

        sec = int(
            timestamp
        )

        if (
            sec // 30
            != last_progress
        ):
            last_progress = sec // 30

            if duration > 0:
                pct = (
                    100.0
                    * timestamp
                    / duration
                )
            else:
                pct = 0.0

            print(
                f"[{hms(timestamp)}] "
                f"{pct:5.1f}% "
                f"candidates={len(candidates)} "
                f"ink={metrics['ink_ratio']:.4f} "
                f"chg={metrics['change_ratio']:.4f}"
            )

        frame_index += 1

    # End-of-video pending stable line.
    if (
        candidate_snapshot is not None
        and stable_count >= stable_needed
        and had_typing
        and not current_saved
    ):
        candidates.append(
            candidate_snapshot
        )

    cap.release()

    accepted, rejected = prune_candidates(
        candidates
    )

    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
        "stride": stride,
        "sample_fps": effective_sample_fps,
        "stable_needed": stable_needed,
        "raw_candidates": candidates,
        "accepted": accepted,
        "rejected": rejected,
    }


def save_selected_frames(
    path,
    accepted,
    active_norm,
    roi_norm,
):
    FRAMES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CROPS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for p in FRAMES_DIR.glob("*"):
        if p.is_file():
            p.unlink()

    for p in CROPS_DIR.glob("*"):
        if p.is_file():
            p.unlink()

    if not accepted:
        return []

    by_frame = {
        int(row["frame_index"]):
            (idx, row)
        for idx, row
        in enumerate(
            accepted,
            1,
        )
    }

    targets = sorted(
        by_frame
    )

    cap = cv2.VideoCapture(
        str(path)
    )

    if not cap.isOpened():
        raise RuntimeError(
            "video reopen failed"
        )

    fps = float(
        cap.get(
            cv2.CAP_PROP_FPS
        )
    )

    saved = []
    target_pos = 0
    frame_index = 0

    while (
        target_pos < len(targets)
    ):
        target = targets[
            target_pos
        ]

        # Fast seek near target if there's a large gap.
        if target - frame_index > int(
            fps * 20
        ):
            cap.set(
                cv2.CAP_PROP_POS_FRAMES,
                target,
            )
            frame_index = target

        ok, frame = cap.read()

        if not ok:
            break

        if frame_index == target:
            out_index, row = by_frame[
                target
            ]

            ts = row[
                "timestamp"
            ]

            stem = (
                f"{out_index:05d}_"
                f"{safe_ts(ts)}"
            )

            frame_path = (
                FRAMES_DIR
                / f"{stem}.jpg"
            )

            crop_path = (
                CROPS_DIR
                / f"{stem}.jpg"
            )

            crop, roi_px = crop_dialogue(
                frame,
                active_norm,
                roi_norm,
            )

            cv2.imwrite(
                str(frame_path),
                frame,
                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    92,
                ],
            )

            cv2.imwrite(
                str(crop_path),
                crop,
                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    95,
                ],
            )

            saved.append({
                **{
                    k: v
                    for k, v
                    in row.items()
                    if k != "small_mask"
                },
                "dialogue_index":
                    out_index,
                "frame_file":
                    str(frame_path),
                "crop_file":
                    str(crop_path),
            })

            target_pos += 1

        frame_index += 1

    cap.release()

    return saved


def contact_sheet(saved):
    if not saved:
        return None

    subset = saved[
        :CONTACT_SHEET_COUNT
    ]

    tiles = []

    tile_w = 480
    tile_h = 150
    label_h = 28

    for row in subset:
        img = cv2.imread(
            row[
                "crop_file"
            ]
        )

        if img is None:
            continue

        ih, iw = img.shape[:2]

        scale = min(
            tile_w / iw,
            tile_h / ih,
        )

        nw = max(
            1,
            int(
                round(
                    iw * scale
                )
            ),
        )

        nh = max(
            1,
            int(
                round(
                    ih * scale
                )
            ),
        )

        resized = cv2.resize(
            img,
            (nw, nh),
            interpolation=cv2.INTER_AREA,
        )

        canvas = np.zeros(
            (
                tile_h + label_h,
                tile_w,
                3,
            ),
            dtype=np.uint8,
        )

        canvas[:] = 245

        x = (
            tile_w - nw
        ) // 2

        y = label_h + (
            tile_h - nh
        ) // 2

        canvas[
            y:y + nh,
            x:x + nw,
        ] = resized

        text = (
            f"{row['dialogue_index']:05d}  "
            f"{row['timestamp_text']}"
        )

        cv2.putText(
            canvas,
            text,
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )

        tiles.append(
            canvas
        )

    if not tiles:
        return None

    cols = 4
    rows = int(
        math.ceil(
            len(tiles) / cols
        )
    )

    blank = np.full_like(
        tiles[0],
        245,
    )

    while len(tiles) < rows * cols:
        tiles.append(
            blank.copy()
        )

    row_imgs = []

    for r in range(rows):
        row_imgs.append(
            np.hstack(
                tiles[
                    r * cols:
                    (r + 1) * cols
                ]
            )
        )

    sheet = np.vstack(
        row_imgs
    )

    path = (
        OUT
        / "stage37_contact_sheet.jpg"
    )

    cv2.imwrite(
        str(path),
        sheet,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            92,
        ],
    )

    return path


def roi_preview(
    frame,
    active_norm,
    roi_norm,
):
    out = frame.copy()

    h, w = frame.shape[:2]
    ax0, ay0, ax1, ay1 = active_norm

    a0 = (
        int(round(ax0 * w)),
        int(round(ay0 * h)),
    )

    a1 = (
        int(round(ax1 * w)),
        int(round(ay1 * h)),
    )

    cv2.rectangle(
        out,
        a0,
        a1,
        (255, 255, 255),
        2,
    )

    _, roi_px = crop_dialogue(
        frame,
        active_norm,
        roi_norm,
    )

    x0, y0, x1, y1 = roi_px

    cv2.rectangle(
        out,
        (x0, y0),
        (x1, y1),
        (0, 0, 255),
        3,
    )

    path = (
        OUT
        / "stage37_roi_preview.jpg"
    )

    cv2.imwrite(
        str(path),
        out,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            92,
        ],
    )

    return path


def main():
    video = source_video()

    print("=" * 72)
    print("Naruto PSP Stage 37")
    print("Dialogue completion frame extractor")
    print("=" * 72)
    print("Video:", video)

    (
        cap,
        fps,
        frame_count,
        width,
        height,
        duration,
    ) = open_video(
        video
    )

    calibration = sample_calibration_frames(
        cap,
        frame_count,
        fps,
        duration,
    )

    active_norm = detect_active_rect(
        calibration
    )

    roi_norm, roi_candidates = (
        detect_dialogue_roi(
            calibration,
            active_norm,
        )
    )

    print()
    print(
        "Active content:",
        ",".join(
            f"{x:.4f}"
            for x in active_norm
        )
    )

    print(
        "Dialogue ROI:",
        (
            f"x={roi_norm['x0']:.3f}..{roi_norm['x1']:.3f} "
            f"y={roi_norm['y0']:.3f}..{roi_norm['y1']:.3f} "
            f"score={roi_norm['score']:.3f} "
            f"fallback={roi_norm['fallback']}"
        )
    )

    preview_frame = calibration[
        len(calibration) // 2
    ]

    preview = roi_preview(
        preview_frame,
        active_norm,
        roi_norm,
    )

    cap.release()

    scan = scan_video(
        video,
        active_norm,
        roi_norm,
    )

    saved = save_selected_frames(
        video,
        scan["accepted"],
        active_norm,
        roi_norm,
    )

    sheet = contact_sheet(
        saved
    )

    candidate_fields = [
        "dialogue_index",
        "frame_index",
        "timestamp",
        "timestamp_text",
        "stable_seconds",
        "ink_pixels",
        "ink_ratio",
        "change_ratio",
        "roi_x0",
        "roi_y0",
        "roi_x1",
        "roi_y1",
        "frame_file",
        "crop_file",
    ]

    write_tsv(
        OUT
        / "stage37_dialogue_frames.tsv",
        saved,
        candidate_fields,
    )

    rejected_rows = []

    for row in scan[
        "rejected"
    ]:
        rejected_rows.append({
            k: v
            for k, v
            in row.items()
            if k != "small_mask"
        })

    write_tsv(
        OUT
        / "stage37_rejected_candidates.tsv",
        rejected_rows,
        [
            "raw_candidate_index",
            "frame_index",
            "timestamp",
            "timestamp_text",
            "stable_seconds",
            "ink_pixels",
            "ink_ratio",
            "change_ratio",
            "reject_reason",
        ],
    )

    config = {
        "video": str(video),
        "video_width": scan["width"],
        "video_height": scan["height"],
        "video_fps": scan["fps"],
        "video_frames": scan["frame_count"],
        "video_duration_seconds": scan["duration"],
        "video_duration": hms(
            scan["duration"]
        ),
        "sample_stride_frames": scan["stride"],
        "effective_sample_fps": scan["sample_fps"],
        "active_content_normalized": {
            "x0": active_norm[0],
            "y0": active_norm[1],
            "x1": active_norm[2],
            "y1": active_norm[3],
        },
        "dialogue_roi_normalized_to_active": roi_norm,
        "roi_candidates": roi_candidates,
        "thresholds": {
            "min_active_ink_ratio":
                MIN_ACTIVE_INK_RATIO,
            "stable_change_ratio":
                STABLE_CHANGE_RATIO,
            "typing_change_ratio":
                TYPING_CHANGE_RATIO,
            "stable_ink_delta_ratio":
                STABLE_INK_DELTA_RATIO,
            "min_stable_seconds":
                MIN_STABLE_SECONDS,
            "max_stable_wait_seconds":
                MAX_STABLE_WAIT_SECONDS,
        },
        "raw_candidates":
            len(
                scan[
                    "raw_candidates"
                ]
            ),
        "accepted_candidates":
            len(saved),
        "rejected_candidates":
            len(
                scan[
                    "rejected"
                ]
            ),
        "roi_preview":
            str(preview),
        "contact_sheet":
            str(sheet)
            if sheet
            else None,
    }

    (
        OUT
        / "stage37_config.json"
    ).write_text(
        json.dumps(
            config,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary_lines = [
        "Naruto PSP Stage 37",
        "=" * 72,
        "",
        "STATUS: FRAME_EXTRACTION_COMPLETE",
        "",
        f"Video: {video}",
        (
            f"Video: {scan['width']}x{scan['height']} "
            f"{scan['fps']:.3f} fps"
        ),
        f"Duration: {hms(scan['duration'])}",
        (
            f"Sampling: {scan['sample_fps']:.2f} fps "
            f"(stride {scan['stride']})"
        ),
        "",
        "Detection:",
        "  audio not used",
        "  circular advance icon not used",
        "  dialogue ROI auto-selected from lower-screen light panel",
        "  dark text strokes isolated with black-hat morphology",
        "  stable typewriter output detected from text-mask change",
        "  early partial pauses / near duplicates pruned",
        "",
        (
            "Active content normalized: "
            + ", ".join(
                f"{x:.4f}"
                for x in active_norm
            )
        ),
        (
            "Dialogue ROI: "
            f"x {roi_norm['x0']:.3f}..{roi_norm['x1']:.3f}, "
            f"y {roi_norm['y0']:.3f}..{roi_norm['y1']:.3f}"
        ),
        f"ROI light-panel score: {roi_norm['score']:.4f}",
        f"ROI fallback: {roi_norm['fallback']}",
        "",
        (
            "Raw completion candidates: "
            f"{len(scan['raw_candidates'])}"
        ),
        (
            "Accepted dialogue frames: "
            f"{len(saved)}"
        ),
        (
            "Rejected partial/duplicate candidates: "
            f"{len(scan['rejected'])}"
        ),
        "",
        "Outputs:",
        f"  frames: {FRAMES_DIR}",
        f"  crops: {CROPS_DIR}",
        f"  timeline: {OUT / 'stage37_dialogue_frames.tsv'}",
        f"  ROI preview: {preview}",
        (
            f"  contact sheet: {sheet}"
            if sheet
            else "  contact sheet: none"
        ),
        "",
        "Next:",
        "  inspect ROI preview + contact sheet.",
        "  If frame selection is good, Stage38 can OCR only these completed frames.",
    ]

    (
        OUT
        / "stage37_summary.txt"
    ).write_text(
        "\n".join(
            summary_lines
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE37 FRAME EXTRACTION COMPLETE")
    print("=" * 72)
    print(
        "Raw candidates:",
        len(
            scan[
                "raw_candidates"
            ]
        )
    )
    print(
        "Accepted:",
        len(saved)
    )
    print(
        "Rejected:",
        len(
            scan[
                "rejected"
            ]
        )
    )
    print()
    print("ROI preview:", preview)
    print("Contact sheet:", sheet)
    print("Timeline:", OUT / "stage37_dialogue_frames.tsv")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content `
        -LiteralPath $analyzer `
        -Value $analyzerCode `
        -Encoding UTF8

    $code = RunPython `
        "analyzer syntax" `
        @("-m","py_compile",$analyzer)

    if ($code -ne 0) {
        throw "Stage37 analyzer Python 문법 오류"
    }

    Log ""
    Log "[2/4] 영상 분석 / 대사 완성 프레임 검출"

    $code = RunPython `
        "frame extraction" `
        @("-u",$analyzer)

    if ($code -ne 0) {
        throw "Stage37 프레임 추출 실패"
    }

    $required = @(
        "stage37_summary.txt",
        "stage37_config.json",
        "stage37_dialogue_frames.tsv",
        "stage37_rejected_candidates.tsv",
        "stage37_roi_preview.jpg"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $name))) {
            throw "Stage37 결과 누락: $name"
        }
    }

    Log ""
    Log "[3/4] 결과 검증"

    $frameCount = (
        Get-ChildItem `
            -LiteralPath $framesDir `
            -Filter "*.jpg" `
            -File `
            -ErrorAction SilentlyContinue
    ).Count

    $cropCount = (
        Get-ChildItem `
            -LiteralPath $cropsDir `
            -Filter "*.jpg" `
            -File `
            -ErrorAction SilentlyContinue
    ).Count

    Log "frames: $frameCount"
    Log "crops:  $cropCount"

    if ($frameCount -ne $cropCount) {
        throw "frames/crops 개수 불일치"
    }

    if ($frameCount -eq 0) {
        throw "대사 완성 프레임을 하나도 검출하지 못했습니다."
    }

    # ========================================================
    # Success-only upload logs.
    # Do NOT include video or thousands of extracted frames.
    # ========================================================

    Log ""
    Log "[4/4] 업로드 ZIP 준비"

    $archive = Join-Path `
        $oldRoot `
        (Get-Date -Format "yyyyMMdd_HHmmss")

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $archive |
        Out-Null

    Get-ChildItem `
        -LiteralPath $logs `
        -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item `
                -LiteralPath $_.FullName `
                -Destination $archive `
                -Force
        }

    $uploadNames = @(
        "stage37_summary.txt",
        "stage37_config.json",
        "stage37_dialogue_frames.tsv",
        "stage37_rejected_candidates.tsv",
        "stage37_roi_preview.jpg",
        "stage37_contact_sheet.jpg"
    )

    foreach ($name in $uploadNames) {
        $p = Join-Path $stage $name

        if (Test-Path -LiteralPath $p) {
            Copy-Item `
                -LiteralPath $p `
                -Destination $logs `
                -Force
        }
    }

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 37"
        "생성: $(Get-Date)"
        ""
        "STATUS: FRAME_EXTRACTION_COMPLETE"
        ""
        "YouTube:"
        " httpLOCAL_PATH"
        ""
        "방식:"
        " - audio 미사용"
        " - 원형 진행 아이콘 미사용"
        " - 하단 대사창 ROI 자동 선택"
        " - 글자 타이핑 변화 -> 안정 구간 검출"
        " - 다음 변화 직전 완성 프레임 선정"
        " - 중간 타이핑 pause / 중복 후보 후처리 제거"
        ""
        "Extracted frames:"
        " $framesDir"
        ""
        "Extracted crops:"
        " $cropsDir"
        ""
        "먼저 ChatGPT에 업로드:"
        " naruto_stage37_upload.zip"
        ""
        "이 ZIP에는 원본 영상/전체 프레임은 넣지 않았습니다."
        "ROI preview와 첫 24개 contact sheet로 검출 품질을 확인합니다."
        ""
        "Previous successful logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path $logs "naruto_stage37_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage37_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 37 SUCCESS"
    Log "=========================================="
    Log "Extracted frames: $frameCount"
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
