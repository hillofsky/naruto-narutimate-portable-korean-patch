#!/usr/bin/env python3
# Naruto PSP MOV03J - movie/voice callgraph + PMF stream verification
#
# Goals:
#  1) Verify all KR dm001..dm010 PMFs at MPEG-PS packet level:
#       video PES (0xE0..0xEF), private stream 1 (0xBD), other stream IDs.
#     This independently tests whether DM PMFs actually contain audio.
#  2) Analyze the function called immediately after movie_init in group14:
#       0x0021FA24
#     and movie group cleanup:
#       0x0021F88C
#  3) Analyze the ordinary voice path builder around:
#       0x0022090C
#     which references:
#       "%s%s.at3"
#       "disc0:/PSP_GAME/USRDIR/sound/voice/"
#  4) Build direct/reverse JAL call chains and determine whether movie playback
#     statically reaches the ordinary AT3 voice loader.
#  5) Trace explicit g_d27_* strings/pointer tables as a separate lead.
#
# No gameplay, no patching.

from __future__ import annotations
import csv, re, struct, sys, traceback
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR = ROOT / "kr_extracted"
BOOT = KR / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
MOVIE_DIR = KR / "PSP_GAME" / "USRDIR" / "movie"
STAGE = ROOT / "analysis" / "mov" / "mov03j_movie_voice_callgraph"
STAGE.mkdir(parents=True, exist_ok=True)

PSP_BASE = 0x08804000

KNOWN = {
    0x0029F4B0: "movie_init",
    0x0021FA24: "post_movie_start_call",
    0x0021F88C: "movie_group_finalize_or_release",
    0x0022090C: "voice_path_builder_candidate",
    0x00220988: "voice_path_helper_candidate",
    0x0001BB10: "format_string_candidate",
    0x00060058: "selector_resource_mark",
    0x00060460: "selector_resource_check",
}

DM_NAMES = [f"dm{i:03d}" for i in range(1,11)]
CONTROL_NAMES = ["da101","dk101","dk102"]

REG = [
    "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
    "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
    "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
    "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra",
]

def sx16(x):
    return x - 0x10000 if x & 0x8000 else x

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
    ph=[]
    for i in range(v[9]):
        o=v[4]+i*v[8]
        if o+32>len(data):
            break
        x=struct.unpack_from(endian+"IIIIIIII",data,o)
        ph.append(dict(index=i,type=x[0],offset=x[1],vaddr=x[2],paddr=x[3],
                       filesz=x[4],memsz=x[5],flags=x[6],align=x[7]))
    return dict(endian=endian,entry=v[3],ph=ph)

