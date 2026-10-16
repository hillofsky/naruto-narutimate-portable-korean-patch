#!/usr/bin/env python3
# Naruto PSP MOV03H - extend DM movie map + find TBL-unreferenced voice banks
#
# Grounded state after MOV03G FIX1:
# - PMF pointer table is file-backed and valid.
# - group14 movie map 0x00459C58 selectors 0..7 -> dm001..dm008.
# - selector state arrays at 0x004BD698/0x004BD6A8 are BSS/runtime data;
#   they MUST NOT be read from file.
# - s_a13/s_a14/s_b13/s_b14 are ordinary TBL dialogue banks, not movie-only
#   merely because their numbers match resource group IDs.
#
# This stage:
# 1. Reads group14 movie map BEYOND selector 7 to determine whether dm009/dm010
#    continue at selectors 8/9.
# 2. Classifies the selector addresses as file-backed vs BSS using PT_LOAD.
# 3. Finds every static MIPS reference to the BSS selector bases, useful for
#    locating initialization/writers without gameplay.
# 4. Enumerates every KR voice AT3 and compares it against every voice ID
#    referenced by the correctly decoded MOV03D TBL scripts.
# 5. Groups never-referenced AT3 files by filename bank prefix to surface
#    likely movie/cinematic-only voice banks.
#
# No patching, no gameplay.

from __future__ import annotations
import csv, re, struct, sys, traceback
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
BOOT = ROOT / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
VOICE = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "sound" / "voice"
DECODED_TBL = ROOT / "analysis" / "mov" / "mov03d_all_tbl_link" / "decoded_tbl"
STAGE = ROOT / "analysis" / "mov" / "mov03h_dm_voice_bank"
STAGE.mkdir(parents=True, exist_ok=True)

PSP_BASE = 0x08804000
PRIMARY = 0x00459250
PRIMARY_COUNT = 24
GROUP14_MAP = 0x00459C58
GROUP13_SELECTOR_BSS = 0x004BD698
GROUP14_SELECTOR_BSS = 0x004BD6A8

