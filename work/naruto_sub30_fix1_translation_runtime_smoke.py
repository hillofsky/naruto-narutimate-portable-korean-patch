#!/usr/bin/env python3
# -*- coding: ascii -*-
# Naruto PSP SUB30 FIX1 - Korean translation runtime smoke
#
# Patches only event000 display messages 1..24 using the validated SUB29 draft,
# rebuilds DAT/IDX with Stage14, builds an ISO with Stage24 + SUB16 BOOT,
# then independently re-opens the ISO9660 filesystem and verifies BOOT/DAT/IDX.
#
# The candidate ISO is promoted only after every verification passes.

from __future__ import annotations
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

EXPECTED_SOURCE_ISO_SHA="6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7"
EXPECTED_MAPPING_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
EXPECTED_BOOT_SHA="2fbbf997e679082d97bb5990c78719c3a1ba8993fb568dfb4434af9ad8a7b376"
EXPECTED_SUB29_MANIFEST_SHA="e7376f57f4b475aaaa0ae3707ea297b28b8d0de4bcbf6fafc21e88fd021b1b71"
EXPECTED_STAGE14_PATCHER_SHA="6b06b849948b12d46ed17e9787c4872ba4271222dbafcbd19e5224cda139bb82"

SMOKE_EVENT="event000.tbl"
SMOKE_FIRST=1
SMOKE_LAST=24
SECTOR=2048

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def sha256_segment(path,offset,size):
    h=hashlib.sha256()
    remain=size
    with Path(path).open("rb") as f:
        f.seek(offset)
        while remain:
            b=f.read(min(remain,1024*1024))
            if not b:
                raise RuntimeError("unexpected EOF while hashing ISO extent")
            h.update(b)
            remain-=len(b)
    return h.hexdigest()

