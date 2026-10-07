#!/usr/bin/env python3
# -*- coding: ascii -*-
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

SECTOR=2048

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
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
                raise RuntimeError("unexpected EOF")
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

def split_line_ending(line):
    if line.endswith(b"\r\n"):
        return line[:-2],b"\r\n"
    if line.endswith(b"\n"):
        return line[:-1],b"\n"
    if line.endswith(b"\r"):
        return line[:-1],b"\r"
    return line,b""

def load_mapping(path):
    rows=read_tsv(path)
    m={}
    for r in rows:
        h=r.get("hangul","")
        sj=r.get("donor_sjis_hex","")
        if h and len(h)==1 and sj:
            m[h]=bytes.fromhex(sj)
    if len(m)!=694:
        raise RuntimeError("font mapping count mismatch: %d" % len(m))
    return m

def runtime_encode(text,mapping):
    if "\r" in text or "\n" in text:
        raise RuntimeError("literal newline in final Korean")
    if "\u3000" in text:
        raise RuntimeError("ideographic space remains in final Korean")
    out=bytearray()
    source_spaces=0
    for c in text:
        if c==" ":
            out.append(0xA0)
            source_spaces+=1
        elif c in mapping:
            out.extend(mapping[c])
        else:
            out.extend(c.encode("cp932","strict"))
    if b"\x20" in out:
        raise RuntimeError("ASCII 0x20 remains in encoded payload")
    return bytes(out),source_spaces

def build_event_tbl(source,out_path,targets,mapping):
    raw=source.read_bytes()
    lines=raw.splitlines(keepends=True)
    result=[]
    display_index=0
    replaced=[]
    cmd_re=re.compile(br"^(MSG|MSG_FORCED|MSG_SYS) =")

    expected=set(targets.keys())
    seen=set()

    for line in lines:
        body,eol=split_line_ending(line)
        if not cmd_re.match(body):
            result.append(line)
            continue

        display_index+=1
        if display_index not in targets:
            result.append(line)
            continue

        r=targets[display_index]
        prefix=(r["command"]+" ="+r["speaker_code"]+","+r["voice_id"]+",").encode("ascii")
        if not body.startswith(prefix):
            raise RuntimeError(
                "%s#%03d prefix mismatch expected=%r got=%r"
                % (r["event_file"],display_index,prefix,body[:len(prefix)+48])
            )

        old_payload=body[len(prefix):]
        try:
            old_jp=old_payload.decode("cp932")
        except Exception as e:
            raise RuntimeError(
                "%s#%03d source CP932 decode failed: %s"
                % (r["event_file"],display_index,e)
            )

        if old_jp!=r["japanese"]:
            raise RuntimeError(
                "%s#%03d JP mismatch\nmanifest=%r\nsource=%r"
                % (r["event_file"],display_index,r["japanese"],old_jp)
            )

        new_payload,spaces=runtime_encode(r["final_korean"],mapping)
        result.append(prefix+new_payload+eol)
        seen.add(display_index)
        replaced.append({
            "review_index":r["review_index"],
            "game_key":r["game_key"],
            "event_file":r["event_file"],
            "event_display_index":r["event_display_index"],
            "command":r["command"],
            "speaker_code":r["speaker_code"],
            "voice_id":r["voice_id"],
            "old_payload_bytes":len(old_payload),
            "new_payload_bytes":len(new_payload),
            "source_ascii_spaces":spaces,
            "encoded_ascii20_count":new_payload.count(b"\x20"),
            "final_korean":r["final_korean"],
        })

    if seen!=expected:
        missing=sorted(expected-seen)
        extra=sorted(seen-expected)
        raise RuntimeError(
            "%s replacement set mismatch missing=%r extra=%r"
            % (source.name,missing,extra)
        )

    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_bytes(b"".join(result))
    return replaced

def run_live(cmd,log_path,cwd=None):
    env=os.environ.copy()
    env["PYTHONUTF8"]="1"
    env["PYTHONIOENCODING"]="utf-8"
    print("\n[RUN] "+" ".join(str(x) for x in cmd),flush=True)
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
    return int.from_bytes(rec[2:6],"little"),int.from_bytes(rec[10:14],"little")

