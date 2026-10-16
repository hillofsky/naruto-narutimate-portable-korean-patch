#!/usr/bin/env python3
# Naruto PSP MOV03C FIX2 - LZFU_RAW-decompressed event TBL movie opcode analysis
#
# Input:
#   Extracted event*.tbl files produced by QuickBMS/macross_pidx.bms
#   KR BOOT.BIN for command/path reference context
#
# Goal:
#   Find which eventXXX.tbl invokes dm001..dm010 without gameplay.
#
# Outputs:
#   event_inventory.tsv
#   direct_string_hits.tsv
#   movie_layout_scores.tsv
#   movie_command_candidates.tsv
#   event_movie_best.tsv
#   printable_audio_tokens.tsv
#   per_event/*.txt
#   SUMMARY.txt

from __future__ import annotations
import csv, hashlib, math, re, struct, sys, traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
STAGE = ROOT / "analysis" / "mov" / "mov03c_event_table_analysis"
EXTRACT = STAGE / "pidx_extract"
DECOMP = STAGE / "decompressed_event"
PER = STAGE / "per_event"
BOOT = ROOT / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"

# BOOT.BIN PMF path order observed in MOV03B.
PMF_TABLE = [
    "logo_b","logo_c","logo_a",
    "dk101","dk102","dk103","dk201","dk202","dk203",
    "da101","da102","da103","da201",
    "dm001","dm002","dm003","dm004","dm005","dm006","dm007","dm008","dm009","dm010",
]
DM_BY_TABLE = {i:name for i,name in enumerate(PMF_TABLE) if name.startswith("dm")}
DM_BY_ZERO = {i:f"dm{i+1:03d}" for i in range(10)}
DM_BY_ONE = {i:f"dm{i:03d}" for i in range(1,11)}

# Command-string order suggests MOVIE is either 22 (NULL == opcode 0)
# or 23 (EVENT == opcode 0), so scan a narrow neighborhood around both.
OPCODE_CANDIDATES = list(range(18, 27))

ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
AUDIO_RE = re.compile(
    r"(?i)(?:"
    r"[a-z0-9_./\\-]{1,100}\.(?:at3|oma|wav|adx|vag)"
    r"|s_[a-z]\d{1,3}[_-]\d{1,4}[a-z]?"
    r"|(?:bgm|voice|sound|se_)[a-z0-9_./\\-]{1,100}"
    r")"
)

