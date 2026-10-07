#!/usr/bin/env python3
# Naruto PSP SUB09 - Final speaker cleanup and canonical subtitle corpus

from __future__ import annotations
import argparse, csv
from pathlib import Path
from collections import Counter, defaultdict

# Rows where text is already correct, but the first line was not parsed as speaker.
METADATA_ONLY = {
    296: "이노",
    306: "쵸지",
    338: "리",
    611: "오로치마루",
    1185: "오로치마루",
    1604: "일동",
    1779: "오로치마루",
    1848: "일동",
}

# SUB08 source-image visual verification.
SPEAKER_TEXT_FIX = {
    325: ("김", "리"),
    401: ("길", "리"),
    474: ("길", "리"),
    494: ("길", "리"),
    602: ("모르지마족", "오로치마루"),
    1239: ("모로치마우", "오로치마루"),
}

EXPECTED_ENTRIES = 1900
EXPECTED_DIALOGUE = 1762
EXPECTED_NARRATION = 138
EXPECTED_UNIQUE_HANGUL = 694

KNOWN_SPEAKERS = {
    "나루토","지라이야","카카시","카스미","츠나데","오로치마루",
    "키리히메","사쿠라","카부토","시카마루","시즈네","히나타",
    "3대 호카게","리","네지","가이","병사대장","여자아이","가아라",
    "키바","시녀","이도","시도","병사","쵸지","사념체","사념제",
    "텐텐","일동","이노",
}

MALFORMED_SPEAKER_TOKENS = {"김","길","모르지마족","모로치마우"}

