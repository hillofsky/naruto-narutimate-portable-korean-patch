$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage37 = Join-Path $base "analysis\stage37"
$stage = Join-Path $base "analysis\stage37b"
$videoDir = Join-Path $stage37 "video"
$framesRoot = Join-Path $stage "frames"
$cropsRoot = Join-Path $stage "crops"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path `
    $stage,$framesRoot,$cropsRoot,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage37b_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
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

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    if (Test-Path -LiteralPath $runLog) {
        Copy-Item -LiteralPath $runLog -Destination $failDir -Force
    }

    Get-ChildItem -LiteralPath $stage -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -in @(".txt",".tsv",".json",".jpg",".py")
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
        }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 37B FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

try {
    Log "Naruto PSP Stage 37B"
    Log "Part2-only analysis + Part1/Part2 timeline merge"
    Log "Started: $(Get-Date)"

    $part1Tsv = Join-Path $stage37 "stage37_dialogue_frames.tsv"
    $stage37Analyzer = Join-Path $stage37 "stage37_extract_completed_dialogues.py"

    foreach ($p in @($part1Tsv,$stage37Analyzer)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 Stage37 파일 없음: $p"
        }
    }

    $part2 = Get-ChildItem `
        -LiteralPath $videoDir `
        -File `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.BaseName -eq "part2" -and
            $_.Extension.ToLower() -in @(".mp4",".mkv",".webm")
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $part2) {
        throw @"
Part2 영상을 찾지 못했습니다.

두 번째 영상을 아래 중 하나로 넣어주세요.
$videoDir\part2.mp4
$videoDir\part2.mkv
$videoDir\part2.webm

영상 URL:
httpLOCAL_PATH
"@
    }

    Log ""
    Log "Part2 video:"
    Log $part2.FullName

    $py = Join-Path $stage "stage37b_multipart.py"

    $codeText = @'
from pathlib import Path
import csv
import importlib.util
import json
import math
import os
import shutil
import sys
import traceback

import cv2
import numpy as np


BASE = Path(r"PROJECT_ROOT")
STAGE37 = BASE / "analysis" / "stage37"
OUT = BASE / "analysis" / "stage37b"

PART1_TSV = STAGE37 / "stage37_dialogue_frames.tsv"
ANALYZER = STAGE37 / "stage37_extract_completed_dialogues.py"
VIDEO_DIR = STAGE37 / "video"

FRAMES_ROOT = OUT / "frames"
CROPS_ROOT = OUT / "crops"

PART1_FRAMES = FRAMES_ROOT / "part1"
PART1_CROPS = CROPS_ROOT / "part1"
PART2_FRAMES = FRAMES_ROOT / "part2"
PART2_CROPS = CROPS_ROOT / "part2"
PART2_WORK = OUT / "part2_work"


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


def load_stage37():
    spec = importlib.util.spec_from_file_location(
        "stage37mod",
        ANALYZER,
    )

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_part2():
    for ext in (".mp4", ".mkv", ".webm"):
        p = VIDEO_DIR / ("part2" + ext)

        if p.exists():
            return p

    raise RuntimeError(
        "part2 video not found"
    )


def hardlink_or_copy(src, dst):
    src = Path(src)
    dst = Path(dst)

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if dst.exists():
        dst.unlink()

    try:
        os.link(
            src,
            dst,
        )
        return "hardlink"

    except OSError:
        shutil.copy2(
            src,
            dst,
        )
        return "copy"


def load_part1():
    rows = []

    with PART1_TSV.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        for row in reader:
            rows.append(row)

    if not rows:
        raise RuntimeError(
            "Stage37 Part1 TSV is empty"
        )

    return rows


def mirror_part1(rows):
    for d in (
        PART1_FRAMES,
        PART1_CROPS,
    ):
        if d.exists():
            shutil.rmtree(d)

        d.mkdir(
            parents=True,
            exist_ok=True,
        )

    mirrored = []
    hardlinks = 0
    copies = 0

    for index, row in enumerate(
        rows,
        1,
    ):
        src_frame = Path(
            row["frame_file"]
        )

        src_crop = Path(
            row["crop_file"]
        )

        if not src_frame.exists():
            raise RuntimeError(
                f"Part1 frame missing: {src_frame}"
            )

        if not src_crop.exists():
            raise RuntimeError(
                f"Part1 crop missing: {src_crop}"
            )

        dst_frame = (
            PART1_FRAMES
            / src_frame.name
        )

        dst_crop = (
            PART1_CROPS
            / src_crop.name
        )

        for src, dst in (
            (src_frame, dst_frame),
            (src_crop, dst_crop),
        ):
            mode = hardlink_or_copy(
                src,
                dst,
            )

            if mode == "hardlink":
                hardlinks += 1
            else:
                copies += 1

        mirrored.append({
            **row,
            "dialogue_index":
                index,
            "frame_file":
                str(dst_frame),
            "crop_file":
                str(dst_crop),
        })

    return mirrored, hardlinks, copies


