#!/usr/bin/env python3
# Naruto PSP SUB13 - Full Hangul donor runtime smoke test
#
# Builds probe event000.tbl from the frozen SUB10 mapping and verifies
# the ISO produced by the existing Stage14/Stage24 patchers.
#
# No permanent source assets are overwritten.

from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from pathlib import Path

EXPECTED_SOURCE_ISO_SHA256 = "6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7"
EXPECTED_SUB12_BOOT_SHA256 = "7b4d8019dc6bd095b58fa7f307d3429e79af3aa9e6d764c13e0afe4418df2ae3"
EXPECTED_MAPPING_SHA256 = "9c73cdb33eb812a813c78cfb5efcad80838322ab5a4da90c91eb3db6aaca056c"
EXPECTED_MAPPING_ROWS = 694
PROBE_SAMPLE_GROUPS = 16
PROBE_CHARS_PER_GROUP = 10
FIXED_SEED = "한글테스트가나다라마"

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
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

def custom_encode(text, mapping):
    out=bytearray()
    for ch in text:
        if ch in mapping:
            code=int(mapping[ch]["donor_sjis_hex"],16)
            out.extend([(code>>8)&0xFF, code&0xFF])
        else:
            out.extend(ch.encode("cp932",errors="strict"))
    return bytes(out)

