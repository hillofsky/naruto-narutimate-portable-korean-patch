#!/usr/bin/env python3
# Naruto PSP SUB14 - Recover actual event SJIS -> glyph mapping from BOOT
#
# Read-only diagnostic.
# Extracts/disassembles:
#   0x088D5640  SJIS byte classification
#   0x088D56EC  two-byte SJIS -> glyph conversion
# plus nearby caller/renderer functions.
#
# Also scans local Stage32/33/34/35/36 analysis artifacts for these addresses.
# No BOOT/EBOOT/ISO modification.

from __future__ import annotations
import argparse, csv, hashlib, json, re, shutil, struct, sys
from pathlib import Path

TARGETS = {
    "sjis_classify_088D5640": (0x088D5640, 0xAC),
    "sjis_to_glyph_088D56EC": (0x088D56EC, 0x300),
    "renderer_1byte_088D64E0": (0x088D64E0, 0x180),
    "renderer_2byte_088D65CC": (0x088D65CC, 0x180),
    "control_parser_088D675C": (0x088D675C, 0x180),
    "event_loop_088D752C": (0x088D752C, 0x200),
}

RUNTIME_BASE_CANDIDATES = [
    0,
    0x08800000,
    0x08804000,
]

TEXT_EXTS = {".py",".ps1",".txt",".log",".md",".tsv",".csv",".json"}

REG = [
    "$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3",
    "$t0","$t1","$t2","$t3","$t4","$t5","$t6","$t7",
    "$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
    "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"
]

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def write_tsv(path, rows, fields):
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def s16(x):
    return x-0x10000 if x & 0x8000 else x

