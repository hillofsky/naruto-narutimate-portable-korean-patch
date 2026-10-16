#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse, base64, csv, hashlib, io, json, os, re, shutil, socket, struct, subprocess, sys, time, traceback
from PIL import Image, ImageDraw, ImageStat, ImageChops

ROOT_DEFAULT = r"PROJECT_ROOT"
SUB51N_REL = Path(r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso")
PPSSPP_REL = Path(r"tools\ppsspp-stage33-2314\PPSSPPWindows64.exe")
OUT_REL = Path(r"analysis\sub\sub51n_pressed_runtime_qa_fix4")
PORTS = list(range(26400, 26420))


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def find_summary_sha(root: Path, actual: str):
    base=root/Path(r"analysis\sub\sub51n_titlehomepolish")
    candidates=[]
    if base.exists(): candidates += list(base.rglob("SUMMARY.txt"))
    for p in candidates:
        try:
            t=p.read_text(encoding="utf-8-sig",errors="replace")
        except Exception:
            continue
        vals=re.findall(r"(?i)\b[0-9a-f]{64}\b",t)
        if actual.lower() in [v.lower() for v in vals]:
            return actual.lower(), str(p)
        for pat in [r"(?im)^\s*(?:FinalSHA256|OutputSHA256|ISO_SHA256|SHA256)\s*[:=]\s*([0-9a-f]{64})\s*$"]:
            m=re.search(pat,t)
            if m: return m.group(1).lower(),str(p)
    return None,None


def choose_port():
    for p in PORTS:
        s=socket.socket()
        try:
            s.bind(("127.0.0.1",p)); return p
        except OSError:
            pass
        finally:s.close()
    raise RuntimeError("No free Naruto debugger port in 26400-26419")


class WS:
    def __init__(self,host,port):
        self.sock=socket.create_connection((host,port),timeout=4.0); self.sock.settimeout(8.0)
        key=base64.b64encode(os.urandom(16)).decode("ascii")
        req=(f"GET /debugger HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: debugger.ppsspp.org\r\n\r\n")
        self.sock.sendall(req.encode("ascii")); raw=b""
        while b"\r\n\r\n" not in raw:
            b=self.sock.recv(4096)
            if not b: raise RuntimeError("WebSocket handshake closed")
            raw+=b
        if " 101 " not in raw.split(b"\r\n\r\n",1)[0].decode("latin1","replace"):
            raise RuntimeError("WebSocket handshake failed")
        self.ticket=0
    def close(self):
        try:self._send_frame(b"",8)
        except:pass
        try:self.sock.close()
        except:pass
    def _send_frame(self,payload:bytes,opcode=1):
        first=0x80|(opcode&15); n=len(payload); mask=os.urandom(4)
        if n<126: head=bytes([first,0x80|n])
        elif n<65536: head=bytes([first,0x80|126])+struct.pack("!H",n)
        else: head=bytes([first,0x80|127])+struct.pack("!Q",n)
        self.sock.sendall(head+mask+bytes(b^mask[i&3] for i,b in enumerate(payload)))
    def _recvn(self,n):
        out=b""
        while len(out)<n:
            b=self.sock.recv(n-len(out))
            if not b: raise RuntimeError("WebSocket closed")
            out+=b
        return out
    def _recv_frame(self):
        h=self._recvn(2); b0,b1=h; opcode=b0&15; n=b1&127; masked=bool(b1&128)
        if n==126:n=struct.unpack("!H",self._recvn(2))[0]
        elif n==127:n=struct.unpack("!Q",self._recvn(8))[0]
        mask=self._recvn(4) if masked else None; payload=self._recvn(n)
        if mask: payload=bytes(b^mask[i&3] for i,b in enumerate(payload))
        if opcode==9:self._send_frame(payload,10); return self._recv_frame()
        if opcode==8:raise RuntimeError("WebSocket server closed connection")
        return opcode,payload
    def request(self,event,**kwargs):
        self.ticket+=1; ticket=self.ticket; obj={"event":event,"ticket":ticket}; obj.update(kwargs)
        self._send_frame(json.dumps(obj,separators=(",",":")).encode("utf-8")); end=time.time()+12
        while time.time()<end:
            op,p=self._recv_frame()
            if op!=1:continue
            m=json.loads(p.decode("utf-8","replace"))
            if m.get("event")=="error" and m.get("ticket")==ticket: raise RuntimeError(f"{event}: {m.get('message')}")
            if m.get("ticket")==ticket and m.get("event")==event:return m
        raise TimeoutError(event)
    def notify(self,event,**kwargs):
        # Deferred debugger events such as cpu.stepping / cpu.resume intentionally
        # have no immediate response. Send them without a ticket and observe state
        # through cpu.status instead of timing out waiting for an acknowledgement.
        obj={"event":event}; obj.update(kwargs)
        self._send_frame(json.dumps(obj,separators=(",",":")).encode("utf-8"))
    def status(self):
        return self.request("cpu.status")
    def screenshot(self):
        m=self.request("gpu.buffer.screenshot",type="uri"); u=m.get("uri")
        if not u or "," not in u:raise RuntimeError("Screenshot response missing PNG URI")
        return Image.open(io.BytesIO(base64.b64decode(u.split(",",1)[1]))).convert("RGBA")
    def wait_stepping(self,want,timeout=4.0):
        end=time.time()+timeout; last=None
        while time.time()<end:
            try:
                st=self.status(); last=st
                if bool(st.get("stepping"))==bool(want):
                    return st
            except Exception as e:
                last={"error":str(e)}
            time.sleep(.04)
        raise RuntimeError(f"cpu stepping state did not become {want}; last={last}")
    def pause_for_capture(self):
        st=self.status()
        if not st.get("stepping"):
            self.notify("cpu.stepping")
            st=self.wait_stepping(True,4.0)
        return st
    def resume(self):
        st=self.status()
        if st.get("stepping"):
            self.notify("cpu.resume")
            try:self.wait_stepping(False,4.0)
            except Exception:
                # Some older builds report transition events slightly differently.
                # A later status/tick check is authoritative.
                pass
    def capture_running(self):
        self.pause_for_capture()
        try:
            return self.screenshot()
        finally:
            try:self.resume()
            except:pass
    def press(self,button,frames=2):self.request("input.buttons.press",button=button,duration=int(frames))
    def button(self,button,down):self.request("input.buttons.send",buttons={button:bool(down)})


def find_ppsspp(root):
    p=root/PPSSPP_REL
    if p.exists():return p
    hits=list(root.glob("tools/**/PPSSPPWindows64.exe"))
    if hits:return hits[0]
    raise RuntimeError("PPSSPPWindows64.exe not found")


def launch(root,iso,port):
    exe=find_ppsspp(root)
    return subprocess.Popen([str(exe),str(iso),f"--debugger={port}"],cwd=str(exe.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def connect_retry(port,timeout=25):
    end=time.time()+timeout; last=None
    while time.time()<end:
        try:
            w=WS("127.0.0.1",port)
            try:w.request("version",name="naruto-sub51n-fix4",version="1.0")
            except:pass
            return w
        except Exception as e:last=e;time.sleep(.3)
    raise RuntimeError("Debugger connection failed: "+repr(last))




def wait_runtime_ready(ws,outdir,label,timeout=45.0):
    """Start a debugger-paused PPSSPP game, verify emulated time advances,
    and prove pause/screenshot/resume works before title-menu QA.

    --debugger starts at the game entry point in stepping mode. GPU buffer reads
    require stepping, so normal screenshots are captured by briefly pausing.
    """
    end=time.time()+timeout; attempts=0; last=None
    resumed_once=False; first_us=None; advancing_seen=False
    while time.time()<end:
        attempts+=1
        try:
            st=ws.status()
            last=st
            pc=int(st.get("pc") or 0)
            us=float(st.get("us") or 0.0)
            # CPU not alive / boot incomplete yet.
            if pc==0 and us==0:
                time.sleep(.25); continue

            if first_us is None:first_us=us

            # PPSSPP --debugger starts paused at entry point. Resume exactly once
            # (and again only if an external/UI pause unexpectedly reappears.)
            if st.get("stepping"):
                ws.notify("cpu.resume")
                resumed_once=True
                time.sleep(.20)
                continue

            if us > (first_us or 0) + 1000:
                advancing_seen=True

            if advancing_seen:
                # Prove the exact capture sequence required by this PPSSPP build:
                # running -> cpu.stepping -> gpu.buffer.screenshot -> cpu.resume.
                im=ws.capture_running()
                p=outdir/f"{label}_runtime_ready.png"; im.save(p)
                st2=ws.status()
                return {
                    "ready":True,"attempts":attempts,
                    "wait_seconds":round(timeout-max(0.0,end-time.time()),3),
                    "first_frame":str(p),"resumed_from_debugger_entry":resumed_once,
                    "emulated_us":st2.get("us"),"capture_mode":"pause_screenshot_resume"
                }
        except Exception as e:
            last={"error":str(e)}
        time.sleep(.20)
    raise RuntimeError(f"{label}: runtime did not enter run/pause-capture cycle within {timeout:.0f}s; last={last}")

def crop_native(im,box):
    w,h=im.size; x0,y0,x1,y1=box
    return im.crop((x0*w//480,y0*h//272,x1*w//480,y1*h//272))


def mean_abs_diff(a,b):
    d=ImageChops.difference(a.convert("RGB"),b.convert("RGB")).convert("L")
    return ImageStat.Stat(d).mean[0]


def selection_response(before,after):
    # Two title scroll regions + whole-screen/background comparison.
    menu_box=(304,150,470,261)
    bg_box=(0,0,280,272)
    md=mean_abs_diff(crop_native(before,menu_box),crop_native(after,menu_box))
    bd=mean_abs_diff(crop_native(before,bg_box),crop_native(after,bg_box))
    ratio=md/max(1.0,bd)
    # Selection movement is usually a localized, clearly visible change in the two scrolls.
    ok=(md>=4.0 and ratio>=1.25) or md>=10.0
    return {"menu_delta":round(md,3),"background_delta":round(bd,3),"ratio":round(ratio,3),"localized_selection_response":ok}


def menu_luma(im):
    def m(box):return ImageStat.Stat(crop_native(im,box).convert("L")).mean[0]
    return m((330,164,452,204)),m((326,204,456,258))


def reach_continue_selected(ws,outdir,label):
    # FIX2: never spam START. First let normal boot settle.
    timeline=[]
    for i in range(8):
        im=ws.capture_running(); im.save(outdir/f"{label}_boot_{i:02d}.png"); timeline.append(f"boot_{i:02d}"); time.sleep(.75)

    attempts=[]
    # Probe DOWN first. If the menu is already present, this moves top -> bottom and START is never sent.
    # If not, only one START pulse is sent per attempt, with a full settle delay before probing again.
    for attempt in range(4):
        before=ws.capture_running(); before.save(outdir/f"{label}_a{attempt}_before_down.png")
        ws.press("down",2); time.sleep(.55)
        after=ws.capture_running(); after.save(outdir/f"{label}_a{attempt}_after_down.png")
        resp=selection_response(before,after); resp["attempt"]=attempt
        top,bottom=menu_luma(after); resp["top_luma"]=round(top,2); resp["bottom_luma"]=round(bottom,2)
        attempts.append(resp)
        if resp["localized_selection_response"]:
            # This DOWN is our positive proof that interactive title-menu selection exists.
            # It should now be on the lower/continue item from the default top item.
            after.save(outdir/f"{label}_continue_selected.png")
            return after,attempts,attempt
        if attempt<3:
            ws.press("start",2)
            im=ws.capture_running(); im.save(outdir/f"{label}_a{attempt}_immediate_after_start.png")
            time.sleep(2.2)
            im=ws.capture_running(); im.save(outdir/f"{label}_a{attempt}_settled_after_start.png")
    # Preserve complete diagnostics instead of silently overrunning the menu.
    raise RuntimeError(label+": no localized title-menu selection response after gated START attempts")


def dense_pressed_capture(ws,outdir,label,frames=32):
    paths=[]; ws.button("circle",True)
    try:
        for i in range(frames):
            im=ws.capture_running(); p=outdir/f"{label}_pressed_{i:03d}.png"; im.save(p); paths.append(p); time.sleep(.018)
    finally:
        try:ws.button("circle",False)
        except:pass
    time.sleep(.25); ws.capture_running().save(outdir/f"{label}_after_release.png")
    return paths


def find_jp_iso(root):
    c=[]
    for p in root.rglob("*.iso"):
        low=str(p).lower()
        if "\\analysis\\" in low or "/analysis/" in low or "sub51" in low or "generated" in low:continue
        c.append(p)
    c.sort(key=lambda p:(0 if any(k in p.name.lower() for k in ("uljs","japan","mugenjou","narutimate")) else 1,len(str(p))))
    needles=(b"ULJS00055",b"ULJS-00055")
    for p in c:
        try:
            with p.open("rb") as f:
                left=96*1024*1024; tail=b""
                while left>0:
                    b=f.read(min(1024*1024,left))
                    if not b:break
                    q=tail+b
                    if any(n in q for n in needles):return p
                    tail=q[-32:];left-=len(b)
        except:pass
    return None


def run_one(root,iso,outdir,label):
    port=choose_port(); proc=launch(root,iso,port); ws=None
    try:
        ws=connect_retry(port)
        ready=wait_runtime_ready(ws,outdir,label,45.0)
        selected,attempts,accepted_attempt=reach_continue_selected(ws,outdir,label)
        pressed=dense_pressed_capture(ws,outdir,label,32)
        return {"port":port,"runtime_ready":ready,"attempts":attempts,"accepted_attempt":accepted_attempt,"pressed":[str(p) for p in pressed]}
    finally:
        if ws:ws.close()
        try:proc.terminate();proc.wait(timeout=4)
        except:
            try:proc.kill()
            except:pass
        time.sleep(.8)


def metric(path):
    try:
        import numpy as np
    except Exception as e:raise RuntimeError("numpy required: "+str(e))
    q=np.asarray(Image.open(path).convert("RGB")); h,w,_=q.shape
    q=q[196*h//272:260*h//272,315*w//480:460*w//480,:].astype("int16")
    white=((q[:,:,0]>220)&(q[:,:,1]>220)&(q[:,:,2]>220)).sum()
    green=((q[:,:,1]>55)&(q[:,:,1]>q[:,:,0]*1.08)&(q[:,:,1]>q[:,:,2]*1.05)).sum()
    red=((q[:,:,0]>80)&(q[:,:,0]>q[:,:,1]*1.18)).sum()
    return int(white),int(green),int(red)


def build_contact(ko,jp,out):
    n=max(len(ko),len(jp),1); cw,ch=480,272
    sheet=Image.new("RGB",(cw*2,ch*n),(20,20,20));d=ImageDraw.Draw(sheet)
    for i in range(n):
        if i<len(ko):sheet.paste(Image.open(ko[i]).convert("RGB").resize((cw,ch)),(0,i*ch))
        if i<len(jp):sheet.paste(Image.open(jp[i]).convert("RGB").resize((cw,ch)),(cw,i*ch))
        d.text((5,i*ch+5),f"KO {i:02d}",fill="yellow");d.text((cw+5,i*ch+5),f"JP {i:02d}",fill="yellow")
    sheet.save(out)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=ROOT_DEFAULT);a=ap.parse_args();root=Path(a.root)
    iso=root/SUB51N_REL;out=root/OUT_REL
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True)
    if not iso.exists():raise RuntimeError("Latest SUB51N ISO missing: "+str(iso))
    actual=sha256_file(iso); summary_sha,summary_path=find_summary_sha(root,actual)
    pre={"stage":"SUB51N_FIX4_PRESSED_RUNTIME_QA","iso":str(iso),"actual_sha256":actual,
         "summary_sha256":summary_sha,"summary_path":summary_path,"summary_sha_match":summary_sha==actual if summary_sha else None,
         "normal_boot":True,"save_state_used":False,"game_modified":False,"bc250_used":False,"local_llm_used":False,
         "fix4":"resume from debugger entry; each screenshot uses pause/stepping -> GPU capture -> resume; gated START + DOWN proof; no START spam"}
    (out/"preflight.json").write_text(json.dumps(pre,ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== SUB51N FIX4 PRESSED RUNTIME QA ===",flush=True);print("ISO:",iso,flush=True);print("SHA256:",actual,flush=True)
    ko_dir=out/"ko";ko_dir.mkdir();print("[1/3] KO normal boot + gated menu reach + pressed capture",flush=True)
    ko=run_one(root,iso,ko_dir,"ko")
    (out/"ko_runtime.json").write_text(json.dumps(ko,ensure_ascii=False,indent=2),encoding="utf-8")
    print("[2/3] JP comparison source",flush=True);jp_iso=find_jp_iso(root);jp=None;jp_dir=out/"jp"
    if jp_iso:
        jp_dir.mkdir();print("Japanese ISO:",jp_iso,flush=True);jp=run_one(root,jp_iso,jp_dir,"jp")
        (out/"jp_runtime.json").write_text(json.dumps(jp,ensure_ascii=False,indent=2),encoding="utf-8")
    else:print("Japanese ULJS-00055 ISO not found; KO capture remains valid.",flush=True)
    print("[3/3] metrics/contact",flush=True)
    kp=sorted(ko_dir.glob("ko_pressed_*.png"));jp_paths=sorted(jp_dir.glob("jp_pressed_*.png")) if jp else []
    rows=[]
    for i,p in enumerate(kp):
        kw,kg,kr=metric(p);r={"frame":i,"ko_white":kw,"ko_green":kg,"ko_red":kr}
        if i<len(jp_paths):
            jw,jg,jr=metric(jp_paths[i]);r.update(jp_white=jw,jp_green=jg,jp_red=jr,white_delta=kw-jw,green_delta=kg-jg,red_delta=kr-jr)
        rows.append(r)
    fields=["frame","ko_white","ko_green","ko_red","jp_white","jp_green","jp_red","white_delta","green_delta","red_delta"]
    with (out/"pressed_metrics.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader();w.writerows(rows)
    build_contact(kp,jp_paths,out/"pressed_KO_vs_JP_contact.png")
    result={**pre,"ko_pressed_frames":len(kp),"jp_iso":str(jp_iso) if jp_iso else None,"jp_pressed_frames":len(jp_paths),
            "runtime_qa_status":"CAPTURE_COMPLETE_NEEDS_VISUAL_JUDGEMENT",
            "required_judgement":["Korean pressed state has no white block","green scroll/roll remains visible","left side is not clipped","compare KO and JP pressed frames"]}
    (out/"RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51N FIX4 Pressed Runtime QA\n\n"+f"ISO={iso}\nActualSHA256={actual}\nSummarySHA256={summary_sha or 'NOT_FOUND'}\n"
        +f"SummaryPath={summary_path or 'NOT_FOUND'}\nSummarySHAMatch={result['summary_sha_match']}\nKOPressedFrames={len(kp)}\nJapaneseISO={jp_iso or 'NOT_FOUND'}\nJPPressedFrames={len(jp_paths)}\n"
        +"RuntimeReadyGate=RESUME_THEN_PAUSE_SCREENSHOT_RESUME\nNormalBoot=YES\nOldSaveStateVisualQA=NO\nGameDataModified=NO\nSTARTSpam=NO\nMenuReachProof=DOWN_LOCALIZED_RESPONSE\nRuntimeQAStatus=CAPTURE_COMPLETE_NEEDS_VISUAL_JUDGEMENT\n",
        encoding="utf-8-sig")
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
