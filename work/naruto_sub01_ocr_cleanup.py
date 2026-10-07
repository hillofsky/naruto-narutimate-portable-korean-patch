#!/usr/bin/env python3
# Naruto PSP SUB01 - OCR cleanup / triage
from __future__ import annotations
import argparse, csv, re, sys, unicodedata
from pathlib import Path
from collections import Counter, defaultdict

EXPECTED_ROWS = 2086
VISUAL_CONFIRMED_EMPTY = {553, 677, 682, 1461, 1822, 1847}

# Conservative speaker-name corrections only.
SPEAKER_ALIASES = {
    "나두토": "나루토",
    "나우토": "나루토",
    "나수토": "나루토",
    "나주토": "나루토",
    "나누토": "나루토",
    "시카마우": "시카마루",
    "오로치마속": "오로치마루",
    "오토치마속": "오로치마루",
    "오로치마우": "오로치마루",
    "즈나데": "츠나데",
    "사부라": "사쿠라",
    "텐틴": "텐텐",
    "3대 호가게": "3대 호카게",
    "명사대장": "병사대장",
    "명사": "병사",
    "조지": "쵸지",
    "죠지": "쵸지",
}

CANONICAL_SPEAKERS = {
    "나루토","시카마루","오로치마루","츠나데","사쿠라","텐텐","3대 호카게",
    "병사대장","병사","쵸지","지라이야","카카시","카스미","키리히메","카부토",
    "시즈네","히나타","네지","리","가이","가아라","키바","여자아이","시녀",
    "시도","이도","사념체","사념제",
}

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KO_RE = re.compile(r"[\uac00-\ud7a3]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")
TS_RE = re.compile(r"_(\d{2})-(\d{2})-(\d{2})_(\d{3})")
REPEAT_CHAR_RE = re.compile(r"(.)\1{19,}", re.S)
NUMERIC_RUN_RE = re.compile(r"1234567890(?:1234567890){3,}")

PROMPT_FRAGMENTS = (
    "이름표가 보이면 이름표부터 읽고",
    "문자가 하나도 보이지 않으면",
    "읽을 수 없는 한 글자만",
    "출력은 <OCR>와",
    "너는 게임 화면 OCR 엔진",
)

YOUTUBE_NARRATION_FRAGMENTS = (
    "이야기로 구성되어 있습니다",
    "지금 바로 보시죠",
    "전투 플레이가 시작되었습니다",
    "한 칸씩 이동하며",
    "각종 이벤트를 열람합니다",
)

# These are visibly/semantically non-dialogue items in the opening capture.
KNOWN_CREDIT_ROWS = {1,4,12,13}
KNOWN_CREDIT_PREFIX_ROWS = {5,6,7,8,9,10,11,14,15}
KNOWN_YOUTUBE_NARRATION_ROWS = {25,26,104,125}

def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_tsv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def clean_raw(text: str) -> str:
    s = (text or "").replace("\r\n","\n").replace("\r","\n").strip()
    m = re.match(r"(?s)^\s*<OCR>\s*(.*?)\s*</OCR>\s*$", s)
    if m:
        s = m.group(1).strip()
    if s == "EMPTY":
        s = "[EMPTY]"
    return s

def timestamp_from_filename(name: str) -> str:
    m = TS_RE.search(name or "")
    if not m:
        return ""
    return f"{m.group(1)}:{m.group(2)}:{m.group(3)}.{m.group(4)}"

def strip_known_credit_prefix(global_index: int, text: str):
    if global_index not in KNOWN_CREDIT_PREFIX_ROWS:
        return text, []
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    actions = []
    kept = []
    for line in lines:
        # Opening overlay contains Japanese voice-actor/company credit lines.
        if JP_RE.search(line) and not KO_RE.search(line):
            actions.append("CREDIT_PREFIX_REMOVED:" + line)
            continue
        kept.append(line)
    return "\n".join(kept).strip(), actions