def write_tsv(path: Path, rows: list[dict], fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    if fields is None:
        fields=list(rows[0].keys())
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def entropy(data: bytes) -> float:
    if not data: return 0.0
    c=Counter(data)
    n=len(data)
    return -sum((v/n)*math.log2(v/n) for v in c.values())

def hexdump(data: bytes, base=0, width=16):
    out=[]
    for i in range(0,len(data),width):
        chunk=data[i:i+width]
        hx=" ".join(f"{b:02X}" for b in chunk)
        asc="".join(chr(b) if 32<=b<127 else "." for b in chunk)
        out.append(f"{base+i:08X}  {hx:<47}  {asc}")
    return "\n".join(out)

def printable_strings(data: bytes):
    return [(m.start(),m.group().decode("ascii","replace")) for m in ASCII_RE.finditer(data)]

def discover_events():
    # FIX2: do not scan the compressed PIDX payloads.
    candidates=[]
    if DECOMP.exists():
        candidates += list(DECOMP.rglob("event*.tbl"))
    seen=set(); out=[]
    for p in sorted(candidates):
        try: k=str(p.resolve()).lower()
        except: k=str(p).lower()
        if k in seen: continue
        seen.add(k); out.append(p)
    return out


def direct_string_scan(name, data):
    rows=[]
    low=data.lower()
    for movie in [f"dm{i:03d}" for i in range(1,11)]:
        for needle in [movie.encode(),(movie+".pmf").encode()]:
            pos=0
            while True:
                idx=low.find(needle,pos)
                if idx<0: break
                rows.append({
                    "event_file":name,
                    "offset_hex":f"0x{idx:08X}",
                    "movie":movie,
                    "matched":needle.decode(),
                })
                pos=idx+1
    return rows

def audio_string_scan(name,data):
    rows=[]
    for off,s in printable_strings(data):
        for m in AUDIO_RE.finditer(s):
            rows.append({
                "event_file":name,
                "offset_hex":f"0x{off+m.start():08X}",
                "audio_token":m.group(0),
                "container_string":s[:300],
            })
    return rows

# layout: label, opcode width/offset, param width/offset, step alignment requirement
LAYOUTS = [
    ("u8_op_u8_arg",   1,0,1,1,1),
    ("u8_op_u16_arg1", 1,0,2,1,1),
    ("u8_op_u32_arg1", 1,0,4,1,1),
    ("u16_op_u16_arg", 2,0,2,2,2),
    ("u16_op_u32_arg2",2,0,4,2,2),
    ("u32_op_u32_arg", 4,0,4,4,4),
    ("u32_op_arg_plus8",4,0,4,8,4),
    ("u32_op_arg_plus12",4,0,4,12,4),
    ("u32_op_arg_plus16",4,0,4,16,4),
]

DOMAINS = [
    ("pmf_table_index", DM_BY_TABLE),
    ("dm_zero_based", DM_BY_ZERO),
    ("dm_one_based", DM_BY_ONE),
]

def read_uint(data,off,width):
    if off<0 or off+width>len(data): return None
    if width==1: return data[off]
    if width==2: return struct.unpack_from("<H",data,off)[0]
    if width==4: return struct.unpack_from("<I",data,off)[0]
    raise ValueError(width)

def scan_layout(event_name,data,layout,opcode,domain_name,domain):
    label,opw,opoff,argw,argoff,align=layout
    rows=[]
    # Keep scan bounded to plausible aligned command starts.
    maxneed=max(opoff+opw,argoff+argw)
    for pos in range(0,max(0,len(data)-maxneed+1),align):
        op=read_uint(data,pos+opoff,opw)
        if op!=opcode: continue
        arg=read_uint(data,pos+argoff,argw)
        if arg not in domain: continue
        movie=domain[arg]
        # Capture 32 bytes around candidate.
        lo=max(0,pos-16); hi=min(len(data),pos+32)
        rows.append({
            "event_file":event_name,
            "offset_hex":f"0x{pos:08X}",
            "offset_dec":pos,
            "layout":label,
            "opcode":opcode,
            "arg_value":arg,
            "arg_domain":domain_name,
            "movie":movie,
            "context_hex":data[lo:hi].hex(" "),
        })
    return rows

def score_layout(all_candidates, layout, opcode, domain):
    rows=[r for r in all_candidates
          if r["layout"]==layout and r["opcode"]==opcode and r["arg_domain"]==domain]
    if not rows:
        return {
            "layout":layout,"opcode":opcode,"arg_domain":domain,
            "total_hits":0,"distinct_dm":0,"event_files":0,
            "singleton_movies":0,"max_hits_one_movie":0,"score":0.0
        }
    bymovie=Counter(r["movie"] for r in rows)
    byevent=Counter(r["event_file"] for r in rows)
    distinct=len(bymovie)
    singletons=sum(1 for v in bymovie.values() if v<=3)
    maxone=max(bymovie.values())
    # Reward coverage of different DM movies, moderate number of hits,
    # and candidates not exploding across every event file.
    score=distinct*12 + singletons*3 - max(0,len(rows)-distinct*4)*0.5 - max(0,len(byevent)-distinct*3)*0.25
    # Small prior for the expected MOVIE opcode neighborhood 22/23.
    if opcode in (22,23): score+=4
    return {
        "layout":layout,"opcode":opcode,"arg_domain":domain,
        "total_hits":len(rows),"distinct_dm":distinct,"event_files":len(byevent),
        "singleton_movies":singletons,"max_hits_one_movie":maxone,
        "score":round(score,3)
    }

def boot_context():
    if not BOOT.exists(): return []
    data=BOOT.read_bytes()
    rows=[]
    # PMF path table.
    for i,name in enumerate(PMF_TABLE):
        needle=(f"disc0:/PSP_GAME/USRDIR/movie/{name}.pmf").encode("ascii")
        idx=data.find(needle)
        rows.append({
            "kind":"pmf_path",
            "index":i,
            "name":name,
            "offset_hex":f"0x{idx:08X}" if idx>=0 else "",
        })
    # Event command labels.
    commands=[
        "NULL","MSG_FORCED","MSG_SYS","WAIT_NOMSG","WAIT","IMG_BG","IMG_CHAR","IMG_ITEM",
        "FLASH_WHITE","FLASH_BLACK","FLASH_YELLOW","FLASH_RED","FLASH_BLUE","FLASH_REV",
        "FADEIN_WHITE","FADEOUT_WHITE","FADEIN_BLACK","FADEOUT_BLACK","SCR_EFF","CAM_QUAKE",
        "CAM_BLUR","BATTLE","MOVIE","TEAM_IN","TEAM_OUT","ITEM","HEAL","MAIN_CHAR","EVENT_FLAG",
        "CLEAR","SCROLL_INIT","FLOOR_LIMIT"
    ]
    for i,name in enumerate(commands):
        idx=data.find(name.encode("ascii")+b"\x00")
        rows.append({
            "kind":"command_null_based",
            "index":i,
            "name":name,
            "offset_hex":f"0x{idx:08X}" if idx>=0 else "",
        })
    return rows

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    PER.mkdir(parents=True,exist_ok=True)

    events=discover_events()
    print("="*76,flush=True)
    print(" Naruto PSP MOV03C FIX2 - Decompressed Event TBL movie opcode analysis",flush=True)
    print("="*76,flush=True)
    print(f"Event TBL files: {len(events)}",flush=True)

    if not events:
        raise RuntimeError(
            "No decompressed event*.tbl files found. LZFU_RAW decompression likely failed."
        )

    inventory=[]
    direct=[]
    audio=[]
    all_candidates=[]

    for i,p in enumerate(events,1):
        data=p.read_bytes()
        name=p.name.lower()
        strings=printable_strings(data)
        printable_bytes=sum(len(s) for _,s in strings)
        inventory.append({
            "event_file":name,
            "path":str(p),
            "size":len(data),
            "sha256":hashlib.sha256(data).hexdigest(),
            "entropy":round(entropy(data),4),
            "printable_strings":len(strings),
            "printable_string_bytes":printable_bytes,
            "first16":data[:16].hex(" "),
        })

        direct.extend(direct_string_scan(name,data))
        audio.extend(audio_string_scan(name,data))

        for layout in LAYOUTS:
            for opcode in OPCODE_CANDIDATES:
                for domain_name,domain in DOMAINS:
                    all_candidates.extend(
                        scan_layout(name,data,layout,opcode,domain_name,domain)
                    )

        # Compact event context dump.
        dump=[
            f"FILE={name}",
            f"PATH={p}",
            f"SIZE={len(data)}",
            f"SHA256={hashlib.sha256(data).hexdigest()}",
            f"ENTROPY={entropy(data):.4f}",
            "",
            "===== HEAD 512 =====",
            hexdump(data[:512]),
            "",
            "===== TAIL 256 =====",
            hexdump(data[-256:], max(0,len(data)-256)),
            "",
            "===== PRINTABLE STRINGS =====",
        ]
        for off,s in strings[:500]:
            dump.append(f"0x{off:08X}  {s}")
        (PER/f"{p.stem}.txt").write_text("\n".join(dump)+"\n",encoding="utf-8-sig")

        if i%25==0 or i==len(events):
            print(f"[analyze] {i}/{len(events)} candidates={len(all_candidates)}",flush=True)

    scores=[]
    for layout in [x[0] for x in LAYOUTS]:
        for opcode in OPCODE_CANDIDATES:
            for domain_name,_ in DOMAINS:
                scores.append(score_layout(all_candidates,layout,opcode,domain_name))
    scores.sort(key=lambda r:(-float(r["score"]),-int(r["distinct_dm"]),int(r["total_hits"])))

    # Rank each candidate based on global layout score.
    score_map={(r["layout"],r["opcode"],r["arg_domain"]):float(r["score"]) for r in scores}
    for r in all_candidates:
        r["layout_score"]=score_map[(r["layout"],r["opcode"],r["arg_domain"])]
    all_candidates.sort(key=lambda r:(-r["layout_score"],r["movie"],r["event_file"],r["offset_dec"]))

    # Best candidate(s) per DM from the highest-scoring structural model.
    best=[]
    if scores:
        top=scores[0]
        subset=[r for r in all_candidates
                if r["layout"]==top["layout"]
                and r["opcode"]==top["opcode"]
                and r["arg_domain"]==top["arg_domain"]]
        for movie in [f"dm{i:03d}" for i in range(1,11)]:
            rr=[r for r in subset if r["movie"]==movie]
            for rank,r in enumerate(rr[:20],1):
                best.append({
                    "movie":movie,
                    "rank":rank,
                    "event_file":r["event_file"],
                    "offset_hex":r["offset_hex"],
                    "layout":r["layout"],
                    "opcode":r["opcode"],
                    "arg_domain":r["arg_domain"],
                    "arg_value":r["arg_value"],
                    "layout_score":r["layout_score"],
                    "context_hex":r["context_hex"],
                })

    write_tsv(STAGE/"event_inventory.tsv",inventory)
    write_tsv(STAGE/"direct_string_hits.tsv",direct)
    write_tsv(STAGE/"printable_audio_tokens.tsv",audio)
    write_tsv(STAGE/"movie_layout_scores.tsv",scores)
    write_tsv(STAGE/"movie_command_candidates.tsv",all_candidates)
    write_tsv(STAGE/"event_movie_best.tsv",best)
    write_tsv(STAGE/"boot_reference_table.tsv",boot_context())

    top=scores[0] if scores else None
    best_movies=sorted({r["movie"] for r in best})
    direct_movies=sorted({r["movie"] for r in direct})
    audio_events=sorted({r["event_file"] for r in audio})

    summary=[
        "Naruto PSP MOV03C FIX2 - Decompressed Event TBL movie opcode analysis",
        "="*76,"",
        f"Event TBL files analyzed={len(events)}",
        f"Direct dm*.pmf/name string hits={len(direct)} across {len(direct_movies)} movies",
        f"Event files containing printable audio-like tokens={len(audio_events)}",
        "",
        "BOOT-derived hypotheses:",
        "- MOVIE command ordinal candidates: 22 (NULL=0) or 23 (EVENT=0).",
        "- PMF path table: dm001..dm010 are indices 13..22.",
        "- Scanner also tests zero-based 0..9 and one-based 1..10 DM arguments.",
        "",
    ]
    if top:
        summary += [
            "Top structural layout candidate:",
            f"  layout={top['layout']}",
            f"  opcode={top['opcode']}",
            f"  arg_domain={top['arg_domain']}",
            f"  total_hits={top['total_hits']}",
            f"  distinct_dm={top['distinct_dm']}/10",
            f"  event_files={top['event_files']}",
            f"  score={top['score']}",
            f"  DM movies represented in best table={len(best_movies)}/10: {', '.join(best_movies) if best_movies else '(none)'}",
            "",
        ]
    summary += [
        "Interpretation:",
        "- A strong result is one layout/opcode/domain covering most or all 10 DM IDs",
        "  with only a small number of event hits per movie.",
        "- A weak result means TBL records need format reversal before mapping audio.",
        "- printable_audio_tokens.tsv is only direct evidence if actual AT3/voice names",
        "  are embedded in the event file; otherwise numeric voice IDs need a later pass.",
    ]

    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
