#!/usr/bin/env python3
# Naruto PSP MOV03I - DM resource predicate + full AT3 duration/counterpart scan
#
# Grounded before this stage:
#   group14 selector 0..9 -> dm001..dm010 exactly.
#   selector BSS is a runtime filtered list built by predicate 0x0005F8C0
#   with arguments (global, group=14, selector=0..9).
#
# This stage does NOT guess that an AT3 belongs to a movie.
# It produces independent evidence:
#   - resource predicate/check MIPS code and callers
#   - all BOOT audio-related ASCII anchors + MIPS xrefs
#   - all KR AT3 durations (RIFF parser, ffprobe fallback)
#   - US same/localized counterpart candidates
#   - individual AT3 durations close to each DM duration
#   - grouped-bank total durations close to each DM duration
#
# No gameplay, no patching.

from __future__ import annotations
import csv, math, re, struct, subprocess, sys, traceback, hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR = ROOT / "kr_extracted"
US = ROOT / "us_extracted"
BOOT = KR / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
SOUND_KR = KR / "PSP_GAME" / "USRDIR" / "sound"
SOUND_US = US / "PSP_GAME" / "USRDIR" / "sound"
STAGE = ROOT / "analysis" / "mov" / "mov03i_dm_audio_static"
STAGE.mkdir(parents=True,exist_ok=True)

PSP_BASE=0x08804000

DM_DURATIONS = {
    "dm001":53.620,
    "dm002":36.770,
    "dm003":66.600,
    "dm004":72.039,
    "dm005":66.366,
    "dm006":58.358,
    "dm007":59.826,
    "dm008":49.550,
    "dm009":59.960,
    "dm010":119.486,
}

TARGET_FUNCS = {
    0x0005F8C0:"selector_resource_predicate",
    0x00060460:"selector_resource_check_or_state",
    0x00060058:"selector_resource_load_or_mark",
    0x0029F4B0:"movie_init",
}

AUDIO_ANCHORS = [
    b".at3", b"sound/", b"sound\\", b"voice/", b"voice\\",
    b"g_d", b"s_a", b"s_b", b"bgm", b"BGM", b"SE",
    b"%02d", b"%03d",
]

