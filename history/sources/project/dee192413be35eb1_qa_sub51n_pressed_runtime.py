#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
from pathlib import Path
import argparse, base64, hashlib, json, os, random, re, socket, struct, subprocess, sys, time, traceback
from PIL import Image, ImageDraw, ImageStat
import io

ROOT_DEFAULT = r"PROJECT_ROOT"
SUB51N_REL = Path(r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso")
SUMMARY_REL = Path(r"analysis\sub\sub51n_titlehomepolish\SUMMARY.txt")
PPSSPP_REL = Path(r"tools\ppsspp-stage33-2314\PPSSPPWindows64.exe")
OUT_REL = Path(r"analysis\sub\sub51n_pressed_runtime_qa")
PORTS = list(range(26400, 26420))

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def read_summary_sha(path: Path):
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    pats = [
        r"(?im)^\s*FinalSHA256\s*=\s*([0-9a-f]{64})\s*$",
        r"(?im)^\s*FinalSHA256\s*:\s*([0-9a-f]{64})\s*$",
        r"(?im)^\s*SHA256\s*=\s*([0-9a-f]{64})\s*$",
    ]
    for p in pats:
        m = re.search(p, text)
        if m:
            return m.group(1).lower()
    return None

def choose_port():
    for p in PORTS:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            pass
        finally:
            s.close()
    raise RuntimeError("No free debugger port in 26400-26419")

class WS:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=4.0)
        self.sock.settimeout(8.0)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET /debugger HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: debugger.ppsspp.org\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket handshake closed")
            raw += chunk
        header = raw.split(b"\r\n\r\n",1)[0].decode("latin1","replace")
        if " 101 " not in header:
            raise RuntimeError("WebSocket handshake failed: " + header[:500])
        self.ticket = 0

    def close(self):
        try:
            self._send_frame(b"", opcode=8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def _send_frame(self, payload: bytes, opcode=1):
        # Client frames must be masked.
        first = 0x80 | (opcode & 0x0f)
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            head = bytes([first, 0x80 | n])
        elif n < 65536:
            head = bytes([first, 0x80 | 126]) + struct.pack("!H", n)
        else:
            head = bytes([first, 0x80 | 127]) + struct.pack("!Q", n)
        masked = bytes(b ^ mask[i & 3] for i,b in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def _recvn(self, n):
        out = b""
        while len(out) < n:
            b = self.sock.recv(n-len(out))
            if not b:
                raise RuntimeError("WebSocket closed")
            out += b
        return out

    def _recv_frame(self):
        h = self._recvn(2)
        b0,b1 = h[0],h[1]
        opcode = b0 & 0x0f
        masked = bool(b1 & 0x80)
        n = b1 & 0x7f
        if n == 126:
            n = struct.unpack("!H", self._recvn(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._recvn(8))[0]
        mask = self._recvn(4) if masked else None
        payload = self._recvn(n)
        if mask:
            payload = bytes(b ^ mask[i & 3] for i,b in enumerate(payload))
        if opcode == 9:  # ping
            self._send_frame(payload, opcode=10)
            return self._recv_frame()
        if opcode == 8:
            raise RuntimeError("WebSocket server closed connection")
        return opcode,payload

    def request(self, event, **kwargs):
        self.ticket += 1
        ticket = self.ticket
        obj = {"event":event, "ticket":ticket}
        obj.update(kwargs)
        self._send_frame(json.dumps(obj,separators=(",",":")).encode("utf-8"))
        end = time.time() + 12.0
        while time.time() < end:
            opcode,payload = self._recv_frame()
            if opcode != 1:
                continue
            msg = json.loads(payload.decode("utf-8","replace"))
            if msg.get("event") == "error" and msg.get("ticket") == ticket:
                raise RuntimeError(f"{event}: {msg.get('message')}")
            if msg.get("ticket") == ticket and msg.get("event") == event:
                return msg
        raise TimeoutError(event)

    def screenshot(self) -> Image.Image:
        msg = self.request("gpu.buffer.screenshot", type="uri")
        uri = msg.get("uri")
        if not uri or "," not in uri:
            raise RuntimeError("Screenshot response missing PNG URI")
        raw = base64.b64decode(uri.split(",",1)[1])
        return Image.open(io.BytesIO(raw)).convert("RGBA")

    def press(self, button, frames=2):
        self.request("input.buttons.press", button=button, duration=int(frames))

    def button(self, button, down):
        self.request("input.buttons.send", buttons={button:bool(down)})

def find_ppsspp(root: Path):
    p = root / PPSSPP_REL
    if p.exists():
        return p
    hits = list(root.glob("tools/**/PPSSPPWindows64.exe"))
    if hits:
        return hits[0]
    raise RuntimeError("PPSSPPWindows64.exe not found")

def launch(root: Path, iso: Path, port: int):
    exe = find_ppsspp(root)
    return subprocess.Popen(
        [str(exe), str(iso), f"--debugger={port}"],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def connect_retry(port, timeout=20.0):
    end=time.time()+timeout
    last=None
    while time.time()<end:
        try:
            ws=WS("127.0.0.1",port)
            try:
                ws.request("version", name="naruto-sub51n-qa", version="1.0")
            except Exception:
                pass
            return ws
        except Exception as e:
            last=e
            time.sleep(0.3)
    raise RuntimeError("Debugger connection failed: "+repr(last))

def menu_luma(im: Image.Image):
    # 480x272 native framebuffer coordinates, scaled if necessary.
    w,h=im.size
    def crop_mean(box):
        x0,y0,x1,y1=box
        c=im.crop((x0*w//480,y0*h//272,x1*w//480,y1*h//272)).convert("L")
        return ImageStat.Stat(c).mean[0]
    top=crop_mean((346,171,438,197))
    bottom=crop_mean((338,211,448,244))
    return top,bottom

def likely_title(im):
    top,bottom=menu_luma(im)
    # Title menu normally has one dark and one light scroll interior.
    return abs(top-bottom) >= 28 and max(top,bottom) >= 100

def wait_for_title(ws, outdir: Path, label: str, max_seconds=35):
    start=time.time()
    i=0
    last=None
    while time.time()-start < max_seconds:
        try:
            im=ws.screenshot()
            last=im
            if likely_title(im):
                im.save(outdir/f"{label}_title_detected.png")
                return im
        except Exception:
            pass
        # Start safely skips/advances opening/title splash without selecting a menu item.
        try:
            ws.press("start",2)
        except Exception:
            pass
        time.sleep(0.8)
        i+=1
    if last is not None:
        last.save(outdir/f"{label}_title_detection_failed_last.png")
    raise RuntimeError(label+": title menu not detected within timeout")

def ensure_continue_selected(ws, outdir, label):
    im=ws.screenshot()
    top,bottom=menu_luma(im)
    # In this UI, the selected scroll is the lighter one.
    if bottom <= top:
        ws.press("down",2)
        time.sleep(0.35)
        im=ws.screenshot()
        top,bottom=menu_luma(im)
    im.save(outdir/f"{label}_continue_selected.png")
    if bottom <= top:
        raise RuntimeError(f"{label}: could not confirm bottom/continue selected (top={top:.1f}, bottom={bottom:.1f})")
    return im,top,bottom

def dense_pressed_capture(ws, outdir, label, frames=24):
    ws.button("circle", True)
    captured=[]
    try:
        for i in range(frames):
            im=ws.screenshot()
            p=outdir/f"{label}_pressed_{i:03d}.png"
            im.save(p)
            captured.append(p)
            time.sleep(0.012)
    finally:
        try:
            ws.button("circle", False)
        except Exception:
            pass
    time.sleep(0.2)
    ws.screenshot().save(outdir/f"{label}_after_release.png")
    return captured

def white_green_metrics(path: Path):
    im=np_image(path)
    h,w,_=im.shape
    # Left side of the lower "continue" scroll.
    x0,x1=326*w//480,382*w//480
    y0,y1=199*h//272,252*h//272
    q=im[y0:y1,x0:x1,:3].astype("int16")
    white=((q[:,:,0]>220)&(q[:,:,1]>220)&(q[:,:,2]>220)).sum()
    green=((q[:,:,1]>55)&(q[:,:,1]>q[:,:,0]*1.08)&(q[:,:,1]>q[:,:,2]*1.05)).sum()
    red=((q[:,:,0]>80)&(q[:,:,0]>q[:,:,1]*1.18)).sum()
    return int(white),int(green),int(red)

def np_image(path):
    # Avoid a numpy dependency: convert to nested bytes, then import numpy only if present.
    try:
        import numpy as np
        return np.asarray(Image.open(path).convert("RGBA"))
    except Exception as e:
        raise RuntimeError("numpy is required for metrics and is expected in this Naruto tool environment: "+str(e))

def build_contact(ko_paths, jp_paths, out):
    pairs=max(len(ko_paths),len(jp_paths),1)
    cellw,cellh=480,272
    sheet=Image.new("RGB",(cellw*2,cellh*pairs),(20,20,20))
    d=ImageDraw.Draw(sheet)
    for i in range(pairs):
        if i < len(ko_paths):
            k=Image.open(ko_paths[i]).convert("RGB").resize((cellw,cellh))
            sheet.paste(k,(0,i*cellh))
        if i < len(jp_paths):
            j=Image.open(jp_paths[i]).convert("RGB").resize((cellw,cellh))
            sheet.paste(j,(cellw,i*cellh))
        d.text((5,i*cellh+5),f"KO {i:02d}",fill="yellow")
        d.text((cellw+5,i*cellh+5),f"JP {i:02d}",fill="yellow")
    sheet.save(out)

def find_jp_iso(root: Path):
    # Avoid analysis-generated ISOs. Scan likely user/source ISOs for ULJS-00055 in first 96 MiB.
    candidates=[]
    for p in root.rglob("*.iso"):
        low=str(p).lower()
        if "\\analysis\\" in low or "/analysis/" in low:
            continue
        if "sub51" in low or "generated" in low:
            continue
        candidates.append(p)
    # Likely filenames first.
    candidates.sort(key=lambda p: (
        0 if any(k in p.name.lower() for k in ("uljs","japan","mugenjou","narutimate")) else 1,
        len(str(p))
    ))
    needles=(b"ULJS00055",b"ULJS-00055")
    for p in candidates:
        try:
            with p.open("rb") as f:
                remaining=96*1024*1024
                tail=b""
                while remaining>0:
                    b=f.read(min(1024*1024,remaining))
                    if not b:break
                    q=tail+b
                    if any(n in q for n in needles):
                        return p
                    tail=q[-32:]
                    remaining-=len(b)
        except Exception:
            pass
    return None

def run_one(root, iso, outdir, label):
    port=choose_port()
    proc=launch(root,iso,port)
    ws=None
    try:
        ws=connect_retry(port)
        wait_for_title(ws,outdir,label)
        selected,top,bottom=ensure_continue_selected(ws,outdir,label)
        pressed=dense_pressed_capture(ws,outdir,label,24)
        return {"port":port,"selected_top_luma":top,"selected_bottom_luma":bottom,
                "pressed":[str(p) for p in pressed]}
    finally:
        if ws:
            ws.close()
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            try: proc.kill()
            except Exception: pass
        time.sleep(0.8)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=ROOT_DEFAULT)
    a=ap.parse_args()
    root=Path(a.root)
    iso=root/SUB51N_REL
    summary=root/SUMMARY_REL
    out=root/OUT_REL
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if not iso.exists():
        raise RuntimeError("Latest SUB51N ISO missing: "+str(iso))

    actual_sha=sha256_file(iso)
    summary_sha=read_summary_sha(summary)
    pre={
        "stage":"SUB51N_PRESSED_RUNTIME_QA",
        "iso":str(iso),
        "actual_sha256":actual_sha,
        "summary_sha256":summary_sha,
        "summary_sha_match": (summary_sha==actual_sha if summary_sha else None),
        "normal_boot":True,
        "save_state_used":False,
        "game_modified":False,
        "bc250_used":False,
        "local_llm_used":False,
    }
    (out/"preflight.json").write_text(json.dumps(pre,ensure_ascii=False,indent=2),encoding="utf-8")

    ko_dir=out/"ko";ko_dir.mkdir()
    print("=== SUB51N pressed runtime QA ===",flush=True)
    print("ISO:",iso,flush=True)
    print("SHA256:",actual_sha,flush=True)
    print("Summary SHA:",summary_sha or "(not found)",flush=True)
    print("[1/3] Normal-boot Korean latest SUB51N and capture dense pressed frames",flush=True)
    ko=run_one(root,iso,ko_dir,"ko")

    print("[2/3] Find Japanese ULJS-00055 source for same-frame comparison",flush=True)
    jp_iso=find_jp_iso(root)
    jp=None
    jp_dir=out/"jp"
    if jp_iso:
        jp_dir.mkdir()
        print("Japanese ISO:",jp_iso,flush=True)
        jp=run_one(root,jp_iso,jp_dir,"jp")
    else:
        print("Japanese ULJS-00055 ISO not found outside analysis; KO capture still valid.",flush=True)

    print("[3/3] Generate metrics/contact sheet",flush=True)
    ko_paths=sorted(ko_dir.glob("ko_pressed_*.png"))
    jp_paths=sorted(jp_dir.glob("jp_pressed_*.png")) if jp else []

    metrics=[]
    for i,p in enumerate(ko_paths):
        kw,kg,kr=white_green_metrics(p)
        row={"frame":i,"ko_white":kw,"ko_green":kg,"ko_red":kr}
        if i<len(jp_paths):
            jw,jg,jr=white_green_metrics(jp_paths[i])
            row.update(jp_white=jw,jp_green=jg,jp_red=jr,
                       white_delta=kw-jw,green_delta=kg-jg,red_delta=kr-jr)
        metrics.append(row)

    fields=["frame","ko_white","ko_green","ko_red","jp_white","jp_green","jp_red",
            "white_delta","green_delta","red_delta"]
    import csv
    with (out/"pressed_metrics.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(metrics)

    build_contact(ko_paths,jp_paths,out/"pressed_KO_vs_JP_contact.png")

    result={
        **pre,
        "ko_pressed_frames":len(ko_paths),
        "jp_iso":str(jp_iso) if jp_iso else None,
        "jp_pressed_frames":len(jp_paths),
        "runtime_qa_status":"CAPTURE_COMPLETE_NEEDS_VISUAL_JUDGEMENT",
        "required_judgement":[
            "white block disappears in Korean pressed state",
            "green scroll roll remains visible",
            "left side is not clipped",
            "compare to Japanese pressed frames if available"
        ],
    }
    (out/"RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51N Latest Pressed Runtime QA\n\n"
        f"ISO={iso}\nActualSHA256={actual_sha}\n"
        f"SummarySHA256={summary_sha or 'NOT_FOUND'}\n"
        f"SummarySHAMatch={result['summary_sha_match']}\n"
        f"KOPressedFrames={len(ko_paths)}\n"
        f"JapaneseISO={jp_iso or 'NOT_FOUND'}\n"
        f"JPPressedFrames={len(jp_paths)}\n"
        "NormalBoot=YES\nOldSaveStateVisualQA=NO\n"
        "GameDataModified=NO\nBC250Used=NO\nLocalLLMUsed=NO\n"
        "RuntimeQAStatus=CAPTURE_COMPLETE_NEEDS_VISUAL_JUDGEMENT\n",
        encoding="utf-8-sig"
    )
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
