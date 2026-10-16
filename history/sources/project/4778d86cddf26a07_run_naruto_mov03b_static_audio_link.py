#!/usr/bin/env python3
# Naruto PSP MOV03B - Static PMF -> external audio reference scan
#
# No gameplay required.
# Searches extracted KR game data for dm001..dm010 / da / dk PMF references,
# then inspects nearby binary context for voice/BGM/SE identifiers.
#
# Outputs:
#   pmf_reference_hits.tsv
#   pmf_nearby_audio_ids.tsv
#   per_movie/<stem>_context.txt
#   SUMMARY.txt

from __future__ import annotations
import csv, mmap, os, re, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR = ROOT / "kr_extracted"
ANALYSIS = ROOT / "analysis"
STAGE = ANALYSIS / "mov" / "mov03b_static_audio_link"
PER = STAGE / "per_movie"

MOVIES = [
    "da101","da102","da103","da201",
    "dk101","dk102","dk103","dk104","dk201","dk202","dk203",
    "dm001","dm002","dm003","dm004","dm005","dm006","dm007","dm008","dm009","dm010",
]

# Files worth scanning for references. Skip media/assets where a movie name
# appearing inside its own file would be irrelevant and expensive.
SKIP_EXT = {
    ".pmf",".at3",".oma",".wav",".mp3",".ogg",".png",".jpg",".jpeg",".bmp",
    ".gif",".webp",".mp4",".avi",".mkv",".zip",".7z",".rar"
}
SKIP_NAMES = {"data.psar"}

CONTEXT_SMALL = 64 * 1024
CONTEXT_LARGE = 1024 * 1024

ASCII_STR = re.compile(rb"[\x20-\x7e]{4,}")
AUDIO_TOKEN = re.compile(
    r"(?i)(?:"
    r"[a-z0-9_./\\-]{0,80}\.(?:at3|oma|wav|mp3|adx|vag)"
    r"|s_[a-z]\d{1,3}[_-]\d{1,4}[a-z]?"
    r"|(?:bgm|se|voice|sound)[a-z0-9_./\\-]{1,100}"
    r")"
)

def write_tsv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows)

def candidate_files():
    for p in KR.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in SKIP_NAMES:
            continue
        if p.suffix.lower() in SKIP_EXT:
            continue
        # PSP update payloads are unrelated and large.
        low=str(p).lower()
        if "\\psp_game\\sysdir\\update\\" in low:
            continue
        yield p

def find_all(data: mmap.mmap, needles: list[bytes]):
    seen=set()
    for needle in needles:
        start=0
        while True:
            idx=data.find(needle,start)
            if idx<0: break
            if idx not in seen:
                seen.add(idx)
                yield idx,needle
            start=idx+1

def printable_strings(blob: bytes, base_off: int):
    out=[]
    for m in ASCII_STR.finditer(blob):
        s=m.group().decode("ascii","replace")
        out.append((base_off+m.start(), s))
    return out