REG=[
 "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
 "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
 "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
 "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sx16(x): return x-0x10000 if x&0x8000 else x

def write_tsv(path,rows,fields=None):
    path=Path(path)
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields: fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def parse_elf(data):
    if not data.startswith(b"\x7fELF") or data[4]!=1:
        raise RuntimeError("BOOT.BIN is not ELF32")
    e="<" if data[5]==1 else ">"
    v=struct.unpack_from(e+"HHIIIIIHHHHHH",data,16)
    ph=[]
    for i in range(v[9]):
        o=v[4]+i*v[8]
        if o+32>len(data):break
        x=struct.unpack_from(e+"IIIIIIII",data,o)
        ph.append(dict(index=i,type=x[0],offset=x[1],vaddr=x[2],paddr=x[3],
                       filesz=x[4],memsz=x[5],flags=x[6],align=x[7]))
    return dict(endian=e,entry=v[3],ph=ph)

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

def rt(va): return PSP_BASE+va if va is not None else None

def mips(word,pc=None):
    op=(word>>26)&63;rs=(word>>21)&31;rt0=(word>>16)&31;rd=(word>>11)&31
    sa=(word>>6)&31;fn=word&63;imm=word&0xffff
    if word==0:return "nop"
    if op==0:
        d={0x00:f"sll {REG[rd]},{REG[rt0]},{sa}",0x02:f"srl {REG[rd]},{REG[rt0]},{sa}",
           0x08:f"jr {REG[rs]}",0x09:f"jalr {REG[rd]},{REG[rs]}",
           0x21:f"addu {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x23:f"subu {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x24:f"and {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x25:f"or {REG[rd]},{REG[rs]},{REG[rt0]}",
           0x2a:f"slt {REG[rd]},{REG[rs]},{REG[rt0]}"}
        return d.get(fn,f"SPECIAL fn=0x{fn:X}")
    if op in (2,3):
        tgt=((pc+4)&0xF0000000)|((word&0x03ffffff)<<2) if pc is not None else ((word&0x03ffffff)<<2)
        return ("j" if op==2 else "jal")+f" 0x{tgt:08X}"
    if op==4:return f"beq {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==5:return f"bne {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==6:return f"blez {REG[rs]},{sx16(imm)}"
    if op==7:return f"bgtz {REG[rs]},{sx16(imm)}"
    if op==9:return f"addiu {REG[rt0]},{REG[rs]},{sx16(imm)}"
    if op==0x0A:return f"slti {REG[rt0]},{REG[rs]},{sx16(imm)}"
    if op==0x0B:return f"sltiu {REG[rt0]},{REG[rs]},{sx16(imm)}"
    if op==0x0C:return f"andi {REG[rt0]},{REG[rs]},0x{imm:04X}"
    if op==0x0D:return f"ori {REG[rt0]},{REG[rs]},0x{imm:04X}"
    if op==0x0F:return f"lui {REG[rt0]},0x{imm:04X}"
    if op==0x14:return f"beql {REG[rs]},{REG[rt0]},{sx16(imm)}"
    if op==0x15:return f"bnel {REG[rs]},{REG[rt0]},{sx16(imm)}"
    mem={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2b:"sw"}
    if op in mem:return f"{mem[op]} {REG[rt0]},{sx16(imm)}({REG[rs]})"
    return f"op=0x{op:X} word=0x{word:08X}"

def dump_code(data,elf,center_va,radius=0x240):
    c=va2off(center_va,elf)
    if c is None:return "UNMAPPED\n"
    lo=max(0,(c-radius)&~3);hi=min(len(data),(c+radius)&~3)
    out=[]
    for o in range(lo,hi,4):
        va=off2va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        mark=">>" if va==center_va else "  "
        out.append(f"{mark} file=0x{o:08X} elfva=0x{va:08X} runtime=0x{rt(va):08X} {w:08X}  {mips(w,va)}")
    return "\n".join(out)

def jal_callers(data,elf,target):
    rows=[]
    for o in range(0,len(data)-4,4):
        va=off2va(o,elf)
        if va is None:continue
        w=struct.unpack_from("<I",data,o)[0]
        if (w>>26)!=3:continue
        tgt=((va+4)&0xF0000000)|((w&0x03ffffff)<<2)
        if tgt==target:rows.append((o,va))
    return rows

def find_all(data,needle):
    out=[];p=0
    while True:
        p=data.find(needle,p)
        if p<0:break
        out.append(p);p+=1
    return out

def scan_lui_xrefs(data,elf,target_va,label):
    rows=[]
    for off in range(0,len(data)-28,4):
        w=struct.unpack_from("<I",data,off)[0]
        if (w>>26)!=0x0F:continue
        r=(w>>16)&31;hi=w&0xffff
        if r==0:continue
        for j in range(1,7):
            o2=off+j*4;w2=struct.unpack_from("<I",data,o2)[0]
            op=(w2>>26)&63;rs=(w2>>21)&31;rt0=(w2>>16)&31;lo=w2&0xffff
            if rs!=r or rt0!=r or op not in (9,0x0D):continue
            val=(((hi<<16)+sx16(lo)) if op==9 else ((hi<<16)|lo))&0xffffffff
            if val==target_va:
                va=off2va(off,elf)
                rows.append(dict(anchor=label,anchor_elfva=f"0x{target_va:08X}",
                                 xref_file=f"0x{off:08X}",
                                 xref_elfva=f"0x{va:08X}" if va is not None else "",
                                 xref_runtime=f"0x{rt(va):08X}" if va is not None else "",
                                 register=REG[r],gap=j))
            break
    return rows

def riff_at3_info(path:Path):
    try:
        b=path.read_bytes()
    except Exception:
        return None
    if len(b)<12 or b[:4]!=b"RIFF" or b[8:12]!=b"WAVE":
        return None
    pos=12;fmt=None;fact_samples=None;data_size=None
    while pos+8<=len(b):
        cid=b[pos:pos+4]
        sz=struct.unpack_from("<I",b,pos+4)[0]
        d0=pos+8;d1=min(len(b),d0+sz)
        chunk=b[d0:d1]
        if cid==b"fmt " and len(chunk)>=16:
            tag,channels,rate,avg,align,bits=struct.unpack_from("<HHIIHH",chunk,0)
            fmt=(tag,channels,rate,avg,align,bits)
        elif cid==b"fact" and len(chunk)>=4:
            fact_samples=struct.unpack_from("<I",chunk,0)[0]
        elif cid==b"data":
            data_size=sz
        pos=d0+sz+(sz&1)
    if not fmt:return None
    tag,channels,rate,avg,align,bits=fmt
    duration=None;method=""
    if fact_samples and rate:
        duration=fact_samples/rate;method="RIFF_FACT"
    elif data_size is not None and avg:
        duration=data_size/avg;method="RIFF_AVG_BPS"
    return dict(format_tag=tag,channels=channels,sample_rate=rate,avg_bytes_per_sec=avg,
                block_align=align,bits=bits,fact_samples=fact_samples or "",
                data_size=data_size if data_size is not None else "",
                duration=duration,method=method)

def find_ffprobe():
    for p in [Path(r"LOCAL_PATH"),Path(r"LOCAL_PATH")]:
        if p.exists():return p
    return None

def ffprobe_duration(path,exe):
    if exe is None:return None
    try:
        cp=subprocess.run([str(exe),"-v","error","-show_entries","format=duration",
                           "-of","default=nw=1:nk=1",str(path)],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding="utf-8",errors="replace",timeout=10)
        s=cp.stdout.strip()
        return float(s) if s else None
    except Exception:return None

def bank_key(stem):
    s=stem.lower()
    m=re.match(r"^(.+?)[_-](\d+)(?:[a-z])?$",s)
    if m:return m.group(1)
    return s

def rel_lower(p,base):
    try:return str(p.relative_to(base)).replace("\\","/").lower()
    except:return str(p).replace("\\","/").lower()

def main():
    if not BOOT.exists():raise RuntimeError(f"Missing {BOOT}")
    if not SOUND_KR.exists():raise RuntimeError(f"Missing {SOUND_KR}")
    data=BOOT.read_bytes();elf=parse_elf(data)

    print("="*78,flush=True)
    print(" Naruto PSP MOV03I - DM resource predicate + full AT3 static scan",flush=True)
    print("="*78,flush=True)

    # 1) Function bodies + callers.
    callrows=[];blocks=[]
    for va,name in TARGET_FUNCS.items():
        cs=jal_callers(data,elf,va)
        for o,cva in cs:
            callrows.append(dict(function=name,target_elfva=f"0x{va:08X}",
                                 target_runtime=f"0x{rt(va):08X}",
                                 caller_file=f"0x{o:08X}",
                                 caller_elfva=f"0x{cva:08X}",
                                 caller_runtime=f"0x{rt(cva):08X}"))
        blocks.append("="*100+"\n"+
                      f"{name} ELFVA=0x{va:08X} runtime=0x{rt(va):08X} callers={len(cs)}\n"+
                      dump_code(data,elf,va,0x300))
    write_tsv(STAGE/"resource_function_callers.tsv",callrows)
    (STAGE/"resource_function_context.txt").write_text("\n\n".join(blocks),encoding="utf-8-sig")

    # 2) Audio-related strings and code xrefs.
    anchorrows=[];xrefrows=[];actx=[]
    seen_offsets=set()
    for needle in AUDIO_ANCHORS:
        for off in find_all(data,needle):
            # Expand to containing printable string.
            lo=off
            while lo>0 and 32<=data[lo-1]<=126:lo-=1
            hi=off
            while hi<len(data) and 32<=data[hi]<=126:hi+=1
            txt=data[lo:hi].decode("ascii","replace")
            key=(lo,txt)
            if key in seen_offsets:continue
            seen_offsets.add(key)
            va=off2va(lo,elf)
            anchorrows.append(dict(anchor=needle.decode("ascii","replace"),
                                   text=txt,file_offset=f"0x{lo:08X}",
                                   elfva=f"0x{va:08X}" if va is not None else "",
                                   runtime=f"0x{rt(va):08X}" if va is not None else ""))
            if va is not None:
                xs=scan_lui_xrefs(data,elf,va,txt[:120])
                xrefrows.extend(xs)
    write_tsv(STAGE/"boot_audio_string_anchors.tsv",anchorrows)
    write_tsv(STAGE/"boot_audio_string_xrefs.tsv",xrefrows)
    for r in xrefrows:
        o=int(r["xref_file"],16)
        va=off2va(o,elf)
        actx.append("="*100+"\n"+f"ANCHOR XREF {r['anchor']} at {r['xref_file']}\n"+dump_code(data,elf,va,0x180))
    (STAGE/"boot_audio_xref_context.txt").write_text("\n\n".join(actx),encoding="utf-8-sig")

    # 3) All KR AT3 duration inventory.
    ffprobe=find_ffprobe()
    at3s=sorted(SOUND_KR.rglob("*.at3"))
    inv=[]
    unresolved=[]
    for i,p in enumerate(at3s,1):
        info=riff_at3_info(p)
        dur=None;method=""
        if info and info["duration"] is not None and 0 < info["duration"] < 3600:
            dur=info["duration"];method=info["method"]
        else:
            dur=ffprobe_duration(p,ffprobe);method="FFPROBE" if dur is not None else ""
        if dur is None:unresolved.append(p)
        stem=p.stem.lower()
        inv.append(dict(
            relative=rel_lower(p,SOUND_KR),
            file=p.name,stem=stem,bank=bank_key(stem),
            bytes=p.stat().st_size,
            duration_sec=f"{dur:.6f}" if dur is not None else "",
            duration_method=method,
            sample_rate=info["sample_rate"] if info else "",
            channels=info["channels"] if info else "",
            avg_bytes_per_sec=info["avg_bytes_per_sec"] if info else "",
        ))
        if i%250==0:
            print(f"AT3 duration scan {i}/{len(at3s)}",flush=True)
    write_tsv(STAGE/"all_kr_at3_durations.tsv",inv)

    # 4) Individual duration matches to DM, conservative ±2.0 sec and ranked.
    ind=[]
    for dm,dd in DM_DURATIONS.items():
        scored=[]
        for r in inv:
            if not r["duration_sec"]:continue
            d=float(r["duration_sec"]);delta=d-dd
            if abs(delta)<=5.0:
                scored.append((abs(delta),r,d,delta))
        scored.sort(key=lambda x:x[0])
        for rank,(ad,r,d,delta) in enumerate(scored[:100],1):
            ind.append(dict(dm=dm,dm_duration=f"{dd:.3f}",rank=rank,
                            at3=r["relative"],at3_duration=f"{d:.3f}",
                            delta_sec=f"{delta:+.3f}",
                            within_2sec="YES" if ad<=2.0 else "NO",
                            bank=r["bank"],bytes=r["bytes"]))
    write_tsv(STAGE/"dm_individual_at3_duration_matches.tsv",ind)

    # 5) Bank total-duration matches.
    groups=defaultdict(list)
    for r in inv:
        if r["duration_sec"]:
            groups[r["bank"]].append(r)
    banks=[]
    for bank,rs in groups.items():
        total=sum(float(x["duration_sec"]) for x in rs)
        banks.append((bank,rs,total))
    bmatch=[]
    for dm,dd in DM_DURATIONS.items():
        ss=[]
        for bank,rs,total in banks:
            delta=total-dd
            if abs(delta)<=10.0:
                ss.append((abs(delta),bank,rs,total,delta))
        ss.sort(key=lambda x:x[0])
        for rank,(ad,bank,rs,total,delta) in enumerate(ss[:100],1):
            bmatch.append(dict(dm=dm,dm_duration=f"{dd:.3f}",rank=rank,
                               bank=bank,file_count=len(rs),
                               bank_total_duration=f"{total:.3f}",
                               delta_sec=f"{delta:+.3f}",
                               within_3sec="YES" if ad<=3.0 else "NO",
                               examples=",".join(x["file"] for x in rs[:12])))
    write_tsv(STAGE/"dm_bank_total_duration_matches.tsv",bmatch)

    # 6) Explicit g_d25/26/27 details.
    gd=[]
    for bank in ("g_d25","g_d26","g_d27"):
        rs=groups.get(bank,[])
        total=sum(float(x["duration_sec"]) for x in rs if x["duration_sec"])
        for r in rs:
            gd.append(dict(bank=bank,file=r["file"],bytes=r["bytes"],
                           duration_sec=r["duration_sec"],relative=r["relative"]))
        gd.append(dict(bank=bank,file="[BANK TOTAL]",bytes=sum(int(x["bytes"]) for x in rs),
                       duration_sec=f"{total:.6f}",relative=""))
    write_tsv(STAGE/"gd25_27_duration_detail.tsv",gd)

    # 7) KR/US counterpart matching.
    us_files=sorted(SOUND_US.rglob("*.at3")) if SOUND_US.exists() else []
    by_name=defaultdict(list)
    by_stem=defaultdict(list)
    for p in us_files:
        by_name[p.name.lower()].append(p)
        by_stem[p.stem.lower()].append(p)
    counterparts=[]
    for r in inv:
        stem=r["stem"];fn=r["file"].lower()
        cands=[]
        cands += by_name.get(fn,[])
        # common localized convention: suffix e
        cands += by_stem.get(stem+"e",[])
        if stem.endswith("e"):
            cands += by_stem.get(stem[:-1],[])
        # de-dupe
        seen=set();cc=[]
        for p in cands:
            sp=str(p)
            if sp not in seen:
                seen.add(sp);cc.append(p)
        for p in cc[:10]:
            counterparts.append(dict(
                kr=r["relative"],kr_bytes=r["bytes"],kr_duration=r["duration_sec"],
                us=rel_lower(p,SOUND_US),us_bytes=p.stat().st_size,
                relation=("SAME_FILENAME" if p.name.lower()==fn else "E_SUFFIX_CANDIDATE"),
            ))
    write_tsv(STAGE/"kr_us_at3_counterparts.tsv",counterparts)

    # Summary.
    exact_ind=sum(1 for r in ind if r["within_2sec"]=="YES")
    exact_bank=sum(1 for r in bmatch if r["within_3sec"]=="YES")
    gd_totals=[]
    for bank in ("g_d25","g_d26","g_d27"):
        rs=groups.get(bank,[])
        gd_totals.append(f"{bank}={sum(float(x['duration_sec']) for x in rs if x['duration_sec']):.3f}s/{len(rs)} files")
    summary=[
        "Naruto PSP MOV03I - DM resource predicate + full AT3 static scan",
        "="*78,"",
        "Grounded DM selector map:",
        "  0=dm001 1=dm002 2=dm003 3=dm004 4=dm005",
        "  5=dm006 6=dm007 7=dm008 8=dm009 9=dm010",
        "",
        f"KR AT3 files scanned={len(inv)}",
        f"AT3 duration unresolved={len(unresolved)}",
        f"Individual DM/AT3 rows within 2 sec={exact_ind}",
        f"Bank-total DM rows within 3 sec={exact_bank}",
        f"US AT3 files indexed={len(us_files)}",
        f"KR/US counterpart rows={len(counterparts)}",
        f"Audio-related BOOT strings={len(anchorrows)}",
        f"Grounded audio-string code xrefs={len(xrefrows)}",
        "",
        "g_d candidate totals:",
        *["  "+x for x in gd_totals],
        "",
        "Interpretation rules:",
        "- Duration similarity is a candidate generator, never proof.",
        "- Strong evidence requires duration + separate-use path + code/table linkage.",
        "- resource_function_context.txt is intended to reveal what predicate 0x5F8C0",
        "  actually tests before a DM selector is inserted into runtime BSS.",
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
