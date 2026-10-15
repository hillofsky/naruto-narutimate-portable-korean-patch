#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52Q: isolated PPSSPP live-texture capture, read-only ISO, per-process PID bound.
The only gameplay interaction is user-controlled; no automated inputs, no other PPSSPP control.
"""
from __future__ import annotations
import argparse, configparser, csv, hashlib, json, os, shutil, socket, subprocess
import sys, tempfile, time, traceback, zipfile
from pathlib import Path
from datetime import datetime

ROOT = Path(r'D:\narutimate portable')
SOURCE_ISO = ROOT / r'analysis\sub\sub52n_reward_safe_fix1\Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso'
SOURCE_SHA = '00bd998359e64e5d3f2af28c4f0d5b0dac7db8b11a35b773ea8a4ee290d58663'
EXE = Path(r'C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe')
LOG_ROOT = ROOT / 'logs'
NAME = 'naruto_sub52q_live_texture_probe'
MAX_SAMPLE_BYTES = 350*1024*1024


def sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda: f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()


def select_port():
    for port in range(39410, 39530):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            try: s.bind(('127.0.0.1',port)); return port
            except OSError: continue
    raise RuntimeError('No free local debugger port available')


def maybe_ini_candidates(exe):
    return [
      exe.parent/'memstick'/'PSP'/'SYSTEM'/'ppsspp.ini',
      exe.parent/'PSP'/'SYSTEM'/'ppsspp.ini',
      Path.home()/'Documents'/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
      Path(os.environ.get('APPDATA',''))/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
    ]


def build_isolated_settings(work, exe):
    memstick = work/'memstick'
    sysdir = memstick/'PSP'/'SYSTEM';sysdir.mkdir(parents=True,exist_ok=True)
    original = next((p for p in maybe_ini_candidates(exe) if p.exists()),None)
    ini=sysdir/'ppsspp.ini'
    cfg=configparser.ConfigParser(interpolation=None,strict=False)
    cfg.optionxform=str
    if original:
        try:
            cfg.read(original,encoding='utf-8-sig')
        except Exception:
            cfg=configparser.ConfigParser(interpolation=None,strict=False)
            cfg.optionxform=str
        # Reuse controls without changing original memstick.
        controls=original.parent/'controls.ini'
        if controls.exists(): shutil.copy2(controls,sysdir/'controls.ini')
    if not cfg.has_section('Graphics'): cfg.add_section('Graphics')
    for k,v in {'SaveNewTextures':'True','ReplaceTextures':'False','TexScalingLevel':'1'}.items():
        cfg.set('Graphics',k,v)
    with ini.open('w',encoding='utf-8') as f:cfg.write(f,space_around_delimiters=True)
    # A command line overlay is loaded after default settings, keeping the capture flags on.
    overlay=work/'sub52q_overrides.ini'
    overlay.write_text('[Graphics]\nSaveNewTextures = True\nReplaceTextures = False\nTexScalingLevel = 1\n',encoding='utf-8')
    return memstick,original,overlay


def check_ws_instance(port,pid,iso,report):
    try:
        import websocket
    except ImportError:
        report['debugger_websocket']='websocket-client package missing: skip PID check'
        return
    uri=f'ws://127.0.0.1:{port}/debugger'
    for i in range(20):
        try:
            ws=websocket.create_connection(uri,timeout=2,subprotocols=['debugger.ppsspp.org'],http_proxy_host=None)
            ws.send(json.dumps({'event':'version','name':'sub52q','version':'1.0','ticket':1}))
            for _ in range(6):
                r=json.loads(ws.recv())
                if r.get('ticket')==1 and r.get('event')=='version':
                    ws.close()
                    report['debugger_version']=r
                    gotpid=r.get('pid')
                    gotpath=str(r.get('path') or '')
                    if gotpid!=pid:
                        raise RuntimeError(f'Debugger PID mismatch: expected={pid}, got={gotpid}; no control attempted')
                    # Some PPSSPP builds send path=null during boot. Validate when non-empty.
                    if gotpath and os.path.normcase(os.path.normpath(gotpath))!=os.path.normcase(os.path.normpath(str(iso))):
                        raise RuntimeError(f'Debugger game path mismatch: {gotpath}; no control attempted')
                    report['debugger_websocket']='PID verified'+(' and ISO path verified' if gotpath else '; ISO path not yet reported')
                    return
            ws.close()
        except RuntimeError:
            raise
        except Exception as e:
            report['debugger_retry_info']=repr(e)[:240]
            time.sleep(0.5)
    report['debugger_websocket']='Unavailable, capture may still work (no other process controlled)'


def texture_files(memstick):
    base=memstick/'PSP'/'TEXTURES'
    if not base.exists():return []
    return sorted([p for p in base.rglob('*.png') if 'new' in [x.lower() for x in p.parts] and p.is_file()])


def inventory(items,memstick):
    rows=[]
    for p in items:
        try:
            st=p.stat();rows.append({'path':str(p.relative_to(memstick)),'size':st.st_size,'sha256':sha256_file(p)})
        except OSError:continue
    return rows


def snapshot(memstick):
    fs=texture_files(memstick)
    return {'files':len(fs),'bytes':sum(p.stat().st_size for p in fs),'names':[str(p.relative_to(memstick)) for p in fs]}


def ensure_pillow(report):
    try:
        from PIL import Image,ImageOps,ImageDraw,ImageFont
        return Image,ImageOps,ImageDraw,ImageFont
    except ImportError:
        print('Pillow installing to create small comparison sheets...',flush=True)
        r=subprocess.run([sys.executable,'-m','pip','install','--user','--disable-pip-version-check','Pillow'],capture_output=True,text=True)
        report['pillow_install_stdout']=r.stdout[-1200:]
        report['pillow_install_stderr']=r.stderr[-1200:]
        if r.returncode:raise RuntimeError('Pillow install failed')
        from PIL import Image,ImageOps,ImageDraw,ImageFont
        return Image,ImageOps,ImageDraw,ImageFont


def collect_comparison(memstick,stage_data,pack,reference,report):
    fs=texture_files(memstick)
    if not fs:
        report['classification']='NO_TEXTURE_DUMP: check isolated PPSSPP version/ini/texture dumping'
        return
    Image,ImageOps,ImageDraw,ImageFont=ensure_pillow(report)
    ref_imgs=[]
    for p in sorted(reference.glob('*.png')):
        try:
            im=Image.open(p).convert('RGBA');ref_imgs.append((p.name,im))
        except Exception:pass
    if not ref_imgs:
        report['classification']='Reference image missing';return

    # Conservative, explicit: a high score is only a candidate for visual review,
    # not proof that the named CCS is used by the game.
    def bits(im):
        im=im.resize((96,32),Image.Resampling.BILINEAR)
        bg=Image.new('RGBA',im.size,(255,255,255,255));bg.alpha_composite(im)
        return bg.convert('L').point(lambda x:255 if x>=128 else 0).tobytes()
    refbits=[(n,bits(im),im.width,im.height) for n,im in ref_imgs]
    candidates=[]
    for p in fs[:12000]:
        try:
            with Image.open(p) as im:
                w,h=im.size
                # Favor small names and thin HUD strips. Wide/large backgrounds won't match.
                if w>1024 or h>512 or w<32 or h<8 or w/h<1.2:continue
                test=bits(im.convert('RGBA'))
                bestname,bestscore=None,-1.0
                for name,rb,rw,rh in refbits:
                    aspect=(w/h)/(rw/rh)
                    if not (0.50<=aspect<=2.0):continue
                    score=1-sum(a!=b for a,b in zip(test,rb))/len(test)
                    if score>bestscore:bestname,bestscore=name,score
                if bestscore>=0:
                    candidates.append((bestscore,p,bestname,w,h))
        except Exception:continue
    candidates.sort(key=lambda q:q[0],reverse=True)
    fields=['score','texture','reference','width','height','stage']
    with (pack/'ranked_texture_candidates.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t');w.writeheader()
        by_stage={}
        for snap in stage_data:
            for filename in snap['names']:by_stage.setdefault(filename,snap['label'])
        for score,p,ref,wid,hei in candidates:
            n=str(p.relative_to(memstick))
            w.writerow({'score':round(score,4),'texture':n,'reference':ref,'width':wid,'height':hei,'stage':by_stage.get(n,'OTHER')})
    top=candidates[:60]
    if not top:return
    thumbs=[]
    for score,p,ref,_,_ in top:
        try:
            with Image.open(p) as im:
                rgba=im.convert('RGBA')
                bg=Image.new('RGBA',rgba.size,(250,250,250,255));bg.alpha_composite(rgba)
                thumb=ImageOps.contain(bg.convert('RGB'),(240,110))
                thumbs.append((p,thumb,score,ref))
        except Exception:pass
    font=ImageFont.load_default()
    for offset in range(0,len(thumbs),20):
        part=thumbs[offset:offset+20];ncol=4;nrow=(len(part)+3)//4
        sheet=Image.new('RGB',(ncol*270,nrow*158),'white');d=ImageDraw.Draw(sheet)
        for i,(p,im,score,ref) in enumerate(part):
            x=(i%4)*270;y=(i//4)*158
            sheet.paste(im,(x+10,y+8))
            d.text((x+5,y+119),f'sim={score:.3f} {p.stem[:25]}',font=font,fill='black')
            d.text((x+5,y+135),ref[:35],font=font,fill='black')
        sheet.save(pack/f'dump_contact_{offset//20+1:02d}.jpg',quality=85)
    selection=pack/'top_texture_png';selection.mkdir(exist_ok=True)
    total=0
    for score,p,ref,wid,hei in candidates[:32]:
        sz=p.stat().st_size
        if total+sz>12*1024*1024:break
        dst=selection/(f'{len(list(selection.glob("*.png"))):02d}_{p.stem}.png')
        shutil.copy2(p,dst);total+=sz
    report['classification']=f'Ranked {len(candidates)} candidate textures against {len(ref_imgs)} original/current references; ranking not source proof'


def create_zip(pack,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():target.unlink()
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in pack.rglob('*'):
            if p.is_file(): z.write(p,p.relative_to(pack))
    return target


def prompt_when_ready(proc,msg):
    if proc.poll() is not None:return False
    print(msg,flush=True)
    try:input('화면이 표시되면 이 창에서 Enter를 누르세요 (건너뛰려면 바로 Enter): ')
    except EOFError:return False
    return True


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--iso',default=str(SOURCE_ISO))
    ap.add_argument('--exe',default=str(EXE))
    ap.add_argument('--state',default='',help='Optional existing savestate .ppst; never auto-select')
    ap.add_argument('--root',default=str(ROOT))
    args=ap.parse_args()
    root=Path(args.root);iso=Path(args.iso);exe=Path(args.exe)
    logs=root/'logs'
    print('=== SUB52Q: isolated real-texture provenance capture ===',flush=True)
    print('NO ISO modification. Existing PPSSPP processes are untouched.',flush=True)
    if not iso.is_file() or not exe.is_file():raise RuntimeError('Expected ISO/PPSSPP executable missing')
    expected=SOURCE_SHA if iso==SOURCE_ISO else None
    actual=sha256_file(iso)
    if expected and actual!=expected:raise RuntimeError('Source SUB52N SHA256 unexpected: '+actual)
    state=Path(args.state) if args.state else None
    if state and not state.is_file():raise RuntimeError('Savestate not found: '+str(state))
    when=datetime.now().strftime('%Y%m%d_%H%M%S')
    work=Path(tempfile.gettempdir())/('naruto_sub52q_'+when)
    work.mkdir(parents=True,exist_ok=False)
    pack=work/'pack';pack.mkdir()
    report={'stage':'SUB52Q_LIVE_TEXTURE_PROVENANCE','iso':str(iso),'sha256':actual,
            'ppsspp_exe':str(exe),'started_at':datetime.now().isoformat(),
            'iso_modified':False,'other_ppsspp_controlled':False,'selected_state':str(state) if state else None}
    proc=None
    exit_code=1
    try:
        memstick,original_cfg,overlay=build_isolated_settings(work,exe)
        report['original_cfg_copied_from']=str(original_cfg) if original_cfg else None
        port=select_port();report['unique_debugger_port']=port
        cmd=[str(exe),'--windowed',f'--memstick={memstick}',f'--debugger={port}',f'--appendconfig={overlay}',str(iso)]
        if state:cmd += [f'--state={state}']
        print('Launching separate PPSSPP instance; port',port,flush=True)
        proc=subprocess.Popen(cmd,cwd=str(exe.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        report['launched_pid']=proc.pid
        try:check_ws_instance(port,proc.pid,iso,report)
        except Exception as e:
            report['instance_verification_error']=str(e)
            print('WARNING: '+str(e),flush=True)
        print('PPSSPP PID',proc.pid, '— 다른 PPSSPP 인스턴스는 제어하지 않습니다.',flush=True)
        snaps=[dict(label='START',**snapshot(memstick))]
        if prompt_when_ready(proc,'1/2 전투 HUD에서 일본어 이름이 보이면 Enter (게임 조작은 직접 수행)'):
            snaps.append(dict(label='HUD',**snapshot(memstick)))
        if prompt_when_ready(proc,'2/2 승리 화면의 勝者 문구가 보이면 Enter'):
            snaps.append(dict(label='VICTORY',**snapshot(memstick)))
        print('이 진단에서 새로 띄운 PPSSPP 창만 닫아 주세요. (다른 인스턴스는 그대로 두세요.)',flush=True)
        while proc.poll() is None:
            total=snapshot(memstick)['bytes']
            if total>MAX_SAMPLE_BYTES:
                print(f'WARNING: dump now {total//(1024*1024)} MiB. 이 진단용 PPSSPP 창을 닫아 주세요.',flush=True)
            time.sleep(2)
        snaps.append(dict(label='EXIT',**snapshot(memstick)))
        report['ppsspp_exit_code']=proc.returncode
        report['snapshots']=[{k:v for k,v in s.items() if k!='names'} for s in snaps]
        (pack/'texture_dump_inventory.tsv').parent.mkdir(parents=True,exist_ok=True)
        with (pack/'texture_dump_inventory.tsv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['path','size','sha256'],delimiter='\t');w.writeheader()
            w.writerows(inventory(texture_files(memstick),memstick))
        ref=Path(__file__).parent/'reference'
        for rp in ref.glob('*.png'):
            d=pack/'reference';d.mkdir(exist_ok=True)
            shutil.copy2(rp,d/rp.name)
        collect_comparison(memstick,snaps,pack,ref,report)
        (pack/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        exit_code=0
    except Exception:
        report['error']=traceback.format_exc()
        (pack/'FAILURE.txt').write_text(report['error'],encoding='utf-8')
        (pack/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(report['error'],flush=True)
    finally:
        (pack/'README.txt').write_text(
            'SUB52Q runtime texture provenance report. Similarity ranks are candidates, not proof of resource use. '
            'Original/current ISO unchanged. Screenshots of HUD and 勝者 are needed to correlate textures.\n',encoding='utf-8')
        tar=logs/((NAME if exit_code==0 else 'fail_'+NAME)+'_upload.zip')
        print('UPLOAD_ZIP='+str(create_zip(pack,tar)),flush=True)
        if proc is None or proc.poll() is not None:
            try:shutil.rmtree(work)
            except OSError:pass
        else:
            print('Capture instance still running. Temporary dump left at '+str(work),flush=True)
    if exit_code:sys.exit(exit_code)


if __name__=='__main__':
    main()
