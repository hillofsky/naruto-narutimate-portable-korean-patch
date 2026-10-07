#!/usr/bin/env python3
# -*- coding: ascii -*-
from __future__ import annotations
import argparse,csv,hashlib,json,re,sys
from pathlib import Path
from collections import Counter,defaultdict

EXPECTED_ROWS=1976
EXPECTED_CHANGED=1163
EXPECTED_FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):
            h.update(b)
    return h.hexdigest()

def rt(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def wt(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def controls(s):
    return re.findall(r"<[^>]+>",s or "")

def max_visible_chars(s):
    lines=(s or "").split("<br>")
    return max([len(re.sub(r"<[^>]+>","",x)) for x in lines] or [0])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    manifest_path=Path(__file__).with_name("sub33_source_manifest.json")
    manifest=json.loads(manifest_path.read_text(encoding="ascii"))
    font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    sub31=root/"analysis"/"sub"/"sub31_full_semantic_review"

    if not font.exists():
        raise RuntimeError(f"font mapping missing: {font}")
    if sha(font)!=EXPECTED_FONT_SHA:
        raise RuntimeError(f"font mapping SHA mismatch: {sha(font)}")
    font_chars={r["hangul"] for r in rt(font) if r.get("hangul") and len(r["hangul"])==1}

    merged=[]
    source_manifest=[]
    for s in manifest["stages"]:
        p=root/"analysis"/"sub"/s["stage_dir"]/s["filename"]
        if not p.exists():
            raise RuntimeError(f"SUB32 source missing: {p}")
        actual_sha=sha(p)
        if actual_sha!=s["sha256"]:
            raise RuntimeError(f"SUB32 source SHA mismatch stage={s['stage']}: {actual_sha}")
        rows=rt(p)
        expected_count=s["end"]-s["start"]+1
        if len(rows)!=expected_count:
            raise RuntimeError(f"SUB32 stage {s['stage']} rows={len(rows)} expected={expected_count}")
        idx=[int(r["review_index"]) for r in rows]
        if idx!=list(range(s["start"],s["end"]+1)):
            raise RuntimeError(f"SUB32 stage {s['stage']} review_index range/order mismatch")
        merged.extend(rows)
        source_manifest.append({
            "stage":f"SUB32-{s['stage']}",
            "review_range":f"{s['start']}-{s['end']}",
            "rows":len(rows),
            "source_path":str(p),
            "sha256":actual_sha,
            "changed_vs_sub29":sum(r["revised_korean"]!=r["current_sub29_korean"] for r in rows),
        })

    if len(merged)!=EXPECTED_ROWS:
        raise RuntimeError(f"merged rows={len(merged)} expected={EXPECTED_ROWS}")

    idx=[int(r["review_index"]) for r in merged]
    if idx!=list(range(1,EXPECTED_ROWS+1)):
        raise RuntimeError("merged review_index not exactly 1..1976")
    if len({r["game_global_dialogue_index"] for r in merged})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate game_global_dialogue_index")
    if len({r["game_key"] for r in merged})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate game_key")
    if any(int(r["game_global_dialogue_index"])!=int(r["review_index"]) for r in merged):
        raise RuntimeError("review_index/game_global_dialogue_index mismatch")

    immutable_fields=list(merged[0].keys())[:21]
    source31=[]
    for s in manifest["stages"]:
        q=sub31/f"sub31_review_{s['start']:04d}_{s['end']:04d}.tsv"
        if not q.exists():
            raise RuntimeError(f"SUB31 packet missing: {q}")
        source31.extend(rt(q))
    if len(source31)!=EXPECTED_ROWS:
        raise RuntimeError("SUB31 merged row count mismatch")
    immutable_mismatches=[]
    for a,b in zip(source31,merged):
        for k in immutable_fields:
            if a.get(k,"")!=b.get(k,""):
                immutable_mismatches.append({
                    "review_index":a["review_index"],"field":k,
                    "sub31":a.get(k,""),"sub32":b.get(k,"")
                })
                break
    if immutable_mismatches:
        raise RuntimeError(f"immutable field mismatches={len(immutable_mismatches)}")

    blanks=[r for r in merged if not r["revised_korean"].strip()]
    ctl_bad=[r for r in merged if controls(r["revised_korean"])!=controls(r["japanese"])]
    not_reviewed=[r for r in merged if not r["review_status"].startswith("REVIEWED_")]
    missing=set()
    jp_rows=[]
    replacement_rows=[]
    compat_rows=[]
    final_hangul=set()
    for r in merged:
        s=r["revised_korean"]
        hs={c for c in s if 0xAC00<=ord(c)<=0xD7A3}
        final_hangul |= hs
        missing |= (hs-font_chars)
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]",s):
            jp_rows.append(r)
        if "\ufffd" in s:
            replacement_rows.append(r)
        if re.search(r"[\u3130-\u318f]",s):
            compat_rows.append(r)

    changed=[r for r in merged if r["revised_korean"]!=r["current_sub29_korean"]]
    if len(changed)!=EXPECTED_CHANGED:
        raise RuntimeError(f"changed_vs_sub29={len(changed)} expected={EXPECTED_CHANGED}")
    if blanks:
        raise RuntimeError(f"blank revised_korean rows={len(blanks)}")
    if ctl_bad:
        raise RuntimeError(f"control mismatches={len(ctl_bad)}")
    if not_reviewed:
        raise RuntimeError(f"not reviewed rows={len(not_reviewed)}")
    if missing:
        raise RuntimeError("new Hangul glyphs required: "+"".join(sorted(missing)))
    if jp_rows:
        raise RuntimeError(f"Japanese letters remain in revised Korean rows={len(jp_rows)}")
    if replacement_rows:
        raise RuntimeError(f"Unicode replacement chars remain={len(replacement_rows)}")
    if compat_rows:
        raise RuntimeError(f"compatibility jamo remain={len(compat_rows)}")

    fields=list(merged[0].keys())
    final_path=out/"sub33_final_semantic_review_1976.tsv"
    wt(final_path,merged,fields)

    patch_fields=[
        "review_index","game_global_dialogue_index","game_key","event_file",
        "event_display_index","command","speaker_code","voice_id","topology_status",
        "sub09_sequences","japanese","final_korean","original_control_sequence"
    ]
    patch_rows=[]
    for r in merged:
        patch_rows.append({
            "review_index":r["review_index"],
            "game_global_dialogue_index":r["game_global_dialogue_index"],
            "game_key":r["game_key"],
            "event_file":r["event_file"],
            "event_display_index":r["event_display_index"],
            "command":r["command"],
            "speaker_code":r["speaker_code"],
            "voice_id":r["voice_id"],
            "topology_status":r["topology_status"],
            "sub09_sequences":r["sub09_sequences"],
            "japanese":r["japanese"],
            "final_korean":r["revised_korean"],
            "original_control_sequence":r["original_control_sequence"],
        })
    patch_path=out/"sub33_patcher_ready_1976.tsv"
    wt(patch_path,patch_rows,patch_fields)

    changed_rows=[]
    for r in changed:
        changed_rows.append({
            "review_index":r["review_index"],"game_key":r["game_key"],
            "speaker_code":r["speaker_code"],"japanese":r["japanese"],
            "sub29_korean":r["current_sub29_korean"],
            "final_korean":r["revised_korean"],"review_note":r["review_note"],
        })
    wt(out/"sub33_changed_vs_sub29_1163.tsv",changed_rows,
       ["review_index","game_key","speaker_code","japanese","sub29_korean","final_korean","review_note"])

    ev=defaultdict(list)
    for r in merged:
        ev[r["event_file"]].append(r)
    event_rows=[]
    for name in sorted(ev):
        rs=ev[name]
        event_rows.append({
            "event_file":name,
            "rows":len(rs),
            "msg_rows":sum(r["command"]=="MSG" for r in rs),
            "msg_forced_rows":sum(r["command"]=="MSG_FORCED" for r in rs),
            "changed_vs_sub29":sum(r["revised_korean"]!=r["current_sub29_korean"] for r in rs),
            "max_visible_chars_per_line":max(max_visible_chars(r["revised_korean"]) for r in rs),
        })
    wt(out/"sub33_event_summary.tsv",event_rows,
       ["event_file","rows","msg_rows","msg_forced_rows","changed_vs_sub29","max_visible_chars_per_line"])

    long_rows=[]
    for r in merged:
        ml=max_visible_chars(r["revised_korean"])
        if ml>28:
            long_rows.append({
                "review_index":r["review_index"],"game_key":r["game_key"],
                "speaker_code":r["speaker_code"],"max_visible_chars_per_line":ml,
                "final_korean":r["revised_korean"],
            })
    wt(out/"sub33_long_line_review.tsv",long_rows,
       ["review_index","game_key","speaker_code","max_visible_chars_per_line","final_korean"])

    wt(out/"sub33_source_manifest.tsv",source_manifest,
       ["stage","review_range","rows","source_path","sha256","changed_vs_sub29"])

    terms=[
        "\ud0a4\ub9ac\ud788\uba54",
        "\uce74\uc2a4\ubbf8",
        "\ubb34\ud658\uc131",
        "\uc800\ub141\uc548\uac1c\uc131",
        "\ucc28\ucc98\ube44\uc758 \uc220",
        "\uc0dd\uae30",
        "\uc794\ub300\uaf43",
        "\uc0ac\ucfe0\ub77c\uc9f1"
    ]
    term_rows=[]
    for term in terms:
        term_rows.append({"term":term,"occurrence_rows":sum(term in r["revised_korean"] for r in merged)})
    wt(out/"sub33_term_audit.tsv",term_rows,["term","occurrence_rows"])

    report={
        "stage":"SUB33",
        "rows_merged":len(merged),
        "review_index_exact_1_to_1976":True,
        "unique_game_global_dialogue_index":EXPECTED_ROWS,
        "unique_game_key":EXPECTED_ROWS,
        "immutable_fields_match_sub31":True,
        "blank_revised_korean":0,
        "reviewed_rows":EXPECTED_ROWS,
        "changed_vs_sub29":len(changed),
        "retained_vs_sub29":EXPECTED_ROWS-len(changed),
        "control_exact_rows":EXPECTED_ROWS,
        "control_mismatches":0,
        "frozen_font_mapping_sha256":EXPECTED_FONT_SHA,
        "final_unique_hangul":len(final_hangul),
        "new_hangul_required":0,
        "japanese_letters_remaining":0,
        "unicode_replacement_chars_remaining":0,
        "compatibility_jamo_remaining":0,
        "commands":dict(Counter(r["command"] for r in merged)),
        "event_files":len(ev),
        "ascii_spaces_total":sum(r["revised_korean"].count(" ") for r in merged),
        "rows_with_ascii_spaces":sum(" " in r["revised_korean"] for r in merged),
        "max_visible_chars_per_line":max(max_visible_chars(r["revised_korean"]) for r in merged),
        "long_line_warning_rows_over_28":len(long_rows),
        "final_merged_tsv_sha256":sha(final_path),
        "patcher_ready_tsv_sha256":sha(patch_path),
        "game_files_modified":False,
        "runtime_space_encoding_validated":False,
        "runtime_smoke_required_before_full_patch":True,
    }
    (out/"sub33_qa_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB33 - Merge Full Semantic Review + Static QA",
        "",
        f"RowsMerged={report['rows_merged']}",
        "ReviewIndexExact=1..1976",
        f"ChangedVsSUB29={report['changed_vs_sub29']}",
        f"RetainedVsSUB29={report['retained_vs_sub29']}",
        f"ControlExactRows={report['control_exact_rows']}",
        "ControlMismatches=0",
        f"FinalUniqueHangul={report['final_unique_hangul']}",
        "NewHangulRequired=0",
        "JapaneseLettersRemaining=0",
        "UnicodeReplacementCharsRemaining=0",
        "CompatibilityJamoRemaining=0",
        f"Commands=MSG:{report['commands'].get('MSG',0)} MSG_FORCED:{report['commands'].get('MSG_FORCED',0)}",
        f"EventFiles={report['event_files']}",
        f"MaxVisibleCharsPerLine={report['max_visible_chars_per_line']}",
        f"LongLineWarningRowsOver28={report['long_line_warning_rows_over_28']}",
        f"FinalMergedTSVSHA256={report['final_merged_tsv_sha256']}",
        f"PatcherReadyTSVSHA256={report['patcher_ready_tsv_sha256']}",
        "",
        "StaticQA=PASS",
        "GameFilesModified=NO",
        "RuntimeSpaceEncodingValidated=NO",
        "RuntimeSmokeRequiredBeforeFullPatch=YES",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
