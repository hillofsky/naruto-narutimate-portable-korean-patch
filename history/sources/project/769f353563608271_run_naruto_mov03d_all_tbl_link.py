#!/usr/bin/env python3
# Naruto PSP MOV03D - all TBL movie / voice linkage scan
#
# Proven game-specific TBL codec from prior Stage13/14 work:
#   " 3;1" = XOR 0x72 + 4096-byte LZSS
#       window=0x1000, initial ring pos=0xFEE
#       flags LSB-first
#       flag bit 1 = literal
#       flag bit 0 = match
#       offset = b1 | ((b2 & 0xF0) << 4)
#       length = (b2 & 0x0F) + 3
#       flags/literal/match bytes are XORed with 0x72 before use
#   " 3;0" = uncompressed payload XOR 0x72
#
# No gameplay required.

from __future__ import annotations
import csv, hashlib, os, re, shutil, struct, subprocess, sys, traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
DAT = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "naruto.dat"
TOOLS = ROOT / "tools"
STAGE = ROOT / "analysis" / "mov" / "mov03d_all_tbl_link"
EXTRACT = STAGE / "tbl_extract"
DECODED = STAGE / "decoded_tbl"
CTX = STAGE / "contexts"
LOG = STAGE / "quickbms_all_tbl.log"

DM_NAMES = [f"dm{i:03d}" for i in range(1,11)]
KNOWN_MOVIES = [
    "da101","da102","da103","da201",
    "dk101","dk102","dk103","dk104","dk201","dk202","dk203",
] + DM_NAMES

MOVIE_RE = re.compile(r"(?im)^\s*MOVIE\s*=\s*([A-Za-z0-9_]+)\s*$")
BARE_MOVIE_RE = re.compile(r"(?i)\b(?:da\d{3}|dk\d{3}|dm\d{3})\b")
VOICE_RE = re.compile(r"(?i)\bs_[ab]\d{1,3}_[0-9]{2,4}(?:_plus)?\b")
SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")

def write_tsv(path: Path, rows: list[dict], fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if fields is None:
        fields=[]
        for row in rows:
            for k in row:
                if k not in fields:
                    fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def find_quickbms():
    for base in [ROOT/"tools"/"quickbms", ROOT/"tools", ROOT]:
        if not base.exists():
            continue
        hits=sorted(base.rglob("quickbms.exe"))
        if hits:
            return hits[0]
    return None

def find_bms():
    for base in [ROOT/"tools"/"quickbms", ROOT/"tools", ROOT]:
        if not base.exists():
            continue
        hits=sorted(base.rglob("macross_pidx.bms"))
        if hits:
            return hits[0]
    return None

def run_quickbms_all_tbl():
    qb=find_quickbms()
    bms=find_bms()
    if not qb:
        raise RuntimeError("quickbms.exe not found. MOV03C should have installed it under tools\\quickbms.")
    if not bms:
        raise RuntimeError("macross_pidx.bms not found. MOV03C should have installed it under tools\\quickbms.")
    if not DAT.exists():
        raise RuntimeError(f"naruto.dat not found: {DAT}")

    if EXTRACT.exists():
        shutil.rmtree(EXTRACT,ignore_errors=True)
    EXTRACT.mkdir(parents=True,exist_ok=True)

    # Filtered extraction first.
    cmd=[str(qb),"-o","-F","*.tbl",str(bms),str(DAT),str(EXTRACT)]
    cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                      text=True,encoding="utf-8",errors="replace",
                      cwd=str(DAT.parent))
    LOG.write_text(
        "COMMANLOCAL_PATH"+" ".join(f'"{x}"' if " " in x else x for x in cmd)+
        "\n\nOUTPULOCAL_PATH"+cp.stdout,
        encoding="utf-8-sig"
    )

    tbls=[p for p in EXTRACT.rglob("*.tbl") if p.is_file()]
    if tbls:
        return qb,bms,cp.returncode,tbls,"FILTERED"

    # Fallback: full extraction once, then keep only TBL files.
    full=STAGE/"full_extract_fallback"
    if full.exists():
        shutil.rmtree(full,ignore_errors=True)
    full.mkdir(parents=True,exist_ok=True)
    cmd2=[str(qb),"-o",str(bms),str(DAT),str(full)]
    cp2=subprocess.run(cmd2,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                       text=True,encoding="utf-8",errors="replace",
                       cwd=str(DAT.parent))
    with LOG.open("a",encoding="utf-8-sig") as f:
        f.write("\n\nFALLBACK COMMANLOCAL_PATH"+
                " ".join(f'"{x}"' if " " in x else x for x in cmd2)+
                "\n\nFALLBACK OUTPULOCAL_PATH"+cp2.stdout)

    tbls=[p for p in full.rglob("*.tbl") if p.is_file()]
    if not tbls:
        raise RuntimeError(
            f"QuickBMS extracted zero *.tbl files. filtered_exit={cp.returncode}, full_exit={cp2.returncode}"
        )
    # Copy only TBL files into compact extraction dir, preserving unique names.
    seen=Counter()
    copied=[]
    for p in tbls:
        name=p.name.lower()
        seen[name]+=1
        dst_name=p.name if seen[name]==1 else f"{p.stem}__dup{seen[name]}{p.suffix}"
        dst=EXTRACT/dst_name
        shutil.copy2(p,dst)
        copied.append(dst)
    shutil.rmtree(full,ignore_errors=True)
    return qb,bms,cp2.returncode,copied,"FULL_FALLBACK"