def split_speaker(text: str):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return text, "", "", []

    first = lines[0]
    actions = []

    # Exact alias on first line.
    if first in SPEAKER_ALIASES:
        canonical = SPEAKER_ALIASES[first]
        actions.append(f"SPEAKER:{first}->{canonical}")
        lines[0] = canonical
        body = "\n".join(lines[1:]).strip()
        return "\n".join(lines), canonical, body, actions

    # Alias + dialogue on same line.
    for alias, canonical in sorted(SPEAKER_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for sep in (" ", "\t", ":", "："):
            prefix = alias + sep
            if first.startswith(prefix):
                rest = first[len(prefix):].strip(" \t:：")
                actions.append(f"SPEAKER_PREFIX:{alias}->{canonical}")
                new_lines = [canonical]
                if rest:
                    new_lines.append(rest)
                new_lines.extend(lines[1:])
                body = "\n".join(new_lines[1:]).strip()
                return "\n".join(new_lines), canonical, body, actions

    # Canonical first line / canonical prefix.
    if first in CANONICAL_SPEAKERS:
        body = "\n".join(lines[1:]).strip()
        return "\n".join(lines), first, body, actions

    for canonical in sorted(CANONICAL_SPEAKERS, key=len, reverse=True):
        for sep in (" ", "\t", ":", "："):
            prefix = canonical + sep
            if first.startswith(prefix):
                rest = first[len(prefix):].strip(" \t:：")
                new_lines = [canonical]
                if rest:
                    new_lines.append(rest)
                new_lines.extend(lines[1:])
                body = "\n".join(new_lines[1:]).strip()
                return "\n".join(new_lines), canonical, body, actions

    return "\n".join(lines), "", "\n".join(lines).strip(), actions

def classify(text: str) -> str:
    if text == "[EMPTY]" or not text.strip():
        return "EMPTY"
    ko = bool(KO_RE.search(text))
    jp = bool(JP_RE.search(text))
    if ko and jp:
        return "MIXED_KO_JP"
    if ko:
        return "KOREAN"
    if jp:
        return "JAPANESE_ONLY"
    return "OTHER"

def repeated_line_loop(text: str) -> bool:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) >= 6:
        c = Counter(lines)
        if c and c.most_common(1)[0][1] >= 5:
            return True
    return bool(REPEAT_CHAR_RE.search(text) or NUMERIC_RUN_RE.search(text))

def review_reasons(global_index: int, text: str, cls: str, speaker: str):
    reasons = []
    if any(x in text for x in PROMPT_FRAGMENTS):
        reasons.append("PROMPT_LEAK")
    if "<OCR>" in text or "</OCR>" in text:
        reasons.append("OCR_TAG_LEFTOVER")
    if repeated_line_loop(text):
        reasons.append("REPETITION_LOOP")
    if "[불명]" in text:
        reasons.append("UNREADABLE")
    if cls == "JAPANESE_ONLY":
        reasons.append("JAPANESE_ONLY")
    if cls == "MIXED_KO_JP":
        reasons.append("MIXED_KO_JP")
    if global_index in KNOWN_YOUTUBE_NARRATION_ROWS or any(x in text for x in YOUTUBE_NARRATION_FRAGMENTS):
        reasons.append("YOUTUBE_NARRATION")
    if KO_RE.search(text) and LATIN_WORD_RE.search(text):
        reasons.append("LATIN_IN_KOREAN")
    if len(text) > 100:
        reasons.append("LONG_OUTPUT")
    return reasons

