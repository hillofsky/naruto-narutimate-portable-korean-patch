#!/usr/bin/env python3
# Naruto PSP SUB18 - Game event MSG inventory / subtitle alignment readiness
#
# Read-only.
# Scans original Stage3 KR TBL scripts, inventories every MSG-like command,
# speaker code, voice id, raw payload and CP932-decoded Japanese text.
# Compares structural counts with the final SUB09 1900-entry Korean subtitle corpus.
#
# Does NOT patch TBL/DAT/BOOT/ISO.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_SUB09_ROWS = 1900
EXPECTED_SUB09_DIALOGUE = 1762
EXPECTED_SUB09_NARRATION = 138

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path: Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def decode_cp932(data: bytes):
    try:
        return data.decode("cp932","strict"),"STRICT"
    except UnicodeDecodeError:
        return data.decode("cp932","replace"),"REPLACE"

def parse_message_line(body: bytes):
    """
    Recognize script commands whose command token contains MSG.
    Known format:
      MSG =SIK,s_a01_000,<payload>
    But this keeps unknown MSG-like commands visible rather than discarding them.
    """
    if b"=" not in body:
        return None
    left,right=body.split(b"=",1)
    command=left.strip().decode("ascii",errors="replace")
    if "MSG" not in command.upper():
        return None

    # Preserve comma structure exactly; only classic MSG gets speaker/voice/payload.
    parts=right.split(b",",2)
    speaker=""
    voice_id=""
    payload=b""
    parse_kind="GENERIC_MSG_LIKE"

    if len(parts)==3:
        speaker=parts[0].strip().decode("ascii",errors="replace")
        voice_id=parts[1].strip().decode("ascii",errors="replace")
        payload=parts[2]
        parse_kind="THREE_FIELD"
    elif len(parts)==2:
        speaker=parts[0].strip().decode("ascii",errors="replace")
        payload=parts[1]
        parse_kind="TWO_FIELD"
    elif len(parts)==1:
        payload=parts[0]
        parse_kind="ONE_FIELD"

    text,status=decode_cp932(payload)
    return {
        "command":command,
        "speaker_code":speaker,
        "voice_id":voice_id,
        "payload_bytes":payload,
        "jp_text":text,
        "decode_status":status,
        "parse_kind":parse_kind,
    }

def text_byte_stats(data: bytes):
    return {
        "bytes":len(data),
        "high_bytes":sum(1 for b in data if b>=0x80),
        "nul_bytes":data.count(0),
    }

def scan_scripts(tbl_root: Path):
    msg_rows=[]
    file_rows=[]
    command_counts=Counter()
    speaker_counts=Counter()
    voice_prefix_counts=Counter()
    global_seq=0

    files=sorted(tbl_root.glob("*.tbl"))
    for file_index,p in enumerate(files):
        raw=p.read_bytes()
        lines=raw.splitlines()
        file_msg_count=0
        msg_like_commands=Counter()
        speaker_local=Counter()
        first_voice=""
        last_voice=""

        for line_no,line in enumerate(lines,1):
            body=line.rstrip(b"\r\n")
            parsed=parse_message_line(body)
            if not parsed:
                continue

            global_seq+=1
            file_msg_count+=1
            command_counts[parsed["command"]]+=1
            msg_like_commands[parsed["command"]]+=1
            if parsed["speaker_code"]:
                speaker_counts[parsed["speaker_code"]]+=1
                speaker_local[parsed["speaker_code"]]+=1

            voice=parsed["voice_id"]
            if voice:
                if not first_voice:
                    first_voice=voice
                last_voice=voice
                m=re.match(r"([A-Za-z]+_[A-Za-z0-9]+)",voice)
                prefix=m.group(1) if m else voice.split("_")[0]
                voice_prefix_counts[prefix]+=1

            st=text_byte_stats(parsed["payload_bytes"])
            msg_rows.append({
                "global_msg_sequence":global_seq,
                "tbl_file_index":file_index,
                "tbl_file":p.name,
                "tbl_path":str(p),
                "line_no":line_no,
                "command":parsed["command"],
                "parse_kind":parsed["parse_kind"],
                "speaker_code":parsed["speaker_code"],
                "voice_id":parsed["voice_id"],
                "jp_text":parsed["jp_text"],
                "decode_status":parsed["decode_status"],
                "payload_hex":parsed["payload_bytes"].hex(" "),
                "payload_bytes":st["bytes"],
                "payload_high_bytes":st["high_bytes"],
            })

        file_rows.append({
            "tbl_file_index":file_index,
            "tbl_file":p.name,
            "bytes":len(raw),
            "sha256":sha256_file(p),
            "line_count":len(lines),
            "msg_like_count":file_msg_count,
            "msg_commands":" | ".join(
                f"{k}:{v}" for k,v in sorted(msg_like_commands.items())
            ),
            "unique_speaker_codes":len(speaker_local),
            "speaker_codes":" ".join(
                f"{k}:{v}" for k,v in speaker_local.most_common()
            ),
            "first_voice_id":first_voice,
            "last_voice_id":last_voice,
        })

    return (
        files,msg_rows,file_rows,command_counts,speaker_counts,voice_prefix_counts
    )