def decode_3x(blob: bytes):
    if len(blob)<8:
        return blob, "RAW_SHORT", None
    magic=blob[:4]
    expected=struct.unpack_from("<I",blob,4)[0]

    if magic == b" 3;0":
        avail=blob[8:]
        out=bytes((b ^ 0x72) for b in avail[:expected])
        if len(out)!=expected:
            raise ValueError(f"3;0 short payload: got={len(out)} expected={expected}")
        return out, "3;0_XOR72", expected

    if magic != b" 3;1":
        return blob, "RAW", None

    src=8
    window=bytearray(0x1000)
    ring=0xFEE
    out=bytearray()

    while len(out)<expected:
        if src>=len(blob):
            raise ValueError(f"3;1 truncated before flags: got={len(out)} expected={expected}")
        flags=blob[src] ^ 0x72
        src+=1

        for bit in range(8):
            if len(out)>=expected:
                break

            if flags & (1<<bit):
                if src>=len(blob):
                    raise ValueError(f"3;1 truncated literal: got={len(out)} expected={expected}")
                c=blob[src] ^ 0x72
                src+=1
                out.append(c)
                window[ring]=c
                ring=(ring+1)&0xFFF
            else:
                if src+1>=len(blob):
                    raise ValueError(f"3;1 truncated match: got={len(out)} expected={expected}")
                b1=blob[src] ^ 0x72
                b2=blob[src+1] ^ 0x72
                src+=2

                offset=b1 | ((b2 & 0xF0)<<4)
                length=(b2 & 0x0F)+3

                for j in range(length):
                    if len(out)>=expected:
                        break
                    c=window[(offset+j)&0xFFF]
                    out.append(c)
                    window[ring]=c
                    ring=(ring+1)&0xFFF

    if len(out)!=expected:
        raise ValueError(f"3;1 size mismatch: got={len(out)} expected={expected}")
    return bytes(out), "3;1_XOR72_LZSS", expected

def decode_text(data: bytes):
    # Event scripts are ASCII + Shift-JIS text. CP932 handles the actual JP
    # script while preserving ASCII command names.
    for enc in ("cp932","shift_jis"):
        try:
            return data.decode(enc),enc
        except UnicodeDecodeError:
            pass
    return data.decode("cp932",errors="replace"),"cp932_replace"

def current_section(lines, line_idx):
    for j in range(line_idx,-1,-1):
        m=SECTION_RE.match(lines[j])
        if m:
            return m.group(1)
    return ""

