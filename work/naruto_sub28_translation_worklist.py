#!/usr/bin/env python3
# -*- coding: ascii -*-
# Naruto PSP SUB28 - Full 1976-row translation worklist + patcher length audit
#
# Read-only. No game patching.
#
# Purpose:
# 1) Merge the resolved SUB27 topology with the stable SUB25 1G<->1S rows.
# 2) Produce exactly one translation-work row for every game MSG/MSG_FORCED.
# 3) Separate:
#      reusable 1G1S Korean
#      subtitle-fragment merge work
#      one-subtitle-to-two-game-message split work
#      direct JP/EN -> KO translation work
# 4) Audit the local Stage14 patcher source for explicit size/byte constraints.
#
# This stage intentionally DOES NOT invent a per-message max_bytes value.

from __future__ import annotations
import argparse, ast, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

PINNED = {
    "sub27_mapping_units.tsv":"d8ea9611c5aa72ef12174e7d1f0742fbe47910296212964ffe590485d6905472",
    "sub27_all_unmapped_game_rows.tsv":"7cf35c6a89272fe75388f57c0bcb4c9d1d04f3a96ea3de3145637b583aa20b27",
    "sub27_anchor_overrides.tsv":"f44f9d923ed27453e939b936c98539efc1617459e28edffd1039b19625a222a1",
    "sub27_subtitle_exclusions.tsv":"334ba332d9c5597bfd7f8e1e7f645c154d242c915d0b239c885a77f52bf5f254",
    "sub25_fix2_subtitle_voice_groups.tsv":"f672817978cc7e2045f711436af88871a1e7e451a79b7fe0abb54e3b7b3b32e9",
    "sub19_fix1_kr_display_messages.tsv":"aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54",
    "sub19_fix1_us_display_messages.tsv":"1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9",
    "sub09_final_sequence.tsv":"59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e",
}

EXPECTED = {
    "game_rows":1976,
    "stable_1g1s":1407,
    "exception_1g1s":134,
    "exception_unvoiced_1g1s":16,
    "merge_subtitle_parts_to_1g":91,
    "split_1s_to_2g":24,
    "direct_translate":304,
    "ready_reuse":1557,
    "manual_task_rows":419,
    "split_merge_rows":115,
    "translation_task_units":407,
}

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
        for r in rows:w.writerow(r)