def va2off(va:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["vaddr"] <= va < p["vaddr"]+p["filesz"]:
            return p["offset"]+(va-p["vaddr"])
    return None

def off2va(off:int, elf):
    for p in elf["ph"]:
        if p["type"]==1 and p["offset"] <= off < p["offset"]+p["filesz"]:
            return p["vaddr"]+(off-p["offset"])
    return None

def runtime(va):
    return None if va is None else PSP_BASE+va

def mips(word:int, pc=None):
    op=(word>>26)&63; rs=(word>>21)&31; rt=(word>>16)&31; rd=(word>>11)&31
    sa=(word>>6)&31; fn=word&63; imm=word&0xffff
    if word==0:return "nop"
    if op==0:
        d={
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
        return d.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        tgt=((pc+4)&0xF0000000)|((word&0x03ffffff)<<2) if pc is not None else ((word&0x03ffffff)<<2)
        return ("j" if op==2 else "jal")+f" 0x{tgt:08X}"
    if op==4:return f"beq {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==5:return f"bne {REG[rs]},{REG[rt]},{sx16(imm)}"
    if op==9:return f"addiu {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0a:return f"slti {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0b:return f"sltiu {REG[rt]},{REG[rs]},{sx16(imm)}"
    if op==0x0c:return f"andi {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0d:return f"ori {REG[rt]},{REG[rs]},0x{imm:04X}"
    if op==0x0f:return f"lui {REG[rt]},0x{imm:04X}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem:return f"{mem[op]} {REG[rt]},{sx16(imm)}({REG[rs]})"
    return f"op=0x{op:X} word=0x{word:08X}"

def jal_target(word:int, pc:int):
    if (word>>26)!=3:
        return None
    return ((pc+4)&0xF0000000)|((word&0x03ffffff)<<2)

def is_jr_ra(word:int):
    return word == 0x03E00008

def is_stack_prologue(word:int):
    # addiu sp,sp,negative
    op=(word>>26)&63; rs=(word>>21)&31; rt=(word>>16)&31; imm=word&0xffff
    return op==9 and rs==29 and rt==29 and sx16(imm)<0

def infer_function_start(data:bytes, elf, callsite_va:int, max_back=0x800):
    off=va2off(callsite_va,elf)
    if off is None:
        return None
    lo=max(0,off-max_back)
    candidates=[]
    for o in range(off&~3,lo-1,-4):
        w=struct.unpack_from("<I",data,o)[0]
        if not is_stack_prologue(w):
            continue
        # Require a store of RA to SP in the next 8 instructions.
        ok=False
        for j in range(1,9):
            q=o+j*4
            if q+4>len(data):break
            w2=struct.unpack_from("<I",data,q)[0]
            op=(w2>>26)&63;rs=(w2>>21)&31;rt=(w2>>16)&31
            if op==0x2B and rs==29 and rt==31:
                ok=True;break
        if ok:
            return off2va(o,elf)
    return None

def function_extent(data:bytes, elf, start_va:int, max_len=0x1800):
    off=va2off(start_va,elf)
    if off is None:
        return None,None
    # Stop after first jr ra + delay slot, but not before 8 bytes.
    end=min(len(data),off+max_len)
    for o in range(off+4,end,4):
        w=struct.unpack_from("<I",data,o)[0]
        if is_jr_ra(w):
            return off,min(len(data),o+8)
    return off,end

def function_calls(data:bytes, elf, start_va:int):
    a,b=function_extent(data,elf,start_va)
    if a is None:
        return []
    rows=[]
    for o in range(a,b,4):
        va=off2va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        tgt=jal_target(w,va)
        if tgt is not None:
            rows.append((va,tgt))
    return rows

def all_jal_edges(data:bytes, elf):
    edges=[]
    for o in range(0,len(data)-4,4):
        va=off2va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        tgt=jal_target(w,va)
        if tgt is None:continue
        caller=infer_function_start(data,elf,va)
        edges.append((caller,va,tgt))
    return edges

def dump_code(data:bytes, elf, start_va:int, radius_before=0x20, after=0x500):
    o=va2off(start_va,elf)
    if o is None:return "UNMAPPED\n"
    lo=max(0,(o-radius_before)&~3); hi=min(len(data),(o+after)&~3)
    out=[]
    for p in range(lo,hi,4):
        va=off2va(p,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,p)[0]
        mark=">>" if va==start_va else "  "
        out.append(f"{mark} file=0x{p:08X} elfva=0x{va:08X} runtime=0x{runtime(va):08X} {w:08X}  {mips(w,va)}")
        if p>o and is_jr_ra(w) and p+8<=hi:
            # Include delay slot then stop.
            q=p+4
            if q+4<=len(data):
                qva=off2va(q,elf)
                qw=struct.unpack_from("<I",data,q)[0]
                if qva is not None:
                    out.append(f"   file=0x{q:08X} elfva=0x{qva:08X} runtime=0x{runtime(qva):08X} {qw:08X}  {mips(qw,qva)}")
            break
    return "\n".join(out)

def find_all(data:bytes, needle:bytes):
    out=[];p=0
    while True:
        p=data.find(needle,p)
        if p<0:break
        out.append(p);p+=1
    return out

def scan_lui_pairs(data:bytes, elf, targets:dict[int,str]):
    rows=[]
    for off in range(0,len(data)-28,4):
        w=struct.unpack_from("<I",data,off)[0]
        if (w>>26)!=0x0F:continue
        r=(w>>16)&31; hi=w&0xffff
        if r==0:continue
        for j in range(1,7):
            o2=off+j*4; w2=struct.unpack_from("<I",data,o2)[0]
            op=(w2>>26)&63; rs=(w2>>21)&31; rt=(w2>>16)&31; lo=w2&0xffff
            if rs!=r or rt!=r or op not in (9,0x0D):
                continue
            val=(((hi<<16)+sx16(lo)) if op==9 else ((hi<<16)|lo)) & 0xffffffff
            if val in targets:
                va=off2va(off,elf)
                rows.append(dict(
                    target=targets[val],target_elfva=f"0x{val:08X}",
                    xref_file=f"0x{off:08X}",
                    xref_elfva=f"0x{va:08X}" if va is not None else "",
                    xref_runtime=f"0x{runtime(va):08X}" if va is not None else "",
                    register=REG[r],gap=j,
                ))
            break
    return rows

def parse_ps_packet_streams(path:Path):
    data=path.read_bytes()
    # PMF payload normally starts near 0x800. Ground to first pack header.
    pos=data.find(b"\x00\x00\x01\xBA",0x100)
    if pos<0:
        return dict(ok=False,error="no MPEG pack header",counts=Counter(),sub=Counter(),packets=0,start=-1)
    counts=Counter();sub=Counter();packets=0;errors=0
    n=len(data)
    while pos+4<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01\xBA",pos+1)
            if nxt<0:break
            pos=nxt
            continue
        sid=data[pos+3]
        counts[sid]+=1;packets+=1
        if sid==0xBA:
            if pos+14>n:break
            stuffing=data[pos+13]&0x07
            pos += 14+stuffing
            continue
        if sid==0xB9:
            pos += 4
            continue
        if pos+6>n:break
        plen=(data[pos+4]<<8)|data[pos+5]
        if plen==0:
            # Rare/unbounded PES. Jump to next pack header rather than scanning
            # arbitrary H.264 payload start codes.
            nxt=data.find(b"\x00\x00\x01\xBA",pos+6)
            if nxt<0:break
            pos=nxt
            continue
        packet_end=pos+6+plen
        if packet_end>n:
            errors+=1;break
        if sid==0xBD:
            # MPEG2 PES payload begins after optional PES header.
            payload=pos+6
            if payload+3<=packet_end and (data[payload]&0xC0)==0x80:
                hlen=data[payload+2]
                payload=payload+3+hlen
            if payload<packet_end:
                sub[data[payload]]+=1
        pos=packet_end
    return dict(ok=True,error="",counts=counts,sub=sub,packets=packets,start=data.find(b"\x00\x00\x01\xBA",0x100),errors=errors)

def stream_label(sid):
    if 0xE0<=sid<=0xEF:return "video"
    if 0xC0<=sid<=0xDF:return "mpeg_audio"
    return {
        0xBA:"pack",0xBB:"system_header",0xBC:"program_stream_map",
        0xBD:"private_stream_1",0xBE:"padding",0xBF:"private_stream_2",
    }.get(sid,f"sid_{sid:02X}")

def main():
    if not BOOT.exists():raise RuntimeError(f"Missing {BOOT}")
    if not MOVIE_DIR.exists():raise RuntimeError(f"Missing {MOVIE_DIR}")
    data=BOOT.read_bytes(); elf=parse_elf(data)

    print("="*80,flush=True)
    print(" Naruto PSP MOV03J - movie/voice callgraph + PMF stream verification",flush=True)
    print("="*80,flush=True)

    # ------------------------------------------------------------------
    # A) PMF packet-level stream inventory.
    # ------------------------------------------------------------------
    pmf_rows=[];sid_rows=[]
    for name in DM_NAMES+CONTROL_NAMES:
        p=MOVIE_DIR/(name+".pmf")
        if not p.exists():
            pmf_rows.append(dict(movie=name,status="MISSING"))
            continue
        r=parse_ps_packet_streams(p)
        video=sum(v for k,v in r["counts"].items() if 0xE0<=k<=0xEF)
        private1=r["counts"].get(0xBD,0)
        mpa=sum(v for k,v in r["counts"].items() if 0xC0<=k<=0xDF)
        pmf_rows.append(dict(
            movie=name,status="OK" if r["ok"] else "FAILED",
            bytes=p.stat().st_size,first_pack_offset=f"0x{r['start']:X}" if r["start"]>=0 else "",
            parsed_packets=r["packets"],parse_errors=r.get("errors",0),
            video_pes=video,private_stream_1_pes=private1,mpeg_audio_pes=mpa,
            has_any_audio_pes="YES" if (private1 or mpa) else "NO",
            private_substreams=",".join(f"0x{k:02X}:{v}" for k,v in sorted(r["sub"].items())),
            error=r["error"],
        ))
        for sid,count in sorted(r["counts"].items()):
            sid_rows.append(dict(movie=name,stream_id=f"0x{sid:02X}",
                                 label=stream_label(sid),packet_count=count))
        print(f"PMF {name}: video={video} private1={private1} mpeg_audio={mpa}",flush=True)
    write_tsv(STAGE/"pmf_stream_inventory.tsv",pmf_rows)
    write_tsv(STAGE/"pmf_stream_id_counts.tsv",sid_rows)

    # ------------------------------------------------------------------
    # B) Known function bodies/callers.
    # ------------------------------------------------------------------
    edges=all_jal_edges(data,elf)
    callers_by_target=defaultdict(list)
    children_by_func=defaultdict(list)
    for caller,site,tgt in edges:
        callers_by_target[tgt].append((caller,site))
        if caller is not None:
            children_by_func[caller].append((site,tgt))

    known_rows=[];blocks=[]
    for va,name in KNOWN.items():
        calls=function_calls(data,elf,va)
        known_rows.append(dict(
            function=name,elfva=f"0x{va:08X}",runtime=f"0x{runtime(va):08X}",
            direct_call_count=len(calls),
            callers=len(callers_by_target.get(va,[])),
            direct_targets=",".join(f"0x{t:08X}" for _,t in calls),
        ))
        blocks.append("="*104+"\n"+
                      f"{name} ELFVA=0x{va:08X} runtime=0x{runtime(va):08X}\n"+
                      dump_code(data,elf,va,0x20,0x900))
    write_tsv(STAGE/"known_function_summary.tsv",known_rows)
    (STAGE/"known_function_context.txt").write_text("\n\n".join(blocks),encoding="utf-8-sig")

    caller_rows=[]
    for va,name in KNOWN.items():
        for caller,site in callers_by_target.get(va,[]):
            caller_rows.append(dict(
                target=name,target_elfva=f"0x{va:08X}",
                caller_function_elfva=f"0x{caller:08X}" if caller is not None else "",
                callsite_elfva=f"0x{site:08X}",
                callsite_runtime=f"0x{runtime(site):08X}",
            ))
    write_tsv(STAGE/"known_function_callers.tsv",caller_rows)

    # ------------------------------------------------------------------
    # C) Forward graph from post-movie function and reverse graph from voice builder.
    # ------------------------------------------------------------------
    forward=[]
    start=0x0021FA24
    q=deque([(start,0,[start])]); seen={(start,0)}
    seen_funcs=set([start])
    max_depth=4
    while q:
        fn,depth,path=q.popleft()
        if depth>=max_depth:continue
        for site,tgt in function_calls(data,elf,fn):
            forward.append(dict(
                depth=depth+1,
                from_function=f"0x{fn:08X}",
                callsite=f"0x{site:08X}",
                to_function=f"0x{tgt:08X}",
                to_known=KNOWN.get(tgt,""),
                path=" -> ".join(f"0x{x:08X}" for x in path+[tgt]),
            ))
            if tgt not in seen_funcs and va2off(tgt,elf) is not None:
                seen_funcs.add(tgt)
                q.append((tgt,depth+1,path+[tgt]))
    write_tsv(STAGE/"post_movie_forward_callgraph.tsv",forward)

    reverse=[]
    voice=0x0022090C
    rq=deque([(voice,0,[voice])])
    rseen={voice}
    while rq:
        tgt,depth,path=rq.popleft()
        if depth>=5:continue
        for caller,site in callers_by_target.get(tgt,[]):
            reverse.append(dict(
                depth=depth+1,target=f"0x{tgt:08X}",
                callsite=f"0x{site:08X}",
                caller_function=f"0x{caller:08X}" if caller is not None else "",
                caller_known=KNOWN.get(caller,"") if caller is not None else "",
                path=" <- ".join(f"0x{x:08X}" for x in path+([caller] if caller is not None else [])),
            ))
            if caller is not None and caller not in rseen:
                rseen.add(caller);rq.append((caller,depth+1,path+[caller]))
    write_tsv(STAGE/"voice_builder_reverse_callgraph.tsv",reverse)

    # Detect actual intersection.
    forward_targets={int(r["to_function"],16) for r in forward}
    reverse_callers={int(r["caller_function"],16) for r in reverse if r["caller_function"]}
    intersections=sorted(forward_targets & reverse_callers)
    int_rows=[dict(function=f"0x{x:08X}",runtime=f"0x{runtime(x):08X}",
                   known=KNOWN.get(x,"")) for x in intersections]
    write_tsv(STAGE/"movie_voice_callgraph_intersections.tsv",int_rows)

    # ------------------------------------------------------------------
    # D) Voice path strings and g_d27 explicit table investigation.
    # ------------------------------------------------------------------
    string_targets={}
    string_rows=[]
    for s in [b"%s%s.at3",b"disc0:/PSP_GAME/USRDIR/sound/voice/",
              b"g_d27_00",b"g_d27_04",b"g_d27_01",b"g_d27_03",b"g_d27_07",b"g_d27_08"]:
        for occ,off in enumerate(find_all(data,s),1):
            va=off2va(off,elf)
            string_rows.append(dict(
                text=s.decode("ascii"),occurrence=occ,
                file_offset=f"0x{off:08X}",
                elfva=f"0x{va:08X}" if va is not None else "",
                runtime=f"0x{runtime(va):08X}" if va is not None else "",
            ))
            if va is not None:
                string_targets[va]=s.decode("ascii")
    write_tsv(STAGE/"focused_string_inventory.tsv",string_rows)

    string_xrefs=scan_lui_pairs(data,elf,string_targets)
    write_tsv(STAGE/"focused_string_code_xrefs.tsv",string_xrefs)

    # Raw pointers to strings.
    raw=[]
    pointer_locations={}
    for va,label in string_targets.items():
        for kind,val in [("ELFVA",va),("RUNTIME",runtime(va))]:
            needle=struct.pack("<I",val)
            for off in find_all(data,needle):
                pva=off2va(off,elf)
                raw.append(dict(
                    string=label,target_kind=kind,target=f"0x{val:08X}",
                    pointer_file=f"0x{off:08X}",
                    pointer_elfva=f"0x{pva:08X}" if pva is not None else "",
                    pointer_runtime=f"0x{runtime(pva):08X}" if pva is not None else "",
                ))
                if pva is not None:
                    pointer_locations[pva]=f"ptr_to:{label}"
    write_tsv(STAGE/"focused_string_raw_pointers.tsv",raw)

    ptr_xrefs=scan_lui_pairs(data,elf,pointer_locations)
    write_tsv(STAGE/"focused_pointer_table_code_xrefs.tsv",ptr_xrefs)

    # Compact contexts around pointer-table xrefs.
    fctx=[]
    for r in ptr_xrefs+string_xrefs:
        if not r.get("xref_elfva"):continue
        va=int(r["xref_elfva"],16)
        fctx.append("="*100+"\n"+
                    f"{r['target']} @ {r['xref_elfva']}\n"+
                    dump_code(data,elf,va,0x40,0x280))
    (STAGE/"focused_xref_context.txt").write_text("\n\n".join(fctx),encoding="utf-8-sig")

    # ------------------------------------------------------------------
    # Summary.
    # ------------------------------------------------------------------
    dm_rows=[r for r in pmf_rows if r.get("movie","").startswith("dm") and r.get("status")=="OK"]
    dm_with_audio=[r["movie"] for r in dm_rows if r.get("has_any_audio_pes")=="YES"]
    voice_direct_callers=callers_by_target.get(voice,[])
    post_direct=function_calls(data,elf,start)
    reaches_voice=(
        voice in forward_targets or
        bool(intersections)
    )

    summary=[
        "Naruto PSP MOV03J - movie/voice callgraph + PMF stream verification",
        "="*80,"",
        f"DM PMFs parsed={len(dm_rows)}/10",
        f"DM PMFs containing private/MPEG audio PES={len(dm_with_audio)}/10",
        f"DM audio-stream movies={','.join(dm_with_audio) if dm_with_audio else '(none)'}",
        "",
        f"post_movie_start 0x0021FA24 direct calls={len(post_direct)}",
        f"voice_path_builder 0x0022090C direct callers={len(voice_direct_callers)}",
        f"forward movie graph rows depth<=4={len(forward)}",
        f"reverse voice graph rows depth<=5={len(reverse)}",
        f"movie/voice callgraph intersections={len(intersections)}",
        f"static movie path reaches ordinary voice builder={'YES' if reaches_voice else 'NO'}",
        "",
        f"Focused voice/g_d strings={len(string_rows)}",
        f"Focused raw string pointers={len(raw)}",
        f"Focused pointer-table code xrefs={len(ptr_xrefs)}",
        "",
        "Interpretation:",
        "- 0 private/MPEG audio PES across dm001..dm010 is packet-level evidence",
        "  that the PMFs themselves are video-only.",
        "- A callgraph intersection would support shared external-audio code.",
        "- No intersection means the ordinary sound/voice AT3 loader is not",
        "  statically reached from the immediate post-movie path within this depth.",
        "- g_d27_* remains a separate static lead; raw-pointer/table xrefs are",
        "  reported without assuming it belongs to DM playback.",
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
