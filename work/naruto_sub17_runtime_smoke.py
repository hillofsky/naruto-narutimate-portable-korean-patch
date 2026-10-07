#!/usr/bin/env python3
# Naruto PSP SUB17 - Collision-free runtime smoke test
#
# Uses:
# - SUB16 collision-free mapping (694/694 STRICT)
# - SUB16 patched BOOT
# - Stage14 naruto_patcher.py
# - Stage24 stage24_iso_multi_patch.py
#
# Probe design:
# - Probe 00: 한글테스트가나다라마
#   This covers final mapping leads 0x81, 0x82, 0x89 including all five
#   reassigned characters 한/글/스/나/마.
# - Probes 01..15: one probe for each lead 0x8A..0x98.
#   Ten characters are sampled evenly across each lead's assigned trail range.
#
# No permanent source files are overwritten.

from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_SOURCE_ISO_SHA256 = "6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7"
EXPECTED_MAPPING_SHA256 = "fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
EXPECTED_BOOT_SHA256 = "2fbbf997e679082d97bb5990c78719c3a1ba8993fb568dfb4434af9ad8a7b376"
EXPECTED_ROWS = 694
EXPECTED_LEADS = [0x81,0x82] + list(range(0x89,0x99))
BASELINE = "한글테스트가나다라마"
PER_LEAD = 10

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""):
            h.update(block)
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

def custom_encode(text: str, by_char: dict[str,dict]):
    out=bytearray()
    for ch in text:
        if ch in by_char:
            code=int(by_char[ch]["donor_sjis_hex"],16)
            out.extend([(code>>8)&0xFF,code&0xFF])
        else:
            out.extend(ch.encode("cp932",errors="strict"))
    return bytes(out)