def disasm_word(addr, w):
    op=(w>>26)&0x3F
    rs=(w>>21)&0x1F
    rt=(w>>16)&0x1F
    rd=(w>>11)&0x1F
    sa=(w>>6)&0x1F
    fn=w&0x3F
    imm=w&0xFFFF
    simm=s16(imm)
    target=w&0x03FFFFFF

    if w==0:
        return "nop",""

    if op==0:
        table={
            0x00:"sll",0x02:"srl",0x03:"sra",
            0x04:"sllv",0x06:"srlv",0x07:"srav",
            0x08:"jr",0x09:"jalr",
            0x0A:"movz",0x0B:"movn",
            0x0C:"syscall",0x0D:"break",
            0x10:"mfhi",0x11:"mthi",0x12:"mflo",0x13:"mtlo",
            0x18:"mult",0x19:"multu",0x1A:"div",0x1B:"divu",
            0x20:"add",0x21:"addu",0x22:"sub",0x23:"subu",
            0x24:"and",0x25:"or",0x26:"xor",0x27:"nor",
            0x2A:"slt",0x2B:"sltu",
        }
        m=table.get(fn,f"special_{fn:02X}")
        if fn in (0x00,0x02,0x03):
            o=f"{REG[rd]}, {REG[rt]}, {sa}"
        elif fn in (0x04,0x06,0x07):
            o=f"{REG[rd]}, {REG[rt]}, {REG[rs]}"
        elif fn==0x08:
            o=REG[rs]
        elif fn==0x09:
            o=f"{REG[rd]}, {REG[rs]}"
        elif fn in (0x0A,0x0B):
            o=f"{REG[rd]}, {REG[rs]}, {REG[rt]}"
        elif fn in (0x0C,0x0D):
            o=""
        elif fn in (0x10,0x12):
            o=REG[rd]
        elif fn in (0x11,0x13):
            o=REG[rs]
        elif fn in (0x18,0x19,0x1A,0x1B):
            o=f"{REG[rs]}, {REG[rt]}"
        else:
            o=f"{REG[rd]}, {REG[rs]}, {REG[rt]}"
        return m,o

    if op==0x01:
        kinds={0x00:"bltz",0x01:"bgez",0x10:"bltzal",0x11:"bgezal"}
        m=kinds.get(rt,f"regimm_{rt:02X}")
        dest=(addr+4+(simm<<2))&0xFFFFFFFF
        return m,f"{REG[rs]}, 0x{dest:08X}"

    if op in (0x02,0x03):
        m="j" if op==0x02 else "jal"
        dest=((addr+4)&0xF0000000)|(target<<2)
        return m,f"0x{dest:08X}"

    branches={0x04:"beq",0x05:"bne",0x06:"blez",0x07:"bgtz",
              0x14:"beql",0x15:"bnel",0x16:"blezl",0x17:"bgtzl"}
    if op in branches:
        dest=(addr+4+(simm<<2))&0xFFFFFFFF
        if op in (0x06,0x07,0x16,0x17):
            o=f"{REG[rs]}, 0x{dest:08X}"
        else:
            o=f"{REG[rs]}, {REG[rt]}, 0x{dest:08X}"
        return branches[op],o

    immed={
        0x08:"addi",0x09:"addiu",0x0A:"slti",0x0B:"sltiu",
        0x0C:"andi",0x0D:"ori",0x0E:"xori",0x0F:"lui"
    }
    if op in immed:
        m=immed[op]
        if op==0x0F:
            o=f"{REG[rt]}, 0x{imm:04X}"
        elif op in (0x0C,0x0D,0x0E):
            o=f"{REG[rt]}, {REG[rs]}, 0x{imm:04X}"
        else:
            o=f"{REG[rt]}, {REG[rs]}, {simm}"
        return m,o

    loads={
        0x20:"lb",0x21:"lh",0x22:"lwl",0x23:"lw",
        0x24:"lbu",0x25:"lhu",0x26:"lwr",
        0x28:"sb",0x29:"sh",0x2A:"swl",0x2B:"sw",0x2E:"swr",
        0x31:"lwc1",0x39:"swc1"
    }
    if op in loads:
        return loads[op],f"{REG[rt]}, {simm}({REG[rs]})"

    # SPECIAL2 / SPECIAL3 raw-ish decode for common MIPS32r2 ops.
    if op==0x1C:
        fn=w&0x3F
        names={0x00:"madd",0x01:"maddu",0x02:"mul",0x04:"msub",0x05:"msubu",
               0x20:"clz",0x21:"clo"}
        m=names.get(fn,f"special2_{fn:02X}")
        return m,f"{REG[rd]}, {REG[rs]}, {REG[rt]}"

    if op==0x1F:
        fn=w&0x3F
        if fn==0x00: # ext
            size=rd+1
            return "ext",f"{REG[rt]}, {REG[rs]}, {sa}, {size}"
        if fn==0x04: # ins
            size=rd-sa+1
            return "ins",f"{REG[rt]}, {REG[rs]}, {sa}, {size}"
        if fn==0x20:
            # BSHFL family; exact subop in sa
            if sa==0x10:
                return "seb",f"{REG[rd]}, {REG[rt]}"
            if sa==0x18:
                return "seh",f"{REG[rd]}, {REG[rt]}"
            return "bshfl",f"{REG[rd]}, {REG[rt]}, sa={sa}"
        return f"special3_{fn:02X}",f"rs={rs} rt={rt} rd={rd} sa={sa}"

    return f"op_{op:02X}",f"0x{w:08X}"

def parse_elf(path: Path):
    data=path.read_bytes()
    if data[:4]!=b"\x7fELF":
        raise RuntimeError(f"not ELF: {path}")
    if data[4]!=1 or data[5]!=1:
        raise RuntimeError("expected ELF32 little-endian")

    e_type,e_machine,e_version=struct.unpack_from("<HHI",data,0x10)
    e_entry=struct.unpack_from("<I",data,0x18)[0]
    e_phoff=struct.unpack_from("<I",data,0x1C)[0]
    e_shoff=struct.unpack_from("<I",data,0x20)[0]
    e_flags=struct.unpack_from("<I",data,0x24)[0]
    e_ehsize,e_phentsize,e_phnum,e_shentsize,e_shnum,e_shstrndx=struct.unpack_from(
        "<HHHHHH",data,0x28
    )

    ph=[]
    for i in range(e_phnum):
        off=e_phoff+i*e_phentsize
        if off+32>len(data):
            break
        vals=struct.unpack_from("<IIIIIIII",data,off)
        p_type,p_offset,p_vaddr,p_paddr,p_filesz,p_memsz,p_flags,p_align=vals
        ph.append({
            "index":i,"type":p_type,"offset":p_offset,
            "vaddr":p_vaddr,"paddr":p_paddr,
            "filesz":p_filesz,"memsz":p_memsz,
            "flags":p_flags,"align":p_align,
        })

    return data,{
        "e_type":e_type,"e_machine":e_machine,"e_entry":e_entry,
        "e_phoff":e_phoff,"e_phentsize":e_phentsize,"e_phnum":e_phnum,
        "e_flags":e_flags,
    },ph

