#!/usr/bin/env python3
# Naruto PSP MOV03G - decode grounded DM dispatcher tables
#
# Grounded MOV03F code:
#   state = *(s1+0x24)
#   selector = selector_table[state]          (u16)
#   movie_index = movie_map[selector]         (u32)
#   movie_path = pmf_pointer_table[movie_index]
#   movie_init(..., movie_path, 4)
#
# Group 13:
#   selector table ELFVA 0x004BD698 (8 x u16 inferred from next-table boundary)
#   movie map      ELFVA 0x00459C38 (8 x u32 inferred from next-table boundary)
#
# Group 14:
#   selector table ELFVA 0x004BD6A8
#   movie map      ELFVA 0x00459C58
#
# Primary PMF pointer table ELFVA 0x00459250.
#
# This stage unfolds all 16 mappings and inventories possible group-number
# audio assets, without assuming that matching numbers prove synchronization.

from __future__ import annotations
import csv, re, struct, subprocess, sys, traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
BOOT = ROOT / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
KR = ROOT / "kr_extracted"
STAGE = ROOT / "analysis" / "mov" / "mov03g_dispatch_tables"
STAGE.mkdir(parents=True,exist_ok=True)

PSP_BASE=0x08804000

PRIMARY=0x00459250
PRIMARY_COUNT=24

GROUPS=[
    {"group":13,"selector_base":0x004BD698,"map_base":0x00459C38,"count":8,
     "code_runtime":"0x08AB38C4","resource_check":"0x00060460","resource_load":"0x00060058"},
    {"group":14,"selector_base":0x004BD6A8,"map_base":0x00459C58,"count":8,
     "code_runtime":"0x08AB3D28","resource_check":"0x00060460","resource_load":"0x00060058"},
]

TARGET_FUNCS={
    0x0029F4B0:"movie_init",
    0x00060058:"group_resource_load",
    0x00060460:"group_resource_check",
    0x0029F654:"movie_status_or_stop_A",
    0x0029F5AC:"movie_status_or_stop_B",
}

