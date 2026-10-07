#!/usr/bin/env python3
# Naruto PSP SUB19 - Canonical decoded event MSG inventory
#
# Fast, read-only stage.
# Uses the already-decoded canonical event scripts:
#   analysis/stage8/decoded_tbl/kr/*.tbl
#   analysis/stage8/decoded_tbl/us/*.tbl
#
# No recursive analysis tree scan.
# No DAT/IDX/BOOT/ISO modification.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_KR_FILES=39
EXPECTED_US_FILES=39
EXPECTED_KR_MSGS=2958
EXPECTED_US_MSGS=2965
EXPECTED_SUB09=1900

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def write_tsv(path:Path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def read_tsv(path:Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def event_num(path:Path):
    m=re.fullmatch(r"event(\d+)\.tbl",path.name,re.I)
    return int(m.group(1)) if m else 999999

def parse_msg_line(line:bytes):
    body=line.rstrip(b"\r\n")
    if not body.startswith(b"MSG ="):
        return None
    rest=body[len(b"MSG ="):]
    parts=rest.split(b",",2)
    if len(parts)!=3:
        return {
            "speaker_code":"",
            "voice_id":"",
            "raw_text":rest,
            "parse_status":"BAD_FIELD_COUNT",
        }
    speaker=parts[0].decode("ascii",errors="replace").strip()
    voice=parts[1].decode("ascii",errors="replace").strip()
    return {
        "speaker_code":speaker,
        "voice_id":voice,
        "raw_text":parts[2],
        "parse_status":"OK",
    }

def decode_text(raw:bytes):
    try:
        return raw.decode("cp932","strict"),"STRICT"
    except UnicodeDecodeError:
        return raw.decode("cp932","replace"),"REPLACE"

def strip_tags(text:str):
    # Preserve readable content while removing control-like markup for diagnostics.
    s=re.sub(r"<[^>]+>","",text)
    s=s.replace("　"," ")
    return s

def scan_side(side:str,root:Path):
    files=sorted(root.glob("event*.tbl"),key=event_num)
    messages=[]
    file_rows=[]
    speaker_counts=Counter()
    voice_counts=Counter()
    global_seq=0

    for file_index,p in enumerate(files):
        raw=p.read_bytes()
        event_msgs=[]
        bad=0
        for line_no,line in enumerate(raw.splitlines(),1):
            x=parse_msg_line(line)
            if x is None:
                continue
            global_seq+=1
            text,status=decode_text(x["raw_text"])
            clean=strip_tags(text)
            if x["parse_status"]!="OK":
                bad+=1
            speaker_counts[x["speaker_code"]]+=1
            if x["voice_id"]:
                voice_counts[x["voice_id"]]+=1

            row={
                "side":side,
                "global_msg_sequence":global_seq,
                "event_file":p.name,
                "event_number":event_num(p),
                "event_msg_index":len(event_msgs)+1,
                "line_no":line_no,
                "speaker_code":x["speaker_code"],
                "voice_id":x["voice_id"],
                "text":text,
                "clean_text":clean,
                "decode_status":status,
                "parse_status":x["parse_status"],
                "payload_bytes":len(x["raw_text"]),
                "payload_hex":x["raw_text"].hex(" "),
            }
            messages.append(row)
            event_msgs.append(row)

        file_rows.append({
            "side":side,
            "event_file":p.name,
            "event_number":event_num(p),
            "bytes":len(raw),
            "sha256":sha256_file(p),
            "msg_count":len(event_msgs),
            "bad_msg_rows":bad,
            "first_voice_id":next((r["voice_id"] for r in event_msgs if r["voice_id"]),""),
            "last_voice_id":next((r["voice_id"] for r in reversed(event_msgs) if r["voice_id"]),""),
        })

    return files,messages,file_rows,speaker_counts,voice_counts

def make_voice_crosswalk(kr_msgs,us_msgs):
    # Same-event + exact nonempty voice_id is a strong cross-language anchor.
    us_by=defaultdict(list)
    for r in us_msgs:
        if r["voice_id"]:
            us_by[(r["event_file"],r["voice_id"])].append(r)

    rows=[]
    for k in kr_msgs:
        if not k["voice_id"]:
            continue
        matches=us_by.get((k["event_file"],k["voice_id"]),[])
        rows.append({
            "event_file":k["event_file"],
            "voice_id":k["voice_id"],
            "kr_event_msg_index":k["event_msg_index"],
            "kr_speaker_code":k["speaker_code"],
            "kr_text":k["text"],
            "us_match_count":len(matches),
            "us_event_msg_indices":" ".join(str(x["event_msg_index"]) for x in matches),
            "us_speaker_codes":" ".join(x["speaker_code"] for x in matches),
            "us_texts":" || ".join(x["text"] for x in matches),
            "exact_unique_voice_anchor":"YES" if len(matches)==1 else "NO",
        })
    return rows

def event000_seed(sub09_rows,kr_msgs):
    ev=[r for r in kr_msgs if r["event_file"]=="event000.tbl"]
    # Known opening correspondence established by direct text comparison:
    # SUB09 sequence 19 begins with event000 MSG #1 (Shikamaru).
    sub_by={int(r["sequence"]):r for r in sub09_rows}
    speaker_map={
        "SIK":"시카마루",
        "SKR":"사쿠라",
        "NRT":"나루토",
        "TND":"츠나데",
        "SZN":"시즈네",
    }
    rows=[]
    # Only the first 20 game MSG rows are emitted as a seed diagnostic.
    # Do not pretend this is full 1:1 alignment: consecutive same-speaker
    # game messages can be merged into one OCR subtitle frame.
    for i,g in enumerate(ev[:20],1):
        nominal_seq=18+i
        s=sub_by.get(nominal_seq,{})
        rows.append({
            "game_event_msg_index":i,
            "game_speaker_code":g["speaker_code"],
            "game_speaker_known":speaker_map.get(g["speaker_code"],""),
            "game_voice_id":g["voice_id"],
            "game_jp_text":g["text"],
            "nominal_sub09_sequence_if_1to1":nominal_seq,
            "sub09_speaker_at_nominal":s.get("speaker",""),
            "sub09_text_at_nominal":s.get("text",""),
            "speaker_match_if_1to1":(
                "YES" if s and speaker_map.get(g["speaker_code"])==s.get("speaker")
                else "NO"
            ),
            "note":"SEED_DIAGNOSTIC_ONLY_NOT_FINAL_ALIGNMENT",
        })
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    kr_root=root/"analysis"/"stage8"/"decoded_tbl"/"kr"
    us_root=root/"analysis"/"stage8"/"decoded_tbl"/"us"
    sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    for p in (kr_root,us_root,sub09):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    print("[1/5] Scan canonical KR decoded event TBLs",flush=True)
    kr_files,kr_msgs,kr_file_rows,kr_speakers,kr_voices=scan_side("KR",kr_root)
    print(f"      files={len(kr_files)} messages={len(kr_msgs)}",flush=True)

    print("[2/5] Scan canonical US decoded event TBLs",flush=True)
    us_files,us_msgs,us_file_rows,us_speakers,us_voices=scan_side("US",us_root)
    print(f"      files={len(us_files)} messages={len(us_msgs)}",flush=True)

    if len(kr_files)!=EXPECTED_KR_FILES:
        raise RuntimeError(f"KR event file count {len(kr_files)} != {EXPECTED_KR_FILES}")
    if len(us_files)!=EXPECTED_US_FILES:
        raise RuntimeError(f"US event file count {len(us_files)} != {EXPECTED_US_FILES}")
    if len(kr_msgs)!=EXPECTED_KR_MSGS:
        raise RuntimeError(f"KR MSG count {len(kr_msgs)} != {EXPECTED_KR_MSGS}")
    if len(us_msgs)!=EXPECTED_US_MSGS:
        raise RuntimeError(f"US MSG count {len(us_msgs)} != {EXPECTED_US_MSGS}")

    print("[3/5] Compare KR/US event counts and voice anchors",flush=True)
    krf={r["event_file"]:r for r in kr_file_rows}
    usf={r["event_file"]:r for r in us_file_rows}
    events=sorted(set(krf)|set(usf),key=lambda n:int(re.search(r"\d+",n).group()))
    event_cmp=[]
    for ev in events:
        k=krf.get(ev)
        u=usf.get(ev)
        event_cmp.append({
            "event_file":ev,
            "kr_msg_count":k["msg_count"] if k else "",
            "us_msg_count":u["msg_count"] if u else "",
            "us_minus_kr":(
                int(u["msg_count"])-int(k["msg_count"]) if k and u else ""
            ),
            "kr_sha256":k["sha256"] if k else "",
            "us_sha256":u["sha256"] if u else "",
        })

    voice_x=make_voice_crosswalk(kr_msgs,us_msgs)
    unique_voice=sum(1 for r in voice_x if r["exact_unique_voice_anchor"]=="YES")

    print("[4/5] Load SUB09 final 1900 anchors",flush=True)
    sub_rows=read_tsv(sub09)
    if len(sub_rows)!=EXPECTED_SUB09:
        raise RuntimeError(f"SUB09 row count {len(sub_rows)} != {EXPECTED_SUB09}")

    seed=event000_seed(sub_rows,kr_msgs)

    print("[5/5] Write inventories",flush=True)
    write_tsv(out/"sub19_kr_messages.tsv",kr_msgs,list(kr_msgs[0].keys()))
    write_tsv(out/"sub19_us_messages.tsv",us_msgs,list(us_msgs[0].keys()))
    write_tsv(out/"sub19_kr_event_summary.tsv",kr_file_rows,list(kr_file_rows[0].keys()))
    write_tsv(out/"sub19_us_event_summary.tsv",us_file_rows,list(us_file_rows[0].keys()))
    write_tsv(
        out/"sub19_event_count_compare.tsv",event_cmp,
        ["event_file","kr_msg_count","us_msg_count","us_minus_kr","kr_sha256","us_sha256"]
    )
    write_tsv(
        out/"sub19_kr_speaker_codes.tsv",
        [{"speaker_code":k,"count":v} for k,v in kr_speakers.most_common()],
        ["speaker_code","count"]
    )
    write_tsv(
        out/"sub19_us_speaker_codes.tsv",
        [{"speaker_code":k,"count":v} for k,v in us_speakers.most_common()],
        ["speaker_code","count"]
    )
    write_tsv(
        out/"sub19_voice_crosswalk.tsv",voice_x,
        [
            "event_file","voice_id","kr_event_msg_index","kr_speaker_code","kr_text",
            "us_match_count","us_event_msg_indices","us_speaker_codes","us_texts",
            "exact_unique_voice_anchor"
        ]
    )
    write_tsv(
        out/"sub19_event000_sub09_seed.tsv",seed,
        list(seed[0].keys())
    )

    deltas=[r for r in event_cmp if r["us_minus_kr"] not in ("",0)]
    report={
        "stage":"SUB19",
        "mode":"READ_ONLY_CANONICAL_DECODED_INVENTORY",
        "kr_event_files":len(kr_files),
        "us_event_files":len(us_files),
        "kr_messages":len(kr_msgs),
        "us_messages":len(us_msgs),
        "us_minus_kr_messages":len(us_msgs)-len(kr_msgs),
        "event_count_differences":deltas,
        "kr_unique_speaker_codes":len(kr_speakers),
        "us_unique_speaker_codes":len(us_speakers),
        "kr_nonempty_voice_rows":sum(1 for r in kr_msgs if r["voice_id"]),
        "kr_us_unique_voice_anchors":unique_voice,
        "sub09_rows":len(sub_rows),
        "known_opening_relation":{
            "sub09_sequence":19,
            "game_event":"event000.tbl",
            "game_msg_index":1,
            "speaker_code":"SIK",
            "speaker":"시카마루",
            "sub09_text":"후아아~ 피곤하다...",
            "jp_text":next(r["text"] for r in kr_msgs if r["event_file"]=="event000.tbl"),
        },
        "game_files_modified":False,
    }
    (out/"sub19_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB19 - Canonical Decoded Event MSG Inventory",
        "",
        f"KREventFiles={len(kr_files)}",
        f"USEventFiles={len(us_files)}",
        f"KRMessages={len(kr_msgs)}",
        f"USMessages={len(us_msgs)}",
        f"USMinusKR={len(us_msgs)-len(kr_msgs)}",
        f"KRUniqueSpeakerCodes={len(kr_speakers)}",
        f"KRNonemptyVoiceRows={report['kr_nonempty_voice_rows']}",
        f"KRUSUniqueVoiceAnchors={unique_voice}",
        f"SUB09Rows={len(sub_rows)}",
        "",
        "Count differences:",
    ]
    for r in deltas:
        summary.append(
            f"  {r['event_file']}: KR={r['kr_msg_count']} "
            f"US={r['us_msg_count']} delta={r['us_minus_kr']:+d}"
        )
    summary += [
        "",
        "Confirmed opening anchor:",
        "  SUB09 #19 시카마루 '후아아~ 피곤하다...'",
        "  = event000.tbl MSG #1 SIK / s_a01_000",
        "",
        "Important:",
        "  2958 game MSG rows vs 1900 OCR anchors is NOT a 1:1 mapping.",
        "  Consecutive game messages can merge into one subtitle anchor,",
        "  and the video does not necessarily traverse every event/branch.",
        "",
        "No game files were modified.",
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