def iso_dir_entries(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR)
        data=f.read(size)
    if len(data)!=size:
        raise RuntimeError("short ISO directory read")
    out=[]
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
        out.append({"name":name,"lba":extent,"size":length,"is_dir":bool(flags&2)})
        pos+=ln
    return out

def iso_find(iso,path):
    parts=[p for p in path.replace("\\","/").split("/") if p]
    lba,size=iso_root_record(iso)
    cur={"name":"/","lba":lba,"size":size,"is_dir":True}
    for part in parts:
        entries=iso_dir_entries(iso,cur["lba"],cur["size"])
        hit=None
        for e in entries:
            if e["name"].casefold()==part.casefold():
                hit=e
                break
        if hit is None:
            raise RuntimeError("ISO path not found: %s at %s" % (path,part))
        cur=hit
    return cur

def iso_file_sha(iso,path):
    e=iso_find(iso,path)
    if e["is_dir"]:
        raise RuntimeError("expected file: "+path)
    return {
        "path":path,
        "size":e["size"],
        "lba":e["lba"],
        "sha256":sha256_segment(iso,e["lba"]*SECTOR,e["size"]),
    }

def list_movie_pmfs(iso):
    d=iso_find(iso,"PSP_GAME/USRDIR/movie")
    if not d["is_dir"]:
        raise RuntimeError("movie path is not directory")
    entries=iso_dir_entries(iso,d["lba"],d["size"])
    names=sorted(
        e["name"] for e in entries
        if not e["is_dir"] and e["name"].lower().endswith(".pmf")
    )
    return names

def compare_movies(source_iso,output_iso,required_names):
    source_names=list_movie_pmfs(source_iso)
    output_names=list_movie_pmfs(output_iso)
    if source_names!=output_names:
        raise RuntimeError(
            "movie PMF name set changed source=%r output=%r"
            % (source_names,output_names)
        )
    missing=[n for n in required_names if n not in source_names]
    if missing:
        raise RuntimeError("required MOV06E PMFs missing: %r" % missing)

    rows=[]
    for name in source_names:
        p="PSP_GAME/USRDIR/movie/"+name
        a=iso_file_sha(source_iso,p)
        b=iso_file_sha(output_iso,p)
        same=(a["size"]==b["size"] and a["sha256"]==b["sha256"])
        rows.append({
            "filename":name,
            "required_final_movie":"YES" if name in required_names else "NO",
            "source_size":a["size"],
            "output_size":b["size"],
            "source_sha256":a["sha256"],
            "output_sha256":b["sha256"],
            "match":"YES" if same else "NO",
        })
        if not same:
            raise RuntimeError("MOV06E PMF changed unexpectedly: "+name)
    return rows