def read_tsv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_csv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def parse_as_dialogue(r, expected_speaker: str):
    lines = r["full_text"].splitlines()
    if len(lines) < 2:
        raise SystemExit(
            f"seq{r['sequence']}: expected speaker + dialogue, got {r['full_text']!r}"
        )
    if lines[0] != expected_speaker:
        raise SystemExit(
            f"seq{r['sequence']}: first line mismatch, expected {expected_speaker!r}, "
            f"got {lines[0]!r}"
        )
    r["speaker"] = expected_speaker
    r["text"] = "\n".join(lines[1:])
    r["entry_type"] = "DIALOGUE"
    r["sub09_speaker_status"] = "VISUAL_OR_STRUCTURE_VERIFIED"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shared", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    shared = Path(args.shared)
    out.mkdir(parents=True, exist_ok=True)
    shared.mkdir(parents=True, exist_ok=True)

    src = root / "analysis" / "sub" / "sub07_final_corpus" / "sub07_final_sequence.tsv"
    sub08_exact = root / "analysis" / "sub" / "sub08_speaker_audit" / "sub08_exact_structure_rows.tsv"
    sub08_amb = root / "analysis" / "sub" / "sub08_speaker_audit" / "sub08_ambiguous_speaker_rows.tsv"

    for p in (src, sub08_exact, sub08_amb):
        if not p.exists():
            raise SystemExit(f"Required input missing: {p}")

    rows = read_tsv(src)
    exact_rows = read_tsv(sub08_exact)
    amb_rows = read_tsv(sub08_amb)

    if len(rows) != EXPECTED_ENTRIES:
        raise SystemExit(f"Expected {EXPECTED_ENTRIES} SUB07 entries, got {len(rows)}")
    if len(exact_rows) != len(METADATA_ONLY):
        raise SystemExit(f"Expected {len(METADATA_ONLY)} SUB08 exact rows, got {len(exact_rows)}")
    if len(amb_rows) != len(SPEAKER_TEXT_FIX):
        raise SystemExit(f"Expected {len(SPEAKER_TEXT_FIX)} SUB08 ambiguous rows, got {len(amb_rows)}")

    exact_seq = {int(r["sequence"]) for r in exact_rows}
    amb_seq = {int(r["sequence"]) for r in amb_rows}
    if exact_seq != set(METADATA_ONLY):
        raise SystemExit(f"SUB08 exact sequence set mismatch: {sorted(exact_seq)}")
    if amb_seq != set(SPEAKER_TEXT_FIX):
        raise SystemExit(f"SUB08 ambiguous sequence set mismatch: {sorted(amb_seq)}")

    byseq = {int(r["sequence"]): r for r in rows}
    audit = []

    # Metadata-only reparsing.
    for seq, speaker in sorted(METADATA_ONLY.items()):
        r = byseq[seq]
        before = {
            "entry_type": r["entry_type"],
            "speaker": r["speaker"],
            "text": r["text"],
            "full_text": r["full_text"],
        }
        parse_as_dialogue(r, speaker)
        audit.append({
            "sequence": seq,
            "source_global_indices": r["source_global_indices"],
            "action": "REPARSE_SPEAKER_METADATA",
            "before_first_line": speaker,
            "after_speaker": speaker,
            "before_full_text": before["full_text"],
            "after_full_text": r["full_text"],
        })

    # Visual speaker-text corrections.
    for seq, (bad, good) in sorted(SPEAKER_TEXT_FIX.items()):
        r = byseq[seq]
        lines = r["full_text"].splitlines()
        if len(lines) < 2:
            raise SystemExit(f"seq{seq}: malformed full_text: {r['full_text']!r}")
        if lines[0] != bad:
            raise SystemExit(
                f"seq{seq}: expected malformed speaker {bad!r}, got {lines[0]!r}"
            )

        before_full = r["full_text"]
        lines[0] = good
        r["full_text"] = "\n".join(lines)
        parse_as_dialogue(r, good)

        audit.append({
            "sequence": seq,
            "source_global_indices": r["source_global_indices"],
            "action": "VISUAL_SPEAKER_CORRECTION",
            "before_first_line": bad,
            "after_speaker": good,
            "before_full_text": before_full,
            "after_full_text": r["full_text"],
        })

    # Mark untouched rows.
    touched = set(METADATA_ONLY) | set(SPEAKER_TEXT_FIX)
    for r in rows:
        if "sub09_speaker_status" not in r:
            r["sub09_speaker_status"] = "UNCHANGED"

    # Structural validation:
    # no NARRATION row may begin with a known speaker label.
    structural_residual = []
    malformed_residual = []
    for r in rows:
        lines = [x.strip() for x in r["full_text"].splitlines() if x.strip()]
        first = lines[0] if lines else ""

        if r["entry_type"] == "NARRATION" and len(lines) >= 2 and first in KNOWN_SPEAKERS:
            x = dict(r)
            x["residual_reason"] = "NARRATION_STARTS_WITH_KNOWN_SPEAKER"
            structural_residual.append(x)

        if first in MALFORMED_SPEAKER_TOKENS:
            x = dict(r)
            x["residual_reason"] = "MALFORMED_SPEAKER_TOKEN"
            malformed_residual.append(x)

    if structural_residual:
        write_tsv(
            out / "sub09_structural_residual.tsv",
            structural_residual,
            list(structural_residual[0].keys())
        )
        raise SystemExit(
            f"Speaker structure residual rows remain: {len(structural_residual)}"
        )

    if malformed_residual:
        write_tsv(
            out / "sub09_malformed_speaker_residual.tsv",
            malformed_residual,
            list(malformed_residual[0].keys())
        )
        raise SystemExit(
            f"Malformed speaker tokens remain: {len(malformed_residual)}"
        )

    type_counts = Counter(r["entry_type"] for r in rows)
    if type_counts["DIALOGUE"] != EXPECTED_DIALOGUE:
        raise SystemExit(
            f"Expected {EXPECTED_DIALOGUE} DIALOGUE rows, got {type_counts['DIALOGUE']}"
        )
    if type_counts["NARRATION"] != EXPECTED_NARRATION:
        raise SystemExit(
            f"Expected {EXPECTED_NARRATION} NARRATION rows, got {type_counts['NARRATION']}"
        )

    # Recompute speaker frequency after final reparsing.
    speaker_counts = Counter(r["speaker"] for r in rows if r["speaker"].strip())
    speaker_rows = [
        {"speaker": speaker, "count": count}
        for speaker, count in speaker_counts.most_common()
    ]

    # Final character corpus. Keep SUB07's explicit inclusion decision (g24 excluded).
    cc = Counter()
    ec = Counter()
    examples = defaultdict(list)
    included_entries = 0

    for r in rows:
        include = r.get("sub07_corpus_include", r.get("sub05_corpus_include", "YES"))
        r["sub09_corpus_include"] = include
        if include != "YES":
            continue

        included_entries += 1
        seen = set()
        for ch in r["full_text"]:
            if "\uac00" <= ch <= "\ud7a3":
                cc[ch] += 1
                seen.add(ch)
                if len(examples[ch]) < 3:
                    tag = f"seq{r['sequence']}:g{r['source_global_indices']}"
                    if tag not in examples[ch]:
                        examples[ch].append(tag)
        for ch in seen:
            ec[ch] += 1

    if len(cc) != EXPECTED_UNIQUE_HANGUL:
        raise SystemExit(
            f"Expected {EXPECTED_UNIQUE_HANGUL} unique Hangul, got {len(cc)}"
        )

    fields = list(rows[0].keys())
    write_tsv(out / "sub09_final_sequence.tsv", rows, fields)
    write_csv(out / "sub09_final_sequence.csv", rows, fields)

    write_tsv(
        out / "sub09_speaker_audit.tsv",
        audit,
        [
            "sequence","source_global_indices","action","before_first_line",
            "after_speaker","before_full_text","after_full_text"
        ]
    )
    write_tsv(out / "sub09_speaker_frequency.tsv", speaker_rows, ["speaker","count"])

    char_rows = [
        {
            "char": ch,
            "unicode": f"U+{ord(ch):04X}",
            "count": cc[ch],
            "entry_count": ec[ch],
            "examples": " | ".join(examples[ch]),
        }
        for ch in cc
    ]
    char_rows.sort(key=lambda x: (-x["count"], ord(x["char"])))
    write_tsv(
        out / "sub09_final_char_frequency.tsv",
        char_rows,
        ["char","unicode","count","entry_count","examples"]
    )

    unique = "".join(sorted(cc, key=ord))
    (out / "sub09_final_unique_hangul.txt").write_text(unique, encoding="utf-8-sig")

    blocks = []
    for r in rows:
        if r["sub09_corpus_include"] == "YES":
            blocks.append(r["full_text"])
    (out / "sub09_final_dialogue_corpus.txt").write_text(
        "\n\n".join(blocks) + "\n", encoding="utf-8-sig"
    )

    excluded = [r for r in rows if r["sub09_corpus_include"] != "YES"]
    write_tsv(out / "sub09_excluded_from_char_corpus.tsv", excluded, fields)

    # Update shared MOV handoff.
    shared_out = shared / "youtube_subtitle_anchors.tsv"
    write_tsv(shared_out, rows, fields)

    summary = [
        "Naruto PSP SUB09 - Final Speaker-Corrected Subtitle Corpus",
        "",
        f"Entries={len(rows)}",
        f"SpeakerMetadataReparsed={len(METADATA_ONLY)}",
        f"SpeakerTextCorrections={len(SPEAKER_TEXT_FIX)}",
        f"DialogueEntries={type_counts['DIALOGUE']}",
        f"NarrationEntries={type_counts['NARRATION']}",
        f"StructuralResidualRows=0",
        f"MalformedSpeakerResidualRows=0",
        f"CorpusIncludedEntries={included_entries}",
        f"CorpusExcludedEntries={len(excluded)}",
        f"FinalUniqueHangul={len(cc)}",
        "",
        "Visual speaker corrections:",
        "  seq325 g374: 김 -> 리",
        "  seq401 g457: 길 -> 리",
        "  seq474 g543: 길 -> 리",
        "  seq494 g565: 길 -> 리",
        "  seq602 g688: 모르지마족 -> 오로치마루",
        "  seq1239 g1383: 모로치마우 -> 오로치마루",
        "",
        "The 8 SUB08 exact rows were reparsed as DIALOGUE without changing their text.",
        "g24 remains intentionally excluded from the character corpus.",
        "",
        f"SharedHandoff={shared_out}",
    ]
    (out / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary))

if __name__ == "__main__":
    main()