REG=[
 "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
 "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
 "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
 "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sx16(x):return x-0x10000 if x&0x8000 else x

def write_tsv(path,rows,fields=None):
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields:fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def parse_elf(data):
    if not data.startswith(b"\x7fELF"):raise RuntimeError("BOOT is not ELF")
    endian="<" if data[5]==1 else ">"
    vals=struct.unpack_from(endian+"HHIIIIIHHHHHH",data,16)
    e_phoff=vals[4];e_phentsize=vals[8];e_phnum=vals[9]
    ph=[]
    for i in range(e_phnum):
        o=e_phoff+i*e_phentsize
        x=struct.unpack_from(endian+"IIIIIIII",data,o)
        ph.append(dict(type=x[0],offset=x[1],vaddr=x[2],paddr=x[3],filesz=x[4],memsz=x[5],flags=x[6],align=x[7]))
    return dict(endian=endian,entry=vals[3],ph=ph)

def va2off(va,elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["vaddr"]<=va<p["vaddr"]+p["filesz"]:
            return p["offset"]+(va-p["vaddr"])
    return None

def off2va(off,elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["offset"]<=off<p["offset"]+p["filesz"]:
            return p["vaddr"]+(off-p["offset"])
    return None

def rt(va):return PSP_BASE+va if va is not None else None

def u16(data,va,elf):
    o=va2off(va,elf)
    if o is None or o+2>len(data):raise RuntimeError(f"bad u16 VA 0x{va:X}")
    return struct.unpack_from("<H",data,o)[0]

def u32(data,va,elf):
    o=va2off(va,elf)
    if o is None or o+4>len(data):raise RuntimeError(f"bad u32 VA 0x{va:X}")
    return struct.unpack_from("<I",data,o)[0]

def cstr(data,va,elf,maxlen=256):
    o=va2off(va,elf)
    if o is None:return ""
    e=data.find(b"\0",o,min(len(data),o+maxlen))
    if e<0:e=min(len(data),o+maxlen)
    return data[o:e].decode("ascii","replace")

def mips(word,pc=None):
    op=(word>>26)&63;rs=(word>>21)&31;rt0=(word>>16)&31;rd=(word>>11)&31;sa=(word>>6)&31;fn=word&63;imm=word&0xffff
    if word==0:return "nop"
    if op==0:
        d={0x00:f"sll {REG[rd]},{REG[rt0]},{sa}",0x02:f"srl {REG[rd]},{REG[rt0]},{sa}",0x08:f"jr {REG[rs]}",
           0x09:f"jalr {REG[rd]},{REG[rs]}",0x21:f"addu {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x23:f"subu {REG[rd]},{REG[rs]},{REG[rt0]}",0x24:f"and {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x25:f"or {REG[rd]},{REG[rs]},{REG[rt0]}"}
        return d.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        t=((pc+4)&0xF0000000)|((word&0x03ffffff)<<2) if pc is not None else ((word&0x03ffffff)<<2)
        return ("j" if op==2 else "jal")+f" 0x{t:08X}"
    if op==4:return f"beq {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==5:return f"bne {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==9:return f"addiu {REG[rt0]},{REG[rs]},{sx16(imm)}"
    if op==0x0d:return f"ori {REG[rt0]},{REG[rs]},0x{imm:04X}"
    if op==0x0f:return f"lui {REG[rt0]},0x{imm:04X}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem:return f"{mem[op]} {REG[rt0]},{sx16(imm)}({REG[rs]})"
    return f"op=0x{op:X} word=0x{word:08X}"

def dump_code(data,elf,center_va,radius=0x120):
    center=va2off(center_va,elf)
    if center is None:return "UNMAPPED\n"
    lo=max(0,(center-radius)&~3);hi=min(len(data),(center+radius)&~3)
    out=[]
    for o in range(lo,hi,4):
        w=struct.unpack_from("<I",data,o)[0]
        va=off2va(o,elf)
        mark=">>" if va==center_va else "  "
        out.append(f"{mark} file=0x{o:08X} elfva=0x{va:08X} runtime=0x{rt(va):08X} {w:08X}  {mips(w,va)}")
    return "\n".join(out)

def all_jal_callers(data,elf,target_va):
    rows=[]
    for o in range(0,len(data)-4,4):
        va=off2va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        if (w>>26)!=3:continue
        tgt=((va+4)&0xF0000000)|((w&0x03ffffff)<<2)
        if tgt==target_va:
            rows.append((o,va))
    return rows

def probe_duration(path:Path):
    probes=[
        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH"),
    ]
    exe=next((p for p in probes if p.exists()),None)
    if exe is None:return ""
    try:
        cp=subprocess.run([str(exe),"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(path)],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",timeout=15)
        s=cp.stdout.strip()
        return f"{float(s):.6f}" if s else ""
    except Exception:
        return ""

def main():
    if not BOOT.exists():raise RuntimeError(f"Missing {BOOT}")
    data=BOOT.read_bytes();elf=parse_elf(data)

    print("="*78,flush=True)
    print(" Naruto PSP MOV03G - grounded DM dispatcher table decode",flush=True)
    print("="*78,flush=True)

    # Primary PMF table
    primary=[]
    for i in range(PRIMARY_COUNT):
        pva=u32(data,PRIMARY+i*4,elf)
        path=cstr(data,pva,elf,128)
        m=re.search(r"/movie/([^/]+)\.pmf$",path,re.I)
        name=m.group(1).lower() if m else ""
        primary.append(dict(index=i,pointer_elfva=f"0x{pva:08X}",pointer_runtime=f"0x{rt(pva):08X}",
                            movie=name,path=path))
    write_tsv(STAGE/"primary_pmf_table.tsv",primary)

    # Grounded 2-stage dispatch tables.
    selector_rows=[];map_rows=[];dispatch=[]
    for g in GROUPS:
        for state in range(g["count"]):
            sel=u16(data,g["selector_base"]+state*2,elf)
            selector_rows.append(dict(group=g["group"],state_index=state,selector=sel,
                                      selector_entry_elfva=f"0x{g['selector_base']+state*2:08X}"))
        for j in range(g["count"]):
            mi=u32(data,g["map_base"]+j*4,elf)
            name=primary[mi]["movie"] if mi<len(primary) else ""
            path=primary[mi]["path"] if mi<len(primary) else ""
            map_rows.append(dict(group=g["group"],selector=j,movie_index=mi,movie=name,path=path,
                                 map_entry_elfva=f"0x{g['map_base']+j*4:08X}"))

        for state in range(g["count"]):
            sel=u16(data,g["selector_base"]+state*2,elf)
            if sel>=g["count"]:
                dispatch.append(dict(group=g["group"],state_index=state,selector=sel,status="SELECTOR_OUT_OF_RANGE",
                                     movie_index="",movie="",path="",code_runtime=g["code_runtime"]))
                continue
            mi=u32(data,g["map_base"]+sel*4,elf)
            name=primary[mi]["movie"] if mi<len(primary) else ""
            path=primary[mi]["path"] if mi<len(primary) else ""
            dispatch.append(dict(group=g["group"],state_index=state,selector=sel,
                                 status="OK" if mi<len(primary) else "MOVIE_INDEX_OUT_OF_RANGE",
                                 movie_index=mi,movie=name,path=path,code_runtime=g["code_runtime"]))
    write_tsv(STAGE/"selector_tables.tsv",selector_rows)
    write_tsv(STAGE/"movie_index_maps.tsv",map_rows)
    write_tsv(STAGE/"resolved_dispatch.tsv",dispatch)

    # Raw neighborhoods around all four grounded tables.
    table_dump=[]
    for g in GROUPS:
        for label,base,size in [
            ("selector",g["selector_base"],0x20),
            ("movie_map",g["map_base"],0x40),
        ]:
            off=va2off(base,elf)
            blob=data[off:off+size]
            table_dump.append(
                f"GROUP {g['group']} {label} base=0x{base:08X} runtime=0x{rt(base):08X}\n"
                + "\n".join(
                    f"0x{base+i:08X}: "+blob[i:i+16].hex(" ")
                    for i in range(0,len(blob),16)
                )
            )
    (STAGE/"table_hex_context.txt").write_text("\n\n".join(table_dump),encoding="utf-8-sig")

    # Function callers and contexts.
    caller_rows=[];ctx=[]
    for target,name in TARGET_FUNCS.items():
        callers=all_jal_callers(data,elf,target)
        for o,va in callers:
            caller_rows.append(dict(function=name,target_elfva=f"0x{target:08X}",target_runtime=f"0x{rt(target):08X}",
                                    caller_file=f"0x{o:08X}",caller_elfva=f"0x{va:08X}",caller_runtime=f"0x{rt(va):08X}"))
        ctx.append("="*100+"\n"+f"FUNCTION {name} ELFVA=0x{target:08X} runtime=0x{rt(target):08X}\n"+dump_code(data,elf,target,0x180))
    write_tsv(STAGE/"target_function_callers.tsv",caller_rows)
    (STAGE/"target_function_context.txt").write_text("\n\n".join(ctx),encoding="utf-8-sig")

    # Explicit dispatcher contexts from MOV03F.
    disp_ctx=[]
    for va,name in [(0x002AF8C4,"group13_primary_table_xref"),
                    (0x002AFD28,"group14_primary_table_xref")]:
        disp_ctx.append("="*100+"\n"+name+"\n"+dump_code(data,elf,va,0x180))
    (STAGE/"dispatcher_code_context.txt").write_text("\n\n".join(disp_ctx),encoding="utf-8-sig")

    # Inventory candidate audio assets whose names carry group numbers.
    voice_dir=KR/"PSP_GAME"/"USRDIR"/"sound"/"voice"
    bgm_dir=KR/"PSP_GAME"/"USRDIR"/"sound"/"bgm"
    audio=[]
    patterns=[
        (13,re.compile(r"(?i)^s_[ab]13[_-].*\.at3$")),
        (14,re.compile(r"(?i)^s_[ab]14[_-].*\.at3$")),
    ]
    if voice_dir.exists():
        for p in sorted(voice_dir.rglob("*.at3")):
            for grp,pat in patterns:
                if pat.match(p.name):
                    audio.append(dict(group=grp,kind="voice_name_match",file=p.name,
                                      relative=str(p.relative_to(KR)),bytes=p.stat().st_size,duration_sec=probe_duration(p)))
    if bgm_dir.exists():
        for p in sorted(bgm_dir.glob("*.at3")):
            low=p.stem.lower()
            grp=""
            why=""
            if low in ("d13","ev13"):
                grp=13;why="numeric_name_match"
            elif low in ("d14","ev14"):
                grp=14;why="numeric_name_match"
            if grp:
                audio.append(dict(group=grp,kind="bgm_"+why,file=p.name,
                                  relative=str(p.relative_to(KR)),bytes=p.stat().st_size,duration_sec=probe_duration(p)))
    write_tsv(STAGE/"group_number_audio_candidates.tsv",audio)

    # Check whether s_a13/s_a14 voice banks are already used by ordinary decoded TBL.
    decoded=ROOT/"analysis"/"mov"/"mov03d_all_tbl_link"/"decoded_tbl"
    usages=[]
    if decoded.exists():
        rx=re.compile(r"\b(s_[ab](13|14)[_-][A-Za-z0-9_+-]+)",re.I)
        for p in sorted(decoded.glob("*.tbl")):
            txt=p.read_text(encoding="cp932",errors="replace")
            for ln,line in enumerate(txt.splitlines(),1):
                for m in rx.finditer(line):
                    usages.append(dict(group=int(m.group(2)),voice_id=m.group(1),tbl=p.name,line_no=ln,line=line[:500]))
    write_tsv(STAGE/"group_number_voice_tbl_usage.tsv",usages)

    # Summaries of resolved mapping.
    dm=[r for r in dispatch if str(r.get("movie","")).startswith("dm")]
    dm_names=sorted(set(r["movie"] for r in dm))
    groupsum=[]
    for grp in (13,14):
        rr=[r for r in dispatch if r["group"]==grp]
        groupsum.append(f"Group {grp}: "+", ".join(f"state{r['state_index']}->{r['movie'] or '?'}(sel={r['selector']},idx={r['movie_index']})" for r in rr))

    # This proves selector mapping, NOT audio linkage.
    summary=[
        "Naruto PSP MOV03G - Grounded DM dispatcher table decode",
        "="*78,"",
        f"Primary PMF table entries={len(primary)}",
        f"Resolved dispatcher rows={len(dispatch)}",
        f"DM rows in dispatcher={len(dm)}",
        f"Distinct DM movies reached={len(dm_names)}/10: {', '.join(dm_names) if dm_names else '(none)'}",
        "",
        *groupsum,
        "",
        f"Group-number audio candidate files={len(audio)}",
        f"Ordinary decoded TBL usages of s_a13/s_b13/s_a14/s_b14={len(usages)}",
        "",
        "Interpretation:",
        "- resolved_dispatch.tsv is grounded by the exact MIPS table lookup seen in MOV03F.",
        "- group numbers 13/14 are passed to 0x60058/0x60460 before movie selection.",
        "- Matching s_a13/s_a14 or d13/ev13 names are only candidates; numeric similarity alone",
        "  does NOT prove that those files are the PMF soundtrack.",
        "- target_function_context.txt and callers are included to determine what the",
        "  group-resource functions actually manage.",
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