def map_runtime(data, ph, runtime_addr):
    candidates=[]
    for base in RUNTIME_BASE_CANDIDATES:
        logical=runtime_addr-base
        if logical<0:
            continue
        for seg in ph:
            if seg["type"]!=1:
                continue
            start=seg["vaddr"]
            end=start+seg["filesz"]
            if start <= logical < end:
                foff=seg["offset"]+(logical-start)
                if 0<=foff<len(data):
                    candidates.append({
                        "runtime_base":base,
                        "logical_vaddr":logical,
                        "segment_index":seg["index"],
                        "file_offset":foff,
                    })
    if not candidates:
        return None
    # Prefer the conventional PSP base if it maps cleanly.
    candidates.sort(key=lambda x:(0 if x["runtime_base"]==0x08804000 else 1,
                                  x["runtime_base"]))
    return candidates[0]

def capstone_disasm(blob, start_addr):
    try:
        from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
        md=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
        rows=[]
        for insn in md.disasm(blob,start_addr):
            rows.append({
                "address":f"0x{insn.address:08X}",
                "word_hex":blob[insn.address-start_addr:insn.address-start_addr+4][::-1].hex().upper(),
                "mnemonic":insn.mnemonic,
                "operands":insn.op_str,
                "decoder":"capstone",
            })
        return rows
    except Exception:
        return []

def fallback_disasm(blob,start_addr):
    rows=[]
    usable=len(blob)-(len(blob)%4)
    for i in range(0,usable,4):
        w=struct.unpack_from("<I",blob,i)[0]
        addr=start_addr+i
        m,o=disasm_word(addr,w)
        rows.append({
            "address":f"0x{addr:08X}",
            "word_hex":f"{w:08X}",
            "mnemonic":m,
            "operands":o,
            "decoder":"builtin",
        })
    return rows

