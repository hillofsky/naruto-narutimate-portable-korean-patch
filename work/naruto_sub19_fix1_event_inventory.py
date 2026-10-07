#!/usr/bin/env python3
# Naruto PSP SUB19 FIX1 - Accurate decoded event message inventory
#
# Fixes SUB19 counting bug:
# old "2958/2965" values were substring counts of b"MSG =" and included
# WAIT_NOMSG = rows. This version parses command tokens at line start:
#   MSG
#   MSG_FORCED
#   MSG_SYS
# while explicitly excluding WAIT_NOMSG.
#
# Read-only. No game files modified.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_KR_FILES=39
EXPECTED_US_FILES=39
EXPECTED_NORMAL_MSG_KR=1932
EXPECTED_NORMAL_MSG_US=1932
EXPECTED_SUB09=1900

DISPLAY_RE=re.compile(rb"^\s*(MSG(?:_[A-Z0-9]+)?)\s*=(.*)$",re.I)

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

def event_num(path:Path):
    m=re.fullmatch(r"event(\d+)\.tbl",path.name,re.I)
    return int(m.group(1)) if m else 999999

def decode_cp932(raw:bytes):
    try:
        return raw.decode("cp932","strict"),"STRICT"
    except UnicodeDecodeError:
        return raw.decode("cp932","replace"),"REPLACE"

def strip_tags(text:str):
    s=re.sub(r"<[^>]+>","",text)
    return s.replace("　"," ")

def parse_display_line(line:bytes):
    body=line.rstrip(b"\r\n")
    m=DISPLAY_RE.match(body)
    if not m:
        return None

    command=m.group(1).decode("ascii",errors="replace").upper()
    rest=m.group(2)

    speaker=""
    voice=""
    payload=b""
    parse_status="OK"

    if command in ("MSG","MSG_FORCED"):
        parts=rest.split(b",",2)
        if len(parts)==3:
            speaker=parts[0].strip().decode("ascii",errors="replace")
            voice=parts[1].strip().decode("ascii",errors="replace")
            payload=parts[2]
        else:
            payload=rest
            parse_status=f"EXPECTED_3_FIELDS_GOT_{len(parts)}"
    elif command=="MSG_SYS":
        # System message has only payload; commas inside English text are content.
        payload=rest
    else:
        # Future/unknown MSG_* command: preserve as one raw payload.
        payload=rest
        parse_status="UNKNOWN_MSG_COMMAND"

    text,status=decode_cp932(payload)
    return {
        "command":command,
        "speaker_code":speaker,
        "voice_id":voice,
        "raw_text":payload,
        "text":text,
        "clean_text":strip_tags(text),
        "decode_status":status,
        "parse_status":parse_status,
    }

def scan_side(side:str,root:Path):
    files=sorted(root.glob("event*.tbl"),key=event_num)
    messages=[]
    file_rows=[]
    command_counts=Counter()
    speaker_counts=Counter()
    voice_counts=Counter()
    global_seq=0

    for file_index,p in enumerate(files):
        raw=p.read_bytes()
        local=[]
        local_commands=Counter()
        wait_nomsg=0
        raw_msg_substring=raw.count(b"MSG =")

        for line_no,line in enumerate(raw.splitlines(),1):
            stripped=line.lstrip()
            if stripped.startswith(b"WAIT_NOMSG"):
                wait_nomsg+=1

            x=parse_display_line(line)
            if x is None:
                continue

            global_seq+=1
            command_counts[x["command"]]+=1
            local_commands[x["command"]]+=1
            if x["speaker_code"]:
                speaker_counts[x["speaker_code"]]+=1
            if x["voice_id"]:
                voice_counts[x["voice_id"]]+=1

            row={
                "side":side,
                "global_display_sequence":global_seq,
                "event_file":p.name,
                "event_number":event_num(p),
                "event_display_index":len(local)+1,
                "line_no":line_no,
                "command":x["command"],
                "speaker_code":x["speaker_code"],
                "voice_id":x["voice_id"],
                "text":x["text"],
                "clean_text":x["clean_text"],
                "decode_status":x["decode_status"],
                "parse_status":x["parse_status"],
                "payload_bytes":len(x["raw_text"]),
                "payload_hex":x["raw_text"].hex(" "),
            }
            messages.append(row)
            local.append(row)

        file_rows.append({
            "side":side,
            "event_file":p.name,
            "event_number":event_num(p),
            "bytes":len(raw),
            "sha256":sha256_file(p),
            "display_message_count":len(local),
            "msg_count":local_commands["MSG"],
            "msg_forced_count":local_commands["MSG_FORCED"],
            "msg_sys_count":local_commands["MSG_SYS"],
            "other_msg_command_count":sum(
                v for k,v in local_commands.items()
                if k not in ("MSG","MSG_FORCED","MSG_SYS")
            ),
            "wait_nomsg_count":wait_nomsg,
            "raw_substring_MSG_space_equals":raw_msg_substring,
            "raw_substring_minus_wait_nomsg":raw_msg_substring-wait_nomsg,
            "first_voice_id":next((r["voice_id"] for r in local if r["voice_id"]),""),
            "last_voice_id":next((r["voice_id"] for r in reversed(local) if r["voice_id"]),""),
        })

    return files,messages,file_rows,command_counts,speaker_counts,voice_counts