def pin(path:Path,expected:str,name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def stable_group(r):
    return (
        int(r["assigned_game_count"])==1
        and int(r["speaker_incompatible_count"])==0
        and r["potential_1G_2S_split"]=="NO"
    )

def split_pipe(s):
    return [x.strip() for x in (s or "").split("|") if x.strip()]

def split_space_ints(s):
    return [int(x) for x in (s or "").split() if x.strip()]

def normalize_text(s):
    return (s or "").replace("\r\n","\n").replace("\r","\n").strip()

def joined_sub_text(sub_by_seq, seqs):
    return "\n".join(normalize_text(sub_by_seq[s]["text"]) for s in seqs)

def hangul_chars(s):
    return {c for c in s if 0xAC00<=ord(c)<=0xD7A3}

def extract_controls(s):
    return " | ".join(re.findall(r"<[^>]+>",s or ""))

def load_font_chars(path:Path):
    if not path.exists():
        return set(), "MAPPING_FILE_NOT_FOUND"
    try:
        rows=read_tsv(path)
    except Exception as e:
        return set(), "MAPPING_READ_ERROR:"+str(e)
    chars=set()
    for r in rows:
        for v in r.values():
            if v and len(v)==1 and 0xAC00<=ord(v)<=0xD7A3:
                chars.add(v)
    if not chars:
        return set(), "NO_HANGUL_COLUMN_DETECTED"
    return chars, "OK"

def patcher_audit(path:Path,out_path:Path):
    if not path.exists():
        out_path.write_text(
            "Patcher source not found.\n"
            "Per-message max_bytes is NOT assumed.\n",
            encoding="utf-8"
        )
        return {
            "patcher_found":False,
            "patcher_sha256":"",
            "line_count":0,
            "explicit_max_bytes_token":False,
            "size_guard_snippet_count":0,
            "policy":"NOT_ASSUMED",
        }

    raw=path.read_bytes()
    try:
        text=raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text=raw.decode("cp932",errors="replace")
    lines=text.splitlines()

    max_token=bool(re.search(r"\bmax_bytes\b|\bmax_len(?:gth)?\b",text,re.I))
    interesting=[]
    guard_re=re.compile(
        r"(?:if|assert|raise|len\(|size|length|replacement|compress|encode|payload|entry)",
        re.I
    )
    focus_re=re.compile(
        r"(?:len\(|size|length|max_bytes|max_len|replacement|compressed|payload|encode\()",
        re.I
    )
    for i,line in enumerate(lines,1):
        if focus_re.search(line):
            lo=max(1,i-2);hi=min(len(lines),i+2)
            snippet="\n".join(f"{j:04d}: {lines[j-1]}" for j in range(lo,hi+1))
            interesting.append((i,snippet))

    # De-duplicate heavily overlapping windows.
    chosen=[]
    last=-100
    for i,s in interesting:
        if i-last>=3:
            chosen.append((i,s));last=i
        if len(chosen)>=120:
            break

    # AST function inventory if parseable.
    funcs=[]
    try:
        tree=ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                name=node.name
                if re.search(r"patch|replace|compress|decompress|event|tbl|dat|idx|encode|pack",name,re.I):
                    funcs.append((node.lineno,name))
        funcs=sorted(set(funcs))
    except Exception:
        funcs=[]

    report=[
        "Naruto Stage14 patcher length/size audit",
        "",
        f"Path: {path}",
        f"SHA256: {hashlib.sha256(raw).hexdigest()}",
        f"Lines: {len(lines)}",
        f"Explicit max_bytes/max_len token found: {'YES' if max_token else 'NO'}",
        "",
        "POLICY:",
        "  SUB28 does NOT assume that original JP payload byte length is a Korean max_bytes limit.",
        "  Any final byte cap must be supported by patcher/container evidence.",
        "",
        "Relevant function inventory:",
    ]
    for ln,name in funcs:
        report.append(f"  {ln:04d}: {name}")
    report += ["","Size/length/encoding source snippets:"]
    for _,s in chosen:
        report += ["-"*80,s]
    out_path.write_text("\n".join(report)+"\n",encoding="utf-8")

    return {
        "patcher_found":True,
        "patcher_sha256":hashlib.sha256(raw).hexdigest(),
        "line_count":len(lines),
        "explicit_max_bytes_token":max_token,
        "size_guard_snippet_count":len(chosen),
        "policy":"NOT_ASSUMED",
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_map=root/"analysis"/"sub"/"sub27_fix1_semantic_topology_resolution"/"sub27_mapping_units.tsv"
    p_unmapped=root/"analysis"/"sub"/"sub27_fix1_semantic_topology_resolution"/"sub27_all_unmapped_game_rows.tsv"
    p_overrides=root/"analysis"/"sub"/"sub27_fix1_semantic_topology_resolution"/"sub27_anchor_overrides.tsv"
    p_excl=root/"analysis"/"sub"/"sub27_fix1_semantic_topology_resolution"/"sub27_subtitle_exclusions.tsv"
    p_groups=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_subtitle_voice_groups.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned semantic inputs",flush=True)
    maps=pin(p_map,PINNED[p_map.name],"SUB27 mapping units")
    unmapped=pin(p_unmapped,PINNED[p_unmapped.name],"SUB27 unmapped")
    overrides=pin(p_overrides,PINNED[p_overrides.name],"SUB27 overrides")
    exclusions=pin(p_excl,PINNED[p_excl.name],"SUB27 exclusions")
    groups=pin(p_groups,PINNED[p_groups.name],"SUB25 groups")
    kr=pin(p_kr,PINNED[p_kr.name],"SUB19 KR")
    us=pin(p_us,PINNED[p_us.name],"SUB19 US")
    sub09=pin(p_sub,PINNED[p_sub.name],"SUB09")

    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=EXPECTED["game_rows"]:
        raise RuntimeError(f"game rows={len(game)}")

    sub_by_seq={int(r["sequence"]):r for r in sub09}
    game_by_key={game_key(r):r for r in game}
    game_pos={game_key(r):i for i,r in enumerate(game)}

    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:
            us_by[(r["event_file"],r["voice_id"])].append(r)

    print("[2/7] Build stable base + SUB27 semantic overlay",flush=True)
    stable_map={}
    for r in groups:
        if stable_group(r):
            k=r["assigned_game_keys"].strip()
            stable_map[k]=int(r["sub09_sequence"])
    if len(stable_map)!=1417:
        raise RuntimeError(f"raw stable base={len(stable_map)} expected=1417")

    overlay={}
    overlay_units={}
    for m in maps:
        gs=split_pipe(m["game_keys"])
        ss=split_space_ints(m["subtitle_sequences"])
        uid=f"B{int(m['block_id']):03d}_U{int(m['unit_index']):03d}"
        overlay_units[uid]={
            "unit_id":uid,
            "block_id":int(m["block_id"]),
            "unit_index":int(m["unit_index"]),
            "relation":m["relation"],
            "subs":ss,
            "games":gs,
            "note":m["note"],
        }
        for g in gs:
            if g in overlay:
                raise RuntimeError(f"duplicate semantic overlay game row: {g}")
            overlay[g]=overlay_units[uid]

    unmapped_keys={r["game_key"] for r in unmapped}
    final_mapped=set(stable_map)|set(overlay)
    if len(final_mapped)!=1672 or len(unmapped_keys)!=304:
        raise RuntimeError(
            f"semantic coverage mismatch mapped={len(final_mapped)} unmapped={len(unmapped_keys)}"
        )
    if final_mapped & unmapped_keys:
        raise RuntimeError("mapped/unmapped overlap")
    if final_mapped | unmapped_keys != set(game_by_key):
        raise RuntimeError("mapped/unmapped union does not cover all game rows")

    print("[3/7] Build one work row per game message",flush=True)
    font_map=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    font_chars,font_status=load_font_chars(font_map)

    rows=[]
    status_counts=Counter()
    ready=[]
    tasks=[]
    direct=[]
    splitmerge=[]

    for idx,g in enumerate(game,1):
        k=game_key(g)
        hits=us_by.get((g["event_file"],g["voice_id"]),[])
        en=" || ".join(x["text"] for x in hits)
        rel=""
        seqs=[]
        source_ko=""
        draft=""
        action=""
        unit_id=""

        if k in overlay:
            u=overlay[k]
            unit_id=u["unit_id"]
            rel=u["relation"]
            seqs=u["subs"]
            source_ko=joined_sub_text(sub_by_seq,seqs)
            if rel=="1G1S":
                status="EXCEPTION_1G1S"
                draft=source_ko
                action="REUSE_SUB09"
            elif rel=="UNVOICED_1G1S":
                status="EXCEPTION_UNVOICED_1G1S"
                draft=source_ko
                action="REUSE_SUB09"
            elif rel in ("1G_TO_2S","1G_TO_3S","ANCHOR_SPLIT_1G_TO_2S"):
                status="MERGE_SUBTITLE_PARTS_TO_1G"
                draft=source_ko
                action="MERGE_POLISH_REQUIRED"
            elif rel=="2G_TO_1S":
                status="SPLIT_1S_TO_2G"
                draft=""
                action="SEMANTIC_SPLIT_REQUIRED"
            else:
                raise RuntimeError(f"unknown relation {rel}")
        elif k in stable_map:
            status="STABLE_1G1S"
            seqs=[stable_map[k]]
            source_ko=joined_sub_text(sub_by_seq,seqs)
            draft=source_ko
            action="REUSE_SUB09"
        else:
            status="DIRECT_TRANSLATE"
            source_ko=""
            draft=""
            action="DIRECT_TRANSLATE_JP_EN"

        status_counts[status]+=1

        original_payload_bytes=int(g["payload_bytes"])
        controls=extract_controls(g["text"])
        missing=sorted(hangul_chars(draft)-font_chars) if draft and font_chars else []

        row={
            "game_global_dialogue_index":idx,
            "game_key":k,
            "event_file":g["event_file"],
            "event_display_index":g["event_display_index"],
            "line_no":g["line_no"],
            "command":g["command"],
            "speaker_code":g["speaker_code"],
            "voice_id":g["voice_id"],
            "japanese":g["text"],
            "english":en,
            "original_payload_bytes":original_payload_bytes,
            "original_control_tokens":controls,
            "topology_status":status,
            "relation":rel,
            "semantic_unit_id":unit_id,
            "sub09_sequences":" ".join(map(str,seqs)),
            "source_korean":source_ko,
            "draft_korean":draft,
            "translation_action":action,
            "font_mapping_status":font_status,
            "draft_missing_font_hangul":"".join(missing),
            "byte_budget_policy":"NOT_ASSUMED_FROM_ORIGINAL_JP_LENGTH",
            "final_korean":"",
            "review_notes":"",
        }
        rows.append(row)

        if status in ("STABLE_1G1S","EXCEPTION_1G1S","EXCEPTION_UNVOICED_1G1S"):
            ready.append(row)
        else:
            tasks.append(row)
        if status=="DIRECT_TRANSLATE":
            direct.append(row)
        if status in ("MERGE_SUBTITLE_PARTS_TO_1G","SPLIT_1S_TO_2G"):
            splitmerge.append(row)

    expected_status={
        "STABLE_1G1S":EXPECTED["stable_1g1s"],
        "EXCEPTION_1G1S":EXPECTED["exception_1g1s"],
        "EXCEPTION_UNVOICED_1G1S":EXPECTED["exception_unvoiced_1g1s"],
        "MERGE_SUBTITLE_PARTS_TO_1G":EXPECTED["merge_subtitle_parts_to_1g"],
        "SPLIT_1S_TO_2G":EXPECTED["split_1s_to_2g"],
        "DIRECT_TRANSLATE":EXPECTED["direct_translate"],
    }
    if dict(status_counts)!=expected_status:
        raise RuntimeError(f"status counts={dict(status_counts)} expected={expected_status}")
    if len(ready)!=EXPECTED["ready_reuse"]:
        raise RuntimeError(f"ready reuse={len(ready)}")
    if len(tasks)!=EXPECTED["manual_task_rows"]:
        raise RuntimeError(f"manual task rows={len(tasks)}")
    if len(splitmerge)!=EXPECTED["split_merge_rows"]:
        raise RuntimeError(f"split/merge rows={len(splitmerge)}")
    if len(direct)!=EXPECTED["direct_translate"]:
        raise RuntimeError(f"direct rows={len(direct)}")

    print("[4/7] Build semantic translation task units",flush=True)
    task_units=[]

    # 304 direct translations, one unit each.
    for r in direct:
        task_units.append({
            "task_unit_id":"DIRECT_"+r["game_key"],
            "task_type":"DIRECT_TRANSLATE",
            "game_keys":r["game_key"],
            "sub09_sequences":"",
            "speaker_codes":r["speaker_code"],
            "voice_ids":r["voice_id"],
            "japanese":r["japanese"],
            "english":r["english"],
            "korean_source":"",
            "instruction":"Translate JP/EN to natural Korean for this game MSG.",
            "final_korean_or_split_spec":"",
            "notes":"",
        })

    # 103 topology units requiring wording work: 91 merge + 12 split.
    for uid,u in sorted(overlay_units.items(),key=lambda kv:(kv[1]["block_id"],kv[1]["unit_index"])):
        rel=u["relation"]
        if rel not in ("1G_TO_2S","1G_TO_3S","ANCHOR_SPLIT_1G_TO_2S","2G_TO_1S"):
            continue
        gs=u["games"]
        seqs=u["subs"]
        jp=[]
        en=[]
        sp=[]
        vo=[]
        for k in gs:
            g=game_by_key[k]
            hits=us_by.get((g["event_file"],g["voice_id"]),[])
            jp.append(g["text"])
            en.append(" || ".join(x["text"] for x in hits))
            sp.append(g["speaker_code"])
            vo.append(g["voice_id"])
        instruction=(
            "Merge the Korean subtitle fragments into one natural game MSG."
            if rel!="2G_TO_1S"
            else "Split/rewrite the single Korean subtitle meaning across the two game MSG rows."
        )
        task_units.append({
            "task_unit_id":uid,
            "task_type":rel,
            "game_keys":" | ".join(gs),
            "sub09_sequences":" ".join(map(str,seqs)),
            "speaker_codes":" | ".join(sp),
            "voice_ids":" | ".join(vo),
            "japanese":" || ".join(jp),
            "english":" || ".join(en),
            "korean_source":joined_sub_text(sub_by_seq,seqs),
            "instruction":instruction,
            "final_korean_or_split_spec":"",
            "notes":u["note"],
        })

    if len(task_units)!=EXPECTED["translation_task_units"]:
        raise RuntimeError(f"translation task units={len(task_units)}")

    print("[5/7] Write worklists",flush=True)
    full_fields=list(rows[0].keys())
    write_tsv(out/"sub28_full_translation_manifest_1976.tsv",rows,full_fields)
    write_tsv(out/"sub28_ready_reuse_1557.tsv",ready,full_fields)
    write_tsv(out/"sub28_manual_task_rows_419.tsv",tasks,full_fields)
    write_tsv(out/"sub28_direct_translate_304.tsv",direct,full_fields)
    write_tsv(out/"sub28_split_merge_rows_115.tsv",splitmerge,full_fields)
    write_tsv(
        out/"sub28_translation_task_units_407.tsv",
        task_units,
        [
            "task_unit_id","task_type","game_keys","sub09_sequences","speaker_codes",
            "voice_ids","japanese","english","korean_source","instruction",
            "final_korean_or_split_spec","notes"
        ]
    )

    # Existing draft font coverage should remain inside the frozen SUB16 corpus.
    draft_hangul=set()
    missing_hangul=set()
    for r in rows:
        draft_hangul |= hangul_chars(r["draft_korean"])
        missing_hangul |= set(r["draft_missing_font_hangul"])

    font_report=[
        "Naruto SUB28 existing-draft font coverage",
        "",
        f"MappingPath={font_map}",
        f"MappingStatus={font_status}",
        f"DetectedMappedHangul={len(font_chars)}",
        f"ExistingDraftUniqueHangul={len(draft_hangul)}",
        f"ExistingDraftMissingHangul={len(missing_hangul)}",
        "MissingChars="+"".join(sorted(missing_hangul)),
        "",
        "Direct translations are still blank in SUB28.",
        "After direct/split/merge translation, new Hangul demand must be audited again",
        "before font allocation or patching.",
    ]
    (out/"sub28_font_coverage.txt").write_text("\n".join(font_report)+"\n",encoding="utf-8-sig")

    print("[6/7] Audit Stage14 patcher size/length behavior",flush=True)
    patcher=root/"analysis"/"stage14"/"naruto_patcher.py"
    patcher_info=patcher_audit(patcher,out/"sub28_patcher_length_audit.txt")

    payload_sizes=[int(r["payload_bytes"]) for r in game]
    payload_sorted=sorted(payload_sizes)
    def pct(p):
        i=min(len(payload_sorted)-1,max(0,round((len(payload_sorted)-1)*p)))
        return payload_sorted[i]

    print("[7/7] Report",flush=True)
    report={
        "stage":"SUB28",
        "mode":"READ_ONLY_FULL_TRANSLATION_WORKLIST_AND_PATCHER_AUDIT",
        "game_rows":len(rows),
        "status_counts":dict(status_counts),
        "ready_reuse_rows":len(ready),
        "manual_task_rows":len(tasks),
        "direct_translation_rows":len(direct),
        "split_merge_rows":len(splitmerge),
        "translation_task_units":len(task_units),
        "original_payload_bytes":{
            "min":min(payload_sizes),
            "p50":pct(0.50),
            "p95":pct(0.95),
            "max":max(payload_sizes),
        },
        "font_mapping_status":font_status,
        "font_detected_hangul":len(font_chars),
        "existing_draft_unique_hangul":len(draft_hangul),
        "existing_draft_missing_hangul":len(missing_hangul),
        "patcher_audit":patcher_info,
        "per_message_max_bytes_assumed":False,
        "final_translation_completed":False,
        "game_files_modified":False,
    }
    (out/"sub28_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB28 - Full Translation Worklist + Patcher Length Audit",
        "",
        f"GameRows={len(rows)}",
        f"Stable1G1S={status_counts['STABLE_1G1S']}",
        f"Exception1G1S={status_counts['EXCEPTION_1G1S']}",
        f"ExceptionUnvoiced1G1S={status_counts['EXCEPTION_UNVOICED_1G1S']}",
        f"MergeSubtitlePartsTo1G={status_counts['MERGE_SUBTITLE_PARTS_TO_1G']}",
        f"Split1STo2G={status_counts['SPLIT_1S_TO_2G']}",
        f"DirectTranslate={status_counts['DIRECT_TRANSLATE']}",
        "",
        f"ReadyReuseRows={len(ready)}",
        f"ManualTaskRows={len(tasks)}",
        f"TranslationTaskUnits={len(task_units)}",
        "",
        f"FontMappingStatus={font_status}",
        f"ExistingDraftUniqueHangul={len(draft_hangul)}",
        f"ExistingDraftMissingHangul={len(missing_hangul)}",
        "",
        f"PatcherFound={patcher_info['patcher_found']}",
        f"PatcherExplicitMaxBytesToken={patcher_info['explicit_max_bytes_token']}",
        "PerMessageMaxBytesAssumed=NO",
        "",
        "Next step:",
        "  translate/rewrite the 407 task units, then audit new Hangul demand and",
        "  actual patcher/container size constraints before building event TBLs.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
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
