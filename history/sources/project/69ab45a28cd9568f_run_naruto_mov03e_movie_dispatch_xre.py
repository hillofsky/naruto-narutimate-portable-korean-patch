#!/usr/bin/env python3
# Naruto PSP MOV03E - BOOT/EBOOT movie table static xref analysis
#
# Goal:
#   Locate the PMF path table (dm001..dm010 etc.) in the executable,
#   map file offsets to runtime addresses when ELF metadata permits,
#   find raw pointer and MIPS LUI+ADDIU/ORI xrefs to the table,
#   and dump code/data context around those xrefs.
#
# This does NOT guess a DM->audio mapping. It only reports grounded xrefs.

from __future__ import annotations
import csv, json, re, struct, sys, traceback
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"PROJECT_ROOT")
KR = ROOT / "kr_extracted"
STAGE = ROOT / "analysis" / "mov" / "mov03e_movie_dispatch_xref"
STAGE.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    KR / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
    KR / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN",
]

MOVIES = [
    "logo_b","logo_c","logo_a",
    "dk101","dk102","dk103","dk104","dk201","dk202","dk203",
    "da101","da102","da103","da201",
    "dm001","dm002","dm003","dm004","dm005","dm006","dm007","dm008","dm009","dm010",
]

# We search several anchor spellings because path prefixes can differ.
ANCHORS = [
    b"dm001.pmf", b"dm010.pmf", b"da101.pmf", b"dk101.pmf",
    b"/movie/", b"movie/", b"MOVIE", b"movie_dec", b"adnpspmovie",
]

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

def find_all(data: bytes, needle: bytes):
    out=[]
    p=0
    while True:
        p=data.find(needle,p)
        if p<0: break
        out.append(p); p+=1
    return out

def parse_elf32(data: bytes):
    # Return (elf_base_offset, program headers) or None.
    positions=[]
    if data.startswith(b"\x7fELF"):
        positions.append(0)
    for p in find_all(data[:0x4000],b"\x7fELF"):
        if p not in positions:
            positions.append(p)
    for base in positions:
        try:
            if len(data)<base+0x34: continue
            ident=data[base:base+16]
            if ident[:4]!=b"\x7fELF" or ident[4]!=1: continue  # ELF32 only
            endian="<" if ident[5]==1 else ">"
            hdr=struct.unpack_from(endian+"HHIIIIIHHHHHH",data,base+16)
            e_type,e_machine,e_version,e_entry,e_phoff,e_shoff,e_flags,e_ehsize,e_phentsize,e_phnum,e_shentsize,e_shnum,e_shstrndx=hdr
            ph=[]
            for i in range(e_phnum):
                off=base+e_phoff+i*e_phentsize
                if off+32>len(data): break
                p_type,p_offset,p_vaddr,p_paddr,p_filesz,p_memsz,p_flags,p_align=struct.unpack_from(endian+"IIIIIIII",data,off)
                ph.append({
                    "index":i,"type":p_type,"offset":p_offset,"vaddr":p_vaddr,
                    "filesz":p_filesz,"memsz":p_memsz,"flags":p_flags,"align":p_align,
                })
            return {
                "base":base,"endian":endian,"entry":e_entry,"machine":e_machine,
                "phoff":e_phoff,"phnum":e_phnum,"ph":ph
            }
        except Exception:
            continue
    return None

def fileoff_to_vaddr(fileoff: int, elf):
    if not elf: return None
    base=elf["base"]
    rel=fileoff-base
    for p in elf["ph"]:
        if p["type"]!=1: continue # PT_LOAD
        if p["offset"] <= rel < p["offset"]+p["filesz"]:
            return p["vaddr"] + (rel-p["offset"])
    return None

def vaddr_to_fileoff(vaddr: int, elf):
    if not elf: return None
    base=elf["base"]
    for p in elf["ph"]:
        if p["type"]!=1: continue
        if p["vaddr"] <= vaddr < p["vaddr"]+p["filesz"]:
            return base + p["offset"] + (vaddr-p["vaddr"])
    return None