def build_voice_crosswalk(kr_msgs,us_msgs):
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
            "command":k["command"],
            "voice_id":k["voice_id"],
            "kr_event_display_index":k["event_display_index"],
            "kr_speaker_code":k["speaker_code"],
            "kr_text":k["text"],
            "us_match_count":len(matches),
            "us_commands":" ".join(x["command"] for x in matches),
            "us_event_display_indices":" ".join(str(x["event_display_index"]) for x in matches),
            "us_speaker_codes":" ".join(x["speaker_code"] for x in matches),
            "us_texts":" || ".join(x["text"] for x in matches),
            "exact_unique_voice_anchor":"YES" if len(matches)==1 else "NO",
        })
    return rows

def build_event000_seed(sub_rows,kr_msgs):
    sub_by={int(r["sequence"]):r for r in sub_rows}
    ev=[r for r in kr_msgs if r["event_file"]=="event000.tbl" and r["command"] in ("MSG","MSG_FORCED")]
    speaker_map={
        "SIK":"시카마루","SKR":"사쿠라","NRT":"나루토",
        "TND":"츠나데","SZN":"시즈네","JRY":"지라이야",
        "ORC":"오로치마루","KBT":"카부토",
    }
    rows=[]
    for i,g in enumerate(ev[:30],1):
        nominal=18+i
        s=sub_by.get(nominal,{})
        rows.append({
            "game_dialogue_index":i,
            "game_command":g["command"],
            "game_speaker_code":g["speaker_code"],
            "game_speaker_known":speaker_map.get(g["speaker_code"],""),
            "game_voice_id":g["voice_id"],
            "game_jp_text":g["text"],
            "nominal_sub09_sequence_if_1to1":nominal,
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

    print("[1/5] Parse KR display-message commands",flush=True)
    kr_files,kr_msgs,kr_filesum,kr_cmds,kr_speakers,kr_voices=scan_side("KR",kr_root)
    print(f"      files={len(kr_files)} display={len(kr_msgs)} commands={dict(kr_cmds)}",flush=True)

    print("[2/5] Parse US display-message commands",flush=True)
    us_files,us_msgs,us_filesum,us_cmds,us_speakers,us_voices=scan_side("US",us_root)
    print(f"      files={len(us_files)} display={len(us_msgs)} commands={dict(us_cmds)}",flush=True)

    if len(kr_files)!=EXPECTED_KR_FILES:
        raise RuntimeError(f"KR event files={len(kr_files)} expected={EXPECTED_KR_FILES}")
    if len(us_files)!=EXPECTED_US_FILES:
        raise RuntimeError(f"US event files={len(us_files)} expected={EXPECTED_US_FILES}")
    if kr_cmds["MSG"]!=EXPECTED_NORMAL_MSG_KR:
        raise RuntimeError(f"KR normal MSG={kr_cmds['MSG']} expected={EXPECTED_NORMAL_MSG_KR}")
    if us_cmds["MSG"]!=EXPECTED_NORMAL_MSG_US:
        raise RuntimeError(f"US normal MSG={us_cmds['MSG']} expected={EXPECTED_NORMAL_MSG_US}")

    bad_kr=[r for r in kr_msgs if r["parse_status"] not in ("OK","UNKNOWN_MSG_COMMAND")]
    bad_us=[r for r in us_msgs if r["parse_status"] not in ("OK","UNKNOWN_MSG_COMMAND")]
    if bad_kr or bad_us:
        raise RuntimeError(
            f"display-row parse failures KR={len(bad_kr)} US={len(bad_us)}"
        )

    print("[3/5] Compare event counts + voice anchors",flush=True)
    krf={r["event_file"]:r for r in kr_filesum}
    usf={r["event_file"]:r for r in us_filesum}
    events=sorted(set(krf)|set(usf),key=lambda n:int(re.search(r"\d+",n).group()))
    event_cmp=[]
    for ev in events:
        k=krf.get(ev); u=usf.get(ev)
        event_cmp.append({
            "event_file":ev,
            "kr_display":k["display_message_count"] if k else "",
            "us_display":u["display_message_count"] if u else "",
            "display_delta_us_minus_kr":(
                int(u["display_message_count"])-int(k["display_message_count"])
                if k and u else ""
            ),
            "kr_msg":k["msg_count"] if k else "",
            "us_msg":u["msg_count"] if u else "",
            "kr_forced":k["msg_forced_count"] if k else "",
            "us_forced":u["msg_forced_count"] if u else "",
            "kr_sys":k["msg_sys_count"] if k else "",
            "us_sys":u["msg_sys_count"] if u else "",
            "kr_wait_nomsg":k["wait_nomsg_count"] if k else "",
            "us_wait_nomsg":u["wait_nomsg_count"] if u else "",
        })

    voice_x=build_voice_crosswalk(kr_msgs,us_msgs)

    print("[4/5] Load SUB09 and opening seed",flush=True)
    sub_rows=read_tsv(sub09)
    if len(sub_rows)!=EXPECTED_SUB09:
        raise RuntimeError(f"SUB09 rows={len(sub_rows)} expected={EXPECTED_SUB09}")
    seed=build_event000_seed(sub_rows,kr_msgs)

    print("[5/5] Write reports",flush=True)
    write_tsv(out/"sub19_fix1_kr_display_messages.tsv",kr_msgs,list(kr_msgs[0].keys()))
    write_tsv(out/"sub19_fix1_us_display_messages.tsv",us_msgs,list(us_msgs[0].keys()))
    write_tsv(out/"sub19_fix1_kr_event_summary.tsv",kr_filesum,list(kr_filesum[0].keys()))
    write_tsv(out/"sub19_fix1_us_event_summary.tsv",us_filesum,list(us_filesum[0].keys()))
    write_tsv(
        out/"sub19_fix1_command_counts.tsv",
        [
            {"side":"KR","command":k,"count":v}
            for k,v in sorted(kr_cmds.items())
        ]+[
            {"side":"US","command":k,"count":v}
            for k,v in sorted(us_cmds.items())
        ],
        ["side","command","count"]
    )
    write_tsv(
        out/"sub19_fix1_event_compare.tsv",event_cmp,
        [
            "event_file","kr_display","us_display","display_delta_us_minus_kr",
            "kr_msg","us_msg","kr_forced","us_forced","kr_sys","us_sys",
            "kr_wait_nomsg","us_wait_nomsg"
        ]
    )
    write_tsv(
        out/"sub19_fix1_kr_speaker_codes.tsv",
        [{"speaker_code":k,"count":v} for k,v in kr_speakers.most_common()],
        ["speaker_code","count"]
    )
    write_tsv(
        out/"sub19_fix1_voice_crosswalk.tsv",voice_x,
        [
            "event_file","command","voice_id","kr_event_display_index",
            "kr_speaker_code","kr_text","us_match_count","us_commands",
            "us_event_display_indices","us_speaker_codes","us_texts",
            "exact_unique_voice_anchor"
        ]
    )
    write_tsv(
        out/"sub19_fix1_event000_sub09_seed.tsv",seed,list(seed[0].keys())
    )

    raw_substring_kr=sum(int(r["raw_substring_MSG_space_equals"]) for r in kr_filesum)
    wait_kr=sum(int(r["wait_nomsg_count"]) for r in kr_filesum)
    raw_substring_us=sum(int(r["raw_substring_MSG_space_equals"]) for r in us_filesum)
    wait_us=sum(int(r["wait_nomsg_count"]) for r in us_filesum)

    report={
        "stage":"SUB19_FIX1",
        "mode":"READ_ONLY_ACCURATE_MESSAGE_COMMAND_INVENTORY",
        "kr_event_files":len(kr_files),
        "us_event_files":len(us_files),
        "kr_command_counts":dict(kr_cmds),
        "us_command_counts":dict(us_cmds),
        "kr_display_message_rows":len(kr_msgs),
        "us_display_message_rows":len(us_msgs),
        "kr_raw_MSG_space_equals_substring_count":raw_substring_kr,
        "kr_wait_nomsg_rows":wait_kr,
        "kr_substring_minus_wait":raw_substring_kr-wait_kr,
        "us_raw_MSG_space_equals_substring_count":raw_substring_us,
        "us_wait_nomsg_rows":wait_us,
        "us_substring_minus_wait":raw_substring_us-wait_us,
        "sub09_rows":len(sub_rows),
        "unique_voice_anchors":sum(
            1 for r in voice_x if r["exact_unique_voice_anchor"]=="YES"
        ),
        "counting_bug_explained":(
            "Old 2958/2965 values counted raw substring 'MSG =' which also "
            "occurs inside WAIT_NOMSG =. They are not dialogue counts."
        ),
        "known_opening_anchor":{
            "sub09_sequence":19,
            "event_file":"event000.tbl",
            "game_dialogue_index":1,
            "speaker_code":"SIK",
            "voice_id":"s_a01_000",
        },
        "game_files_modified":False,
    }
    (out/"sub19_fix1_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    diff_events=[r for r in event_cmp if r["display_delta_us_minus_kr"] not in ("",0)]

    summary=[
        "Naruto PSP SUB19 FIX1 - Accurate Decoded Event Message Inventory",
        "",
        f"KREventFiles={len(kr_files)}",
        f"USEventFiles={len(us_files)}",
        f"KRDisplayMessageRows={len(kr_msgs)}",
        f"USDisplayMessageRows={len(us_msgs)}",
        "KRCommands="+", ".join(f"{k}={v}" for k,v in sorted(kr_cmds.items())),
        "USCommands="+", ".join(f"{k}={v}" for k,v in sorted(us_cmds.items())),
        f"KRNormalMSG={kr_cmds['MSG']}",
        f"USNormalMSG={us_cmds['MSG']}",
        f"KRRawSubstringMSGEquals={raw_substring_kr}",
        f"KRWAIT_NOMSG={wait_kr}",
        f"KRRawMinusWAIT={raw_substring_kr-wait_kr}",
        f"USRawSubstringMSGEquals={raw_substring_us}",
        f"USWAIT_NOMSG={wait_us}",
        f"USRawMinusWAIT={raw_substring_us-wait_us}",
        f"SUB09Rows={len(sub_rows)}",
        f"UniqueVoiceAnchors={report['unique_voice_anchors']}",
        "",
        "Counting bug fixed:",
        "  2958/2965 were substring counts, not dialogue counts.",
        "  WAIT_NOMSG rows were included because 'WAIT_NOMSG =' contains 'MSG ='.",
        "",
        "Display commands now inventoried separately:",
        "  MSG / MSG_FORCED / MSG_SYS / any other MSG_*",
        "",
        "Confirmed opening anchor remains:",
        "  SUB09 #19 = event000 dialogue #1 SIK / s_a01_000",
        "",
        "Events with KR/US display-row count differences:",
    ]
    if diff_events:
        for r in diff_events:
            summary.append(
                f"  {r['event_file']}: KR={r['kr_display']} "
                f"US={r['us_display']} delta={int(r['display_delta_us_minus_kr']):+d}"
            )
    else:
        summary.append("  none")

    summary += ["","No game files were modified."]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