def read_tsv(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def controls(s):
    return re.findall(r"<[^>]+>",s or "")

def load_mapping(path):
    rows=read_tsv(path)
    char_bytes={}
    for r in rows:
        h=r.get("hangul","")
        sj=r.get("donor_sjis_hex","")
        if h and len(h)==1 and sj:
            char_bytes[h]=bytes.fromhex(sj)
    if len(char_bytes)!=694:
        raise RuntimeError("mapping row count mismatch: %d" % len(char_bytes))
    return char_bytes

def runtime_encode(s,char_bytes):
    out=bytearray()
    for c in s:
        if c==" ":
            # Event dialogue runtime treats ASCII 0x20 as a field/text terminator.
            # Native Japanese event scripts use ideographic space U+3000 (SJIS 81 40),
            # which is parsed as a normal two-byte glyph and renders blank.
            out.extend(b"\x81\x40")
        elif c in char_bytes:
            out.extend(char_bytes[c])
        else:
            out.extend(c.encode("cp932","strict"))
    return bytes(out)

def locate_event000_source(root):
    candidates=[
        root/"analysis"/"stage8"/"decoded_tbl"/"kr"/"event000.tbl",
        root/"analysis"/"stage9"/"decoded_tbl"/"kr"/"event000.tbl",
        root/"analysis"/"stage14"/"test_patch"/"event000_original.tbl",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise RuntimeError("decoded event000.tbl source not found")

def split_line_ending(line):
    if line.endswith(b"\r\n"):
        return line[:-2],b"\r\n"
    if line.endswith(b"\n"):
        return line[:-1],b"\n"
    if line.endswith(b"\r"):
        return line[:-1],b"\r"
    return line,b""

def build_smoke_tbl(source,out_path,manifest_rows,char_bytes):
    targets={
        int(r["event_display_index"]):r
        for r in manifest_rows
        if r["event_file"]==SMOKE_EVENT
        and SMOKE_FIRST<=int(r["event_display_index"])<=SMOKE_LAST
    }
    expected=set(range(SMOKE_FIRST,SMOKE_LAST+1))
    if set(targets)!=expected:
        raise RuntimeError("SUB29 smoke rows missing")

    raw=source.read_bytes()
    lines=raw.splitlines(keepends=True)
    out=[]
    display_index=0
    changed=[]
    cmd_re=re.compile(br"^(MSG|MSG_FORCED|MSG_SYS) =")

    for line in lines:
        body,eol=split_line_ending(line)
        if not cmd_re.match(body):
            out.append(line)
            continue

        display_index+=1
        if display_index not in targets:
            out.append(line)
            continue

        r=targets[display_index]
        prefix=(
            r["command"]+" ="+r["speaker_code"]+","+r["voice_id"]+","
        ).encode("ascii")

        if not body.startswith(prefix):
            raise RuntimeError(
                "event000 row %d prefix mismatch: expected %r got %r"
                % (display_index,prefix,body[:len(prefix)+32])
            )

        old_payload=body[len(prefix):]
        try:
            old_jp=old_payload.decode("cp932")
        except Exception as e:
            raise RuntimeError("old payload cp932 decode failed row %d: %r" % (display_index,e))

        if old_jp!=r["japanese"]:
            raise RuntimeError(
                "event000 row %d JP mismatch\nmanifest=%r\nsource=%r"
                % (display_index,r["japanese"],old_jp)
            )

        new_payload=runtime_encode(r["final_korean"],char_bytes)
        if b" " in new_payload:
            raise RuntimeError(
                "ASCII 0x20 remains inside encoded payload row %d" % display_index
            )
        expected_spaces=r["final_korean"].count(" ")
        actual_fullwidth=new_payload.count(b"\x81\x40")
        if actual_fullwidth<expected_spaces:
            raise RuntimeError(
                "fullwidth-space conversion mismatch row %d: expected at least %d got %d"
                % (display_index,expected_spaces,actual_fullwidth)
            )
        out.append(prefix+new_payload+eol)
        changed.append({
            "event_display_index":display_index,
            "command":r["command"],
            "speaker_code":r["speaker_code"],
            "voice_id":r["voice_id"],
            "topology_status":r["topology_status"],
            "japanese":r["japanese"],
            "final_korean":r["final_korean"],
            "old_payload_bytes":len(old_payload),
            "new_payload_bytes":len(new_payload),
            "ascii_space_count_source":r["final_korean"].count(" "),
            "fullwidth_space_8140_count_encoded":new_payload.count(b"\x81\x40"),
            "ascii_20_count_encoded":new_payload.count(b" "),
            "control_tokens":" ".join(controls(r["final_korean"])),
        })

    if len(changed)!=(SMOKE_LAST-SMOKE_FIRST+1):
        raise RuntimeError("changed rows=%d expected=%d" % (
            len(changed),SMOKE_LAST-SMOKE_FIRST+1
        ))

    out_path.write_bytes(b"".join(out))
    return changed

def run_live(cmd,log_path,cwd=None):
    env=os.environ.copy()
    env["PYTHONUTF8"]="1"
    env["PYTHONIOENCODING"]="utf-8"
    print()
    print("[RUN] "+" ".join(str(x) for x in cmd),flush=True)
    with Path(log_path).open("w",encoding="utf-8") as log:
        p=subprocess.Popen(
            [str(x) for x in cmd],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=(0x08000000 if os.name=="nt" else 0),
        )
        for line in p.stdout:
            print(line,end="",flush=True)
            log.write(line)
            log.flush()
        rc=p.wait()
    if rc!=0:
        raise RuntimeError("command failed rc=%d: %s" % (rc,cmd[0]))

def iso_root_record(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR)
        pvd=f.read(SECTOR)
    if len(pvd)!=SECTOR or pvd[0]!=1 or pvd[1:6]!=b"CD001":
        raise RuntimeError("ISO9660 PVD not found")
    rec=pvd[156:190]
    if not rec or rec[0]<34:
        raise RuntimeError("invalid ISO root record")
    lba=int.from_bytes(rec[2:6],"little")
    size=int.from_bytes(rec[10:14],"little")
    return lba,size

def iso_dir_entries(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR)
        data=f.read(size)
    if len(data)!=size:
        raise RuntimeError("short ISO directory read")
    entries=[]
    pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//SECTOR)+1)*SECTOR
            continue
        rec=data[pos:pos+ln]
        if len(rec)<34:
            raise RuntimeError("short ISO directory record")
        extent=int.from_bytes(rec[2:6],"little")
        length=int.from_bytes(rec[10:14],"little")
        flags=rec[25]
        nlen=rec[32]
        nameb=rec[33:33+nlen]
        if nameb==b"\x00":
            name="."
        elif nameb==b"\x01":
            name=".."
        else:
            name=nameb.decode("ascii",errors="replace")
            if ";" in name:
                name=name.split(";",1)[0]
        entries.append({
            "name":name,
            "lba":extent,
            "size":length,
            "is_dir":bool(flags&2),
        })
        pos+=ln
    return entries

def iso_find(iso,path):
    parts=[x for x in path.replace("\\","/").split("/") if x]
    lba,size=iso_root_record(iso)
    current={"lba":lba,"size":size,"is_dir":True,"name":"/"}
    for part in parts:
        if not current["is_dir"]:
            raise RuntimeError("ISO path traversed through file: "+path)
        entries=iso_dir_entries(iso,current["lba"],current["size"])
        hit=None
        for e in entries:
            if e["name"].casefold()==part.casefold():
                hit=e
                break
        if hit is None:
            raise RuntimeError("ISO path not found: "+path+" at "+part)
        current=hit
    return current

def verify_iso_file(iso,iso_path,host):
    e=iso_find(iso,iso_path)
    if e["is_dir"]:
        raise RuntimeError("expected ISO file, found directory: "+iso_path)
    host_size=Path(host).stat().st_size
    host_sha=sha256_file(host)
    iso_sha=sha256_segment(iso,e["lba"]*SECTOR,e["size"])
    ok=(e["size"]==host_size and iso_sha==host_sha)
    return {
        "iso_path":iso_path,
        "iso_lba":e["lba"],
        "iso_size":e["size"],
        "host_path":str(host),
        "host_size":host_size,
        "host_sha256":host_sha,
        "iso_sha256":iso_sha,
        "match":ok,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    source_iso=root/"kr"/"Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
    mapping=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    manifest=root/"analysis"/"sub"/"sub29_completed_korean_draft"/"sub29_full_korean_draft_1976.tsv"
    boot=root/"analysis"/"sub"/"sub16_collision_free_boot"/"BOOT_sub16_collision_free_hangul.bin"
    stage14=root/"analysis"/"stage14"/"naruto_patcher.py"
    stage24=root/"analysis"/"stage24"/"stage24_iso_multi_patch.py"

    print("[1/8] Verify authoritative inputs",flush=True)
    required=[source_iso,mapping,manifest,boot,stage14,stage24]
    for p in required:
        if not p.exists():
            raise RuntimeError("required input missing: "+str(p))

    checks=[
        ("source ISO",source_iso,EXPECTED_SOURCE_ISO_SHA),
        ("mapping",mapping,EXPECTED_MAPPING_SHA),
        ("SUB16 BOOT",boot,EXPECTED_BOOT_SHA),
        ("SUB29 manifest",manifest,EXPECTED_SUB29_MANIFEST_SHA),
        ("Stage14 patcher",stage14,EXPECTED_STAGE14_PATCHER_SHA),
    ]
    input_hashes={}
    for name,p,expected in checks:
        got=sha256_file(p)
        input_hashes[name]=got
        print("  %s: %s" % (name,got),flush=True)
        if got.lower()!=expected.lower():
            raise RuntimeError("%s SHA mismatch" % name)
    stage24_sha=sha256_file(stage24)
    input_hashes["Stage24 patcher"]=stage24_sha
    print("  Stage24 patcher: %s" % stage24_sha,flush=True)

    print("[2/8] Build event000 rows 1..24 Korean replacement",flush=True)
    rows=read_tsv(manifest)
    char_bytes=load_mapping(mapping)
    source_tbl=locate_event000_source(root)
    source_tbl_bytes=source_tbl.read_bytes()
    native_fullwidth_space_count=source_tbl_bytes.count(b"\x81\x40")
    if native_fullwidth_space_count<1:
        raise RuntimeError("original event000 has no native SJIS 0x8140 space evidence")
    print("  original event000 native SJIS 8140 spaces: %d" % native_fullwidth_space_count,flush=True)
    replacement=out/"event000_sub30_fix1_smoke.tbl"
    smoke_rows=build_smoke_tbl(source_tbl,replacement,rows,char_bytes)
    encoded_ascii20=sum(int(r["ascii_20_count_encoded"]) for r in smoke_rows)
    if encoded_ascii20!=0:
        raise RuntimeError("ASCII 0x20 remains in smoke payloads: %d" % encoded_ascii20)

    statuses={r["topology_status"] for r in smoke_rows}
    required_statuses={
        "STABLE_1G1S",
        "SPLIT_1S_TO_2G",
        "EXCEPTION_1G1S",
        "EXCEPTION_UNVOICED_1G1S",
        "DIRECT_TRANSLATE",
        "MERGE_SUBTITLE_PARTS_TO_1G",
    }
    if not required_statuses.issubset(statuses):
        raise RuntimeError("smoke topology coverage incomplete: %r" % sorted(statuses))
    if not any("<br>" in r["final_korean"] for r in smoke_rows):
        raise RuntimeError("no <br> smoke row")
    if not any("<KOFF>" in r["final_korean"] for r in smoke_rows):
        raise RuntimeError("no KOFF/KON smoke row")

    write_tsv(
        out/"sub30_fix1_smoke_rows.tsv",
        smoke_rows,
        [
            "event_display_index","command","speaker_code","voice_id","topology_status",
            "japanese","final_korean","old_payload_bytes","new_payload_bytes",
            "ascii_space_count_source","fullwidth_space_8140_count_encoded",
            "ascii_20_count_encoded","control_tokens"
        ]
    )
    print("  decoded source: %s" % source_tbl,flush=True)
    print("  changed rows: %d" % len(smoke_rows),flush=True)

    print("[3/8] Rebuild DAT/IDX with Stage14",flush=True)
    stage14_out=out/"stage14_build"
    if stage14_out.exists():
        shutil.rmtree(stage14_out)
    cmd=[
        sys.executable,str(stage14),
        "--root",str(root),
        "--output",str(stage14_out),
        "--replace","event000.tbl="+str(replacement),
        "--force",
    ]
    run_live(cmd,out/"sub30_fix1_stage14_console.log")

    patched_dat=stage14_out/"naruto.dat"
    patched_idx=stage14_out/"naruto.idx"
    for p in (patched_dat,patched_idx):
        if not p.exists():
            raise RuntimeError("Stage14 output missing: "+str(p))
    stage14_dat_sha=sha256_file(patched_dat)
    stage14_idx_sha=sha256_file(patched_idx)
    print("  DAT SHA: %s" % stage14_dat_sha,flush=True)
    print("  IDX SHA: %s" % stage14_idx_sha,flush=True)

    print("[4/8] Build candidate ISO with Stage24",flush=True)
    stage24_report=out/"stage24_report"
    if stage24_report.exists():
        shutil.rmtree(stage24_report)
    candidate_iso=out/"SUB30_FIX1_candidate.iso"
    if candidate_iso.exists():
        candidate_iso.unlink()

    cmd=[
        sys.executable,str(stage24),
        "--source-iso",str(source_iso),
        "--dat",str(patched_dat),
        "--idx",str(patched_idx),
        "--boot",str(boot),
        "--output-iso",str(candidate_iso),
        "--report-dir",str(stage24_report),
    ]
    run_live(cmd,out/"sub30_fix1_stage24_console.log")
    if not candidate_iso.exists():
        raise RuntimeError("Stage24 candidate ISO missing")

    print("[5/8] Independently verify ISO9660 embedded files",flush=True)
    iso_checks=[
        verify_iso_file(candidate_iso,"PSP_GAME/SYSDIR/BOOT.BIN",boot),
        verify_iso_file(candidate_iso,"PSP_GAME/USRDIR/NARUTO.DAT",patched_dat),
        verify_iso_file(candidate_iso,"PSP_GAME/USRDIR/NARUTO.IDX",patched_idx),
    ]
    for c in iso_checks:
        print(
            "  %s size=%d match=%s sha=%s"
            % (c["iso_path"],c["iso_size"],c["match"],c["iso_sha256"]),
            flush=True
        )
        if not c["match"]:
            raise RuntimeError("embedded ISO verification failed: "+c["iso_path"])

    print("[6/8] Verify smoke coverage and expected checkpoints",flush=True)
    key_indices={1,3,8,11,12,16,19,23,24}
    key_rows=[r for r in smoke_rows if int(r["event_display_index"]) in key_indices]
    if len(key_rows)!=len(key_indices):
        raise RuntimeError("checkpoint rows missing")
    write_tsv(
        out/"sub30_fix1_expected_checkpoints.tsv",
        key_rows,
        [
            "event_display_index","speaker_code","voice_id","topology_status",
            "final_korean","control_tokens","new_payload_bytes"
        ]
    )

    instructions=[
        "Naruto PSP SUB30 FIX1 Korean Translation Runtime Smoke",
        "",
        "ISO:",
        "  "+str(root/"Naruto - SUB30 FIX1 Korean Translation Runtime Smoke.iso"),
        "",
        "Scope:",
        "  event000 display messages #1..#24 only",
        "",
        "Runtime checks:",
        "  1. Start the opening story/event000.",
        "  2. Confirm Korean now continues past every word boundary (no first-space truncation).",
        "  3. Confirm the fullwidth/native spaces look acceptable between Korean words.",
        "  4. Confirm Korean glyphs render normally with no Japanese donor glyph leakage.",
        "  5. Confirm <br> rows wrap at the intended positions.",
        "  6. Confirm Shikamaru thought row (#8) displays correctly with KOFF/KON controls.",
        "  7. Confirm the former 2G->1S split is natural across #11 and #12.",
        "  8. Confirm unvoiced row #16, direct-translation rows #19/#21, and merged row #23.",
        "  9. Continue through #24 and watch for crash, truncation, text overrun, or timing issues.",
        "",
        "Key expected text:",
    ]
    for r in key_rows:
        instructions.append(
            "  #%s %s %s: %s"
            % (
                r["event_display_index"],
                r["speaker_code"],
                r["voice_id"] or "<NO-VOICE>",
                r["final_korean"],
            )
        )
    (out/"TEST_INSTRUCTIONS.txt").write_text(
        "\n".join(instructions)+"\n",encoding="utf-8-sig"
    )

    print("[7/8] Promote verified ISO",flush=True)
    canonical=root/"Naruto - SUB30 FIX1 Korean Translation Runtime Smoke.iso"
    previous=out/"previous_success.iso"
    if canonical.exists():
        if previous.exists():
            previous.unlink()
        canonical.replace(previous)
    candidate_iso.replace(canonical)

    canonical_sha=sha256_file(canonical)
    print("  promoted: %s" % canonical,flush=True)
    print("  ISO SHA256: %s" % canonical_sha,flush=True)

    print("[8/8] Final report",flush=True)
    report={
        "stage":"SUB30_FIX1",
        "mode":"EVENT000_1_24_KOREAN_RUNTIME_SMOKE_FULLWIDTH_SPACE_FIX",
        "source_iso":str(source_iso),
        "source_iso_sha256":input_hashes["source ISO"],
        "mapping_sha256":input_hashes["mapping"],
        "boot_sha256":input_hashes["SUB16 BOOT"],
        "sub29_manifest_sha256":input_hashes["SUB29 manifest"],
        "stage14_patcher_sha256":input_hashes["Stage14 patcher"],
        "stage24_patcher_sha256":stage24_sha,
        "decoded_event_source":str(source_tbl),
        "smoke_event":SMOKE_EVENT,
        "smoke_first_display_index":SMOKE_FIRST,
        "smoke_last_display_index":SMOKE_LAST,
        "smoke_rows":len(smoke_rows),
        "runtime_space_policy":"U+0020 -> U+3000 / SJIS 0x8140",
        "original_event000_native_8140_count":native_fullwidth_space_count,
        "encoded_ascii_20_count":encoded_ascii20,
        "topology_statuses":sorted(statuses),
        "stage14_dat_size":patched_dat.stat().st_size,
        "stage14_dat_sha256":stage14_dat_sha,
        "stage14_idx_size":patched_idx.stat().st_size,
        "stage14_idx_sha256":stage14_idx_sha,
        "iso_embedded_checks":iso_checks,
        "final_iso":str(canonical),
        "final_iso_size":canonical.stat().st_size,
        "final_iso_sha256":canonical_sha,
        "build_validation_pass":True,
        "visual_runtime_validation_pending":True,
    }
    (out/"sub30_fix1_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB30 - Korean Translation Runtime Smoke",
        "",
        "BuildValidation=PASS",
        "VisualRuntimeValidation=PENDING",
        "SmokeEvent=event000.tbl",
        "SmokeRows=1..24",
        "SmokeRowCount=%d" % len(smoke_rows),
        "SpacePolicy=ASCII U+0020 -> native U+3000 / SJIS 81 40",
        "EncodedASCII20Count=%d" % encoded_ascii20,
        "OriginalEvent000Native8140Count=%d" % native_fullwidth_space_count,
        "",
        "Stage14DAT_SHA256="+stage14_dat_sha,
        "Stage14IDX_SHA256="+stage14_idx_sha,
        "FinalISO_SHA256="+canonical_sha,
        "FinalISO="+str(canonical),
        "",
        "EmbeddedBOOTMatch=YES",
        "EmbeddedDATMatch=YES",
        "EmbeddedIDXMatch=YES",
        "",
        "Next:",
        "  Run the ISO in PPSSPP and visually verify event000 messages #1..#24.",
        "  Do not batch-patch all 39 event TBLs until this smoke is visually accepted.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