REG = [
    "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
    "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
    "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
    "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sx16(x): return x-0x10000 if x & 0x8000 else x

def write_tsv(path: Path, rows: list[dict], fields=None):
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def parse_elf(data: bytes):
    if not data.startswith(b"\x7fELF") or data[4] != 1:
        raise RuntimeError("BOOT.BIN is not ELF32")
    endian="<" if data[5]==1 else ">"
    v=struct.unpack_from(endian+"HHIIIIIHHHHHH",data,16)
    e_entry,e_phoff,e_shoff,e_phentsize,e_phnum,e_shentsize,e_shnum,e_shstrndx = (
        v[3],v[4],v[5],v[8],v[9],v[10],v[11],v[12]
    )
    ph=[]
    for i in range(e_phnum):
        o=e_phoff+i*e_phentsize
        if o+32>len(data): break
        x=struct.unpack_from(endian+"IIIIIIII",data,o)
        ph.append(dict(index=i,type=x[0],offset=x[1],vaddr=x[2],paddr=x[3],
                       filesz=x[4],memsz=x[5],flags=x[6],align=x[7]))
    return dict(endian=endian,entry=e_entry,ph=ph)

def file_backed_va_to_off(va:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["vaddr"] <= va < p["vaddr"]+p["filesz"]:
            return p["offset"]+(va-p["vaddr"])
    return None

def memory_segment_for_va(va:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["vaddr"] <= va < p["vaddr"]+p["memsz"]:
            return p
    return None

def off_to_va(off:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["offset"] <= off < p["offset"]+p["filesz"]:
            return p["vaddr"]+(off-p["offset"])
    return None

def rt(va): return PSP_BASE + va if va is not None else None

def u32_filebacked(data:bytes, va:int, elf):
    o=file_backed_va_to_off(va,elf)
    if o is None or o+4>len(data):
        raise RuntimeError(f"VA 0x{va:08X} is not file-backed u32")
    return struct.unpack_from("<I",data,o)[0]

def cstr_filebacked(data:bytes, va:int, elf, maxlen=256):
    o=file_backed_va_to_off(va,elf)
    if o is None:
        return ""
    e=data.find(b"\0",o,min(len(data),o+maxlen))
    if e<0:e=min(len(data),o+maxlen)
    return data[o:e].decode("ascii","replace")

def mips(word:int, pc=None):
    op=(word>>26)&63; rs=(word>>21)&31; rt0=(word>>16)&31; rd=(word>>11)&31
    sa=(word>>6)&31; fn=word&63; imm=word&0xffff
    if word==0:return "nop"
    if op==0:
        d={
            0x00:f"sll {REG[rd]},{REG[rt0]},{sa}",
            0x02:f"srl {REG[rd]},{REG[rt0]},{sa}",
            0x08:f"jr {REG[rs]}",
            0x09:f"jalr {REG[rd]},{REG[rs]}",
            0x21:f"addu {REG[rd]},{REG[rs]},{REG[rt0]}",
            0x23:f"subu {REG[rd]},{REG[rs]},{REG[rt0]}",
            0x24:f"and {REG[rd]},{REG[rs]},{REG[rt0]}",
            0x25:f"or {REG[rd]},{REG[rs]},{REG[rt0]}",
        }
        return d.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        tgt=((pc+4)&0xF0000000)|((word&0x03ffffff)<<2) if pc is not None else ((word&0x03ffffff)<<2)
        return ("j" if op==2 else "jal")+f" 0x{tgt:08X}"
    if op==4:return f"beq {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==5:return f"bne {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==9:return f"addiu {REG[rt0]},{REG[rs]},{sx16(imm)}"
    if op==0x0c:return f"andi {REG[rt0]},{REG[rs]},0x{imm:04X}"
    if op==0x0d:return f"ori {REG[rt0]},{REG[rs]},0x{imm:04X}"
    if op==0x0f:return f"lui {REG[rt0]},0x{imm:04X}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem:return f"{mem[op]} {REG[rt0]},{sx16(imm)}({REG[rs]})"
    return f"op=0x{op:X} word=0x{word:08X}"

def scan_address_refs(data:bytes, elf, target:int, label:str):
    rows=[]
    # LUI r, hi(target adjusted/or exact) + ADDIU/ORI same register nearby.
    for off in range(0,len(data)-28,4):
        w=struct.unpack_from("<I",data,off)[0]
        if (w>>26)!=0x0f: continue
        reg=(w>>16)&31
        hi=w&0xffff
        if reg==0:continue
        for j in range(1,7):
            o2=off+j*4
            w2=struct.unpack_from("<I",data,o2)[0]
            op2=(w2>>26)&63
            rs2=(w2>>21)&31; rt2=(w2>>16)&31; lo=w2&0xffff
            if rs2!=reg or rt2!=reg or op2 not in (9,0x0d):
                continue
            val=(((hi<<16)+sx16(lo)) if op2==9 else ((hi<<16)|lo)) & 0xffffffff
            if val==target:
                va=off_to_va(off,elf)
                rows.append(dict(
                    target=label,target_elfva=f"0x{target:08X}",
                    xref_file=f"0x{off:08X}",
                    xref_elfva=f"0x{va:08X}" if va is not None else "",
                    xref_runtime=f"0x{rt(va):08X}" if va is not None else "",
                    register=REG[reg],gap=j,
                    first_asm=mips(w,va),
                    second_asm=mips(w2,off_to_va(o2,elf))
                ))
            break
    return rows

def dump_code(data:bytes, elf, center_off:int, radius=0x100):
    lo=max(0,(center_off-radius)&~3)
    hi=min(len(data),(center_off+radius+3)&~3)
    lines=[]
    for o in range(lo,hi,4):
        if o+4>len(data):break
        va=off_to_va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        mark=">>" if o==center_off else "  "
        lines.append(
            f"{mark} file=0x{o:08X} elfva=0x{va:08X} runtime=0x{rt(va):08X} "
            f"{w:08X}  {mips(w,va)}"
        )
    return "\n".join(lines)

def normalize_voice_id(s:str):
    s=s.strip().replace("\\","/").split("/")[-1]
    if s.lower().endswith(".at3"):
        s=s[:-4]
    return s.lower()

def bank_key(stem:str):
    # Main known convention: s_a13_000, s_b14_026e, etc.
    m=re.match(r"^(s_[a-z]+\d+)[_-]",stem,re.I)
    if m:return m.group(1).lower()
    # Generic fallback: prefix before final numeric item.
    m=re.match(r"^(.+?)[_-]\d+[a-z]?$",stem,re.I)
    if m:return m.group(1).lower()
    return stem.lower()

def main():
    if not BOOT.exists():raise RuntimeError(f"Missing BOOT: {BOOT}")
    if not VOICE.exists():raise RuntimeError(f"Missing voice dir: {VOICE}")
    if not DECODED_TBL.exists():raise RuntimeError(f"Missing decoded TBL dir: {DECODED_TBL}")

    data=BOOT.read_bytes()
    elf=parse_elf(data)

    print("="*78,flush=True)
    print(" Naruto PSP MOV03H - DM map extension + unreferenced voice bank scan",flush=True)
    print("="*78,flush=True)

    # Correctly classify BSS selector addresses.
    addr_rows=[]
    for label,va in [
        ("group13_selector",GROUP13_SELECTOR_BSS),
        ("group14_selector",GROUP14_SELECTOR_BSS),
    ]:
        p=memory_segment_for_va(va,elf)
        foff=file_backed_va_to_off(va,elf)
        addr_rows.append(dict(
            label=label,elfva=f"0x{va:08X}",runtime=f"0x{rt(va):08X}",
            in_load_mem="YES" if p else "NO",
            in_file_backed="YES" if foff is not None else "NO",
            segment_vaddr=f"0x{p['vaddr']:08X}" if p else "",
            segment_filesz=f"0x{p['filesz']:X}" if p else "",
            segment_memsz=f"0x{p['memsz']:X}" if p else "",
            classification="FILE_BACKED" if foff is not None else ("BSS_OR_ZERO_FILL" if p else "UNMAPPED"),
        ))
    write_tsv(STAGE/"selector_address_classification.tsv",addr_rows)

    # Primary PMF table.
    primary=[]
    for i in range(PRIMARY_COUNT):
        pva=u32_filebacked(data,PRIMARY+i*4,elf)
        path=cstr_filebacked(data,pva,elf,128)
        m=re.search(r"/movie/([^/]+)\.pmf$",path,re.I)
        movie=m.group(1).lower() if m else ""
        primary.append(dict(index=i,pointer_elfva=f"0x{pva:08X}",movie=movie,path=path))
    write_tsv(STAGE/"primary_pmf_table.tsv",primary)

    # Extend group14 map well beyond the prior assumed 8 entries.
    ext=[]
    consecutive_invalid=0
    valid_prefix_len=0
    for sel in range(0,32):
        va=GROUP14_MAP+sel*4
        try:
            mi=u32_filebacked(data,va,elf)
        except Exception:
            break
        valid=0 <= mi < len(primary) and bool(primary[mi]["movie"])
        if valid:
            consecutive_invalid=0
            if sel==valid_prefix_len:
                valid_prefix_len += 1
        else:
            consecutive_invalid += 1
        ext.append(dict(
            selector=sel,map_entry_elfva=f"0x{va:08X}",
            movie_index=mi,
            valid_pmf_index="YES" if valid else "NO",
            movie=primary[mi]["movie"] if valid else "",
            path=primary[mi]["path"] if valid else "",
        ))
        # Once we have passed at least 10 entries, 4 invalids is enough context.
        if sel>=9 and consecutive_invalid>=4:
            break
    write_tsv(STAGE/"group14_extended_movie_map.tsv",ext)

    # Grounded BSS address xrefs, without attempting to read BSS contents.
    xrefs=[]
    xrefs += scan_address_refs(data,elf,GROUP13_SELECTOR_BSS,"group13_selector_BSS")
    xrefs += scan_address_refs(data,elf,GROUP14_SELECTOR_BSS,"group14_selector_BSS")
    write_tsv(STAGE/"selector_bss_code_xrefs.tsv",xrefs)

    ctx=[]
    seen=set()
    for r in xrefs:
        off=int(r["xref_file"],16)
        if off in seen:continue
        seen.add(off)
        ctx.append("="*100+"\n"+
                   f"{r['target']} xref at {r['xref_file']} / {r['xref_runtime']}\n"+
                   dump_code(data,elf,off,0x140))
    (STAGE/"selector_bss_code_context.txt").write_text("\n\n".join(ctx),encoding="utf-8-sig")

    # Collect every voice token referenced by decoded TBL text.
    referenced={}
    token_rx=re.compile(r"\b([A-Za-z][A-Za-z0-9_+-]{2,})\b")
    for p in sorted(DECODED_TBL.glob("*.tbl")):
        txt=p.read_text(encoding="cp932",errors="replace")
        for ln,line in enumerate(txt.splitlines(),1):
            # Strong extraction: arguments that look like s_* voice IDs.
            for m in re.finditer(r"\b(s_[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+)\b",line,re.I):
                vid=normalize_voice_id(m.group(1))
                referenced.setdefault(vid,[]).append((p.name,ln,line[:500]))

    ref_rows=[]
    for vid,uses in sorted(referenced.items()):
        ref_rows.append(dict(
            voice_id=vid,use_count=len(uses),
            first_tbl=uses[0][0],first_line=uses[0][1],
            first_context=uses[0][2],
        ))
    write_tsv(STAGE/"tbl_referenced_voice_ids.tsv",ref_rows)

    # Enumerate KR voice AT3s and mark referenced/unreferenced.
    voice_rows=[]
    groups=defaultdict(lambda:dict(total=0,ref=0,unref=0,total_bytes=0,unref_bytes=0,files=[]))
    for p in sorted(VOICE.rglob("*.at3")):
        # Ignore localized subfolders if any; only KR root/normal tree is relevant.
        rel=p.relative_to(VOICE)
        # Keep all, but record subdir.
        stem=normalize_voice_id(p.name)
        ref=stem in referenced
        bank=bank_key(stem)
        sz=p.stat().st_size
        voice_rows.append(dict(
            voice_id=stem,file=p.name,relative=str(rel),
            bank=bank,bytes=sz,
            referenced_in_tbl="YES" if ref else "NO",
            tbl_use_count=len(referenced.get(stem,[])),
        ))
        g=groups[bank]
        g["total"]+=1;g["total_bytes"]+=sz;g["files"].append(stem)
        if ref:g["ref"]+=1
        else:
            g["unref"]+=1;g["unref_bytes"]+=sz

    write_tsv(STAGE/"voice_at3_inventory.tsv",voice_rows)

    unref_files=[r for r in voice_rows if r["referenced_in_tbl"]=="NO"]
    write_tsv(STAGE/"unreferenced_voice_files.tsv",unref_files)

    group_rows=[]
    for bank,g in groups.items():
        ratio=(g["unref"]/g["total"]) if g["total"] else 0.0
        if g["unref"]==0:
            cls="ALL_TBL_REFERENCED"
        elif g["ref"]==0:
            cls="ZERO_TBL_REFERENCES"
        elif ratio>=0.8:
            cls="MOSTLY_UNREFERENCED"
        else:
            cls="MIXED"
        group_rows.append(dict(
            bank=bank,total_files=g["total"],
            tbl_referenced_files=g["ref"],
            unreferenced_files=g["unref"],
            unreferenced_ratio=f"{ratio:.4f}",
            total_bytes=g["total_bytes"],
            unreferenced_bytes=g["unref_bytes"],
            classification=cls,
            unreferenced_examples=",".join(
                x for x in g["files"] if x not in referenced
            )[:1000],
        ))
    # Put strongest movie candidates first.
    order={"ZERO_TBL_REFERENCES":0,"MOSTLY_UNREFERENCED":1,"MIXED":2,"ALL_TBL_REFERENCED":3}
    group_rows.sort(key=lambda r:(order[r["classification"]],-int(r["unreferenced_files"]),r["bank"]))
    write_tsv(STAGE/"voice_bank_reference_summary.tsv",group_rows)

    # A more compact candidate sheet: >=2 files and zero ordinary TBL refs.
    candidates=[
        r for r in group_rows
        if r["classification"]=="ZERO_TBL_REFERENCES" and int(r["total_files"])>=2
    ]
    write_tsv(STAGE/"movie_voice_bank_candidates.tsv",candidates)

    dm_map=[r for r in ext if r["movie"].startswith("dm")]
    dm_names=[r["movie"] for r in dm_map]
    zero_groups=[r for r in candidates]
    summary=[
        "Naruto PSP MOV03H - DM map extension + unreferenced voice bank scan",
        "="*78,"",
        "Grounded correction:",
        "- Selector arrays at 0x004BD698 / 0x004BD6A8 are treated as runtime BSS.",
        "- No state->selector mapping is fabricated from BOOT file bytes.",
        "",
        f"Primary PMF entries={len(primary)}",
        f"Group14 consecutive valid PMF map prefix={valid_prefix_len} selectors",
        f"DM entries observed in extended group14 map={len(dm_map)}",
        f"DM sequence={', '.join(dm_names) if dm_names else '(none)'}",
        f"Selector-BSS static code xrefs={len(xrefs)}",
        "",
        f"Distinct TBL-referenced voice IDs={len(referenced)}",
        f"Voice AT3 files enumerated={len(voice_rows)}",
        f"Voice AT3 files never referenced by any decoded TBL={len(unref_files)}",
        f"Voice banks with >=2 files and ZERO TBL references={len(zero_groups)}",
        "",
        "Interpretation:",
        "- If group14 selectors 0..9 resolve to dm001..dm010, the static",
        "  selector->movie mapping is complete even though state->selector remains runtime BSS.",
        "- movie_voice_bank_candidates.tsv is the strongest no-gameplay lead for",
        "  external movie dialogue: these banks exist on disc but are absent from all",
        "  decoded ordinary TBL scripts.",
        "- Absence from TBL is evidence of a separate use path, not by itself proof",
        "  that a bank belongs to a specific DM movie.",
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