def analyze_part2(mod, video):
    if PART2_WORK.exists():
        shutil.rmtree(
            PART2_WORK
        )

    if PART2_FRAMES.exists():
        shutil.rmtree(
            PART2_FRAMES
        )

    if PART2_CROPS.exists():
        shutil.rmtree(
            PART2_CROPS
        )

    PART2_WORK.mkdir(
        parents=True,
        exist_ok=True,
    )

    PART2_FRAMES.mkdir(
        parents=True,
        exist_ok=True,
    )

    PART2_CROPS.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Redirect Stage37 helper output to Stage37B Part2 work dirs.
    mod.OUT = PART2_WORK
    mod.FRAMES_DIR = PART2_FRAMES
    mod.CROPS_DIR = PART2_CROPS

    (
        cap,
        fps,
        frame_count,
        width,
        height,
        duration,
    ) = mod.open_video(
        video
    )

    calibration = mod.sample_calibration_frames(
        cap,
        frame_count,
        fps,
        duration,
    )

    active_norm = mod.detect_active_rect(
        calibration
    )

    roi_norm, roi_candidates = (
        mod.detect_dialogue_roi(
            calibration,
            active_norm,
        )
    )

    preview_frame = calibration[
        len(calibration) // 2
    ]

    preview_tmp = mod.roi_preview(
        preview_frame,
        active_norm,
        roi_norm,
    )

    cap.release()

    scan = mod.scan_video(
        video,
        active_norm,
        roi_norm,
    )

    saved = mod.save_selected_frames(
        video,
        scan["accepted"],
        active_norm,
        roi_norm,
    )

    sheet_tmp = mod.contact_sheet(
        saved
    )

    preview_out = (
        OUT
        / "stage37b_part2_roi_preview.jpg"
    )

    shutil.copy2(
        preview_tmp,
        preview_out,
    )

    sheet_out = None

    if sheet_tmp is not None:
        sheet_out = (
            OUT
            / "stage37b_part2_contact_sheet.jpg"
        )

        shutil.copy2(
            sheet_tmp,
            sheet_out,
        )

    fields = [
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
        OUT / "stage37b_part2.tsv",
        saved,
        fields,
    )

    rejected = []

    for row in scan["rejected"]:
        rejected.append({
            k: v
            for k, v in row.items()
            if k != "small_mask"
        })

    write_tsv(
        OUT / "stage37b_part2_rejected.tsv",
        rejected,
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

    info = {
        "video":
            str(video),
        "width":
            width,
        "height":
            height,
        "fps":
            fps,
        "frame_count":
            frame_count,
        "duration_seconds":
            duration,
        "active_content_normalized": {
            "x0": active_norm[0],
            "y0": active_norm[1],
            "x1": active_norm[2],
            "y1": active_norm[3],
        },
        "dialogue_roi":
            roi_norm,
        "roi_candidates":
            roi_candidates,
        "raw_candidates":
            len(
                scan[
                    "raw_candidates"
                ]
            ),
        "accepted":
            len(saved),
        "rejected":
            len(
                scan[
                    "rejected"
                ]
            ),
        "preview":
            str(preview_out),
        "contact_sheet":
            (
                str(sheet_out)
                if sheet_out
                else None
            ),
    }

    return saved, info


def merged_rows(
    part1,
    part2,
):
    merged = []
    global_index = 1

    for part_name, rows in (
        ("part1", part1),
        ("part2", part2),
    ):
        for part_index, row in enumerate(
            rows,
            1,
        ):
            merged.append({
                "global_index":
                    global_index,
                "video_part":
                    part_name,
                "part_index":
                    part_index,
                "timestamp_seconds":
                    row.get(
                        "timestamp",
                        ""
                    ),
                "timestamp":
                    row.get(
                        "timestamp_text",
                        ""
                    ),
                "frame_index":
                    row.get(
                        "frame_index",
                        ""
                    ),
                "stable_seconds":
                    row.get(
                        "stable_seconds",
                        ""
                    ),
                "ink_pixels":
                    row.get(
                        "ink_pixels",
                        ""
                    ),
                "ink_ratio":
                    row.get(
                        "ink_ratio",
                        ""
                    ),
                "change_ratio":
                    row.get(
                        "change_ratio",
                        ""
                    ),
                "frame_file":
                    row.get(
                        "frame_file",
                        ""
                    ),
                "crop_file":
                    row.get(
                        "crop_file",
                        ""
                    ),
            })

            global_index += 1

    return merged


def make_merged_sheet(
    part1,
    part2,
):
    # First 12 from each part gives a quick visual check
    # that both videos are represented.
    selected = []

    for name, rows in (
        ("P1", part1[:12]),
        ("P2", part2[:12]),
    ):
        for row in rows:
            selected.append(
                (
                    name,
                    row,
                )
            )

    if not selected:
        return None

    tile_w = 480
    tile_h = 150
    label_h = 28
    tiles = []

    for part, row in selected:
        img = cv2.imread(
            row["crop_file"]
        )

        if img is None:
            continue

        ih, iw = img.shape[:2]

        scale = min(
            tile_w / max(1, iw),
            tile_h / max(1, ih),
        )

        nw = max(
            1,
            int(round(iw * scale)),
        )

        nh = max(
            1,
            int(round(ih * scale)),
        )

        resized = cv2.resize(
            img,
            (nw, nh),
            interpolation=cv2.INTER_AREA,
        )

        canvas = np.full(
            (
                tile_h + label_h,
                tile_w,
                3,
            ),
            245,
            dtype=np.uint8,
        )

        x = (
            tile_w - nw
        ) // 2

        y = (
            label_h
            + (
                tile_h - nh
            ) // 2
        )

        canvas[
            y:y + nh,
            x:x + nw,
        ] = resized

        label = (
            f"{part}  "
            f"{row.get('timestamp_text', '')}"
        )

        cv2.putText(
            canvas,
            label,
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

    sheet_rows = []

    for r in range(rows):
        sheet_rows.append(
            np.hstack(
                tiles[
                    r * cols:
                    (r + 1) * cols
                ]
            )
        )

    sheet = np.vstack(
        sheet_rows
    )

    out = (
        OUT
        / "stage37b_merged_contact_sheet.jpg"
    )

    cv2.imwrite(
        str(out),
        sheet,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            92,
        ],
    )

    return out


def main():
    print("=" * 72)
    print("Naruto PSP Stage 37B")
    print("Part2-only analysis + multipart merge")
    print("=" * 72)

    if not PART1_TSV.exists():
        raise RuntimeError(
            f"Part1 Stage37 TSV missing: {PART1_TSV}"
        )

    if not ANALYZER.exists():
        raise RuntimeError(
            f"Stage37 analyzer missing: {ANALYZER}"
        )

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    FRAMES_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    CROPS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    part2_video = find_part2()

    print()
    print(
        "Part2:",
        part2_video
    )

    part1_raw = load_part1()

    print(
        "Part1 rows:",
        len(part1_raw)
    )

    part1, hardlinks, copies = mirror_part1(
        part1_raw
    )

    print(
        "Part1 mirror:",
        f"hardlinks={hardlinks}",
        f"copies={copies}",
    )

    mod = load_stage37()

    part2, part2_info = analyze_part2(
        mod,
        part2_video,
    )

    print(
        "Part2 accepted:",
        len(part2)
    )

    write_tsv(
        OUT / "stage37b_part1.tsv",
        part1,
        [
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
        ],
    )

    merged = merged_rows(
        part1,
        part2,
    )

    write_tsv(
        OUT / "stage37b_merged.tsv",
        merged,
        [
            "global_index",
            "video_part",
            "part_index",
            "timestamp_seconds",
            "timestamp",
            "frame_index",
            "stable_seconds",
            "ink_pixels",
            "ink_ratio",
            "change_ratio",
            "frame_file",
            "crop_file",
        ],
    )

    merged_sheet = make_merged_sheet(
        part1,
        part2,
    )

    part1_config_path = (
        STAGE37
        / "stage37_config.json"
    )

    part1_config = None

    if part1_config_path.exists():
        try:
            part1_config = json.loads(
                part1_config_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            part1_config = None

    summary = {
        "stage":
            "37B",
        "status":
            "MULTIPART_FRAME_EXTRACTION_COMPLETE",
        "part1": {
            "source":
                str(
                    STAGE37
                    / "video"
                ),
            "reused":
                True,
            "accepted":
                len(part1),
            "hardlinks_created":
                hardlinks,
            "copies_created":
                copies,
            "original_config":
                part1_config,
        },
        "part2":
            part2_info,
        "merged": {
            "accepted_total":
                len(merged),
            "part1":
                len(part1),
            "part2":
                len(part2),
            "timeline":
                str(
                    OUT
                    / "stage37b_merged.tsv"
                ),
            "contact_sheet":
                (
                    str(
                        merged_sheet
                    )
                    if merged_sheet
                    else None
                ),
        },
    }

    (
        OUT
        / "stage37b_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "Naruto PSP Stage 37B",
        "=" * 72,
        "",
        "STATUS: MULTIPART_FRAME_EXTRACTION_COMPLETE",
        "",
        "Part1:",
        "  existing Stage37 result reused; not re-analyzed",
        f"  accepted frames: {len(part1)}",
        (
            f"  mirror: hardlinks={hardlinks}, "
            f"copies={copies}"
        ),
        "",
        "Part2:",
        f"  video: {part2_video}",
        (
            f"  video: "
            f"{part2_info['width']}x{part2_info['height']} "
            f"{part2_info['fps']:.3f} fps"
        ),
        (
            f"  raw candidates: "
            f"{part2_info['raw_candidates']}"
        ),
        (
            f"  accepted: "
            f"{part2_info['accepted']}"
        ),
        (
            f"  rejected: "
            f"{part2_info['rejected']}"
        ),
        "",
        "Merged:",
        f"  total accepted: {len(merged)}",
        f"  Part1: {len(part1)}",
        f"  Part2: {len(part2)}",
        "",
        "Outputs:",
        f"  Part1 TSV: {OUT / 'stage37b_part1.tsv'}",
        f"  Part2 TSV: {OUT / 'stage37b_part2.tsv'}",
        f"  Merged TSV: {OUT / 'stage37b_merged.tsv'}",
        (
            "  Part2 ROI preview: "
            f"{OUT / 'stage37b_part2_roi_preview.jpg'}"
        ),
        (
            "  Part2 contact sheet: "
            f"{OUT / 'stage37b_part2_contact_sheet.jpg'}"
        ),
        (
            "  Merged contact sheet: "
            f"{merged_sheet}"
        ),
        "",
        "Next:",
        "  Stage38 OCR should run only on merged completed-frame crops.",
    ]

    (
        OUT
        / "stage37b_summary.txt"
    ).write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE37B COMPLETE")
    print("=" * 72)
    print(
        "Part1:",
        len(part1)
    )
    print(
        "Part2:",
        len(part2)
    )
    print(
        "Merged:",
        len(merged)
    )
    print()
    print(
        OUT
        / "stage37b_merged.tsv"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content `
        -LiteralPath $py `
        -Value $codeText `
        -Encoding UTF8

    $code = RunPython `
        "python syntax" `
        @("-m","py_compile",$py)

    if ($code -ne 0) {
        throw "Stage37B Python 문법 오류"
    }

    Log ""
    Log "[1/2] Part1 재사용 + Part2 분석 + 병합"

    $code = RunPython `
        "multipart extraction" `
        @("-u",$py)

    if ($code -ne 0) {
        throw "Stage37B 분석 실패"
    }

    $required = @(
        "stage37b_summary.txt",
        "stage37b_summary.json",
        "stage37b_part1.tsv",
        "stage37b_part2.tsv",
        "stage37b_part2_rejected.tsv",
        "stage37b_merged.tsv",
        "stage37b_part2_roi_preview.jpg",
        "stage37b_merged_contact_sheet.jpg"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $name))) {
            throw "Stage37B 결과 누락: $name"
        }
    }

    Log ""
    Log "[2/2] 업로드 ZIP 준비"

    # Success-only archive.
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
        "stage37b_summary.txt",
        "stage37b_summary.json",
        "stage37b_part1.tsv",
        "stage37b_part2.tsv",
        "stage37b_part2_rejected.tsv",
        "stage37b_merged.tsv",
        "stage37b_part2_roi_preview.jpg",
        "stage37b_part2_contact_sheet.jpg",
        "stage37b_merged_contact_sheet.jpg"
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
        "Naruto PSP Stage 37B"
        "생성: $(Get-Date)"
        ""
        "STATUS: MULTIPART_FRAME_EXTRACTION_COMPLETE"
        ""
        "Part1:"
        " 기존 Stage37 결과 재사용, 재분석 안 함"
        ""
        "Part2:"
        " $($part2.FullName)"
        ""
        "Merged timeline:"
        " $stage\stage37b_merged.tsv"
        ""
        "ChatGPT upload:"
        " naruto_stage37b_upload.zip"
        ""
        "원본 영상 및 전체 frame/crop 이미지는 ZIP에 포함하지 않았습니다."
        ""
        "Previous successful logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage37b_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage37b_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 37B SUCCESS"
    Log "=========================================="
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