def scan_stage_evidence(root: Path, out: Path):
    needles=[
        "088D5640","088D56EC","088D64E0","088D65CC","088D675C","088D752C",
        "0x088D5640","0x088D56EC","0x088D64E0","0x088D65CC",
        "standard_glyph","sjis_to_glyph","Shift-JIS","Shift_JIS",
    ]
    rows=[]
    evdir=out/"stage_evidence"
    evdir.mkdir(exist_ok=True)

    analysis=root/"analysis"
    roots=[]
    if analysis.exists():
        for p in analysis.iterdir():
            if p.is_dir() and re.search(r"(?i)^stage(3[0-6])",p.name):
                roots.append(p)

    for rr in roots:
        for p in rr.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
                continue
            try:
                if p.stat().st_size>5*1024*1024:
                    continue
                txt=p.read_text(encoding="utf-8-sig",errors="replace")
            except Exception:
                continue
            low=txt.lower()
            hits=[n for n in needles if n.lower() in low]
            if not hits:
                continue
            contexts=[]
            for h in hits[:8]:
                pos=low.find(h.lower())
                if pos>=0:
                    contexts.append(txt[max(0,pos-180):pos+700])
            rel=str(p.relative_to(root))
            rows.append({
                "path":rel,
                "hits":"|".join(hits),
                "context":"\n---\n".join(contexts)[:7000],
            })
            dst=evdir/rel.replace(":","_")
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dst)

    write_tsv(out/"sub14_stage_evidence.tsv",rows,["path","hits","context"])
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    boot=root/"kr_extracted"/"PSP_GAME"/"SYSDIR"/"BOOT.BIN"
    if not boot.exists():
        raise RuntimeError(f"BOOT missing: {boot}")

    data,eh,ph=parse_elf(boot)

    ph_rows=[]
    for x in ph:
        ph_rows.append({
            "index":x["index"],
            "type":x["type"],
            "offset":f"0x{x['offset']:X}",
            "vaddr":f"0x{x['vaddr']:08X}",
            "paddr":f"0x{x['paddr']:08X}",
            "filesz":f"0x{x['filesz']:X}",
            "memsz":f"0x{x['memsz']:X}",
            "flags":f"0x{x['flags']:X}",
            "align":f"0x{x['align']:X}",
        })
    write_tsv(
        out/"sub14_elf_program_headers.tsv",
        ph_rows,
        ["index","type","offset","vaddr","paddr","filesz","memsz","flags","align"]
    )

    map_rows=[]
    all_disasm=[]
    rawdir=out/"function_raw"
    rawdir.mkdir(exist_ok=True)

    for name,(runtime,size) in TARGETS.items():
        m=map_runtime(data,ph,runtime)
        if not m:
            map_rows.append({
                "name":name,"runtime_address":f"0x{runtime:08X}",
                "size":f"0x{size:X}","mapped":"NO",
                "runtime_base":"","logical_vaddr":"",
                "segment_index":"","file_offset":"",
            })
            continue

        foff=m["file_offset"]
        blob=data[foff:foff+size]
        (rawdir/f"{name}.bin").write_bytes(blob)

        map_rows.append({
            "name":name,
            "runtime_address":f"0x{runtime:08X}",
            "size":f"0x{size:X}",
            "mapped":"YES",
            "runtime_base":f"0x{m['runtime_base']:08X}",
            "logical_vaddr":f"0x{m['logical_vaddr']:08X}",
            "segment_index":m["segment_index"],
            "file_offset":f"0x{foff:X}",
        })

        rows=capstone_disasm(blob,runtime)
        if not rows:
            rows=fallback_disasm(blob,runtime)
        for r in rows:
            r["function"]=name
            r["file_offset"]=f"0x{foff + (int(r['address'],16)-runtime):X}"
            all_disasm.append(r)

    write_tsv(
        out/"sub14_runtime_address_map.tsv",
        map_rows,
        [
            "name","runtime_address","size","mapped","runtime_base",
            "logical_vaddr","segment_index","file_offset"
        ]
    )

    write_tsv(
        out/"sub14_disassembly.tsv",
        all_disasm,
        ["function","address","file_offset","word_hex","mnemonic","operands","decoder"]
    )

    evidence=scan_stage_evidence(root,out)

    # Pull the previous theoretical standard_glyph function if found.
    theory=[]
    for r in evidence:
        if "standard_glyph" in r["hits"]:
            theory.append({
                "path":r["path"],
                "context":r["context"],
            })
    write_tsv(out/"sub14_previous_mapping_theory.tsv",theory,["path","context"])

    report={
        "boot":str(boot),
        "boot_sha256":sha256_file(boot),
        "elf_header":eh,
        "target_count":len(TARGETS),
        "mapped_targets":sum(1 for r in map_rows if r["mapped"]=="YES"),
        "disassembly_rows":len(all_disasm),
        "stage_evidence_files":len(evidence),
        "note":"read-only diagnostic; no game files modified",
    }
    (out/"sub14_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB14 - Actual Event SJIS -> Glyph Mapping Recovery",
        "",
        f"BOOTSHA256={report['boot_sha256']}",
        f"MappedTargets={report['mapped_targets']}/{report['target_count']}",
        f"DisassemblyRows={report['disassembly_rows']}",
        f"StageEvidenceFiles={report['stage_evidence_files']}",
        "",
        "Targets:",
    ]
    for r in map_rows:
        summary.append(
            f"  {r['name']} runtime={r['runtime_address']} "
            f"mapped={r['mapped']} file={r['file_offset']}"
        )
    summary += [
        "",
        "Purpose:",
        "- replace the incorrect Stage35R theoretical JIS-grid mapping",
        "  with the actual runtime conversion used by 0x088D56EC.",
        "- no BOOT/EBOOT/ISO bytes are modified.",
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
