#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys, wave
from collections import defaultdict
from pathlib import Path
import numpy as np

EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"
EXPECTED_SUB19_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
MEDIA_EXTS={".mp4",".mkv",".webm",".mov",".m4v",".avi"}
TEXT_EXTS={".ps1",".py",".txt",".json",".tsv",".csv",".md",".log"}
REPARSE=0x400

PILOTS=[
    {"name":"OPENING_KNOWN","sub09_sequence":19,"part":"part1","timestamp_sec":151.451,"voice_id":"s_a01_000","expected_relation":"KNOWN_TRUE"},
    {"name":"DRIFT_TRUE","sub09_sequence":164,"part":"part1","timestamp_sec":948.047,"voice_id":"s_a06_043","expected_relation":"KNOWN_TRUE"},
    {"name":"DRIFT_WRONG_STRUCTURAL","sub09_sequence":164,"part":"part1","timestamp_sec":948.047,"voice_id":"s_a07_013","expected_relation":"KNOWN_FALSE"},
]
VOICE_SAMPLES=["s_a01_000","s_a01_010","s_a02_001","s_a06_043","s_a07_013"]

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def write_tsv(path:Path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def read_tsv(path:Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def run_capture(cmd,timeout=60):
    p=subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=(0x08000000 if os.name=="nt" else 0),
    )
    return p.returncode,p.stdout,p.stderr

def find_tool(root:Path,name:str):
    hit=shutil.which(name)
    if hit:return Path(hit)
    exe=name+".exe" if os.name=="nt" and not name.lower().endswith(".exe") else name
    for base in [
        root/"tools",
        root/"analysis"/"stage38a_cuda"/"cuda_runtime",
        root/"analysis"/"stage38a_cuda",
        root/"analysis"
    ]:
        if not base.exists():continue
        for p in base.glob(exe):
            if p.is_file():return p
    return None

def ffprobe_json(ffprobe:Path,path:Path):
    rc,out,err=run_capture([
        ffprobe,"-v","error",
        "-show_entries","format=duration:stream=index,codec_type,codec_name,sample_rate,channels",
        "-of","json",path
    ],timeout=30)
    if rc!=0:
        return None,err.decode("utf-8","replace")[-2000:]
    try:return json.loads(out.decode("utf-8","replace")),""
    except Exception as e:return None,str(e)

def canonical(p:Path):
    try:return str(p.resolve()).casefold()
    except:return str(p.absolute()).casefold()

def safe_media_walk(base:Path,max_depth:int,exclude_parts=()):
    if not base.exists():return
    base=base.resolve()
    stack=[(base,0)]
    visited=set()
    while stack:
        cur,depth=stack.pop()
        ck=canonical(cur)
        if ck in visited:continue
        visited.add(ck)
        if any(x.casefold() in ck for x in exclude_parts):
            continue
        try:entries=list(os.scandir(str(cur)))
        except (OSError,PermissionError):continue
        for e in entries:
            p=Path(e.path)
            try:
                st=e.stat(follow_symlinks=False)
                attrs=getattr(st,"st_file_attributes",0)
                if e.is_symlink() or (attrs & REPARSE):continue
                if e.is_file(follow_symlinks=False):
                    if p.suffix.lower() in MEDIA_EXTS:yield p
                elif e.is_dir(follow_symlinks=False) and depth<max_depth:
                    stack.append((p,depth+1))
            except (OSError,PermissionError):
                continue

def media_candidates(root:Path,ffprobe:Path):
    found={}
    excludes=["\\analysis\\sub\\","\\logs\\","\\kr_extracted\\","\\us_extracted\\"]
    for base,depth in [(root,4),(Path.home()/"Downloads",1)]:
        for p in safe_media_walk(base,depth,excludes):
            found[canonical(p)]=p
    rows=[]
    for p in sorted(found.values(),key=lambda x:str(x).lower()):
        info,err=ffprobe_json(ffprobe,p)
        duration=None;audio_codec="";sample_rate="";channels=""
        if info:
            try:duration=float(info.get("format",{}).get("duration",""))
            except:duration=None
            for s in info.get("streams",[]):
                if s.get("codec_type")=="audio":
                    audio_codec=s.get("codec_name","")
                    sample_rate=s.get("sample_rate","")
                    channels=s.get("channels","")
                    break
        rows.append({
            "path":str(p),"bytes":p.stat().st_size,
            "duration_sec":"" if duration is None else f"{duration:.3f}",
            "audio_codec":audio_codec,"sample_rate":sample_rate,"channels":channels,
            "part1_distance_sec":"" if duration is None else f"{abs(duration-7327.720):.3f}",
            "part2_distance_sec":"" if duration is None else f"{abs(duration-2971.669):.3f}",
            "probe_error":err,
        })
    return rows

def choose_part(rows,part):
    target=7327.720 if part=="part1" else 2971.669
    viable=[]
    for r in rows:
        if not r["duration_sec"] or not r["audio_codec"]:continue
        d=float(r["duration_sec"])
        if d+1.0<target:continue
        viable.append((abs(d-target),Path(r["path"])))
    if not viable:return None
    viable.sort(key=lambda x:x[0])
    return viable[0][1]

def source_hints(root:Path):
    roots=[]
    for name in ("stage37","stage38","stage38a","stage38a_cuda","stage38c_30","stage38d_prompt_ab"):
        p=root/"analysis"/name
        if p.exists():roots.append(p)
    pat=re.compile(r"(?i)([A-Z]:\\[^\"'`\r\n]+?\.(?:mp4|mkv|webm|mov|m4v|avi)|[^\"'`\s]+?\.(?:mp4|mkv|webm|mov|m4v|avi))")
    rows=[]
    for rr in roots:
        for dirpath,dirs,files in os.walk(rr,topdown=True,followlinks=False):
            dirs[:]=[d for d in dirs if d.lower() not in ("images","models","cuda_runtime","selected_images")]
            for fn in files:
                p=Path(dirpath)/fn
                if p.suffix.lower() not in TEXT_EXTS:continue
                try:
                    if p.stat().st_size>4*1024*1024:continue
                    txt=p.read_text(encoding="utf-8-sig",errors="replace")
                except:continue
                for m in pat.finditer(txt):
                    rows.append({"source_file":str(p),"media_path_text":m.group(1)})
    uniq=[];seen=set()
    for r in rows:
        k=(r["source_file"],r["media_path_text"])
        if k not in seen:
            seen.add(k);uniq.append(r)
    return uniq

def voice_path(root:Path,voice_id:str):
    p=root/"kr_extracted"/"PSP_GAME"/"USRDIR"/"sound"/"voice"/(voice_id+".at3")
    return p if p.exists() else None

def decode_pcm(ffmpeg:Path,path:Path,sr=8000,start=None,duration=None):
    cmd=[ffmpeg,"-v","error"]
    if start is not None:cmd+=["-ss",f"{start:.3f}"]
    cmd+=["-i",path]
    if duration is not None:cmd+=["-t",f"{duration:.3f}"]
    cmd+=["-vn","-ac","1","-ar",str(sr),"-f","f32le","pipe:1"]
    rc,out,err=run_capture(cmd,timeout=90)
    if rc!=0 or len(out)<4:
        return None,err.decode("utf-8","replace")[-4000:]
    return np.frombuffer(out,dtype="<f4").astype(np.float64),""

def write_wav16(path:Path,a:np.ndarray,sr:int):
    if a is None or len(a)==0:return
    peak=max(1e-9,float(np.max(np.abs(a))))
    pcm=(np.clip(a/peak,-1,1)*32767.0).astype("<i2")
    with wave.open(str(path),"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes(pcm.tobytes())

def preemph(x):
    if len(x)<2:return x.astype(np.float64)
    y=np.empty_like(x,dtype=np.float64)
    y[0]=x[0];y[1:]=x[1:]-0.97*x[:-1]
    return y

def fft_ncc(window,voice):
    if window is None or voice is None or len(window)<len(voice)+10:return None
    x=preemph(window);y=preemph(voice)
    x=x-np.mean(x);y=y-np.mean(y)
    env=np.abs(y)
    if len(env):
        thr=max(np.max(env)*0.015,1e-7)
        nz=np.flatnonzero(env>thr)
        if len(nz)>50:
            a=max(0,int(nz[0])-80);b=min(len(y),int(nz[-1])+81);y=y[a:b]
    m=len(y);n=len(x)
    if m<100 or n<m:return None
    size=1
    while size<n+m-1:size*=2
    conv=np.fft.irfft(np.fft.rfft(x,size)*np.fft.rfft(y[::-1],size),size)
    corr=conv[m-1:n]
    cs=np.concatenate(([0.0],np.cumsum(x*x)))
    local=cs[m:]-cs[:-m]
    ey=float(np.sum(y*y))
    ncc=corr/np.sqrt(np.maximum(local*ey,1e-20))
    idx=int(np.argmax(ncc))
    return {"raw_ncc":float(ncc[idx]),"offset_samples":idx}

def rms_envelope(x,frame=160,hop=80):
    if x is None or len(x)<frame:return np.empty(0)
    y=preemph(x)
    count=1+(len(y)-frame)//hop
    shape=(count,frame);strides=(y.strides[0]*hop,y.strides[0])
    fr=np.lib.stride_tricks.as_strided(y,shape=shape,strides=strides)
    e=np.sqrt(np.mean(fr*fr,axis=1)+1e-12)
    e=np.log(e+1e-6)
    return (e-e.mean())/(e.std()+1e-8)

def envelope_ncc(window,voice):
    x=rms_envelope(window);y=rms_envelope(voice)
    if len(x)<len(y)+2 or len(y)<3:return None
    c=np.correlate(x,y,mode="valid")
    ey=np.sum(y*y)
    cs=np.concatenate(([0.0],np.cumsum(x*x)))
    m=len(y);local=cs[m:]-cs[:-m]
    ncc=c/np.sqrt(np.maximum(local*ey,1e-20))
    idx=int(np.argmax(ncc))
    return float(ncc[idx]),idx

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)

    sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"
    krinv=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    for p in (sub09,krinv):
        if not p.exists():raise RuntimeError(f"required input missing: {p}")
    if sha256_file(sub09).lower()!=EXPECTED_SUB09_SHA:raise RuntimeError("SUB09 SHA mismatch")
    if sha256_file(krinv).lower()!=EXPECTED_SUB19_KR_SHA:raise RuntimeError("SUB19 KR SHA mismatch")

    print("[1/6] Locate ffmpeg / ffprobe",flush=True)
    ffmpeg=find_tool(root,"ffmpeg");ffprobe=find_tool(root,"ffprobe")
    if not ffmpeg or not ffprobe:raise RuntimeError(f"ffmpeg/ffprobe missing: {ffmpeg} {ffprobe}")
    print(f"ffmpeg={ffmpeg}",flush=True);print(f"ffprobe={ffprobe}",flush=True)

    print("[2/6] Locate gameplay media candidates",flush=True)
    media=media_candidates(root,ffprobe)
    write_tsv(out/"sub22_media_candidates.tsv",media,[
        "path","bytes","duration_sec","audio_codec","sample_rate","channels",
        "part1_distance_sec","part2_distance_sec","probe_error"
    ])
    part1=choose_part(media,"part1");part2=choose_part(media,"part2")
    print(f"media={len(media)} part1={part1} part2={part2}",flush=True)
    hints=source_hints(root)
    write_tsv(out/"sub22_source_path_hints.tsv",hints,["source_file","media_path_text"])

    print("[3/6] Decode standalone AT3 voice samples",flush=True)
    voice_rows=[];decoded={};wavdir=out/"voice_samples";wavdir.mkdir(exist_ok=True)
    for vid in VOICE_SAMPLES:
        p=voice_path(root,vid)
        row={"voice_id":vid,"path":"","exists":"NO","bytes":"","codec":"","duration_sec":"",
             "sample_rate":"","channels":"","decode_success":"NO","decode_error":"","wav_file":""}
        if p:
            row["path"]=str(p);row["exists"]="YES";row["bytes"]=p.stat().st_size
            info,err=ffprobe_json(ffprobe,p)
            if info:
                try:row["duration_sec"]=f"{float(info.get('format',{}).get('duration','')):.3f}"
                except:pass
                for s in info.get("streams",[]):
                    if s.get("codec_type")=="audio":
                        row["codec"]=s.get("codec_name","");row["sample_rate"]=s.get("sample_rate","");row["channels"]=s.get("channels","");break
            else:row["decode_error"]=err
            a,derr=decode_pcm(ffmpeg,p,8000)
            if a is not None:
                decoded[vid]=a;row["decode_success"]="YES"
                wav=wavdir/(vid+".wav");write_wav16(wav,a,8000);row["wav_file"]=str(wav)
            else:row["decode_error"]=(row["decode_error"]+" | "+derr).strip(" |")
        voice_rows.append(row)
        print(f"  {vid}: exists={row['exists']} decode={row['decode_success']} codec={row['codec']}",flush=True)
    write_tsv(out/"sub22_voice_decode.tsv",voice_rows,[
        "voice_id","path","exists","bytes","codec","duration_sec","sample_rate","channels","decode_success","decode_error","wav_file"
    ])

    print("[4/6] Save #164 semantic drift evidence",flush=True)
    inv=read_tsv(krinv);drift=[]
    for r in inv:
        if r["voice_id"] in ("s_a06_043","s_a07_013"):
            drift.append({
                "voice_id":r["voice_id"],"event_file":r["event_file"],"event_display_index":r["event_display_index"],
                "speaker_code":r["speaker_code"],"japanese":r["text"],
                "relation_to_sub09_164":"SEMANTIC_TRUE" if r["voice_id"]=="s_a06_043" else "STRUCTURAL_FALSE"
            })
    write_tsv(out/"sub22_drift164_evidence.tsv",drift,[
        "voice_id","event_file","event_display_index","speaker_code","japanese","relation_to_sub09_164"
    ])

    print("[5/6] Pilot audio matching",flush=True)
    pilot_rows=[]
    for test in PILOTS:
        voice=decoded.get(test["voice_id"])
        row={**test,"video":str(part1) if part1 else "","window_start_sec":"","window_duration_sec":"12.000",
             "voice_decode_available":"YES" if voice is not None else "NO","raw_ncc":"","envelope_ncc":"",
             "best_audio_time_sec":"","delta_from_subtitle_timestamp_sec":"","match_error":""}
        if not part1:row["match_error"]="part1 source video not found"
        elif voice is None:row["match_error"]="voice decode unavailable"
        else:
            start=max(0.0,test["timestamp_sec"]-8.0);row["window_start_sec"]=f"{start:.3f}"
            win,err=decode_pcm(ffmpeg,part1,8000,start=start,duration=12.0)
            if win is None:row["match_error"]=err
            else:
                rr=fft_ncc(win,voice);er=envelope_ncc(win,voice)
                if rr:
                    best=start+rr["offset_samples"]/8000.0
                    row["raw_ncc"]=f"{rr['raw_ncc']:.6f}";row["best_audio_time_sec"]=f"{best:.3f}"
                    row["delta_from_subtitle_timestamp_sec"]=f"{best-test['timestamp_sec']:+.3f}"
                if er:row["envelope_ncc"]=f"{er[0]:.6f}"
        pilot_rows.append(row)
        print(f"  {test['name']}: raw={row['raw_ncc']} env={row['envelope_ncc']} best={row['best_audio_time_sec']} err={row['match_error']}",flush=True)
    write_tsv(out/"sub22_audio_pilot.tsv",pilot_rows,[
        "name","sub09_sequence","part","timestamp_sec","voice_id","expected_relation","video",
        "window_start_sec","window_duration_sec","voice_decode_available","raw_ncc","envelope_ncc",
        "best_audio_time_sec","delta_from_subtitle_timestamp_sec","match_error"
    ])

    print("[6/6] Summarize",flush=True)
    decoded_count=sum(r["decode_success"]=="YES" for r in voice_rows)
    pilot_completed=sum(bool(r["raw_ncc"]) for r in pilot_rows)
    readiness=("READY_FOR_FULL_AUDIO_ALIGNMENT" if part1 and decoded_count>=3 and pilot_completed>=3
               else "VOICE_READY_VIDEO_MISSING" if decoded_count>=3 and not part1
               else "NEEDS_AUDIO_DECODE_OR_VIDEO_FIX")
    ptrue=next((r for r in pilot_rows if r["name"]=="DRIFT_TRUE"),None)
    pfalse=next((r for r in pilot_rows if r["name"]=="DRIFT_WRONG_STRUCTURAL"),None)
    disc=""
    if ptrue and pfalse and ptrue["raw_ncc"] and pfalse["raw_ncc"]:
        disc=f"{float(ptrue['raw_ncc'])-float(pfalse['raw_ncc']):+.6f}"
    report={"stage":"SUB22","mode":"READ_ONLY_AUDIO_ALIGNMENT_READINESS","ffmpeg":str(ffmpeg),"ffprobe":str(ffprobe),
            "media_candidates":len(media),"part1_candidate":str(part1) if part1 else "",
            "part2_candidate":str(part2) if part2 else "","voice_samples":len(voice_rows),
            "voice_decode_success":decoded_count,"pilot_matches_completed":pilot_completed,
            "drift_true_minus_wrong_raw_ncc":disc,"readiness":readiness,"game_files_modified":False}
    (out/"sub22_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary=[
        "Naruto PSP SUB22 - Audio Anchor Readiness","",
        f"FFmpeg={ffmpeg}",f"FFprobe={ffprobe}",f"MediaCandidates={len(media)}",
        f"Part1Candidate={part1 or 'NOT FOUND'}",f"Part2Candidate={part2 or 'NOT FOUND'}",
        f"VoiceDecodeSuccess={decoded_count}/{len(voice_rows)}",f"PilotMatchesCompleted={pilot_completed}/{len(PILOTS)}",
        f"DriftTrueMinusWrongRawNCC={disc or 'N/A'}",f"Readiness={readiness}","",
        "Known semantic correction:",
        "  SUB09 #164 = event003#047 / s_a06_043",
        "  NOT event004#012 / s_a07_013.","",
        "No game files were modified."
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