def even_sample(rows, n):
    rows=sorted(rows,key=lambda r:int(r["donor_sjis_hex"],16))
    if len(rows)<n:
        raise RuntimeError(f"lead group has only {len(rows)} rows, need {n}")
    if n==1:
        return [rows[len(rows)//2]]
    idx=[]
    for i in range(n):
        x=round(i*(len(rows)-1)/(n-1))
        idx.append(x)
    if len(set(idx))!=n:
        raise RuntimeError("sampling produced duplicate indices")
    return [rows[i] for i in idx]

def make_probes(mapping):
    by_char={r["hangul"]:r for r in mapping}
    leads=defaultdict(list)
    for r in mapping:
        code=int(r["donor_sjis_hex"],16)
        leads[(code>>8)&0xFF].append(r)

    actual_leads=sorted(leads)
    if actual_leads!=EXPECTED_LEADS:
        raise RuntimeError(
            "final mapping lead set changed: "
            f"actual={[f'{x:02X}' for x in actual_leads]} "
            f"expected={[f'{x:02X}' for x in EXPECTED_LEADS]}"
        )

    missing=[ch for ch in BASELINE if ch not in by_char]
    if missing:
        raise RuntimeError(f"baseline characters missing: {missing}")

    probes=[]
    base_rows=[by_char[ch] for ch in BASELINE]
    probes.append({
        "probe_index":0,
        "probe_id":"S17-00",
        "kind":"BASELINE_81_82_89",
        "lead":"81/82/89",
        "text":BASELINE,
        "rows":base_rows,
    })

    # Baseline must really cover 81,82,89.
    base_leads=sorted({int(r["donor_sjis_hex"][:2],16) for r in base_rows})
    if base_leads!=[0x81,0x82,0x89]:
        raise RuntimeError(
            f"baseline lead coverage changed: {[f'{x:02X}' for x in base_leads]}"
        )

    pidx=1
    for lead in range(0x8A,0x99):
        sample=even_sample(leads[lead],PER_LEAD)
        probes.append({
            "probe_index":pidx,
            "probe_id":f"S17-{pidx:02d}",
            "kind":"LEAD_RANGE_SAMPLE",
            "lead":f"{lead:02X}",
            "text":"".join(r["hangul"] for r in sample),
            "rows":sample,
        })
        pidx+=1

    if len(probes)!=16:
        raise RuntimeError(f"expected 16 probes, got {len(probes)}")

    return probes,leads

def patch_probe_tbl(source_tbl: Path, output_tbl: Path, mapping, report_path: Path):
    by_char={r["hangul"]:r for r in mapping}
    probes,leads=make_probes(mapping)

    raw=source_tbl.read_bytes()
    lines=raw.splitlines(keepends=True)
    out=[]
    report=[]
    probe_pos=0

    for line_no,line in enumerate(lines,1):
        body=line.rstrip(b"\r\n")
        newline=line[len(body):]

        if probe_pos<len(probes) and body.startswith(b"MSG ="):
            parts=body.split(b",",2)
            if len(parts)==3:
                p=probes[probe_pos]
                visible=f"{probe_pos:02d}:"+p["text"]
                enc=custom_encode(visible,by_char)
                out.append(parts[0]+b","+parts[1]+b","+enc+newline)

                codes=[r["donor_sjis_hex"].upper() for r in p["rows"]]
                glyphs=[int(r["glyph_index"]) for r in p["rows"]]
                report.append({
                    "probe_index":probe_pos,
                    "probe_id":p["probe_id"],
                    "kind":p["kind"],
                    "lead":p["lead"],
                    "source_line":line_no,
                    "msg_id":parts[1].decode("ascii",errors="replace"),
                    "expected_visible":visible,
                    "hangul_chars":p["text"],
                    "sjis_codes":" ".join(codes),
                    "glyphs":" ".join(str(x) for x in glyphs),
                    "min_glyph":min(glyphs),
                    "max_glyph":max(glyphs),
                    "encoded_hex":enc.hex(" "),
                })
                probe_pos+=1
                continue
        out.append(line)

    if probe_pos!=len(probes):
        raise RuntimeError(
            f"event000 has insufficient MSG rows: patched {probe_pos}/{len(probes)}"
        )

    output_tbl.write_bytes(b"".join(out))
    write_tsv(
        report_path,report,
        [
            "probe_index","probe_id","kind","lead","source_line","msg_id",
            "expected_visible","hangul_chars","sjis_codes","glyphs",
            "min_glyph","max_glyph","encoded_hex"
        ]
    )
    return report,leads

def read_iso_directory(f,lba,size):
    sec=2048
    f.seek(lba*sec)
    data=f.read(size)
    rows=[]
    pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//sec)+1)*sec
            continue
        rec=data[pos:pos+ln]
        if len(rec)<34:
            break
        extent=int.from_bytes(rec[2:6],"little")
        fsize=int.from_bytes(rec[10:14],"little")
        flags=rec[25]
        nlen=rec[32]
        nr=rec[33:33+nlen]
        if nr==b"\x00":
            name="."
        elif nr==b"\x01":
            name=".."
        else:
            name=nr.decode("ascii",errors="replace").split(";",1)[0]
        rows.append({
            "name":name,
            "extent":extent,
            "size":fsize,
            "is_dir":bool(flags&2),
        })
        pos+=ln
    return rows

def read_iso_file(path: Path, components):
    sec=2048
    with path.open("rb") as f:
        f.seek(16*sec)
        pvd=f.read(sec)
        if len(pvd)!=sec or pvd[0]!=1 or pvd[1:6]!=b"CD001":
            raise RuntimeError("ISO9660 PVD not found")
        root_len=pvd[156]
        root=pvd[156:156+root_len]
        lba=int.from_bytes(root[2:6],"little")
        size=int.from_bytes(root[10:14],"little")

        for i,want in enumerate(components):
            entries=read_iso_directory(f,lba,size)
            ent=next((x for x in entries if x["name"].upper()==want.upper()),None)
            if ent is None:
                raise RuntimeError("ISO path missing: "+"/".join(components[:i+1]))
            if i<len(components)-1:
                if not ent["is_dir"]:
                    raise RuntimeError(f"{want} is not a directory")
                lba,size=ent["extent"],ent["size"]
            else:
                f.seek(ent["extent"]*sec)
                return f.read(ent["size"]),ent
    raise RuntimeError("ISO traversal failed")

def build(args):
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    source_iso=root/"kr"/"Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
    mapping_path=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    boot_path=root/"analysis"/"sub"/"sub16_collision_free_boot"/"BOOT_sub16_collision_free_hangul.bin"
    source_tbl=root/"analysis"/"stage14"/"test_patch"/"event000_original.tbl"

    for p in (source_iso,mapping_path,boot_path,source_tbl):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    if sha256_file(source_iso).lower()!=EXPECTED_SOURCE_ISO_SHA256:
        raise RuntimeError("source ISO SHA256 mismatch")
    if sha256_file(mapping_path).lower()!=EXPECTED_MAPPING_SHA256:
        raise RuntimeError(
            f"SUB16 mapping SHA mismatch: {sha256_file(mapping_path)}"
        )
    if sha256_file(boot_path).lower()!=EXPECTED_BOOT_SHA256:
        raise RuntimeError(
            f"SUB16 BOOT SHA mismatch: {sha256_file(boot_path)}"
        )

    mapping=read_tsv(mapping_path)
    if len(mapping)!=EXPECTED_ROWS:
        raise RuntimeError(f"mapping rows={len(mapping)}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate Hangul")
    if len({r["donor_sjis_hex"] for r in mapping})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate SJIS")
    if len({r["glyph_index"] for r in mapping})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate glyph")

    # Final collision-free mapping must have zero observed source usage.
    if any(int(r.get("kr_tbl_usage_before","0")) for r in mapping):
        raise RuntimeError("final mapping contains KR TBL-used donor")
    if any(int(r.get("ui_sample_usage","0")) for r in mapping):
        raise RuntimeError("final mapping contains UI-used donor")

    tbl=out/"event000_sub17_runtime_smoke.tbl"
    probe_map=out/"sub17_probe_map.tsv"
    report,leads=patch_probe_tbl(source_tbl,tbl,mapping,probe_map)

    sampled=set()
    for r in report:
        sampled.update(r["hangul_chars"])

    lead_counts=Counter(r["donor_sjis_hex"][:2].upper() for r in mapping)
    lead_rows=[
        {"lead":lead,"mapping_count":lead_counts[lead]}
        for lead in sorted(lead_counts)
    ]
    write_tsv(out/"sub17_lead_coverage.tsv",lead_rows,["lead","mapping_count"])

    checklist=[
        "Naruto PSP SUB17 - Collision-Free Runtime Smoke Checklist",
        "="*76,
        "",
        f"Probe count: {len(report)}",
        f"Unique sampled Hangul: {len(sampled)}",
        "All final mapping lead bytes covered: YES",
        "",
        "특히 00번은 SUB16에서 이동한 한/글/스/나/마와",
        "기존 검증 테/트/가/다/라를 동시에 확인한다.",
        "",
        "Expected dialogue windows:",
    ]
    for r in report:
        checklist.append(
            f"  {int(r['probe_index']):02d}  lead={r['lead']:<8} "
            f"glyph={r['min_glyph']}..{r['max_glyph']}  "
            f"{r['expected_visible']}"
        )
    checklist += [
        "",
        "PASS:",
        "- 00~15의 한글이 모두 해당 expected_visible과 일치한다.",
        "- 일본어 donor 원문, ASCII, 깨진 비트맵으로 치환되는 문자가 없다.",
        "- 00번의 '한글테스트가나다라마'가 모두 정상이다.",
        "",
        "실행은 세이브 스테이트가 아니라 일반 저장/새 로딩으로 한다.",
    ]
    (out/"sub17_runtime_checklist.txt").write_text(
        "\n".join(checklist)+"\n",encoding="utf-8-sig"
    )

    build_report={
        "stage":"SUB17",
        "source_iso_sha256":sha256_file(source_iso),
        "mapping_sha256":sha256_file(mapping_path),
        "boot_sha256":sha256_file(boot_path),
        "mapping_rows":len(mapping),
        "probe_count":len(report),
        "sampled_unique_hangul":len(sampled),
        "mapping_leads":[f"{x:02X}" for x in sorted(leads)],
        "all_mapping_leads_covered":True,
        "probe_tbl":str(tbl),
        "probe_tbl_sha256":sha256_file(tbl),
    }
    (out/"sub17_build_report.json").write_text(
        json.dumps(build_report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    print(f"MappingRows={len(mapping)}")
    print(f"ProbeCount={len(report)}")
    print(f"SampledUniqueHangul={len(sampled)}")
    print("MappingLeads="+" ".join(build_report["mapping_leads"]))
    print(f"ProbeTBL={tbl}")

def verify(args):
    out=Path(args.out)
    iso=Path(args.iso)
    dat=Path(args.dat)
    idx=Path(args.idx)
    boot=Path(args.boot)

    for p in (iso,dat,idx,boot):
        if not p.exists():
            raise RuntimeError(f"verify input missing: {p}")

    iboot,_=read_iso_file(iso,["PSP_GAME","SYSDIR","BOOT.BIN"])
    idat,_=read_iso_file(iso,["PSP_GAME","USRDIR","naruto.dat"])
    iidx,_=read_iso_file(iso,["PSP_GAME","USRDIR","naruto.idx"])

    checks={
        "boot_match":hashlib.sha256(iboot).hexdigest()==sha256_file(boot),
        "dat_match":hashlib.sha256(idat).hexdigest()==sha256_file(dat),
        "idx_match":hashlib.sha256(iidx).hexdigest()==sha256_file(idx),
    }
    if not all(checks.values()):
        raise RuntimeError(f"embedded ISO verification failed: {checks}")

    br=json.loads((out/"sub17_build_report.json").read_text(encoding="utf-8"))
    vr={
        "iso":str(iso),
        "iso_size":iso.stat().st_size,
        "iso_sha256":sha256_file(iso),
        "embedded_boot_sha256":hashlib.sha256(iboot).hexdigest(),
        "embedded_dat_sha256":hashlib.sha256(idat).hexdigest(),
        "embedded_idx_sha256":hashlib.sha256(iidx).hexdigest(),
        **checks,
    }
    (out/"sub17_iso_verify.json").write_text(
        json.dumps(vr,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB17 - Collision-Free Runtime Smoke ISO",
        "",
        f"MappingRows={br['mapping_rows']}",
        f"ProbeCount={br['probe_count']}",
        f"SampledUniqueHangul={br['sampled_unique_hangul']}",
        f"MappingLeads={' '.join(br['mapping_leads'])}",
        "AllMappingLeadsCovered=YES",
        f"ISOSHA256={vr['iso_sha256']}",
        f"EmbeddedBOOTMatch={'YES' if checks['boot_match'] else 'NO'}",
        f"EmbeddedDATMatch={'YES' if checks['dat_match'] else 'NO'}",
        f"EmbeddedIDXMatch={'YES' if checks['idx_match'] else 'NO'}",
        "",
        f"ISO={iso}",
        "",
        "Run with a normal save/new load, not a save state.",
        "Compare 00..15 against sub17_runtime_checklist.txt.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",encoding="utf-8-sig"
    )
    print("\n".join(summary))

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="mode",required=True)

    b=sub.add_parser("build")
    b.add_argument("--root",required=True)
    b.add_argument("--out",required=True)

    v=sub.add_parser("verify")
    v.add_argument("--out",required=True)
    v.add_argument("--iso",required=True)
    v.add_argument("--dat",required=True)
    v.add_argument("--idx",required=True)
    v.add_argument("--boot",required=True)

    args=ap.parse_args()
    if args.mode=="build":
        build(args)
    else:
        verify(args)

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