def dedupe(seq):
    out=[]
    seen=set()
    for x in seq:
        if x not in seen:
            out.append(x); seen.add(x)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage-dir", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    stage_dir = Path(args.stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    src = root / "analysis" / "stage38e_full_ocr" / "ocr_2086_results.csv"
    if not src.exists():
        raise SystemExit(f"Stage38E OCR CSV not found: {src}")

    rows = read_csv(src)
    if len(rows) != EXPECTED_ROWS:
        raise SystemExit(f"Expected {EXPECTED_ROWS} OCR rows, found {len(rows)}")
    if any(r.get("status","") != "OK" for r in rows):
        bad = sum(1 for r in rows if r.get("status","") != "OK")
        raise SystemExit(f"Stage38E has {bad} non-OK rows")

    cleaned_rows=[]
    alias_counter=Counter()
    review_rows=[]
    jp_rows=[]
    use_counts=Counter()

    for r in rows:
        g = int(r["global_index"])
        raw = r.get("ocr_text","")
        cleaned = clean_raw(raw)
        actions=[]

        if g in VISUAL_CONFIRMED_EMPTY:
            cleaned = "[EMPTY]"
            actions.append("VISUAL_CONFIRMED_EMPTY")

        # Opening credit handling is conservative and explicit by known frame id.
        if g in KNOWN_CREDIT_ROWS:
            actions.append("KNOWN_CREDIT_ROW")

        cleaned, credit_actions = strip_known_credit_prefix(g, cleaned)
        actions.extend(credit_actions)

        cleaned, speaker, dialogue, speaker_actions = split_speaker(cleaned)
        actions.extend(speaker_actions)
        for a in speaker_actions:
            alias_counter[a] += 1

        cls = classify(cleaned)
        reasons = review_reasons(g, cleaned, cls, speaker)

        if g in KNOWN_CREDIT_ROWS:
            reasons.append("CREDIT")
        if g in KNOWN_CREDIT_PREFIX_ROWS and credit_actions:
            # Credit stripped successfully, so no review merely for that.
            cls = classify(cleaned)

        reasons = dedupe(reasons)

        if cls == "EMPTY":
            use = "NO"
        elif g in KNOWN_CREDIT_ROWS:
            use = "NO"
        elif "YOUTUBE_NARRATION" in reasons:
            use = "NO"
        elif any(x in reasons for x in (
            "PROMPT_LEAK","OCR_TAG_LEFTOVER","REPETITION_LOOP","UNREADABLE",
            "JAPANESE_ONLY","MIXED_KO_JP","LATIN_IN_KOREAN","LONG_OUTPUT"
        )):
            use = "REVIEW"
        else:
            use = "YES"

        use_counts[use] += 1

        out = {
            "global_index": g,
            "video_part": r.get("video_part",""),
            "part_index": r.get("part_index",""),
            "timestamp": timestamp_from_filename(r.get("filename","")),
            "filename": r.get("filename",""),
            "source_path": r.get("source_path",""),
            "raw_ocr": raw,
            "cleaned_ocr": cleaned,
            "speaker": speaker,
            "dialogue_text": dialogue,
            "class": cls,
            "use_for_dialogue": use,
            "auto_action": ";".join(actions),
            "review_reason": ";".join(reasons),
        }
        cleaned_rows.append(out)

        if use == "REVIEW":
            review_rows.append(out)
        if cls in ("JAPANESE_ONLY","MIXED_KO_JP"):
            jp_rows.append(out)

    fields = [
        "global_index","video_part","part_index","timestamp","filename","source_path",
        "raw_ocr","cleaned_ocr","speaker","dialogue_text","class","use_for_dialogue",
        "auto_action","review_reason"
    ]
    write_tsv(stage_dir/"sub01_cleaned_2086.tsv", cleaned_rows, fields)
    write_csv(stage_dir/"sub01_cleaned_2086.csv", cleaned_rows, fields)
    write_tsv(stage_dir/"sub01_review_queue.tsv", review_rows, fields)
    write_tsv(stage_dir/"sub01_japanese_rows.tsv", jp_rows, fields)

    # Speaker frequency (canonicalized only where certain).
    sp = Counter(r["speaker"] for r in cleaned_rows if r["speaker"])
    speaker_rows = [{"speaker":k,"count":v} for k,v in sp.most_common()]
    write_tsv(stage_dir/"speaker_frequency.tsv", speaker_rows, ["speaker","count"])

    alias_rows = [{"action":k,"count":v} for k,v in alias_counter.most_common()]
    write_tsv(stage_dir/"speaker_alias_report.tsv", alias_rows, ["action","count"])

    # Preliminary character set from auto-accepted dialogue only.
    char_count=Counter()
    char_frames=Counter()
    examples=defaultdict(list)
    for r in cleaned_rows:
        if r["use_for_dialogue"] != "YES":
            continue
        txt = r["dialogue_text"] if r["speaker"] else r["cleaned_ocr"]
        seen=set()
        for ch in txt:
            if "\uac00" <= ch <= "\ud7a3":
                char_count[ch] += 1
                seen.add(ch)
                if len(examples[ch]) < 3:
                    tag=f"g{r['global_index']}:{r['filename']}"
                    if tag not in examples[ch]:
                        examples[ch].append(tag)
        for ch in seen:
            char_frames[ch] += 1

    char_rows=[]
    for ch,count in char_count.items():
        char_rows.append({
            "char":ch,
            "unicode":f"U+{ord(ch):04X}",
            "count":count,
            "frame_count":char_frames[ch],
            "examples":" | ".join(examples[ch]),
        })
    char_rows.sort(key=lambda x:(-x["count"], ord(x["char"])))
    write_tsv(stage_dir/"prelim_char_frequency.tsv", char_rows,
              ["char","unicode","count","frame_count","examples"])
    (stage_dir/"prelim_unique_hangul.txt").write_text(
        "".join(sorted(char_count, key=ord)), encoding="utf-8-sig"
    )

    # Compact summary.
    classes=Counter(r["class"] for r in cleaned_rows)
    review_reason_counts=Counter()
    for r in review_rows:
        for reason in r["review_reason"].split(";"):
            if reason:
                review_reason_counts[reason]+=1

    summary_lines=[
        "Naruto PSP SUB01 - OCR Cleanup / Triage",
        "",
        f"SourceRows={len(rows)}",
        f"VisualConfirmedEmpty={len(VISUAL_CONFIRMED_EMPTY)}",
        f"AutoSpeakerAliasRows={sum(alias_counter.values())}",
        f"UseYES={use_counts['YES']}",
        f"UseNO={use_counts['NO']}",
        f"UseREVIEW={use_counts['REVIEW']}",
        f"PrelimUniqueHangul={len(char_count)}",
        "",
        "ClassCounts:",
    ]
    for k,v in classes.most_common():
        summary_lines.append(f"  {k}={v}")
    summary_lines += ["", "ReviewReasons:"]
    for k,v in review_reason_counts.most_common():
        summary_lines.append(f"  {k}={v}")
    summary_lines += [
        "",
        "Important:",
        "- raw_ocr is never overwritten.",
        "- The six Stage38E visual-review frames are set to [EMPTY].",
        "- Speaker normalization only changes known first-line/prefix aliases.",
        "- REVIEW rows are not automatically accepted into the preliminary font corpus.",
    ]
    (stage_dir/"SUMMARY.txt").write_text("\n".join(summary_lines)+"\n", encoding="utf-8-sig")

    print("\n".join(summary_lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