def verify_iso_target(iso,iso_path,host):
    e=iso_file_sha(iso,iso_path)
    hsha=sha256_file(host)
    hsize=Path(host).stat().st_size
    ok=(e["size"]==hsize and e["sha256"]==hsha)
    if not ok:
        raise RuntimeError("integrated ISO target mismatch: "+iso_path)
    return {
        "iso_path":iso_path,
        "iso_size":e["size"],
        "host_size":hsize,
        "iso_sha256":e["sha256"],
        "host_sha256":hsha,
        "match":"YES",
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--work",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    work=Path(args.work)
    work.mkdir(parents=True,exist_ok=True)

    cfg=json.loads(
        Path(__file__).with_name("sub34_integration_manifest.json").read_text(encoding="ascii")
    )

    source_iso=root/cfg["source_iso_relative"]
    final_iso=root/cfg["final_iso_relative"]
    manifest=root/cfg["sub33_patcher_ready_relative"]
    mapping_path=root/cfg["mapping_relative"]
    boot=root/cfg["boot_relative"]
    stage14=root/cfg["stage14_relative"]
    stage24=root/cfg["stage24_relative"]
    decoded_root=root/cfg["decoded_tbl_root_relative"]

    print("[1/9] Verify exact MOV06E base and SUB authorities",flush=True)
    required=[source_iso,manifest,mapping_path,boot,stage14,stage24,decoded_root]
    for p in required:
        if not p.exists():
            raise RuntimeError("required input missing: "+str(p))

    # No fallback to the old KR ISO is allowed.
    if "mov06e_tail_trim_final" not in str(source_iso).lower():
        raise RuntimeError("source ISO is not the exact MOV06E final base")

    if sha256_file(manifest)!=cfg["sub33_patcher_ready_sha256"]:
        raise RuntimeError("SUB33 patcher-ready SHA mismatch")
    if sha256_file(mapping_path)!=cfg["mapping_sha256"]:
        raise RuntimeError("font mapping SHA mismatch")
    if sha256_file(boot)!=cfg["boot_sha256"]:
        raise RuntimeError("SUB16 BOOT SHA mismatch")
    if sha256_file(stage14)!=cfg["stage14_sha256"]:
        raise RuntimeError("Stage14 patcher SHA mismatch")

    source_iso_sha=sha256_file(source_iso)
    stage24_sha=sha256_file(stage24)
    print("  MOV06E source SHA: "+source_iso_sha,flush=True)
    print("  Stage24 SHA: "+stage24_sha,flush=True)

    rows=read_tsv(manifest)
    if len(rows)!=cfg["expected_dialogue_rows"]:
        raise RuntimeError("SUB33 row count mismatch")
    events=defaultdict(dict)
    for r in rows:
        ev=r["event_file"]
        di=int(r["event_display_index"])
        if di in events[ev]:
            raise RuntimeError("duplicate event/display key: %s#%d" % (ev,di))
        events[ev][di]=r
    if len(events)!=cfg["expected_event_files"]:
        raise RuntimeError("event file count mismatch")

    mapping=load_mapping(mapping_path)

    print("[2/9] Preflight A0 narrow-space runtime encoding",flush=True)
    spaces_total=0
    for r in rows:
        enc,spaces=runtime_encode(r["final_korean"],mapping)
        spaces_total+=spaces
    print("  Korean ASCII spaces converted to A0: %d" % spaces_total,flush=True)

    print("[3/9] Build all 39 patched event TBL files",flush=True)
    tbl_out=work/"event_tbl"
    if tbl_out.exists():
        shutil.rmtree(tbl_out)
    tbl_out.mkdir(parents=True)

    all_replaced=[]
    replacement_paths={}
    for ev in sorted(events):
        src=decoded_root/ev
        if not src.exists():
            raise RuntimeError("decoded TBL source missing: "+str(src))
        dst=tbl_out/ev
        changed=build_event_tbl(src,dst,events[ev],mapping)
        all_replaced.extend(changed)
        replacement_paths[ev]=dst
        print("  %s: %d rows" % (ev,len(changed)),flush=True)

    if len(all_replaced)!=cfg["expected_dialogue_rows"]:
        raise RuntimeError("patched dialogue row total mismatch")
    if any(int(r["encoded_ascii20_count"])!=0 for r in all_replaced):
        raise RuntimeError("ASCII 0x20 remains in patched event payloads")

    write_tsv(
        work/"sub34_event_patch_manifest.tsv",
        all_replaced,
        [
            "review_index","game_key","event_file","event_display_index","command",
            "speaker_code","voice_id","old_payload_bytes","new_payload_bytes",
            "source_ascii_spaces","encoded_ascii20_count","final_korean"
        ]
    )

    print("[4/9] Rebuild DAT/IDX with Stage14",flush=True)
    stage14_out=work/"stage14_build"
    if stage14_out.exists():
        shutil.rmtree(stage14_out)

    cmd=[sys.executable,str(stage14),"--root",str(root),"--output",str(stage14_out)]
    for ev in sorted(replacement_paths):
        cmd.extend(["--replace",ev+"="+str(replacement_paths[ev])])
    cmd.append("--force")
    run_live(cmd,work/"sub34_stage14_console.log")

    patched_dat=stage14_out/"naruto.dat"
    patched_idx=stage14_out/"naruto.idx"
    if not patched_dat.exists() or not patched_idx.exists():
        raise RuntimeError("Stage14 did not produce DAT/IDX")

    print("[5/9] Build integrated ISO from exact MOV06E base",flush=True)
    stage24_report=work/"stage24_report"
    if stage24_report.exists():
        shutil.rmtree(stage24_report)

    candidate=work/"Naruto_KR_MOV06E_SUB34_candidate.iso"
    if candidate.exists():
        candidate.unlink()

    cmd=[
        sys.executable,str(stage24),
        "--source-iso",str(source_iso),
        "--dat",str(patched_dat),
        "--idx",str(patched_idx),
        "--boot",str(boot),
        "--output-iso",str(candidate),
        "--report-dir",str(stage24_report),
    ]
    run_live(cmd,work/"sub34_stage24_console.log")
    if not candidate.exists():
        raise RuntimeError("Stage24 integrated ISO missing")

    print("[6/9] Independently verify BOOT/EBOOT/DAT/IDX",flush=True)
    target_rows=[
        verify_iso_target(candidate,"PSP_GAME/SYSDIR/BOOT.BIN",boot),
        verify_iso_target(candidate,"PSP_GAME/SYSDIR/EBOOT.BIN",boot),
        verify_iso_target(candidate,"PSP_GAME/USRDIR/naruto.dat",patched_dat),
        verify_iso_target(candidate,"PSP_GAME/USRDIR/naruto.idx",patched_idx),
    ]
    write_tsv(
        work/"sub34_iso_target_verification.tsv",
        target_rows,
        ["iso_path","iso_size","host_size","iso_sha256","host_sha256","match"]
    )

    print("[7/9] Verify MOV06E PMFs are byte-identical",flush=True)
    movie_rows=compare_movies(
        source_iso,candidate,
        [x.lower() for x in cfg["translated_movie_pmfs"]]
    )
    write_tsv(
        work/"sub34_movie_preservation.tsv",
        movie_rows,
        [
            "filename","required_final_movie","source_size","output_size",
            "source_sha256","output_sha256","match"
        ]
    )
    translated_ok=sum(
        r["required_final_movie"]=="YES" and r["match"]=="YES"
        for r in movie_rows
    )
    if translated_ok!=len(cfg["translated_movie_pmfs"]):
        raise RuntimeError("required translated PMF preservation count mismatch")

    print("[8/9] Promote integrated ISO",flush=True)
    final_iso.parent.mkdir(parents=True,exist_ok=True)
    if final_iso.exists():
        final_iso.unlink()
    shutil.move(str(candidate),str(final_iso))
    final_sha=sha256_file(final_iso)

    print("[9/9] Write integration report",flush=True)
    report={
        "stage":"SUB34_MOV06E_SUB_INTEGRATION",
        "source_iso":str(source_iso),
        "source_iso_sha256":source_iso_sha,
        "final_iso":str(final_iso),
        "final_iso_sha256":final_sha,
        "source_is_exact_mov06e":True,
        "sub33_rows":len(rows),
        "event_files_patched":len(events),
        "event_rows_patched":len(all_replaced),
        "space_encoding":"A0_NARROW_PROBE",
        "source_ascii_spaces_converted":spaces_total,
        "encoded_ascii20_remaining":0,
        "sub16_boot_sha256":sha256_file(boot),
        "patched_dat_sha256":sha256_file(patched_dat),
        "patched_idx_sha256":sha256_file(patched_idx),
        "movie_pmf_count":len(movie_rows),
        "movie_pmfs_byte_identical":all(r["match"]=="YES" for r in movie_rows),
        "required_translated_movie_pmfs":cfg["translated_movie_pmfs"],
        "required_translated_movie_pmfs_preserved":translated_ok,
        "stage24_sha256":stage24_sha,
        "runtime_visual_validation_required":True,
        "game_files_modified":True,
    }
    (work/"sub34_integration_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB34 - MOV06E + SUB Final Integration",
        "",
        "SourceBase=MOV06E exact final ISO",
        "SourceISOSHA256="+source_iso_sha,
        "FinalISO="+str(final_iso),
        "FinalISOSHA256="+final_sha,
        "EventFilesPatched=%d" % len(events),
        "DialogueRowsPatched=%d" % len(all_replaced),
        "SpaceEncoding=A0_NARROW_PROBE",
        "ASCII20Remaining=0",
        "MoviePMFCount=%d" % len(movie_rows),
        "MoviePMFsByteIdentical=YES",
        "RequiredTranslatedPMFsPreserved=%d/%d" % (
            translated_ok,len(cfg["translated_movie_pmfs"])
        ),
        "StaticIntegrationQA=PASS",
        "RuntimeVisualValidationRequired=YES",
    ]
    (work/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