def nearby_audio_tokens(blob: bytes, base_off: int):
    rows=[]
    for off,s in printable_strings(blob,base_off):
        for m in AUDIO_TOKEN.finditer(s):
            token=m.group(0)
            rows.append((off+m.start(),token,s))
    # de-duplicate by token+offset
    seen=set(); out=[]
    for x in rows:
        k=(x[0],x[1].lower())
        if k in seen: continue
        seen.add(k); out.append(x)
    return out

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    PER.mkdir(parents=True,exist_ok=True)

    files=list(candidate_files())
    print("="*76, flush=True)
    print(" Naruto PSP MOV03B - Static PMF -> external audio reference scan", flush=True)
    print("="*76, flush=True)
    print(f"Candidate files: {len(files)}", flush=True)

    hits=[]
    audio=[]
    contexts={m:[] for m in MOVIES}

    for fi,p in enumerate(files,1):
        try:
            size=p.stat().st_size
            if size==0:
                continue
            with p.open("rb") as f:
                mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
                try:
                    any_file_hit=False
                    for stem in MOVIES:
                        needles=[
                            stem.encode("ascii"),
                            (stem+".pmf").encode("ascii"),
                            stem.upper().encode("ascii"),
                            (stem.upper()+".PMF").encode("ascii"),
                        ]
                        local=list(find_all(mm,needles))
                        if not local:
                            continue
                        any_file_hit=True

                        for pos,needle in local:
                            rel=str(p.relative_to(KR))
                            hit={
                                "movie":stem,
                                "file":rel,
                                "file_size":size,
                                "offset_hex":f"0x{pos:08X}",
                                "offset_dec":pos,
                                "matched_text":needle.decode("ascii","replace"),
                            }
                            hits.append(hit)

                            lo=max(0,pos-CONTEXT_SMALL)
                            hi=min(size,pos+CONTEXT_SMALL)
                            blob=mm[lo:hi]
                            toks=nearby_audio_tokens(blob,lo)
                            for toff,token,container in toks:
                                audio.append({
                                    "movie":stem,
                                    "file":rel,
                                    "movie_ref_offset_hex":f"0x{pos:08X}",
                                    "audio_offset_hex":f"0x{toff:08X}",
                                    "distance_bytes":toff-pos,
                                    "audio_token":token,
                                    "container_string":container[:300],
                                    "window":"64KiB",
                                })

                            # If no audio token in +/-64 KiB, make one wider pass.
                            if not toks:
                                lo2=max(0,pos-CONTEXT_LARGE)
                                hi2=min(size,pos+CONTEXT_LARGE)
                                blob2=mm[lo2:hi2]
                                toks2=nearby_audio_tokens(blob2,lo2)
                                for toff,token,container in toks2:
                                    audio.append({
                                        "movie":stem,
                                        "file":rel,
                                        "movie_ref_offset_hex":f"0x{pos:08X}",
                                        "audio_offset_hex":f"0x{toff:08X}",
                                        "distance_bytes":toff-pos,
                                        "audio_token":token,
                                        "container_string":container[:300],
                                        "window":"1MiB",
                                    })

                            # compact textual context: printable strings +/- 4 KiB
                            lo3=max(0,pos-4096)
                            hi3=min(size,pos+4096)
                            ps=printable_strings(mm[lo3:hi3],lo3)
                            ctx=[
                                f"FILE={rel}",
                                f"MOVIE={stem}",
                                f"OFFSET=0x{pos:08X}",
                                f"MATCH={needle.decode('ascii','replace')}",
                                "--- printable strings +/-4KiB ---",
                            ]
                            for soff,s in ps:
                                mark=" <== PMF REF" if soff <= pos < soff+len(s) else ""
                                ctx.append(f"0x{soff:08X}  {s}{mark}")
                            contexts[stem].append("\n".join(ctx))
                finally:
                    mm.close()
        except Exception as e:
            print(f"[WARN] {p}: {e}", flush=True)

        if fi % 100 == 0 or fi==len(files):
            print(f"[scan] {fi}/{len(files)}  hits={len(hits)} audio_tokens={len(audio)}", flush=True)

    # Rank audio tokens by closeness to PMF reference.
    for r in audio:
        d=abs(int(r["distance_bytes"]))
        if d <= 4096: rank="VERY_NEAR"
        elif d <= 65536: rank="NEAR"
        else: rank="WIDE"
        r["proximity"]=rank

    audio.sort(key=lambda r:(r["movie"], 0 if r["proximity"]=="VERY_NEAR" else 1 if r["proximity"]=="NEAR" else 2, abs(int(r["distance_bytes"]))))

    write_tsv(STAGE/"pmf_reference_hits.tsv",hits)
    write_tsv(STAGE/"pmf_nearby_audio_ids.tsv",audio)

    # Per-movie contexts
    for stem,blocks in contexts.items():
        (PER/f"{stem}_context.txt").write_text(
            ("\n\n"+"="*76+"\n\n").join(blocks) if blocks else "NO PMF STRING REFERENCE FOUND\n",
            encoding="utf-8-sig"
        )

    # Compact best candidate table.
    best=[]
    for stem in MOVIES:
        aa=[x for x in audio if x["movie"]==stem]
        uniq=[]
        seen=set()
        for x in aa:
            k=x["audio_token"].lower()
            if k in seen: continue
            seen.add(k); uniq.append(x)
        for rank,x in enumerate(uniq[:30],1):
            best.append({
                "movie":stem,
                "rank":rank,
                "audio_token":x["audio_token"],
                "proximity":x["proximity"],
                "distance_bytes":x["distance_bytes"],
                "file":x["file"],
                "movie_ref_offset_hex":x["movie_ref_offset_hex"],
                "audio_offset_hex":x["audio_offset_hex"],
            })
    write_tsv(STAGE/"pmf_audio_candidates_top30.tsv",best)

    hit_movies=sorted({x["movie"] for x in hits})
    audio_movies=sorted({x["movie"] for x in audio})
    dm_hit=[m for m in MOVIES if m.startswith("dm") and m in hit_movies]
    dm_audio=[m for m in MOVIES if m.startswith("dm") and m in audio_movies]

    summary=[
        "Naruto PSP MOV03B - Static PMF -> external audio reference scan",
        "="*76,
        "",
        f"Candidate files scanned={len(files)}",
        f"Total PMF string hits={len(hits)}",
        f"Movies with PMF string hits={len(hit_movies)}/{len(MOVIES)}",
        f"Movies with nearby audio-like tokens={len(audio_movies)}/{len(MOVIES)}",
        f"DM movies with PMF refs={len(dm_hit)}/10: {', '.join(dm_hit) if dm_hit else '(none)'}",
        f"DM movies with nearby audio tokens={len(dm_audio)}/10: {', '.join(dm_audio) if dm_audio else '(none)'}",
        "",
        "Interpretation:",
        "- VERY_NEAR: audio-like identifier within 4 KiB of PMF reference.",
        "- NEAR: within 64 KiB.",
        "- WIDE: only found within 1 MiB; may be unrelated.",
        "",
        "Next:",
        "- If voice IDs cluster near dm001..dm010 refs, decode only those AT3 groups.",
        "- Match decoded individual voice clips against Stage37 source audio automatically.",
        "- No PPSSPP gameplay is required.",
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
