#!/usr/bin/env python3
# Naruto PSP MOV03M FIX1 - sector-aligned lossless hybrid PMFs
#
# MOV03M result:
#   dm001..dm006: whole-PES transplant PASS
#   dm008..dm010: only final audio sector has a different short PES length
#   dm007: KR 483 audio sectors, US 484
#
# PSMF media area is 2048-byte MPEG-PS sectors:
#   normally 14-byte pack header + 2034-byte PES/padding payload.
#
# FIX1 preserves each US sector's PACK HEADER (including SCR), but replaces
# the remainder of mapped US audio sectors with the corresponding KR sector
# remainder. This naturally carries:
#   KR whole audio PES + KR padding
# while retaining:
#   US pack/SCR + all US video sectors.
#
# Audio sectors are aligned in monotonic PTS order. A US-only extra audio
# sector (dm007 case) is converted to a standard MPEG padding_stream sector.
#
# Required post-validation:
#   concatenated hybrid audio PES SHA256 == KR
#   recovered ATRAC3+ SHA256 == KR
#   hybrid video PES SHA256 == US
#   hybrid file size == US
#   hybrid audio PES count == KR
#   ATRAC3+ decoder PASS
#
# No re-encoding, at3tool, or oMPSComposer.

from __future__ import annotations
import csv, hashlib, json, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov03m_batch_hybrid"
OUT = STAGE / "output"
WORK = STAGE / "work"
LOGD = STAGE / "logs"
for p in (STAGE, OUT, WORK, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
DM = [f"dm{i:03d}" for i in range(1,11)]

SECTOR = 2048
LOGICAL_AU = 752
ATRAC_FRAME = 744
SRATE_INDEX = 1
CHANNEL_ID_STEREO = 2
EA3_HEADER_SIZE = 96
PTS_NEAR = 5000  # ~55.6 ms, slightly > one 2048-sample ATRAC frame at 44.1k

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields: fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def run(cmd,logname,timeout=600):
    cp=subprocess.run([str(x) for x in cmd],
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                      text=True,encoding="utf-8",errors="replace",timeout=timeout)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%x if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def parse_pts5(b):
    if len(b)<5:return None
    return ((b[0]&0x0E)<<29)|(b[1]<<22)|((b[2]&0xFE)<<14)|(b[3]<<7)|((b[4]&0xFE)>>1)

def parse_sector_payload(data, abs_start, abs_end):
    """Parse PES-like streams after pack header in one fixed 2048-byte sector."""
    sec=data[abs_start:abs_end]
    if len(sec)!=SECTOR:
        return dict(valid=False,error="short sector")
    if sec[:4] != b"\x00\x00\x01\xBA":
        return dict(valid=False,error="no pack start")

    # MPEG-2 pack header: 14 bytes + stuffing.
    if len(sec)<14:
        return dict(valid=False,error="short pack")
    pack_len=14+(sec[13]&7)
    p=pack_len
    items=[]

    while p+6<=SECTOR:
        # trailing FF/00 can be ignored if no start code at p
        if sec[p:p+3] != b"\x00\x00\x01":
            # Search within current sector, but record gap.
            nxt=sec.find(b"\x00\x00\x01",p+1)
            if nxt<0:
                break
            p=nxt
            continue

        sid=sec[p+3]
        if sid==0xB9:
            items.append(dict(sid=sid,start=p,end=p+4,length=4,pts=None))
            p+=4
            continue

        plen=(sec[p+4]<<8)|sec[p+5]
        end=p+6+plen
        if end>SECTOR:
            items.append(dict(sid=sid,start=p,end=SECTOR,length=SECTOR-p,pts=None,truncated=True))
            break

        pts=None
        payload=p+6
        if sid in (0xBD,) or 0xC0<=sid<=0xEF:
            q=p+6
            if q+3<=end and (sec[q]&0xC0)==0x80:
                flags2=sec[q+1]
                hlen=sec[q+2]
                if (flags2&0x80) and q+8<=end:
                    pts=parse_pts5(sec[q+3:q+8])
                payload=q+3+hlen
            else:
                r=q
                while r<end and sec[r]==0xFF:r+=1
                if r+2<=end and (sec[r]&0xC0)==0x40:r+=2
                if r<end and (sec[r]&0xF0) in (0x20,0x30):
                    pts=parse_pts5(sec[r:r+5])
                    r+=5 if (sec[r]&0xF0)==0x20 else 10
                elif r<end and sec[r]==0x0F:r+=1
                payload=r

        items.append(dict(sid=sid,start=p,end=end,length=end-p,pts=pts,payload=payload))
        p=end

    return dict(valid=True,pack_len=pack_len,items=items)

def parse_pmf(path):
    data=Path(path).read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError(f"{Path(path).name}: not PSMF")
    data_offset=struct.unpack_from(">I",data,8)[0]
    declared=struct.unpack_from(">I",data,12)[0]
    if data_offset<=0 or data_offset>=len(data):
        raise RuntimeError(f"{Path(path).name}: bad data offset")

    media_len=len(data)-data_offset
    sector_count=media_len//SECTOR
    sectors=[]
    audio_sectors=[]
    video_pes=[]
    audio_pes=[]

    for si in range(sector_count):
        start=data_offset+si*SECTOR
        end=start+SECTOR
        ps=parse_sector_payload(data,start,end)
        entry=dict(index=si,start=start,end=end,**ps)
        sectors.append(entry)
        if not ps.get("valid"):
            continue

        for it in ps["items"]:
            sid=it["sid"]
            astart=start+it["start"]
            aend=start+it["end"]
            rec=dict(
                sector_index=si,
                start=astart,end=aend,
                pes_total=aend-astart,
                pts=it.get("pts"),
                sid=sid,
                pack_len=ps["pack_len"],
            )
            if sid==0xBD:
                # parse private substream / locator
                payload_abs=start+it.get("payload",it["start"]+6)
                rec["payload"]=payload_abs
                rec["payload_len"]=aend-payload_abs
                if payload_abs+4<=aend:
                    rec["subid"]=data[payload_abs]
                    rec["reserved"]=data[payload_abs+1]
                    rec["locator"]=struct.unpack_from(">H",data,payload_abs+2)[0]
                audio_pes.append(rec)
                if entry not in audio_sectors:
                    audio_sectors.append(entry)
            elif 0xE0<=sid<=0xEF:
                video_pes.append(rec)

    return dict(
        path=Path(path),data=data,data_offset=data_offset,declared=declared,
        sector_count=sector_count,sectors=sectors,
        audio_sectors=audio_sectors,audio_pes=audio_pes,video_pes=video_pes
    )

def concat_pes(parsed,key):
    return b"".join(parsed["data"][x["start"]:x["end"]] for x in parsed[key])

def recover_frames(parsed):
    logical=bytearray()
    for x in parsed["audio_pes"]:
        if x.get("payload") is None:continue
        private=parsed["data"][x["payload"]:x["end"]]
        if len(private)>=4 and private[0]<0x10:
            logical += private[4:]
    logical=bytes(logical)
    if len(logical)%LOGICAL_AU:
        raise RuntimeError(
            f"{parsed['path'].name}: logical ATRAC {len(logical)} not divisible by {LOGICAL_AU}"
        )
    frames=bytearray()
    for i in range(0,len(logical),LOGICAL_AU):
        frames += logical[i+8:i+LOGICAL_AU]
    frames=bytes(frames)
    if len(frames)%ATRAC_FRAME:
        raise RuntimeError(
            f"{parsed['path'].name}: ATRAC frame bytes {len(frames)} not divisible by {ATRAC_FRAME}"
        )
    return dict(logical=logical,frames=frames,
                au_count=len(logical)//LOGICAL_AU,
                frame_count=len(frames)//ATRAC_FRAME)

def syncsafe28(n):
    return bytes([(n>>21)&0x7F,(n>>14)&0x7F,(n>>7)&0x7F,n&0x7F])

def build_oma(frames,path):
    size_code=ATRAC_FRAME//8-1
    params=(SRATE_INDEX<<13)|(CHANNEL_ID_STEREO<<10)|size_code
    out=bytearray()
    out+=b"ea3"+bytes([3,0,0])+syncsafe28(0)
    ea3=bytearray(EA3_HEADER_SIZE)
    ea3[0:4]=b"EA3\x00"
    ea3[4]=EA3_HEADER_SIZE>>7
    ea3[5]=EA3_HEADER_SIZE&0x7F
    ea3[6:8]=struct.pack("<H",0xFFFF)
    ea3[32:36]=struct.pack(">I",(1<<24)|params)
    out+=ea3
    out+=frames
    Path(path).write_bytes(out)

def audio_sector_records(parsed):
    """One representative audio PTS/PES record per audio sector."""
    by={}
    for a in parsed["audio_pes"]:
        by.setdefault(a["sector_index"],a)
    out=[]
    for s in parsed["audio_sectors"]:
        a=by.get(s["index"])
        if a:
            out.append(dict(
                sector_index=s["index"],
                pack_len=s["pack_len"],
                pts=a["pts"],
                pes_total=a["pes_total"],
                payload_len=a.get("payload_len"),
            ))
    return out

def align_audio(kr_list,us_list):
    """
    Monotonic alignment primarily by exact PTS.
    Handles:
      - one-frame PTS deltas by near-match
      - US-only inserted audio sector by lookahead
    Returns list of (kr_index|None, us_index|None, reason).
    """
    out=[]
    i=j=0
    nk=len(kr_list);nu=len(us_list)

    while i<nk and j<nu:
        kp=kr_list[i]["pts"]
        up=us_list[j]["pts"]

        if kp is not None and up is not None and kp==up:
            out.append((i,j,"pts_exact"))
            i+=1;j+=1;continue

        # Strong insertion/deletion evidence from exact one-step lookahead.
        if j+1<nu and kp is not None and us_list[j+1]["pts"]==kp:
            out.append((None,j,"us_extra_before_exact"))
            j+=1;continue

        if i+1<nk and up is not None and kr_list[i+1]["pts"]==up:
            out.append((i,None,"kr_extra_before_exact"))
            i+=1;continue

        # Near PTS (known localized PTS shifts <= one ATRAC frame).
        if kp is not None and up is not None and abs(kp-up)<=PTS_NEAR:
            out.append((i,j,"pts_near"))
            i+=1;j+=1;continue

        # Compare lookahead distances for non-exact cases.
        cur=abs(kp-up) if kp is not None and up is not None else 10**18
        dskipu=(abs(kp-us_list[j+1]["pts"])
                if (j+1<nu and kp is not None and us_list[j+1]["pts"] is not None)
                else 10**18)
        dskipk=(abs(kr_list[i+1]["pts"]-up)
                if (i+1<nk and up is not None and kr_list[i+1]["pts"] is not None)
                else 10**18)

        if dskipu < cur and dskipu <= dskipk:
            out.append((None,j,"us_extra_nearest"))
            j+=1;continue
        if dskipk < cur:
            out.append((i,None,"kr_extra_nearest"))
            i+=1;continue

        # If no useful PTS, ordinal fallback only when remaining counts match.
        if (kp is None or up is None) and (nk-i)==(nu-j):
            out.append((i,j,"ordinal_no_pts"))
            i+=1;j+=1;continue

        raise RuntimeError(
            f"Cannot align audio: KR#{i} pts={kp}, US#{j} pts={up}, "
            f"remaining {nk-i}/{nu-j}"
        )

    while i<nk:
        out.append((i,None,"kr_tail_extra"));i+=1
    while j<nu:
        out.append((None,j,"us_tail_extra"));j+=1

    return out

def make_padding_payload(length):
    """Return exactly length bytes containing one MPEG padding_stream."""
    if length<6 or length-6>0xFFFF:
        raise RuntimeError(f"Cannot make padding payload of {length}")
    return b"\x00\x00\x01\xBE"+struct.pack(">H",length-6)+b"\xFF"*(length-6)

def us_source(name):
    e=US_MOV/(name+"e.pmf")
    if e.exists():return e
    p=US_MOV/(name+".pmf")
    return p if p.exists() else None

def main():
    if not FFMPEG.exists():
        raise RuntimeError("LOCAL_PATH missing")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03M FIX1 - Sector-aligned lossless hybrid PMFs",flush=True)
    print("="*80,flush=True)

    results=[]
    align_rows=[]
    sector_rows=[]
    pass_count=0
    fail_count=0

    for idx,name in enumerate(DM,1):
        print(f"[{idx:02d}/10] {name}",flush=True)
        row=dict(movie=name)

        try:
            kr_path=KR_MOV/(name+".pmf")
            us_path=us_source(name)
            if not kr_path.exists():raise RuntimeError("KR PMF missing")
            if us_path is None:raise RuntimeError("US PMF missing")
            row["kr_source"]=str(kr_path);row["us_source"]=str(us_path)

            kr=parse_pmf(kr_path)
            us=parse_pmf(us_path)
            ka=audio_sector_records(kr)
            ua=audio_sector_records(us)

            row["kr_sector_count"]=kr["sector_count"]
            row["us_sector_count"]=us["sector_count"]
            row["kr_audio_sector_count"]=len(ka)
            row["us_audio_sector_count"]=len(ua)

            alignment=align_audio(ka,ua)
            mapped=0;us_extra=0;kr_extra=0;near=0

            for kix,uix,reason in alignment:
                krrec=ka[kix] if kix is not None else None
                usrec=ua[uix] if uix is not None else None
                if kix is not None and uix is not None:
                    mapped+=1
                    near+=int(reason=="pts_near")
                elif uix is not None:
                    us_extra+=1
                elif kix is not None:
                    kr_extra+=1

                align_rows.append(dict(
                    movie=name,
                    kr_audio_ordinal=kix if kix is not None else "",
                    us_audio_ordinal=uix if uix is not None else "",
                    kr_sector_index=krrec["sector_index"] if krrec else "",
                    us_sector_index=usrec["sector_index"] if usrec else "",
                    kr_pts=krrec["pts"] if krrec and krrec["pts"] is not None else "",
                    us_pts=usrec["pts"] if usrec and usrec["pts"] is not None else "",
                    pts_delta_sec=(f"{(usrec['pts']-krrec['pts'])/90000.0:+.6f}"
                                   if krrec and usrec and krrec["pts"] is not None and usrec["pts"] is not None else ""),
                    reason=reason,
                ))

            row["mapped_audio_sectors"]=mapped
            row["us_extra_audio_sectors"]=us_extra
            row["kr_unmapped_audio_sectors"]=kr_extra
            row["near_pts_matches"]=near

            if kr_extra:
                raise RuntimeError(f"{kr_extra} KR audio sectors have no US slot")

            hybrid=bytearray(us["data"])

            # Map audio sectors: preserve US pack header, transplant full KR
            # post-pack sector contents (audio PES + any padding).
            for kix,uix,reason in alignment:
                if kix is None:
                    # US-only audio sector: preserve US pack/SCR, convert remainder to padding.
                    usrec=ua[uix]
                    usec=us["sectors"][usrec["sector_index"]]
                    plen=usec["pack_len"]
                    start=usec["start"]
                    payload_len=SECTOR-plen
                    hybrid[start+plen:start+SECTOR]=make_padding_payload(payload_len)
                    sector_rows.append(dict(
                        movie=name,action="US_EXTRA_TO_PADDING",
                        kr_sector_index="",us_sector_index=usec["index"],
                        kr_pack_len="",us_pack_len=plen,
                        reason=reason
                    ))
                    continue

                krrec=ka[kix];usrec=ua[uix]
                ksec=kr["sectors"][krrec["sector_index"]]
                usec=us["sectors"][usrec["sector_index"]]
                kpl=ksec["pack_len"];upl=usec["pack_len"]

                if kpl!=upl:
                    raise RuntimeError(
                        f"pack header length mismatch KR sector {ksec['index']}={kpl}, "
                        f"US sector {usec['index']}={upl}"
                    )

                donor=kr["data"][ksec["start"]+kpl:ksec["end"]]
                if len(donor)!=(SECTOR-upl):
                    raise RuntimeError("sector payload length mismatch")
                hybrid[usec["start"]+upl:usec["end"]]=donor

                sector_rows.append(dict(
                    movie=name,action="TRANSPLANT_KR_AUDIO_SECTOR_PAYLOAD",
                    kr_sector_index=ksec["index"],us_sector_index=usec["index"],
                    kr_pack_len=kpl,us_pack_len=upl,
                    kr_pts=krrec["pts"] if krrec["pts"] is not None else "",
                    us_pts=usrec["pts"] if usrec["pts"] is not None else "",
                    reason=reason
                ))

            out=OUT/(name+".pmf")
            out.write_bytes(hybrid)

            if out.stat().st_size!=us_path.stat().st_size:
                raise RuntimeError("hybrid size differs from US")

            hy=parse_pmf(out)

            # Strong exact validations.
            kr_audio_sha=sha_bytes(concat_pes(kr,"audio_pes"))
            hy_audio_sha=sha_bytes(concat_pes(hy,"audio_pes"))
            audio_pes_ok=(kr_audio_sha==hy_audio_sha)

            krf=recover_frames(kr)
            hyf=recover_frames(hy)
            kr_atrac_sha=sha_bytes(krf["frames"])
            hy_atrac_sha=sha_bytes(hyf["frames"])
            atrac_ok=(kr_atrac_sha==hy_atrac_sha)

            us_video_sha=sha_bytes(concat_pes(us,"video_pes"))
            hy_video_sha=sha_bytes(concat_pes(hy,"video_pes"))
            video_ok=(us_video_sha==hy_video_sha)

            count_ok=(len(hy["audio_pes"])==len(kr["audio_pes"]))

            # Decoder test, no WAV output.
            oma=WORK/(name+".oma")
            build_oma(hyf["frames"],oma)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma,
                    "-f","null","-"],f"{name}_FIX1_decode_test.log",600)
            decode_ok=(cp.returncode==0)

            ok=all([audio_pes_ok,atrac_ok,video_ok,count_ok,decode_ok])

            row.update(
                hybrid_pmf=str(out),
                hybrid_bytes=out.stat().st_size,
                hybrid_audio_pes_count=len(hy["audio_pes"]),
                audio_count_equals_kr="YES" if count_ok else "NO",
                kr_audio_pes_sha256=kr_audio_sha,
                hybrid_audio_pes_sha256=hy_audio_sha,
                audio_pes_equals_kr="YES" if audio_pes_ok else "NO",
                kr_atrac_sha256=kr_atrac_sha,
                hybrid_atrac_sha256=hy_atrac_sha,
                atrac_equals_kr="YES" if atrac_ok else "NO",
                us_video_pes_sha256=us_video_sha,
                hybrid_video_pes_sha256=hy_video_sha,
                video_pes_equals_us="YES" if video_ok else "NO",
                ffmpeg_atrac_decode="PASS" if decode_ok else "FAIL",
                status="PASS" if ok else "FAIL",
            )

            if not ok:
                raise RuntimeError(
                    f"validation failed audio={audio_pes_ok} atrac={atrac_ok} "
                    f"video={video_ok} count={count_ok} decode={decode_ok}"
                )

            pass_count+=1
            print(
                f"  KR/US audio sectors={len(ka)}/{len(ua)} "
                f"mapped={mapped} US-extra={us_extra} "
                f"audio=KR video=US decode=PASS => PASS",
                flush=True
            )

        except Exception as e:
            fail_count+=1
            row["status"]="FAIL"
            row["error"]=str(e)
            print(f"  FAIL: {e}",flush=True)

        results.append(row)

    write_tsv(STAGE/"batch_hybrid_results_FIX1.tsv",results)
    write_tsv(STAGE/"audio_sector_alignment_FIX1.tsv",align_rows)
    write_tsv(STAGE/"sector_transplant_actions_FIX1.tsv",sector_rows)

    all_pass=(pass_count==10 and fail_count==0)
    summary=[
        "Naruto PSP MOV03M FIX1 - Sector-aligned lossless hybrid PMFs",
        "="*80,"",
        f"PASS={pass_count}/10",
        f"FAIL={fail_count}/10",
        "",
        "Method:",
        "  preserve US 2048-byte sector positions and pack headers/SCR",
        "  transplant KR post-pack audio sector payload",
        "  convert US-only audio sector to MPEG padding_stream",
        "",
        "Required validation:",
        "  hybrid concatenated audio PES SHA == KR",
        "  hybrid ATRAC3+ SHA == KR",
        "  hybrid video PES SHA == US",
        "  hybrid audio PES count == KR",
        "  PMF size == US",
        "  FFmpeg ATRAC3+ decode == PASS",
        "",
        f"BATCH RESULT={'PASS' if all_pass else 'FAIL'}",
        f"Output: {OUT}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0 if all_pass else 2

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