REG = [
    "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
    "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
    "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
    "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sx16(x): return x-0x10000 if x&0x8000 else x

def mips_decode(word:int, pc:int|None=None):
    op=(word>>26)&0x3f
    rs=(word>>21)&31; rt=(word>>16)&31; rd=(word>>11)&31
    sa=(word>>6)&31; fn=word&63; imm=word&0xffff
    target=word&0x03ffffff
    if word==0: return "nop"
    if op==0:
        m={
            0x00:f"sll {REG[rd]},{REG[rt]},{sa}",
            0x02:f"srl {REG[rd]},{REG[rt]},{sa}",
            0x08:f"jr {REG[rs]}",
            0x09:f"jalr {REG[rd]},{REG[rs]}",
            0x21:f"addu {REG[rd]},{REG[rs]},{REG[rt]}",
            0x23:f"subu {REG[rd]},{REG[rs]},{REG[rt]}",
            0x24:f"and {REG[rd]},{REG[rs]},{REG[rt]}",
            0x25:f"or {REG[rd]},{REG[rs]},{REG[rt]}",
            0x2a:f"slt {REG[rd]},{REG[rs]},{REG[rt]}",
        }
        return m.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        addr=((pc+4)&0xF0000000 | (target<<2)) if pc is not None else (target<<2)
        return ("j" if op==2 else "jal")+f" 0x{addr:08X}"
    if op==4: return f"beq {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==5: return f"bne {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==8: return f"addi {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==9: return f"addiu {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0c: return f"andi {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0d: return f"ori {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0f: return f"lui {REG[rt]},0x{imm:04X}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem: return f"{mem[op]} {REG[rt]},{sx16(imm)}({REG[rs]})"
    if op==0x0a: return f"slti {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0b: return f"sltiu {REG[rt]},{REG[rs]},{sx16(imm)}"
    return f"op=0x{op:X} word=0x{word:08X}"

def scan_lui_address_pairs(data:bytes, targets:dict[int,str], elf):
    # Search LUI rt,hi followed within next 6 instructions by ADDIU/ORI same rt.
    # Accept canonical %hi adjustment for ADDIU.
    rows=[]
    n=len(data)//4
    for i in range(n):
        off=i*4
        w=struct.unpack_from("<I",data,off)[0]
        if (w>>26)!=0x0f: continue
        rt=(w>>16)&31; hi=w&0xffff
        if rt==0: continue
        for j in range(1,7):
            off2=off+j*4
            if off2+4>len(data): break
            w2=struct.unpack_from("<I",data,off2)[0]
            op2=(w2>>26)&0x3f
            rs2=(w2>>21)&31; rt2=(w2>>16)&31; lo=w2&0xffff
            if rt2!=rt or rs2!=rt or op2 not in (9,0x0d):
                continue
            if op2==9:
                val=((hi<<16)+sx16(lo)) & 0xffffffff
                kind="lui+addiu"
            else:
                val=((hi<<16)|lo) & 0xffffffff
                kind="lui+ori"
            if val in targets:
                pc=fileoff_to_vaddr(off,elf)
                rows.append({
                    "target_name":targets[val],
                    "target_vaddr":f"0x{val:08X}",
                    "xref_file_offset":f"0x{off:08X}",
                    "xref_vaddr":f"0x{pc:08X}" if pc is not None else "",
                    "kind":kind,
                    "register":REG[rt],
                    "gap_instructions":j,
                    "first_word":f"0x{w:08X}",
                    "second_word":f"0x{w2:08X}",
                })
            break
    return rows

def dump_mips_context(data:bytes, center:int, elf, radius=0x80):
    lo=max(0,(center-radius)&~3); hi=min(len(data),(center+radius+3)&~3)
    lines=[]
    for off in range(lo,hi,4):
        if off+4>len(data): break
        w=struct.unpack_from("<I",data,off)[0]
        va=fileoff_to_vaddr(off,elf)
        mark=">>" if center<=off<center+8 else "  "
        lines.append(f"{mark} file=0x{off:08X} va={'0x%08X'%va if va is not None else '??????????'}  {w:08X}  {mips_decode(w,va)}")
    return "\n".join(lines)

def ascii_context(data:bytes, center:int, radius=0x300):
    lo=max(0,center-radius); hi=min(len(data),center+radius)
    blob=data[lo:hi]
    out=[]
    for m in re.finditer(rb"[\x20-\x7e]{4,}",blob):
        out.append(f"0x{lo+m.start():08X}  {m.group().decode('ascii','replace')}")
    return "\n".join(out)

def main():
    info=[]; path_rows=[]; all_xrefs=[]; raw_ptrs=[]; anchor_rows=[]; context_blocks=[]
    selected=None

    for exe in CANDIDATES:
        if not exe.exists(): continue
        data=exe.read_bytes()
        elf=parse_elf32(data)
        dm_hits=find_all(data,b"dm001.pmf")
        movie_hits=find_all(data,b"/movie/")+find_all(data,b"movie/")
        info.append({
            "path":str(exe),"size":len(data),
            "elf_found":"YES" if elf else "NO",
            "elf_base":f"0x{elf['base']:X}" if elf else "",
            "elf_entry":f"0x{elf['entry']:08X}" if elf else "",
            "pt_load_count":sum(1 for x in elf["ph"] if x["type"]==1) if elf else 0,
            "dm001_hits":len(dm_hits),"movie_path_hits":len(set(movie_hits)),
        })
        if dm_hits and selected is None:
            selected=(exe,data,elf)

    write_tsv(STAGE/"executable_inventory.tsv",info)

    if selected is None:
        raise RuntimeError("Neither BOOT.BIN nor EBOOT.BIN contains dm001.pmf")

    exe,data,elf=selected
    (STAGE/"SELECTED_EXECUTABLE.txt").write_text(
        f"path={exe}\nsize={len(data)}\nelf={'YES' if elf else 'NO'}\n",
        encoding="utf-8-sig"
    )

    # Inventory every exact PMF filename occurrence.
    movie_offsets={}
    for movie in MOVIES:
        needle=(movie+".pmf").encode("ascii")
        hits=find_all(data,needle)
        for idx,off in enumerate(hits):
            va=fileoff_to_vaddr(off,elf)
            path_rows.append({
                "movie":movie,"occurrence":idx+1,
                "file_offset":f"0x{off:08X}",
                "vaddr":f"0x{va:08X}" if va is not None else "",
                "preceding_ascii":ascii_context(data,off,0x60).replace("\n"," | ")[:500],
            })
        if hits:
            movie_offsets[movie]=hits[0]
    write_tsv(STAGE/"movie_path_occurrences.tsv",path_rows)

    # Infer fixed stride from dm001..dm010 offsets.
    dm_offs=[movie_offsets.get(f"dm{i:03d}") for i in range(1,11)]
    dm_offs2=[x for x in dm_offs if x is not None]
    strides=[b-a for a,b in zip(dm_offs2,dm_offs2[1:])]
    stride_common=max(set(strides),key=strides.count) if strides else None

    # Full string/table start heuristic: contiguous movie filename entries often
    # have the same stride. Use first DM offset and walk backward by stride to
    # see which known movie names align.
    inferred=[]
    if stride_common:
        dm1=movie_offsets.get("dm001")
        for back in range(0,32):
            off=dm1-back*stride_common
            if off<0: break
            chunk=data[off:off+stride_common]
            m=re.search(rb"([a-z]{2}\d{3}|logo_[abc])\.pmf",chunk,re.I)
            if m:
                inferred.append((off,m.group(1).decode("ascii").lower()))
    inferred=sorted(set(inferred))

    # Candidate address targets: every movie string plus inferred table base.
    targets={}
    if elf:
        for movie,off in movie_offsets.items():
            va=fileoff_to_vaddr(off,elf)
            if va is not None:
                targets[va]=f"movie_string:{movie}"
        if inferred:
            baseoff=inferred[0][0]
            va=fileoff_to_vaddr(baseoff,elf)
            if va is not None:
                targets[va]="movie_table_base_inferred"
        # Also string starts can be preceded by path prefix within fixed slot.
        # Add beginning of each 40/stride slot around dm entries.
        if stride_common and movie_offsets.get("dm001") is not None:
            # dm filename may begin after "disc0:/.../movie/" prefix, so examine
            # nearby aligned candidates within first slot.
            dm1=movie_offsets["dm001"]
            for delta in range(0,min(stride_common,64)):
                slot=dm1-delta
                va=fileoff_to_vaddr(slot,elf)
                if va is not None:
                    # Only retain plausible slot beginning when ASCII path starts.
                    s=data[slot:slot+stride_common]
                    if b"movie" in s.lower() or b"disc0:" in s.lower():
                        targets[va]=f"dm001_slot_candidate_minus_{delta}"

    # Raw 32-bit pointer xrefs.
    for va,name in targets.items():
        needle=struct.pack("<I",va)
        for off in find_all(data,needle):
            raw_ptrs.append({
                "target_name":name,"target_vaddr":f"0x{va:08X}",
                "pointer_file_offset":f"0x{off:08X}",
                "pointer_vaddr":f"0x{fileoff_to_vaddr(off,elf):08X}" if fileoff_to_vaddr(off,elf) is not None else "",
            })
    write_tsv(STAGE/"raw_pointer_xrefs.tsv",raw_ptrs)

    # MIPS address construction xrefs.
    if elf and targets:
        all_xrefs=scan_lui_address_pairs(data,targets,elf)
    write_tsv(STAGE/"mips_address_xrefs.tsv",all_xrefs)

    # Anchors and their xrefs.
    anchor_targets={}
    for anc in ANCHORS:
        for n,off in enumerate(find_all(data,anc),1):
            va=fileoff_to_vaddr(off,elf)
            anchor_rows.append({
                "anchor":anc.decode("ascii","replace"),"occurrence":n,
                "file_offset":f"0x{off:08X}",
                "vaddr":f"0x{va:08X}" if va is not None else "",
            })
            if va is not None:
                anchor_targets[va]=f"anchor:{anc.decode('ascii','replace')}#{n}"
    write_tsv(STAGE/"anchor_occurrences.tsv",anchor_rows)

    anchor_xrefs=scan_lui_address_pairs(data,anchor_targets,elf) if elf else []
    write_tsv(STAGE/"anchor_mips_xrefs.tsv",anchor_xrefs)

    # Context dumps for every useful xref, de-duplicated by file offset.
    xoff=set()
    for r in all_xrefs+anchor_xrefs:
        xoff.add(int(r["xref_file_offset"],16))
    for r in raw_ptrs:
        # Raw pointer data may not be code, but include ASCII context separately.
        off=int(r["pointer_file_offset"],16)
        context_blocks.append(
            f"RAW POINTER: {r['target_name']} @ {r['pointer_file_offset']}\n"
            + ascii_context(data,off,0x200)
        )
    for off in sorted(xoff):
        context_blocks.append(
            "="*92+"\n"
            f"MIPS XREF file=0x{off:08X}\n"
            + dump_mips_context(data,off,elf,0x100)
        )
    (STAGE/"xref_context.txt").write_text("\n\n".join(context_blocks),encoding="utf-8-sig")

    # Scan for code patterns that likely index a 40-byte (or inferred stride)
    # table: x*40 = (x<<5)+(x<<3). We do not call these xrefs by themselves.
    stride_rows=[]
    stride=stride_common or 40
    # Common compiler sequence: sll rA,rI,5 ; sll rB,rI,3 ; addu ...
    words=[struct.unpack_from("<I",data,i)[0] for i in range(0,len(data)-3,4)]
    for i in range(len(words)-4):
        ds=[]
        for k in range(4):
            w=words[i+k]
            if (w>>26)==0 and (w&63)==0: # sll
                rt=(w>>16)&31; rd=(w>>11)&31; sa=(w>>6)&31
                ds.append((k,rt,rd,sa))
        shifts={d[3] for d in ds}
        if stride==40 and 5 in shifts and 3 in shifts:
            off=i*4
            stride_rows.append({
                "file_offset":f"0x{off:08X}",
                "vaddr":f"0x{fileoff_to_vaddr(off,elf):08X}" if fileoff_to_vaddr(off,elf) is not None else "",
                "pattern":"nearby sll-by-5 and sll-by-3 (possible x40)",
                "context":" | ".join(mips_decode(words[i+k],fileoff_to_vaddr((i+k)*4,elf)) for k in range(4))
            })
    write_tsv(STAGE/"stride40_code_candidates.tsv",stride_rows[:5000])

    # Nearby call/JAL targets around movie-table xrefs.
    calls=[]
    for r in all_xrefs:
        off=int(r["xref_file_offset"],16)
        lo=max(0,off-0x100); hi=min(len(data)-4,off+0x140)
        seen=set()
        for p in range(lo&~3,hi,4):
            w=struct.unpack_from("<I",data,p)[0]
            if (w>>26)!=3: continue
            pc=fileoff_to_vaddr(p,elf)
            if pc is None: continue
            tgt=((pc+4)&0xF0000000)|((w&0x03ffffff)<<2)
            key=(p,tgt)
            if key in seen: continue
            seen.add(key)
            calls.append({
                "xref_target":r["target_name"],
                "xref_file_offset":r["xref_file_offset"],
                "call_file_offset":f"0x{p:08X}",
                "call_vaddr":f"0x{pc:08X}",
                "jal_target_vaddr":f"0x{tgt:08X}",
                "jal_target_file_offset":f"0x{vaddr_to_fileoff(tgt,elf):08X}" if vaddr_to_fileoff(tgt,elf) is not None else "",
                "distance_from_xref":p-off,
            })
    write_tsv(STAGE/"nearby_jal_targets.tsv",calls)

    # Summary.
    dm_present=sum(1 for x in dm_offs if x is not None)
    summary=[
        "Naruto PSP MOV03E - BOOT/EBOOT movie table static xref analysis",
        "="*76,"",
        f"Selected executable={exe}",
        f"Size={len(data)}",
        f"ELF parsed={'YES' if elf else 'NO'}",
        f"ELF base offset={hex(elf['base']) if elf else ''}",
        f"ELF entry={hex(elf['entry']) if elf else ''}",
        f"DM filenames located={dm_present}/10",
        f"Inferred DM stride={stride_common if stride_common is not None else '(none)'} bytes",
        f"Inferred contiguous movie slots={len(inferred)}",
        f"Address targets built={len(targets)}",
        f"Raw pointer xrefs={len(raw_ptrs)}",
        f"MIPS LUI+ADDIU/ORI xrefs={len(all_xrefs)}",
        f"Anchor MIPS xrefs={len(anchor_xrefs)}",
        f"Possible x40 indexing code windows={len(stride_rows)}",
        "",
        "Interpretation:",
        "- movie_path_occurrences.tsv grounds the actual PMF table layout.",
        "- raw_pointer_xrefs.tsv finds literal pointers to movie table/string addresses.",
        "- mips_address_xrefs.tsv finds code constructing those addresses.",
        "- nearby_jal_targets.tsv lists calls surrounding grounded table xrefs.",
        "- stride40_code_candidates.tsv is heuristic only and must not be treated as proof.",
        "- If no ELF mapping/xrefs are available, the next pass should use runtime-base",
        "  inference or PPSSPP debugger traces, but this stage does not require gameplay.",
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