def context_text(lines, idx, radius=12):
    lo=max(0,idx-radius)
    hi=min(len(lines),idx+radius+1)
    out=[]
    for i in range(lo,hi):
        mark=">>" if i==idx else "  "
        out.append(f"{mark} {i+1:05d}: {lines[i]}")
    return "\n".join(out)

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    if DECODED.exists():
        shutil.rmtree(DECODED,ignore_errors=True)
    if CTX.exists():
        shutil.rmtree(CTX,ignore_errors=True)
    DECODED.mkdir(parents=True,exist_ok=True)
    CTX.mkdir(parents=True,exist_ok=True)

    print("="*76,flush=True)
    print(" Naruto PSP MOV03D - All TBL movie / voice linkage scan",flush=True)
    print("="*76,flush=True)

    qb,bms,qb_exit,tbls,mode=run_quickbms_all_tbl()
    print(f"QuickBMS : {qb}",flush=True)
    print(f"BMS      : {bms}",flush=True)
    print(f"Mode     : {mode}",flush=True)
    print(f"TBL files: {len(tbls)}",flush=True)

    # Deduplicate exact duplicate files caused by archive aliases.
    by_hash={}
    unique=[]
    aliases=defaultdict(list)
    for p in sorted(tbls,key=lambda x:str(x).lower()):
        raw=p.read_bytes()
        h=sha256(raw)
        aliases[h].append(str(p))
        if h not in by_hash:
            by_hash[h]=p
            unique.append(p)

    inventory=[]
    movie_rows=[]
    bare_rows=[]
    voice_rows=[]
    directive_counter=Counter()
    decode_failures=[]
    decoded_meta={}

    for idx,p in enumerate(unique,1):
        raw=p.read_bytes()
        try:
            dec,codec,expected=decode_3x(raw)
        except Exception as e:
            decode_failures.append({
                "file":p.name,
                "path":str(p),
                "error":str(e),
                "source_size":len(raw),
                "first16":raw[:16].hex(" "),
            })
            print(f"[{idx:03d}/{len(unique):03d}] {p.name}: DECODE FAIL {e}",flush=True)
            continue

        out_name=p.name
        dst=DECODED/out_name
        # avoid collisions after dedup by filename
        n=2
        while dst.exists():
            dst=DECODED/f"{p.stem}__{n}{p.suffix}"
            n+=1
        dst.write_bytes(dec)

        text,enc=decode_text(dec)
        lines=text.splitlines()
        decoded_meta[p.name]=(text,lines,dst)

        # Approx text-like ratio
        textish=sum(1 for b in dec if b in (9,10,13) or 32<=b<127 or b>=0x80)/max(1,len(dec))

        inventory.append({
            "file":p.name,
            "source_path":str(p),
            "aliases":len(aliases[sha256(raw)]),
            "source_size":len(raw),
            "codec":codec,
            "declared_decoded_size":expected if expected is not None else "",
            "decoded_size":len(dec),
            "decoded_sha256":sha256(dec),
            "text_encoding":enc,
            "textlike_ratio":f"{textish:.4f}",
        })

        # command/directive inventory
        for li,line in enumerate(lines):
            m=re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=",line,re.I)
            if m:
                directive_counter[m.group(1).upper()]+=1

            for vm in VOICE_RE.finditer(line):
                voice_rows.append({
                    "file":p.name,
                    "section":current_section(lines,li),
                    "line_no":li+1,
                    "voice_id":vm.group(0),
                    "line":line,
                })

            mm=re.match(r"^\s*MOVIE\s*=\s*([A-Za-z0-9_]+)\s*$",line,re.I)
            if mm:
                mov=mm.group(1).lower()
                movie_rows.append({
                    "file":p.name,
                    "section":current_section(lines,li),
                    "line_no":li+1,
                    "movie":mov,
                    "is_dm":"YES" if mov in DM_NAMES else "NO",
                    "context":context_text(lines,li,14),
                })

            for bm in BARE_MOVIE_RE.finditer(line):
                bare_rows.append({
                    "file":p.name,
                    "section":current_section(lines,li),
                    "line_no":li+1,
                    "movie_token":bm.group(0).lower(),
                    "line":line,
                    "is_MOVIE_directive":"YES" if re.match(r"^\s*MOVIE\s*=",line,re.I) else "NO",
                })

        print(f"[{idx:03d}/{len(unique):03d}] {p.name}: {codec} {len(raw)} -> {len(dec)}",flush=True)

    # Per-movie contexts and nearby voice linkage.
    near=[]
    for row in movie_rows:
        pfile=row["file"]
        text,lines,_=decoded_meta[pfile]
        mi=row["line_no"]-1
        voices=[]
        for li in range(max(0,mi-80),min(len(lines),mi+81)):
            found=VOICE_RE.findall(lines[li])
            for v in found:
                voices.append((li,v,lines[li]))
        # Keep nearest unique voice IDs.
        voices.sort(key=lambda x:(abs(x[0]-mi),x[0]))
        seen=set()
        for rank,(li,v,line) in enumerate(voices,1):
            vl=v.lower()
            if vl in seen: continue
            seen.add(vl)
            near.append({
                "movie":row["movie"],
                "file":pfile,
                "section":row["section"],
                "movie_line":row["line_no"],
                "voice_rank_by_line_distance":len(seen),
                "voice_id":v,
                "voice_line":li+1,
                "line_distance":li-mi,
                "voice_line_text":line,
            })
            if len(seen)>=30:
                break

        cfile=CTX/f'{row["movie"]}__{Path(pfile).stem}__L{row["line_no"]:05d}.txt'
        cfile.write_text(row["context"]+"\n",encoding="utf-8-sig")

    write_tsv(STAGE/"tbl_inventory.tsv",inventory)
    write_tsv(STAGE/"decode_failures.tsv",decode_failures,
              ["file","path","error","source_size","first16"])
    write_tsv(STAGE/"movie_commands.tsv",movie_rows,
              ["file","section","line_no","movie","is_dm","context"])
    write_tsv(STAGE/"bare_movie_tokens.tsv",bare_rows,
              ["file","section","line_no","movie_token","line","is_MOVIE_directive"])
    write_tsv(STAGE/"voice_refs.tsv",voice_rows,
              ["file","section","line_no","voice_id","line"])
    write_tsv(STAGE/"movie_nearby_voice_refs.tsv",near,
              ["movie","file","section","movie_line","voice_rank_by_line_distance",
               "voice_id","voice_line","line_distance","voice_line_text"])

    directive_rows=[{"directive":k,"count":v} for k,v in directive_counter.most_common()]
    write_tsv(STAGE/"directive_counts.tsv",directive_rows,["directive","count"])

    # Summary movie coverage
    by_movie=Counter(r["movie"] for r in movie_rows)
    dm_hits=[m for m in DM_NAMES if by_movie[m]]
    known_hits=[m for m in KNOWN_MOVIES if by_movie[m]]
    all_movies=sorted(by_movie)
    movie_summary=[{"movie":m,"command_hits":by_movie[m]} for m in all_movies]
    write_tsv(STAGE/"movie_summary.tsv",movie_summary,["movie","command_hits"])

    summary=[
        "Naruto PSP MOV03D - All TBL movie / voice linkage scan",
        "="*76,
        "",
        f"QuickBMS mode={mode}",
        f"Extracted TBL paths={len(tbls)}",
        f"Unique TBL blobs={len(unique)}",
        f"Decoded/scanned={len(inventory)}",
        f"Decode failures={len(decode_failures)}",
        f"MOVIE command hits={len(movie_rows)}",
        f"Distinct MOVIE values={len(all_movies)}: {', '.join(all_movies) if all_movies else '(none)'}",
        f"DM direct MOVIE hits={len(dm_hits)}/10: {', '.join(dm_hits) if dm_hits else '(none)'}",
        f"Known DA/DK/DM values found={len(known_hits)}/{len(KNOWN_MOVIES)}",
        f"Bare DA/DK/DM token hits={len(bare_rows)}",
        f"Voice ID references={len(voice_rows)}",
        "",
        "Codec used:",
        '  " 3;1" = XOR 0x72 + 4096-byte LZSS, ring=0xFEE, LSB flags,',
        "             offset=b1|((b2&0xF0)<<4), length=(b2&0x0F)+3",
        '  " 3;0" = payload XOR 0x72',
        "",
        "Interpretation:",
        "- A DM hit in movie_commands.tsv gives the direct table/section controlling that PMF.",
        "- movie_nearby_voice_refs.tsv lists the nearest s_a*/s_b* voice IDs in the same script.",
        "- If no DM token exists in ANY TBL, DM playback is controlled outside text TBL scripts",
        "  and the next target should be the BOOT.BIN movie dispatcher / call-site arguments.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    # Success requires correct decoding process, not finding DM specifically.
    return 0 if len(inventory)>0 and not decode_failures else 2

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
