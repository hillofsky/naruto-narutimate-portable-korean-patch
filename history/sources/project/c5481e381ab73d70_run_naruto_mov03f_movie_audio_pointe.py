#!/usr/bin/env python3
# Naruto PSP MOV03F - PMF slot pointer table + audio adjacency analysis
#
# Grounded findings from MOV03E:
# - PMF full-path slots are 40 bytes apart.
# - dm001 full-path slot has a raw pointer reference at BOOT file offset 0x4592DC.
#
# This pass:
# 1) Builds exact targets for ALL PMF full-path slot starts.
# 2) Finds every raw pointer to those slots.
# 3) Inventories .at3 strings and their raw pointers.
# 4) Clusters PMF-pointer xrefs to identify secondary mapping tables.
# 5) Parses MIPS GP value when available and finds GP-relative code xrefs.
# 6) Searches LUI+ADDIU/ORI xrefs to PMF slots, pointer records, and cluster bases.
# 7) Checks each PMF-pointer record neighborhood for direct AT3 pointers.
#
# No patching, no gameplay.

from __future__ import annotations
import csv, math, re, struct, sys, traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
BOOT = ROOT / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
STAGE = ROOT / "analysis" / "mov" / "mov03f_movie_audio_pointer_map"
STAGE.mkdir(parents=True, exist_ok=True)

PSP_LOAD_BASE = 0x08804000

MOVIES = [
    "logo_b","logo_c","logo_a",
    "dk101","dk102","dk103","dk201","dk202","dk203",
    "da101","da102","da103","da201",
    "dm001","dm002","dm003","dm004","dm005","dm006","dm007","dm008","dm009","dm010",
]

