#!/usr/bin/env python3
# -*- coding: ascii -*-
# Naruto PSP SUB29 - Completed Korean draft + runtime encoding/control validation
#
# Read-only. No game patching.
#
# Inputs:
#   SUB28 full 1976-row manifest
#   SUB28 407 translation task units
#   frozen SUB16 Hangul mapping
#   Stage14 naruto_patcher.py
#   external ASCII-only sub29_translations.json
#
# Outputs:
#   completed 407 task units
#   full 1976-row Korean draft
#   control-token exactness audit
#   runtime encoding / payload-size audit
#   font coverage audit
#   patcher constraint conclusion
#
# No per-message max_bytes limit is invented.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter
from pathlib import Path

EXPECTED_MANIFEST_SHA="8ea86fe4c32c1282ee03e31e3e2ac95e06e17c8e8f89c2ea12fbe6b33ee37e4b"
EXPECTED_TASKS_SHA="d5e4867a9d57538a5bc8b80d0b8ac3acf7d184f892edbae976a85f4f616bd1cd"
EXPECTED_FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
EXPECTED_PATCHER_SHA="6b06b849948b12d46ed17e9787c4872ba4271222dbafcbd19e5224cda139bb82"

EXPECTED_ROWS=1976
EXPECTED_TASKS=407
EXPECTED_DIRECT=304
EXPECTED_TOPOLOGY_GAME_ROWS=115
EXPECTED_REUSE=1557
EXPECTED_REUSE_FIX=3
EXPECTED_UNIQUE_HANGUL=673
EXPECTED_CONTROL_CHANGED=728
EXPECTED_NEW_MAX_PAYLOAD=112
EXPECTED_TOTAL_PAYLOAD_DELTA=-5912

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path:Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path:Path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def pin(path:Path,sha:str,name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=sha.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def controls(s):
    return re.findall(r"<[^>]+>",s or "")

def hangul_chars(s):
    return {c for c in (s or "") if 0xAC00<=ord(c)<=0xD7A3}

def has_japanese_letters(s):
    for c in s or "":
        o=ord(c)
        if (
            0x3040<=o<=0x30FF
            or 0x3400<=o<=0x4DBF
            or 0x4E00<=o<=0x9FFF
            or 0xFF61<=o<=0xFF9F
        ):
            return True
    return False

def normalize_newlines(s):
    return (s or "").replace("\r\n","\n").replace("\r","\n").strip()

def strip_ctrl(s):
    return re.sub(r"<[^>]+>","",s or "")

def split_korean_for_n_br(ko,jp,n):
    s=normalize_newlines(ko).replace("<br>","\n")
    parts=[p.strip() for p in s.split("\n") if p.strip()]
    if n==0:
        return " ".join(parts)
    if len(parts)==n+1:
        return "<br>".join(parts)

    plain=" ".join(parts)
    if n==1:
        jp_parts=jp.split("<br>")
        before_vis=len(strip_ctrl(jp_parts[0]))
        total_vis=sum(len(strip_ctrl(x)) for x in jp_parts)
        ratio=before_vis/max(1,total_vis)
        target=int(len(plain)*ratio)
        candidates=[i for i,c in enumerate(plain) if c==" "]
        if not candidates:
            return plain[:target]+"<br>"+plain[target:]
        viable=[
            i for i in candidates
            if i>=max(2,int(len(plain)*0.2))
            and i<=int(len(plain)*0.8)
        ] or candidates
        i=min(viable,key=lambda x:abs(x-target))
        return plain[:i].rstrip()+"<br>"+plain[i+1:].lstrip()

    jp_parts=jp.split("<br>")
    total=sum(len(strip_ctrl(x)) for x in jp_parts)
    ratios=[]
    acc=0
    for p in jp_parts[:-1]:
        acc+=len(strip_ctrl(p))
        ratios.append(acc/max(1,total))

    words=plain.split()
    if len(words)<=n:
        return plain

    positions=[]
    cur=0
    for wi,w in enumerate(words[:-1],1):
        cur+=len(w)
        positions.append((cur+wi-1,wi))

    cuts=[]
    for ratio in ratios:
        target=int(len(plain)*ratio)
        choices=[x for x in positions if x[1] not in cuts]
        _,wi=min(choices,key=lambda x:abs(x[0]-target))
        cuts.append(wi)

    cuts=sorted(set(cuts))
    out=[]
    start=0
    for ci in cuts:
        out.append(" ".join(words[start:ci]))
        start=ci
    out.append(" ".join(words[start:]))
    return "<br>".join(out)

def normalize_controls(jp,ko,key,special):
    if key in special:
        return special[key]

    jp_tokens=controls(jp)
    n_br=jp_tokens.count("<br>")

    if jp.startswith("<KOFF>\uff08<KON>") and jp.endswith("<KOFF>\uff09<KON>"):
        inner=normalize_newlines(ko)
        inner=re.sub(r"^<KOFF>\uff08<KON>","",inner)
        inner=re.sub(r"<KOFF>\uff09<KON>$","",inner)
        if inner.startswith("(") and inner.endswith(")"):
            inner=inner[1:-1].strip()
        if inner.startswith("\uff08") and inner.endswith("\uff09"):
            inner=inner[1:-1].strip()
        inner=split_korean_for_n_br(inner,jp,n_br)
        return "<KOFF>\uff08<KON>"+inner+"<KOFF>\uff09<KON>"

    if all(t=="<br>" for t in jp_tokens):
        return split_korean_for_n_br(ko,jp,n_br)

    if not jp_tokens:
        return split_korean_for_n_br(ko,jp,0)

    return normalize_newlines(ko)

def load_mapping(path:Path):
    rows=read_tsv(path)
    char_bytes={}
    for r in rows:
        h=r.get("hangul","")
        sj=r.get("donor_sjis_hex","")
        if h and len(h)==1 and sj:
            char_bytes[h]=bytes.fromhex(sj)
    return rows,char_bytes

def runtime_encode(s,char_bytes):
    out=bytearray()
    for c in s:
        if c in char_bytes:
            out.extend(char_bytes[c])
        else:
            out.extend(c.encode("cp932","strict"))
    return bytes(out)

def visible_line_lengths(s):
    lines=(s or "").split("<br>")
    vals=[]
    for line in lines:
        text=re.sub(r"<[^>]+>","",line)
        vals.append(len(text))
    return vals or [0]

def patcher_conclusion(path:Path):
    raw=path.read_bytes()
    text=raw.decode("utf-8-sig",errors="replace")
    checks={
        "explicit_max_bytes_token":bool(re.search(r"\bmax_bytes\b|\bmax_len(?:gth)?\b",text,re.I)),
        "encode_3_0_records_len_data":bool(re.search(r"def encode_3_0\(data\).*?len\(data\)",text,re.S)),
        "fsts_uses_32bit_size_fields":bool(re.search(r"struct\.unpack_from\(\s*\"<4I\"",text,re.S)),
        "pidx_patches_new_size":("plan[\"new_size\"]" in text and "p32(" in text),
        "dat_offsets_replanned":("primary_plan" in text and "new_offset" in text and "final_size" in text),
        "dat_growth_reported":("Growth:" in text or "DAT growth:" in text),
    }
    return checks

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_manifest=root/"analysis"/"sub"/"sub28_translation_worklist"/"sub28_full_translation_manifest_1976.tsv"
    p_tasks=root/"analysis"/"sub"/"sub28_translation_worklist"/"sub28_translation_task_units_407.tsv"
    p_font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    p_patcher=root/"analysis"/"stage14"/"naruto_patcher.py"
    p_trans=Path(__file__).with_name("sub29_translations.json")

    print("[1/8] Verify pinned inputs",flush=True)
    manifest=pin(p_manifest,EXPECTED_MANIFEST_SHA,"SUB28 manifest")
    tasks=pin(p_tasks,EXPECTED_TASKS_SHA,"SUB28 tasks")
    font_rows=pin(p_font,EXPECTED_FONT_SHA,"SUB16 font mapping")
    if not p_patcher.exists():
        raise RuntimeError(f"patcher missing: {p_patcher}")
    if sha256_file(p_patcher).lower()!=EXPECTED_PATCHER_SHA.lower():
        raise RuntimeError(f"patcher SHA mismatch: {sha256_file(p_patcher)}")
    if not p_trans.exists():
        raise RuntimeError(f"translation JSON missing: {p_trans}")

    translations=json.loads(p_trans.read_text(encoding="ascii"))
    direct=translations["direct_by_game"]
    single=translations["single_unit_final"]
    split=translations["split_unit_by_game"]
    reuse_fix=translations["reuse_fix_by_game"]
    special=translations["embedded_control_special_by_game"]

    if len(manifest)!=EXPECTED_ROWS:
        raise RuntimeError(f"manifest rows={len(manifest)}")
    if len(tasks)!=EXPECTED_TASKS:
        raise RuntimeError(f"task rows={len(tasks)}")
    if len(direct)!=EXPECTED_DIRECT:
        raise RuntimeError(f"direct translations={len(direct)}")
    if len(reuse_fix)!=EXPECTED_REUSE_FIX:
        raise RuntimeError(f"reuse fixes={len(reuse_fix)}")

    print("[2/8] Expand 407 task units to per-game translations",flush=True)
    topology_by_game={}
    completed_tasks=[]

    for t in tasks:
        typ=t["task_type"]
        uid=t["task_unit_id"]
        games=[x.strip() for x in t["game_keys"].split("|") if x.strip()]

        if typ=="DIRECT_TRANSLATE":
            if len(games)!=1 or games[0] not in direct:
                raise RuntimeError(f"direct task unresolved: {uid}")
            spec=direct[games[0]]
        elif typ in ("1G_TO_2S","1G_TO_3S","ANCHOR_SPLIT_1G_TO_2S"):
            if len(games)!=1 or uid not in single:
                raise RuntimeError(f"single-game topology unresolved: {uid}")
            topology_by_game[games[0]]=single[uid]
            spec=single[uid]
        elif typ=="2G_TO_1S":
            if uid not in split:
                raise RuntimeError(f"split task unresolved: {uid}")
            for g in games:
                if g not in split[uid]:
                    raise RuntimeError(f"split task missing game {uid}: {g}")
                topology_by_game[g]=split[uid][g]
            spec=" || ".join(f"{g}=>{split[uid][g]}" for g in games)
        else:
            raise RuntimeError(f"unknown task type: {typ}")

        r=dict(t)
        r["final_korean_or_split_spec"]=spec
        r["completion_status"]="COMPLETED"
        completed_tasks.append(r)

    if len(topology_by_game)!=EXPECTED_TOPOLOGY_GAME_ROWS:
        raise RuntimeError(f"topology game rows={len(topology_by_game)}")

    print("[3/8] Build 1976-row Korean draft",flush=True)
    _,char_bytes=load_mapping(p_font)
    font_chars=set(char_bytes)

    out_rows=[]
    control_changed=0
    runtime_errors=[]
    missing_chars=set()
    japanese_letter_rows=[]
    payload_rows=[]

    source_counts=Counter()

    for m in manifest:
        k=m["game_key"]
        status=m["topology_status"]

        if status in ("STABLE_1G1S","EXCEPTION_1G1S","EXCEPTION_UNVOICED_1G1S"):
            pre=reuse_fix.get(k,m["draft_korean"])
            source="SUB28_REUSE_FIX" if k in reuse_fix else "SUB28_REUSE"
        elif status=="DIRECT_TRANSLATE":
            if k not in direct:
                raise RuntimeError(f"direct game missing: {k}")
            pre=direct[k]
            source="SUB29_DIRECT"
        elif status in ("MERGE_SUBTITLE_PARTS_TO_1G","SPLIT_1S_TO_2G"):
            if k not in topology_by_game:
                raise RuntimeError(f"topology game missing: {k}")
            pre=topology_by_game[k]
            source="SUB29_TOPOLOGY_REWRITE"
        else:
            raise RuntimeError(f"unexpected status: {status}")

        final=normalize_controls(m["japanese"],pre,k,special)
        if pre!=final:
            control_changed+=1

        jp_ctrl=controls(m["japanese"])
        ko_ctrl=controls(final)
        ctrl_ok=(jp_ctrl==ko_ctrl)

        miss=sorted(hangul_chars(final)-font_chars)
        missing_chars.update(miss)

        try:
            encoded=runtime_encode(final,char_bytes)
            enc_ok=True
            enc_err=""
        except Exception as e:
            encoded=b""
            enc_ok=False
            enc_err=repr(e)
            runtime_errors.append((k,enc_err))

        if has_japanese_letters(final):
            japanese_letter_rows.append(k)

        old_bytes=int(m["original_payload_bytes"])
        new_bytes=len(encoded) if enc_ok else -1
        delta=(new_bytes-old_bytes) if enc_ok else 0
        lens=visible_line_lengths(final)

        r=dict(m)
        r["sub29_source"]=source
        r["pre_control_korean"]=pre
        r["final_korean"]=final
        r["original_control_sequence"]=" ".join(jp_ctrl)
        r["final_control_sequence"]=" ".join(ko_ctrl)
        r["control_tokens_exact"]="YES" if ctrl_ok else "NO"
        r["runtime_encode_ok"]="YES" if enc_ok else "NO"
        r["runtime_encode_error"]=enc_err
        r["final_payload_bytes"]=new_bytes
        r["payload_delta_bytes"]=delta
        r["final_line_count"]=len(lens)
        r["max_visible_chars_per_line"]=max(lens)
        r["missing_font_hangul"]="".join(miss)
        out_rows.append(r)
        source_counts[source]+=1

        payload_rows.append({
            "game_key":k,
            "event_file":m["event_file"],
            "event_display_index":m["event_display_index"],
            "topology_status":status,
            "original_payload_bytes":old_bytes,
            "final_payload_bytes":new_bytes,
            "payload_delta_bytes":delta,
            "final_line_count":len(lens),
            "max_visible_chars_per_line":max(lens),
            "control_tokens_exact":"YES" if ctrl_ok else "NO",
            "runtime_encode_ok":"YES" if enc_ok else "NO",
        })

    if len(out_rows)!=EXPECTED_ROWS:
        raise RuntimeError(f"output rows={len(out_rows)}")
    if runtime_errors:
        raise RuntimeError(f"runtime encoding failures={len(runtime_errors)} first={runtime_errors[:3]}")
    if missing_chars:
        raise RuntimeError("new Hangul glyphs required: "+"".join(sorted(missing_chars)))
    if japanese_letter_rows:
        raise RuntimeError(f"Japanese letters remain in Korean draft: {japanese_letter_rows[:10]}")
    if any(r["control_tokens_exact"]!="YES" for r in out_rows):
        raise RuntimeError("control-token mismatch exists")
    if any("\n" in r["final_korean"] or "\r" in r["final_korean"] for r in out_rows):
        raise RuntimeError("literal newline remains inside game payload")
    if any("\ufffd" in r["final_korean"] for r in out_rows):
        raise RuntimeError("Unicode replacement character remains")

    if control_changed!=EXPECTED_CONTROL_CHANGED:
        raise RuntimeError(f"control-normalized rows={control_changed}")

    unique_hangul=set()
    for r in out_rows:
        unique_hangul |= hangul_chars(r["final_korean"])
    if len(unique_hangul)!=EXPECTED_UNIQUE_HANGUL:
        raise RuntimeError(f"unique Hangul={len(unique_hangul)}")

    print("[4/8] Validate source/result counts",flush=True)
    expected_source={
        "SUB28_REUSE":1554,
        "SUB28_REUSE_FIX":3,
        "SUB29_DIRECT":304,
        "SUB29_TOPOLOGY_REWRITE":115,
    }
    if dict(source_counts)!=expected_source:
        raise RuntimeError(f"source counts={dict(source_counts)}")

    payload_sizes=[int(r["final_payload_bytes"]) for r in out_rows]
    old_sizes=[int(r["original_payload_bytes"]) for r in out_rows]
    deltas=[n-o for n,o in zip(payload_sizes,old_sizes)]
    if max(payload_sizes)!=EXPECTED_NEW_MAX_PAYLOAD:
        raise RuntimeError(f"max payload={max(payload_sizes)}")
    if sum(deltas)!=EXPECTED_TOTAL_PAYLOAD_DELTA:
        raise RuntimeError(f"total payload delta={sum(deltas)}")

    print("[5/8] Write translation outputs",flush=True)
    full_fields=list(out_rows[0].keys())
    write_tsv(out/"sub29_full_korean_draft_1976.tsv",out_rows,full_fields)
    write_tsv(
        out/"sub29_completed_task_units_407.tsv",
        completed_tasks,
        list(completed_tasks[0].keys())
    )
    write_tsv(
        out/"sub29_payload_size_audit.tsv",
        payload_rows,
        list(payload_rows[0].keys())
    )

    # Longest lines are informational only; no arbitrary display cap is enforced.
    longest=sorted(
        out_rows,
        key=lambda r:(int(r["max_visible_chars_per_line"]),int(r["final_payload_bytes"])),
        reverse=True
    )[:100]
    write_tsv(
        out/"sub29_longest_lines_top100.tsv",
        longest,
        [
            "game_key","event_file","event_display_index","speaker_code","voice_id",
            "japanese","final_korean","final_line_count","max_visible_chars_per_line",
            "original_payload_bytes","final_payload_bytes"
        ]
    )

    print("[6/8] Write font/control/encoding reports",flush=True)
    font_report=[
        "Naruto SUB29 font coverage",
        "",
        f"FrozenMappingRows={len(font_rows)}",
        f"FinalDraftUniqueHangul={len(unique_hangul)}",
        "NewHangulRequired=0",
        "NewHangulChars=",
        "",
        "The complete 1976-row draft uses only Hangul already present in the",
        "collision-free SUB16 mapping. No new donor allocation is required.",
    ]
    (out/"sub29_font_validation.txt").write_text(
        "\n".join(font_report)+"\n",encoding="utf-8-sig"
    )

    control_report=[
        "Naruto SUB29 control-token validation",
        "",
        f"Rows={len(out_rows)}",
        f"RowsControlNormalized={control_changed}",
        f"ExactControlSequenceMatches={sum(r['control_tokens_exact']=='YES' for r in out_rows)}",
        "ControlSequenceMismatches=0",
        "LiteralNewlineRows=0",
        "",
        "Validated token order includes <br>, <KOFF>, and <KON>.",
    ]
    (out/"sub29_control_validation.txt").write_text(
        "\n".join(control_report)+"\n",encoding="utf-8-sig"
    )

    enc_report=[
        "Naruto SUB29 runtime encoding validation",
        "",
        f"Rows={len(out_rows)}",
        f"RuntimeEncodingPass={sum(r['runtime_encode_ok']=='YES' for r in out_rows)}",
        "RuntimeEncodingFail=0",
        f"OriginalPayloadBytesTotal={sum(old_sizes)}",
        f"FinalPayloadBytesTotal={sum(payload_sizes)}",
        f"TotalPayloadDeltaBytes={sum(deltas)}",
        f"FinalPayloadMin={min(payload_sizes)}",
        f"FinalPayloadMax={max(payload_sizes)}",
        f"RowsGrowing={sum(d>0 for d in deltas)}",
        f"RowsSameSize={sum(d==0 for d in deltas)}",
        f"RowsShrinking={sum(d<0 for d in deltas)}",
    ]
    (out/"sub29_runtime_encoding_validation.txt").write_text(
        "\n".join(enc_report)+"\n",encoding="utf-8-sig"
    )

    print("[7/8] Reconfirm Stage14 packer constraints",flush=True)
    pc=patcher_conclusion(p_patcher)
    if not (
        pc["encode_3_0_records_len_data"]
        and pc["fsts_uses_32bit_size_fields"]
        and pc["pidx_patches_new_size"]
        and pc["dat_offsets_replanned"]
    ):
        raise RuntimeError(f"patcher structural evidence incomplete: {pc}")

    patch_report=[
        "Naruto SUB29 Stage14 patcher constraint conclusion",
        "",
        f"PatcherSHA256={sha256_file(p_patcher)}",
        f"ExplicitMaxBytesToken={'YES' if pc['explicit_max_bytes_token'] else 'NO'}",
        f"Encode3_0RecordsDecodedLength={'YES' if pc['encode_3_0_records_len_data'] else 'NO'}",
        f"FSTSSizeFields32Bit={'YES' if pc['fsts_uses_32bit_size_fields'] else 'NO'}",
        f"PIDXNewSizePatched={'YES' if pc['pidx_patches_new_size'] else 'NO'}",
        f"DATOffsetsReplanned={'YES' if pc['dat_offsets_replanned'] else 'NO'}",
        f"DATGrowthReported={'YES' if pc['dat_growth_reported'] else 'NO'}",
        "",
        "Conclusion:",
        "  Stage14 does not require a replacement event TBL to keep the original",
        "  decoded resource size or original per-message Japanese byte length.",
        "  It records the new decoded/stored size, rebuilds FSTS members, recalculates",
        "  following offsets, patches embedded/external indexes, and permits DAT growth.",
        "",
        "  Therefore original_payload_bytes is NOT treated as max_bytes.",
        "",
        "Limitation:",
        "  This proves packer/container flexibility, not an unlimited runtime text/UI",
        "  buffer. Runtime smoke testing is still required before a full batch patch.",
    ]
    (out/"sub29_patcher_constraint_conclusion.txt").write_text(
        "\n".join(patch_report)+"\n",encoding="utf-8-sig"
    )

    print("[8/8] Final report",flush=True)
    report={
        "stage":"SUB29",
        "mode":"READ_ONLY_COMPLETED_KOREAN_DRAFT_VALIDATION",
        "game_rows":len(out_rows),
        "translation_task_units_completed":len(completed_tasks),
        "source_counts":dict(source_counts),
        "control_normalized_rows":control_changed,
        "control_exact_rows":sum(r["control_tokens_exact"]=="YES" for r in out_rows),
        "runtime_encoding_pass_rows":sum(r["runtime_encode_ok"]=="YES" for r in out_rows),
        "runtime_encoding_fail_rows":0,
        "frozen_font_mapping_rows":len(font_rows),
        "final_unique_hangul":len(unique_hangul),
        "new_hangul_required":0,
        "original_payload_bytes_total":sum(old_sizes),
        "final_payload_bytes_total":sum(payload_sizes),
        "total_payload_delta_bytes":sum(deltas),
        "final_payload_max":max(payload_sizes),
        "rows_growing":sum(d>0 for d in deltas),
        "rows_same_size":sum(d==0 for d in deltas),
        "rows_shrinking":sum(d<0 for d in deltas),
        "per_message_original_byte_cap_assumed":False,
        "patcher_container_allows_relayout":True,
        "runtime_smoke_required_before_batch_patch":True,
        "game_files_modified":False,
    }
    (out/"sub29_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB29 - Completed Korean Draft Validation",
        "",
        f"GameRows={len(out_rows)}",
        f"TranslationTaskUnitsCompleted={len(completed_tasks)}",
        "SourceCounts="+json.dumps(dict(source_counts),ensure_ascii=False,sort_keys=True),
        "",
        f"ControlNormalizedRows={control_changed}",
        f"ControlExactRows={sum(r['control_tokens_exact']=='YES' for r in out_rows)}",
        "ControlMismatches=0",
        "",
        f"RuntimeEncodingPass={sum(r['runtime_encode_ok']=='YES' for r in out_rows)}",
        "RuntimeEncodingFail=0",
        f"FrozenFontMappingRows={len(font_rows)}",
        f"FinalUniqueHangul={len(unique_hangul)}",
        "NewHangulRequired=0",
        "",
        f"OriginalPayloadBytesTotal={sum(old_sizes)}",
        f"FinalPayloadBytesTotal={sum(payload_sizes)}",
        f"TotalPayloadDeltaBytes={sum(deltas)}",
        f"FinalPayloadMax={max(payload_sizes)}",
        f"RowsGrowing={sum(d>0 for d in deltas)}",
        f"RowsSameSize={sum(d==0 for d in deltas)}",
        f"RowsShrinking={sum(d<0 for d in deltas)}",
        "",
        "Patcher conclusion:",
        "  no original-message max_bytes rule is present in Stage14;",
        "  resource sizes and offsets are rebuilt with new values.",
        "",
        "Next:",
        "  build a SMALL translated runtime smoke first, then patch all 39 event TBLs",
        "  only after visual/runtime validation.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified in SUB29.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