def subtitle_summary(rows):
    types=Counter(r["entry_type"] for r in rows)
    speakers=Counter(r["speaker"] for r in rows if r["speaker"])
    parts=Counter(r["video_part"] for r in rows)
    return types,speakers,parts

def make_sequence_preview(msg_rows,sub_rows,n=100):
    out=[]
    limit=min(len(msg_rows),len(sub_rows),n)
    for i in range(limit):
        m=msg_rows[i]
        s=sub_rows[i]
        out.append({
            "pair_index":i+1,
            "game_tbl":m["tbl_file"],
            "game_line":m["line_no"],
            "game_command":m["command"],
            "game_speaker_code":m["speaker_code"],
            "game_voice_id":m["voice_id"],
            "game_jp_text":m["jp_text"],
            "subtitle_sequence":s["sequence"],
            "subtitle_entry_type":s["entry_type"],
            "subtitle_speaker":s["speaker"],
            "subtitle_ko_text":s["text"],
            "note":"ORDER_ONLY_NOT_ALIGNMENT",
        })
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    tbl_root=root/"analysis"/"stage3"/"extracted"/"kr"
    sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    if not tbl_root.exists():
        raise RuntimeError(f"Stage3 KR TBL directory missing: {tbl_root}")
    if not sub09.exists():
        raise RuntimeError(f"SUB09 final sequence missing: {sub09}")

    sub_rows=read_tsv(sub09)
    if len(sub_rows)!=EXPECTED_SUB09_ROWS:
        raise RuntimeError(f"SUB09 rows={len(sub_rows)} expected={EXPECTED_SUB09_ROWS}")

    types,sub_speakers,parts=subtitle_summary(sub_rows)
    if types["DIALOGUE"]!=EXPECTED_SUB09_DIALOGUE:
        raise RuntimeError(
            f"SUB09 DIALOGUE={types['DIALOGUE']} expected={EXPECTED_SUB09_DIALOGUE}"
        )
    if types["NARRATION"]!=EXPECTED_SUB09_NARRATION:
        raise RuntimeError(
            f"SUB09 NARRATION={types['NARRATION']} expected={EXPECTED_SUB09_NARRATION}"
        )

    (
        files,msg_rows,file_rows,command_counts,
        speaker_counts,voice_prefix_counts
    )=scan_scripts(tbl_root)

    if not files:
        raise RuntimeError("No Stage3 KR TBL files found")
    if not msg_rows:
        raise RuntimeError("No MSG-like rows found in Stage3 KR TBLs")

    write_tsv(
        out/"sub18_game_msg_inventory.tsv",
        msg_rows,
        [
            "global_msg_sequence","tbl_file_index","tbl_file","tbl_path","line_no",
            "command","parse_kind","speaker_code","voice_id","jp_text",
            "decode_status","payload_hex","payload_bytes","payload_high_bytes"
        ]
    )
    write_tsv(
        out/"sub18_event_file_summary.tsv",
        file_rows,
        [
            "tbl_file_index","tbl_file","bytes","sha256","line_count",
            "msg_like_count","msg_commands","unique_speaker_codes",
            "speaker_codes","first_voice_id","last_voice_id"
        ]
    )

    write_tsv(
        out/"sub18_game_speaker_code_frequency.tsv",
        [
            {"speaker_code":k,"count":v}
            for k,v in speaker_counts.most_common()
        ],
        ["speaker_code","count"]
    )
    write_tsv(
        out/"sub18_subtitle_speaker_frequency.tsv",
        [
            {"speaker":k,"count":v}
            for k,v in sub_speakers.most_common()
        ],
        ["speaker","count"]
    )
    write_tsv(
        out/"sub18_msg_command_frequency.tsv",
        [
            {"command":k,"count":v}
            for k,v in command_counts.most_common()
        ],
        ["command","count"]
    )
    write_tsv(
        out/"sub18_voice_prefix_frequency.tsv",
        [
            {"voice_prefix":k,"count":v}
            for k,v in voice_prefix_counts.most_common()
        ],
        ["voice_prefix","count"]
    )

    # Structural count comparison only. Do NOT claim sequence alignment yet.
    comparison=[
        {"metric":"SUB09_TOTAL","count":len(sub_rows)},
        {"metric":"SUB09_DIALOGUE","count":types["DIALOGUE"]},
        {"metric":"SUB09_NARRATION","count":types["NARRATION"]},
        {"metric":"GAME_TBL_FILES","count":len(files)},
        {"metric":"GAME_MSG_LIKE_TOTAL","count":len(msg_rows)},
        {"metric":"GAME_UNIQUE_SPEAKER_CODES","count":len(speaker_counts)},
        {"metric":"GAME_UNIQUE_MSG_COMMANDS","count":len(command_counts)},
    ]
    write_tsv(out/"sub18_structural_counts.tsv",comparison,["metric","count"])

    preview=make_sequence_preview(msg_rows,sub_rows,100)
    write_tsv(
        out/"sub18_first100_order_preview.tsv",
        preview,
        [
            "pair_index","game_tbl","game_line","game_command",
            "game_speaker_code","game_voice_id","game_jp_text",
            "subtitle_sequence","subtitle_entry_type","subtitle_speaker",
            "subtitle_ko_text","note"
        ]
    )

    # Candidate exact-count clues at file granularity.
    exact_count_candidates=[]
    for fr in file_rows:
        c=int(fr["msg_like_count"])
        if c==0:
            continue
        exact_count_candidates.append({
            "tbl_file":fr["tbl_file"],
            "game_msg_count":c,
            "share_of_game_msgs":f"{c/max(1,len(msg_rows)):.6f}",
        })
    write_tsv(
        out/"sub18_event_msg_counts.tsv",
        exact_count_candidates,
        ["tbl_file","game_msg_count","share_of_game_msgs"]
    )

    count_delta=len(msg_rows)-len(sub_rows)
    direct_order_candidate=(len(msg_rows)==len(sub_rows))

    report={
        "stage":"SUB18",
        "mode":"READ_ONLY_INVENTORY",
        "tbl_root":str(tbl_root),
        "tbl_files":len(files),
        "game_msg_like_rows":len(msg_rows),
        "game_msg_commands":dict(command_counts),
        "game_unique_speaker_codes":len(speaker_counts),
        "sub09_rows":len(sub_rows),
        "sub09_dialogue":types["DIALOGUE"],
        "sub09_narration":types["NARRATION"],
        "count_delta_game_minus_subtitle":count_delta,
        "direct_global_order_alignment_candidate":direct_order_candidate,
        "subtitle_video_parts":dict(parts),
        "note":"No mapping or patch was produced; order preview is diagnostic only.",
    }
    (out/"sub18_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB18 - Game Event MSG Inventory / Alignment Readiness",
        "",
        f"Stage3KRTableFiles={len(files)}",
        f"GameMSGLikeRows={len(msg_rows)}",
        f"GameUniqueSpeakerCodes={len(speaker_counts)}",
        f"GameMSGCommands={len(command_counts)}",
        f"SUB09Rows={len(sub_rows)}",
        f"SUB09Dialogue={types['DIALOGUE']}",
        f"SUB09Narration={types['NARRATION']}",
        f"CountDeltaGameMinusSubtitle={count_delta}",
        f"DirectGlobalOrderAlignmentCandidate={'YES' if direct_order_candidate else 'NO'}",
        "",
        "IMPORTANT:",
        "sub18_first100_order_preview.tsv is order-only diagnostic data.",
        "It must not be treated as a confirmed translation alignment.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",
        encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