REG = [
    "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
    "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
    "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
    "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sx16(x): return x-0x10000 if x&0x8000 else x

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

def find_all(data:bytes, needle:bytes):
    out=[]; p=0
    while True:
        p=data.find(needle,p)
        if p<0: break
        out.append(p); p+=1
    return out

def parse_elf32(data:bytes):
    if not data.startswith(b"\x7fELF"):
        return None
    ident=data[:16]
    if ident[4]!=1: return None
    endian="<" if ident[5]==1 else ">"
    vals=struct.unpack_from(endian+"HHIIIIIHHHHHH",data,16)
    e_type,e_machine,e_version,e_entry,e_phoff,e_shoff,e_flags,e_ehsize,e_phentsize,e_phnum,e_shentsize,e_shnum,e_shstrndx=vals
    ph=[]
    for i in range(e_phnum):
        o=e_phoff+i*e_phentsize
        if o+32>len(data): break
        p_type,p_offset,p_vaddr,p_paddr,p_filesz,p_memsz,p_flags,p_align=struct.unpack_from(endian+"IIIIIIII",data,o)
        ph.append(dict(index=i,type=p_type,offset=p_offset,vaddr=p_vaddr,paddr=p_paddr,filesz=p_filesz,memsz=p_memsz,flags=p_flags,align=p_align))
    sh=[]
    if e_shoff and e_shentsize and e_shnum:
        for i in range(e_shnum):
            o=e_shoff+i*e_shentsize
            if o+40>len(data): break
            sh_name,sh_type,sh_flags,sh_addr,sh_offset,sh_size,sh_link,sh_info,sh_addralign,sh_entsize=struct.unpack_from(endian+"IIIIIIIIII",data,o)
            sh.append(dict(index=i,nameoff=sh_name,type=sh_type,flags=sh_flags,addr=sh_addr,offset=sh_offset,size=sh_size,link=sh_link,info=sh_info,align=sh_addralign,entsize=sh_entsize))
        if 0 <= e_shstrndx < len(sh):
            ss=sh[e_shstrndx]
            blob=data[ss["offset"]:ss["offset"]+ss["size"]]
            for s in sh:
                n=s["nameoff"]
                if n<len(blob):
                    e=blob.find(b"\0",n)
                    if e<0:e=len(blob)
                    s["name"]=blob[n:e].decode("ascii","replace")
                else:s["name"]=""
    return dict(endian=endian,entry=e_entry,ph=ph,sh=sh)

def file_to_elfva(off:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["offset"] <= off < p["offset"]+p["filesz"]:
            return p["vaddr"]+(off-p["offset"])
    return None

def elfva_to_file(va:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["vaddr"] <= va < p["vaddr"]+p["filesz"]:
            return p["offset"]+(va-p["vaddr"])
    return None

def runtime(elfva):
    return None if elfva is None else (PSP_LOAD_BASE + elfva) & 0xffffffff

def get_gp(data:bytes, elf):
    candidates=[]
    # SHT_MIPS_REGINFO
    for s in elf["sh"]:
        if s["type"]==0x70000006 and s["size"]>=24 and s["offset"]+24<=len(data):
            gp=struct.unpack_from(elf["endian"]+"I",data,s["offset"]+20)[0]
            candidates.append((f"section:{s.get('name','')}",gp,s["offset"]))
    # PT_MIPS_REGINFO
    for p in elf["ph"]:
        if p["type"]==0x70000000 and p["filesz"]>=24 and p["offset"]+24<=len(data):
            gp=struct.unpack_from(elf["endian"]+"I",data,p["offset"]+20)[0]
            candidates.append(("program_header:PT_MIPS_REGINFO",gp,p["offset"]))
    # de-dupe
    seen=set(); out=[]
    for x in candidates:
        if x[1] not in seen:
            seen.add(x[1]);out.append(x)
    return out

def mips_decode(word:int, pc=None):
    op=(word>>26)&0x3f; rs=(word>>21)&31; rt=(word>>16)&31; rd=(word>>11)&31
    sa=(word>>6)&31; fn=word&63; imm=word&0xffff
    if word==0:return "nop"
    if op==0:
        d={0x00:f"sll {REG[rd]},{REG[rt]},{sa}",0x02:f"srl {REG[rd]},{REG[rt]},{sa}",
           0x08:f"jr {REG[rs]}",0x09:f"jalr {REG[rd]},{REG[rs]}",
           0x21:f"addu {REG[rd]},{REG[rs]},{REG[rt]}",0x23:f"subu {REG[rd]},{REG[rs]},{REG[rt]}",
           0x24:f"and {REG[rd]},{REG[rs]},{REG[rt]}",0x25:f"or {REG[rd]},{REG[rs]},{REG[rt]}",
           0x2a:f"slt {REG[rd]},{REG[rs]},{REG[rt]}"}
        return d.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        tgt=((pc+4)&0xF0000000)|((word&0x03ffffff)<<2) if pc is not None else ((word&0x03ffffff)<<2)
        return ("j" if op==2 else "jal")+f" 0x{tgt:08X}"
    if op==4:return f"beq {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==5:return f"bne {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==8:return f"addi {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==9:return f"addiu {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0c:return f"andi {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0d:return f"ori {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0f:return f"lui {REG[rt]},0x{imm:04X}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem:return f"{mem[op]} {REG[rt]},{sx16(imm)}({REG[rs]})"
    return f"op=0x{op:X} word=0x{word:08X}"

def scan_lui_pairs(data:bytes, targets:dict[int,str], elf):
    rows=[]
    for off in range(0,len(data)-28,4):
        w=struct.unpack_from("<I",data,off)[0]
        if (w>>26)!=0x0f: continue
        rt=(w>>16)&31; hi=w&0xffff
        if rt==0: continue
        for j in range(1,7):
            o2=off+j*4; w2=struct.unpack_from("<I",data,o2)[0]
            op=(w2>>26)&0x3f; rs=(w2>>21)&31; rt2=(w2>>16)&31; lo=w2&0xffff
            if rt2!=rt or rs!=rt or op not in (9,0x0d):
                continue
            val=(((hi<<16)+sx16(lo)) if op==9 else ((hi<<16)|lo)) & 0xffffffff
            if val in targets:
                va=file_to_elfva(off,elf)
                rows.append({
                    "target":targets[val],"target_elfva":f"0x{val:08X}",
                    "target_runtime":f"0x{runtime(val):08X}",
                    "xref_file":f"0x{off:08X}",
                    "xref_elfva":f"0x{va:08X}" if va is not None else "",
                    "xref_runtime":f"0x{runtime(va):08X}" if va is not None else "",
                    "kind":"lui+addiu" if op==9 else "lui+ori",
                    "register":REG[rt],"gap":j,
                    "asm1":mips_decode(w,va),
                    "asm2":mips_decode(w2,file_to_elfva(o2,elf)),
                })
            break
    return rows

def find_ascii_at3(data:bytes, elf):
    rows=[]; byva={}
    # Capture a reasonable containing token/path, then locate .at3 within it.
    for m in re.finditer(rb"[\x20-\x7e]{4,220}",data):
        s=m.group()
        if b".at3" not in s.lower(): continue
        text=s.decode("ascii","replace")
        # A long printable span can contain adjacent NUL-separated strings only if
        # there are no NULs, so usually this is one actual token.
        for am in re.finditer(r"(?i)[A-Za-z0-9_./:\\-]{1,180}\.at3",text):
            token=am.group(0)
            off=m.start()+am.start()
            va=file_to_elfva(off,elf)
            row={
                "token":token,"file_offset":f"0x{off:08X}",
                "elfva":f"0x{va:08X}" if va is not None else "",
                "runtime":f"0x{runtime(va):08X}" if va is not None else "",
            }
            rows.append(row)
            if va is not None:byva[va]=token
    # de-dupe offsets
    uniq=[];seen=set()
    for r in rows:
        k=r["file_offset"]
        if k in seen:continue
        seen.add(k);uniq.append(r)
    return uniq,byva

def dump_words(data:bytes, center:int, elf, movie_by_va, audio_by_va, radius=0x100):
    lo=max(0,(center-radius)&~3); hi=min(len(data),center+radius)
    lines=[]
    for off in range(lo,hi,4):
        w=struct.unpack_from("<I",data,off)[0]
        va=file_to_elfva(off,elf)
        tag=""
        if w in movie_by_va:tag=f"MOVIE_PTR->{movie_by_va[w]}"
        elif w in audio_by_va:tag=f"AT3_PTR->{audio_by_va[w]}"
        mark=">>" if off==center else "  "
        lines.append(
            f"{mark} file=0x{off:08X} elfva={'0x%08X'%va if va is not None else '????????'} "
            f"runtime={'0x%08X'%runtime(va) if va is not None else '??????????'} "
            f"word=0x{w:08X} {tag}"
        )
    return "\n".join(lines)

def main():
    if not BOOT.exists():
        raise RuntimeError(f"BOOT.BIN not found: {BOOT}")
    data=BOOT.read_bytes()
    elf=parse_elf32(data)
    if not elf:
        raise RuntimeError("BOOT.BIN is not parseable ELF32.")

    print("="*76,flush=True)
    print(" Naruto PSP MOV03F - PMF pointer table + AT3 adjacency analysis",flush=True)
    print("="*76,flush=True)
    print(f"BOOT={BOOT}",flush=True)
    print(f"size={len(data)}",flush=True)
    print(f"PSP runtime base=0x{PSP_LOAD_BASE:08X}",flush=True)

    gp_candidates=get_gp(data,elf)
    gp_rows=[]
    for source,gp,off in gp_candidates:
        gp_rows.append({
            "source":source,"gp_elfva":f"0x{gp:08X}",
            "gp_runtime":f"0x{runtime(gp):08X}",
            "source_file_offset":f"0x{off:08X}",
        })
    write_tsv(STAGE/"gp_candidates.tsv",gp_rows)

    # Full path slot targets.
    movie_rows=[]; movie_by_va={}; movie_off_by_name={}
    prefix=b"disc0:/PSP_GAME/USRDIR/movie/"
    for idx,name in enumerate(MOVIES):
        exact=prefix+(name+".pmf").encode("ascii")
        hits=find_all(data,exact)
        if not hits:
            # fallback: infer start from filename occurrence
            fn=(name+".pmf").encode("ascii")
            fh=find_all(data,fn)
            hits=[]
            for x in fh:
                st=x-len(prefix)
                if st>=0 and data[st:x]==prefix:
                    hits.append(st)
        for occ,off in enumerate(hits,1):
            va=file_to_elfva(off,elf)
            movie_rows.append({
                "table_index":idx,"movie":name,"occurrence":occ,
                "slot_file_offset":f"0x{off:08X}",
                "slot_elfva":f"0x{va:08X}" if va is not None else "",
                "slot_runtime":f"0x{runtime(va):08X}" if va is not None else "",
                "slot_text":data[off:off+40].split(b"\0",1)[0].decode("ascii","replace"),
            })
            if occ==1 and va is not None:
                movie_by_va[va]=name
                movie_off_by_name[name]=off
    write_tsv(STAGE/"movie_slot_table.tsv",movie_rows)

    if len(movie_by_va)<20:
        raise RuntimeError(f"Too few PMF slot targets found: {len(movie_by_va)}")

    # Raw pointer xrefs to every movie slot start.
    ptr_rows=[]; ptr_by_off={}
    for va,name in movie_by_va.items():
        for valkind,val in [("ELFVA",va),("RUNTIME",runtime(va))]:
            needle=struct.pack("<I",val)
            for off in find_all(data,needle):
                locva=file_to_elfva(off,elf)
                row={
                    "movie":name,"target_kind":valkind,
                    "movie_slot_elfva":f"0x{va:08X}",
                    "movie_slot_runtime":f"0x{runtime(va):08X}",
                    "pointer_file_offset":f"0x{off:08X}",
                    "pointer_elfva":f"0x{locva:08X}" if locva is not None else "",
                    "pointer_runtime":f"0x{runtime(locva):08X}" if locva is not None else "",
                }
                ptr_rows.append(row)
                ptr_by_off[off]=name
    ptr_rows.sort(key=lambda r:int(r["pointer_file_offset"],16))
    write_tsv(STAGE/"movie_slot_pointer_xrefs.tsv",ptr_rows)

    # AT3 strings + raw pointers.
    audio_rows,audio_by_va=find_ascii_at3(data,elf)
    write_tsv(STAGE/"at3_string_inventory.tsv",audio_rows)
    audio_ptr_rows=[]
    audio_ptr_by_off={}
    for va,token in audio_by_va.items():
        for kind,val in [("ELFVA",va),("RUNTIME",runtime(va))]:
            for off in find_all(data,struct.pack("<I",val)):
                lva=file_to_elfva(off,elf)
                rr={
                    "audio":token,"target_kind":kind,
                    "audio_elfva":f"0x{va:08X}",
                    "audio_runtime":f"0x{runtime(va):08X}",
                    "pointer_file_offset":f"0x{off:08X}",
                    "pointer_elfva":f"0x{lva:08X}" if lva is not None else "",
                    "pointer_runtime":f"0x{runtime(lva):08X}" if lva is not None else "",
                }
                audio_ptr_rows.append(rr)
                audio_ptr_by_off[off]=token
    audio_ptr_rows.sort(key=lambda r:int(r["pointer_file_offset"],16))
    write_tsv(STAGE/"at3_pointer_xrefs.tsv",audio_ptr_rows)

    # Cluster movie pointer xrefs by <= 0x100 gap.
    poffs=sorted(set(int(r["pointer_file_offset"],16) for r in ptr_rows))
    clusters=[]
    cur=[]
    for x in poffs:
        if not cur or x-cur[-1] <= 0x100:
            cur.append(x)
        else:
            clusters.append(cur);cur=[x]
    if cur:clusters.append(cur)

    cluster_rows=[]
    cluster_targets={}
    for ci,c in enumerate(clusters,1):
        lo=min(c);hi=max(c)
        members=[(x,ptr_by_off.get(x,"")) for x in c]
        movie_names=sorted(set(n for _,n in members if n))
        lva=file_to_elfva(lo,elf)
        cluster_rows.append({
            "cluster":ci,"count":len(c),
            "start_file":f"0x{lo:08X}","end_file":f"0x{hi:08X}",
            "span":hi-lo,
            "start_elfva":f"0x{lva:08X}" if lva is not None else "",
            "start_runtime":f"0x{runtime(lva):08X}" if lva is not None else "",
            "movies":",".join(movie_names),
            "member_offsets":",".join(f"0x{x:08X}" for x in c),
        })
        if lva is not None:
            cluster_targets[lva]=f"movie_pointer_cluster_{ci}_base"
    write_tsv(STAGE/"movie_pointer_clusters.tsv",cluster_rows)

    # Neighborhood adjacency: direct AT3 ptr near PMF ptr.
    adjacency=[]
    context_blocks=[]
    for r in ptr_rows:
        poff=int(r["pointer_file_offset"],16)
        pva=file_to_elfva(poff,elf)
        near_audio=[]
        for aoff,token in audio_ptr_by_off.items():
            d=aoff-poff
            if abs(d)<=0x100:
                near_audio.append((abs(d),d,aoff,token))
        near_audio.sort()
        if near_audio:
            for _,d,aoff,token in near_audio[:20]:
                adjacency.append({
                    "movie":r["movie"],
                    "movie_pointer_file":r["pointer_file_offset"],
                    "audio":token,
                    "audio_pointer_file":f"0x{aoff:08X}",
                    "distance_bytes":d,
                    "strength":"VERY_NEAR" if abs(d)<=0x20 else "NEAR",
                })
        context_blocks.append(
            "="*100+"\n"
            f"MOVIE POINTER {r['movie']} at {r['pointer_file_offset']} "
            f"(runtime {r['pointer_runtime']})\n"
            + dump_words(data,poff,elf,movie_by_va,audio_by_va,0x100)
        )
    write_tsv(STAGE/"movie_at3_pointer_adjacency.tsv",adjacency)
    (STAGE/"movie_pointer_context.txt").write_text("\n\n".join(context_blocks),encoding="utf-8-sig")

    # Address targets for code xref scanning: movie slots, pointer record locations,
    # cluster bases, known movie subsystem anchors.
    code_targets={}
    for va,name in movie_by_va.items():
        code_targets[va]=f"movie_slot:{name}"
    for r in ptr_rows:
        off=int(r["pointer_file_offset"],16)
        va=file_to_elfva(off,elf)
        if va is not None:
            code_targets[va]=f"movie_pointer_record:{r['movie']}@{r['pointer_file_offset']}"
    code_targets.update(cluster_targets)

    # Add movie subsystem ASCII anchors.
    for anc in [b"movie_dec",b"adnpspmovie",b"MOVIE"]:
        for i,off in enumerate(find_all(data,anc),1):
            va=file_to_elfva(off,elf)
            if va is not None:
                code_targets[va]=f"anchor:{anc.decode('ascii')}#{i}"

    lui_rows=scan_lui_pairs(data,code_targets,elf)
    write_tsv(STAGE/"code_lui_xrefs.tsv",lui_rows)

    # GP-relative xrefs.
    gp_xrefs=[]
    memops={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw",9:"addiu"}
    for source,gp,gpoff in gp_candidates:
        # Build signed-16 reachable target displacement lookup.
        disp_targets=defaultdict(list)
        for tva,tname in code_targets.items():
            d=(tva-gp)
            if -32768 <= d <= 32767:
                disp_targets[d & 0xffff].append((tva,tname))
        if not disp_targets:
            continue
        for off in range(0,len(data)-4,4):
            w=struct.unpack_from("<I",data,off)[0]
            op=(w>>26)&0x3f; rs=(w>>21)&31; rt=(w>>16)&31; imm=w&0xffff
            if rs!=28 or op not in memops or imm not in disp_targets:
                continue
            iva=file_to_elfva(off,elf)
            for tva,tname in disp_targets[imm]:
                gp_xrefs.append({
                    "gp_source":source,
                    "gp_elfva":f"0x{gp:08X}",
                    "target":tname,
                    "target_elfva":f"0x{tva:08X}",
                    "target_runtime":f"0x{runtime(tva):08X}",
                    "xref_file":f"0x{off:08X}",
                    "xref_elfva":f"0x{iva:08X}" if iva is not None else "",
                    "xref_runtime":f"0x{runtime(iva):08X}" if iva is not None else "",
                    "asm":mips_decode(w,iva),
                })
    write_tsv(STAGE/"gp_relative_xrefs.tsv",gp_xrefs)

    # Context for grounded code xrefs.
    code_ctx=[]
    seen_code=set()
    for r in lui_rows:
        off=int(r["xref_file"],16)
        if off in seen_code:continue
        seen_code.add(off)
        code_ctx.append("="*100+"\n"+f"LUI XREF {r['target']} at {r['xref_file']}\n"+dump_code(data,off,elf,0xC0))
    for r in gp_xrefs:
        off=int(r["xref_file"],16)
        if off in seen_code:continue
        seen_code.add(off)
        code_ctx.append("="*100+"\n"+f"GP XREF {r['target']} at {r['xref_file']}\n"+dump_code(data,off,elf,0xC0))
    (STAGE/"grounded_code_context.txt").write_text("\n\n".join(code_ctx),encoding="utf-8-sig")

    # Summary.
    dm_ptrs=[r for r in ptr_rows if r["movie"].startswith("dm")]
    dm_movies=sorted(set(r["movie"] for r in dm_ptrs))
    direct_pairs=sorted(set((r["movie"],r["audio"]) for r in adjacency))
    summary=[
        "Naruto PSP MOV03F - PMF slot pointer table + AT3 adjacency analysis",
        "="*76,"",
        f"BOOT size={len(data)}",
        f"PSP runtime base=0x{PSP_LOAD_BASE:08X}",
        f"ELF entry=0x{elf['entry']:08X}",
        f"Runtime entry=0x{runtime(elf['entry']):08X}",
        f"GP candidates={len(gp_candidates)}",
        f"PMF full-path slots found={len(movie_by_va)}/{len(MOVIES)}",
        f"PMF slot raw pointer xrefs={len(ptr_rows)}",
        f"DM movies with raw pointer xrefs={len(dm_movies)}/10: {','.join(dm_movies) if dm_movies else '(none)'}",
        f"PMF pointer clusters={len(clusters)}",
        f"AT3 strings found={len(audio_rows)}",
        f"AT3 raw pointer xrefs={len(audio_ptr_rows)}",
        f"PMF<->AT3 nearby pointer rows={len(adjacency)}",
        f"Unique direct-neighborhood movie/audio pairs={len(direct_pairs)}",
        f"LUI address xrefs={len(lui_rows)}",
        f"GP-relative xrefs={len(gp_xrefs)}",
        "",
        "Key files:",
        "- movie_slot_pointer_xrefs.tsv: all grounded pointers to complete PMF path slots.",
        "- movie_pointer_clusters.tsv: secondary data-table candidates.",
        "- movie_at3_pointer_adjacency.tsv: AT3 pointers within +/-0x100 of PMF pointer records.",
        "- gp_relative_xrefs.tsv / code_lui_xrefs.tsv: grounded executable code references.",
        "- movie_pointer_context.txt: annotated words around every PMF pointer record.",
        "- grounded_code_context.txt: MIPS context around code xrefs.",
        "",
        "No adjacency entry by itself proves synchronized playback; a direct mapping",
        "requires a coherent record/table structure or code path using both fields.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0

def dump_code(data:bytes, center:int, elf, radius=0xC0):
    lo=max(0,(center-radius)&~3);hi=min(len(data),(center+radius+3)&~3)
    lines=[]
    for off in range(lo,hi,4):
        w=struct.unpack_from("<I",data,off)[0]
        va=file_to_elfva(off,elf)
        mark=">>" if off==center else "  "
        lines.append(
            f"{mark} file=0x{off:08X} elfva={'0x%08X'%va if va is not None else '????????'} "
            f"runtime={'0x%08X'%runtime(va) if va is not None else '??????????'} "
            f"{w:08X}  {mips_decode(w,va)}"
        )
    return "\n".join(lines)

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