def make_probe_groups(mapping_rows):
    by_char={r["hangul"]:r for r in mapping_rows}
    missing=[ch for ch in FIXED_SEED if ch not in by_char]
    if missing:
        raise RuntimeError(f"fixed seed missing from mapping: {missing}")

    glyph_sorted=sorted(mapping_rows,key=lambda r:int(r["glyph_index"]))
    probes=[]

    # Probe 0: already proven Stage36R baseline, now rendered from SUB12 BOOT.
    probes.append({
        "probe_id":"S13-00",
        "kind":"FIXED10_BASELINE",
        "text":FIXED_SEED,
        "chars":FIXED_SEED,
    })

    # 16 evenly distributed standard-donor windows.
    n=len(glyph_sorted)
    for group in range(PROBE_SAMPLE_GROUPS):
        center=(group+0.5)*n/PROBE_SAMPLE_GROUPS
        center_idx=min(n-1,max(0,int(center)))
        start=max(0,center_idx-PROBE_CHARS_PER_GROUP//2)
        end=min(n,start+PROBE_CHARS_PER_GROUP)
        start=max(0,end-PROBE_CHARS_PER_GROUP)
        chunk=glyph_sorted[start:end]
        chars="".join(r["hangul"] for r in chunk)
        probes.append({
            "probe_id":f"S13-{group+1:02d}",
            "kind":"GLYPH_RANGE_SAMPLE",
            "text":chars,
            "chars":chars,
        })

    # Add metadata.
    for p in probes:
        rs=[by_char[ch] for ch in p["chars"]]
        glyphs=[int(r["glyph_index"]) for r in rs]
        p["min_glyph"]=min(glyphs)
        p["max_glyph"]=max(glyphs)
        p["sjis_codes"]=" ".join(r["donor_sjis_hex"] for r in rs)
        p["glyphs"]=" ".join(str(x) for x in glyphs)

    return probes

def build_probe_tbl(source_tbl: Path, output_tbl: Path, mapping_rows, report_path: Path):
    mapping={r["hangul"]:r for r in mapping_rows}
    probes=make_probe_groups(mapping_rows)

    raw=source_tbl.read_bytes()
    lines=raw.splitlines(keepends=True)
    out=[]
    report=[]
    probe_index=0

    for line_no,line in enumerate(lines,1):
        body=line.rstrip(b"\r\n")
        newline=line[len(body):]

        if probe_index < len(probes) and body.startswith(b"MSG ="):
            parts=body.split(b",",2)
            if len(parts)==3:
                p=probes[probe_index]
                # Keep visible prefix compact. 10 Hangul chars + 4 ASCII chars
                # fits the proven Stage36R message width comfortably.
                visible=f"{probe_index:02d}:"+p["text"]
                encoded=custom_encode(visible,mapping)

                out.append(parts[0]+b","+parts[1]+b","+encoded+newline)

                report.append({
                    "probe_index":probe_index,
                    "probe_id":p["probe_id"],
                    "kind":p["kind"],
                    "source_line":line_no,
                    "msg_id":parts[1].decode("ascii",errors="replace"),
                    "expected_visible":visible,
                    "hangul_chars":p["chars"],
                    "min_glyph":p["min_glyph"],
                    "max_glyph":p["max_glyph"],
                    "glyphs":p["glyphs"],
                    "sjis_codes":p["sjis_codes"],
                    "encoded_hex":encoded.hex(" "),
                })
                probe_index+=1
                continue

        out.append(line)

    if probe_index != len(probes):
        raise RuntimeError(
            f"event000 MSG rows insufficient: {probe_index}/{len(probes)}"
        )

    output_tbl.write_bytes(b"".join(out))
    write_tsv(
        report_path,
        report,
        [
            "probe_index","probe_id","kind","source_line","msg_id",
            "expected_visible","hangul_chars","min_glyph","max_glyph",
            "glyphs","sjis_codes","encoded_hex"
        ]
    )
    return report

def read_iso_directory(iso, lba, size):
    sector=2048
    iso.seek(lba*sector)
    data=iso.read(size)
    records=[]
    pos=0
    while pos<len(data):
        length=data[pos]
        if length==0:
            pos=((pos//sector)+1)*sector
            continue
        rec=data[pos:pos+length]
        if len(rec)<34:
            break
        extent=int.from_bytes(rec[2:6],"little")
        file_size=int.from_bytes(rec[10:14],"little")
        flags=rec[25]
        name_len=rec[32]
        name_raw=rec[33:33+name_len]
        if name_raw==b"\x00":
            name="."
        elif name_raw==b"\x01":
            name=".."
        else:
            name=name_raw.decode("ascii",errors="replace")
            if ";" in name:
                name=name.split(";",1)[0]
        records.append({
            "name":name,
            "extent":extent,
            "size":file_size,
            "is_dir":bool(flags & 0x02),
        })
        pos+=length
    return records

def read_iso_file(path: Path, components):
    sector=2048
    with path.open("rb") as iso:
        iso.seek(16*sector)
        pvd=iso.read(sector)
        if len(pvd)!=sector or pvd[0]!=1 or pvd[1:6]!=b"CD001":
            raise RuntimeError("ISO9660 PVD not found")

        root_len=pvd[156]
        root=pvd[156:156+root_len]
        lba=int.from_bytes(root[2:6],"little")
        size=int.from_bytes(root[10:14],"little")

        for idx,wanted in enumerate(components):
            records=read_iso_directory(iso,lba,size)
            match=next(
                (r for r in records if r["name"].upper()==wanted.upper()),
                None
            )
            if match is None:
                raise RuntimeError("ISO path missing: "+"/".join(components[:idx+1]))
            if idx<len(components)-1:
                if not match["is_dir"]:
                    raise RuntimeError(f"{wanted} is not a directory")
                lba=match["extent"]
                size=match["size"]
            else:
                iso.seek(match["extent"]*sector)
                return iso.read(match["size"]),match
    raise RuntimeError("ISO traversal failed")

def build(args):
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    source_iso=root/"kr"/"Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
    sub12_boot=root/"analysis"/"sub"/"sub12_full_glyph_build"/"BOOT_sub12_full_hangul.bin"
    mapping_path=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    source_tbl=root/"analysis"/"stage14"/"test_patch"/"event000_original.tbl"

    for p in (source_iso,sub12_boot,mapping_path,source_tbl):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    if sha256_file(source_iso).lower()!=EXPECTED_SOURCE_ISO_SHA256:
        raise RuntimeError("source KR ISO SHA256 mismatch")
    if sha256_file(sub12_boot).lower()!=EXPECTED_SUB12_BOOT_SHA256:
        raise RuntimeError("SUB12 patched BOOT SHA256 mismatch")
    if sha256_file(mapping_path).lower()!=EXPECTED_MAPPING_SHA256:
        raise RuntimeError("SUB10 frozen mapping SHA256 mismatch")

    mapping=read_tsv(mapping_path)
    if len(mapping)!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError(f"mapping rows={len(mapping)}, expected={EXPECTED_MAPPING_ROWS}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate Hangul in mapping")
    if len({r["donor_sjis_hex"] for r in mapping})!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate SJIS in mapping")
    if len({r["glyph_index"] for r in mapping})!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate glyph in mapping")

    output_tbl=out/"event000_sub13_runtime_smoke.tbl"
    report_path=out/"sub13_probe_map.tsv"
    report=build_probe_tbl(source_tbl,output_tbl,mapping,report_path)

    covered=set()
    for r in report:
        covered.update(r["hangul_chars"])

    ranges=[]
    for r in report:
        ranges.append(f"{r['probe_id']}: glyph {r['min_glyph']}..{r['max_glyph']}  {r['expected_visible']}")

    checklist=[
        "Naruto PSP SUB13 - Runtime Smoke Checklist",
        "="*72,
        "",
        f"Total probes: {len(report)}",
        f"Unique Hangul sampled: {len(covered)} / {EXPECTED_MAPPING_ROWS}",
        "",
        "Expected dialogue windows:",
    ] + ["  "+x for x in ranges] + [
        "",
        "PASS 기준:",
        "- 각 창의 번호와 한글이 깨지지 않고 읽힌다.",
        "- □/일본어 donor 원문/엉뚱한 한글로 치환되지 않는다.",
        "- 글자가 심하게 잘리거나 빈칸이 되지 않는다.",
        "",
        "이 테스트는 694자를 전부 눈으로 읽는 완전검사가 아니라",
        "donor glyph 0..2064 구간을 고르게 샘플링하는 런타임 스모크 테스트다.",
    ]
    (out/"sub13_runtime_checklist.txt").write_text(
        "\n".join(checklist)+"\n",encoding="utf-8-sig"
    )

    build_report={
        "mode":"build",
        "source_iso":str(source_iso),
        "source_iso_sha256":sha256_file(source_iso),
        "sub12_boot":str(sub12_boot),
        "sub12_boot_sha256":sha256_file(sub12_boot),
        "mapping_sha256":sha256_file(mapping_path),
        "mapping_rows":len(mapping),
        "probe_count":len(report),
        "sampled_unique_hangul":len(covered),
        "min_sampled_glyph":min(int(r["min_glyph"]) for r in report),
        "max_sampled_glyph":max(int(r["max_glyph"]) for r in report),
        "probe_tbl":str(output_tbl),
        "probe_tbl_sha256":sha256_file(output_tbl),
    }
    (out/"sub13_build_report.json").write_text(
        json.dumps(build_report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    print(f"ProbeCount={len(report)}")
    print(f"SampledUniqueHangul={len(covered)}")
    print(f"SampledGlyphRange={build_report['min_sampled_glyph']}..{build_report['max_sampled_glyph']}")
    print(f"ProbeTBL={output_tbl}")

def verify(args):
    root=Path(args.root)
    out=Path(args.out)
    iso=Path(args.iso)
    dat=Path(args.dat)
    idx=Path(args.idx)
    boot=Path(args.boot)

    for p in (iso,dat,idx,boot):
        if not p.exists():
            raise RuntimeError(f"verification input missing: {p}")

    iso_boot,_=read_iso_file(iso,["PSP_GAME","SYSDIR","BOOT.BIN"])
    iso_dat,_=read_iso_file(iso,["PSP_GAME","USRDIR","naruto.dat"])
    iso_idx,_=read_iso_file(iso,["PSP_GAME","USRDIR","naruto.idx"])

    checks={
        "boot_match":hashlib.sha256(iso_boot).hexdigest()==sha256_file(boot),
        "dat_match":hashlib.sha256(iso_dat).hexdigest()==sha256_file(dat),
        "idx_match":hashlib.sha256(iso_idx).hexdigest()==sha256_file(idx),
    }
    if not all(checks.values()):
        raise RuntimeError(f"ISO embedded file verification failed: {checks}")

    report={
        "mode":"verify",
        "iso":str(iso),
        "iso_size":iso.stat().st_size,
        "iso_sha256":sha256_file(iso),
        "embedded_boot_sha256":hashlib.sha256(iso_boot).hexdigest(),
        "expected_boot_sha256":sha256_file(boot),
        "embedded_dat_sha256":hashlib.sha256(iso_dat).hexdigest(),
        "expected_dat_sha256":sha256_file(dat),
        "embedded_idx_sha256":hashlib.sha256(iso_idx).hexdigest(),
        "expected_idx_sha256":sha256_file(idx),
        **checks,
    }
    (out/"sub13_iso_verify.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    build_report=json.loads((out/"sub13_build_report.json").read_text(encoding="utf-8"))
    summary=[
        "Naruto PSP SUB13 - Full Hangul Runtime Smoke ISO",
        "",
        f"ProbeCount={build_report['probe_count']}",
        f"SampledUniqueHangul={build_report['sampled_unique_hangul']}",
        f"SampledGlyphRange={build_report['min_sampled_glyph']}..{build_report['max_sampled_glyph']}",
        f"ISOSize={report['iso_size']}",
        f"ISOSHA256={report['iso_sha256']}",
        f"EmbeddedBOOTMatch={'YES' if checks['boot_match'] else 'NO'}",
        f"EmbeddedDATMatch={'YES' if checks['dat_match'] else 'NO'}",
        f"EmbeddedIDXMatch={'YES' if checks['idx_match'] else 'NO'}",
        "",
        f"ISO={iso}",
        "",
        "Launch the ISO in PPSSPP from a normal save (not a save state).",
        "Compare the first probe dialogue windows with sub13_runtime_checklist.txt.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="mode",required=True)

    b=sub.add_parser("build")
    b.add_argument("--root",required=True)
    b.add_argument("--out",required=True)

    v=sub.add_parser("verify")
    v.add_argument("--root",required=True)
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
