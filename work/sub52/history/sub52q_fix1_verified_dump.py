#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52Q FIX1: texture-dump preflight and source audit, no ISO mutations.

No PPSSPP input injection, no process termination, no modification of existing
memstick.  The newly spawned PPSSPP is the only process observed.
"""
from __future__ import annotations
import argparse, configparser, csv, hashlib, json, os, shutil, socket, subprocess
import sys, tempfile, time, traceback, zipfile
from pathlib import Path
from datetime import datetime

ROOT=Path(r'D:\narutimate portable')
ISO=ROOT/r'analysis\sub\sub52n_reward_safe_fix1\Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso'
ISO_SHA='00bd998359e64e5d3f2af28c4f0d5b0dac7db8b11a35b773ea8a4ee290d58663'
EXE=Path(r'C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe')
GAME='ULKS46086'
NAME='naruto_sub52q_fix1_verified_dump'
MAX_DUMP_BYTES=300*1024*1024


def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def select_port():
    for port in range(39410,39530):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            try:s.bind(('127.0.0.1',port));return port
            except OSError:pass
    raise RuntimeError('No unused debugger port in the dedicated range')


def possible_ini(exe):
    return [
        exe.parent/'memstick'/'PSP'/'SYSTEM'/'ppsspp.ini',
        exe.parent/'PSP'/'SYSTEM'/'ppsspp.ini',
        Path.home()/'Documents'/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
        Path(os.environ.get('APPDATA',''))/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
    ]


def prepare_memstick(work,exe,report):
    mem=work/'memstick'
    sy=mem/'PSP'/'SYSTEM'; sy.mkdir(parents=True,exist_ok=True)
    original=next((p for p in possible_ini(exe) if p.is_file()),None)
    report['original_settings_read_only']=str(original) if original else None
    cfg=configparser.ConfigParser(strict=False,interpolation=None)
    cfg.optionxform=str
    if original:
        try:cfg.read(original,encoding='utf-8-sig')
        except Exception as e: report['settings_copy_warning']=repr(e)
        controls=original.parent/'controls.ini'
        if controls.is_file():shutil.copy2(controls,sy/'controls.ini')
    if not cfg.has_section('Graphics'):cfg.add_section('Graphics')
    # SaveNewTextures is a per-game setting in PPSSPP.  The in-app setting is
    # therefore verified independently in the preflight, not assumed enabled.
    for k,v in {'SaveNewTextures':'True','ReplaceTextures':'False','TexScalingLevel':'1'}.items():
        cfg.set('Graphics',k,v)
    with (sy/'ppsspp.ini').open('w',encoding='utf-8') as f:cfg.write(f)
    overlay=work/'dump_overrides.ini'
    overlay.write_text('[Graphics]\nSaveNewTextures = True\nReplaceTextures = False\nTexScalingLevel = 1\n',encoding='utf-8')
    # PPSSPP texture pack metadata. Leave hashes empty; nothing is replaced.
    # Current user's screenshot filenames identify the game as ULKS46086.
    texdir=mem/'PSP'/'TEXTURES'/GAME
    texdir.mkdir(parents=True,exist_ok=True)
    (texdir/'textures.ini').write_text(
        '[options]\nversion = 1\nhash = quick\nignoreMipmap = true\n\n'
        '[hashes]\n\n[hashranges]\n',encoding='utf-8')
    if original:
        copy_game_saves(original.parent.parent,mem/'PSP',report)
    return mem,overlay


def copy_game_saves(srcpsp,dstpsp,report):
    copied=[];total=0;budget=100*1024*1024
    for folder in ('PPSSPP_STATE','SAVEDATA'):
        parent=srcpsp/folder
        if not parent.is_dir():continue
        for p in parent.iterdir():
            if not p.name.upper().startswith(GAME):continue
            if p.is_file():
                files=[p]
            elif p.is_dir():
                files=[x for x in p.rglob('*') if x.is_file()]
            else:continue
            size=sum(x.stat().st_size for x in files)
            if size>budget-total:continue
            for x in files:
                rel=x.relative_to(parent)
                dest=dstpsp/folder/rel
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(x,dest)
            copied.append({'path':str(p),'bytes':size});total+=size
    report['isolated_copied_saves']=copied
    report['isolated_copied_saves_bytes']=total


def texture_files(mem):
    base=mem/'PSP'/'TEXTURES'
    if not base.is_dir():return []
    files=[]
    for p in base.rglob('*.png'):
        if p.is_file() and any(c.lower()=='new' for c in p.parts):
            files.append(p)
    return sorted(files)


def snapshot(mem):
    fs=texture_files(mem)
    return {'files':len(fs),'bytes':sum(p.stat().st_size for p in fs),
            'names':[str(p.relative_to(mem)) for p in fs]}


def inventory(items,mem):
    return [{'path':str(p.relative_to(mem)),'size':p.stat().st_size,
             'sha256':sha256_file(p)} for p in items]


def config_diagnostics(mem,pack,report):
    result=[]
    for p in (mem/'PSP'/'SYSTEM').rglob('*.ini'):
        # Collect diagnostic config names and exact pertinent keys, no unrelated
        # user settings, credentials, or full ini dumps.
        try:
            lines=p.read_text(encoding='utf-8-sig',errors='replace').splitlines()
            flags=[s.strip() for s in lines if s.strip().lower().startswith(
                ('savenewtextures','replacetextures','texscalinglevel'))]
            result.append({'ini':str(p.relative_to(mem)),'dump_flags':flags})
        except OSError:pass
    report['effective_ini_candidates']=result
    (pack/'effective_settings.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    paths=[]
    for base in [mem/'PSP'/'TEXTURES',*[(p.parent.parent/'TEXTURES') for p in possible_ini(EXE) if p.exists()]]:
        if not base.exists():continue
        count=0
        try:
            for p in base.rglob('*.png'):
                count+=1
                if count>=20000:break
        except OSError:pass
        paths.append({'path':str(base),'png_count':count,
                      'isolated':str(base).lower().startswith(str(mem).lower())})
    report['texture_paths_diagnostic']=paths


def sample_screenshots(mem,pack):
    src=mem/'PSP'/'SCREENSHOT'
    if not src.exists():return []
    ims=[p for p in src.rglob('*') if p.is_file() and p.suffix.lower() in ('.jpg','.png')
         and p.name.upper().startswith(GAME)]
    result=[]
    dst=pack/'isolated_screenshots'
    for p in sorted(ims,key=lambda p:p.stat().st_mtime)[-4:]:
        if p.stat().st_size>6*1024*1024:continue
        dst.mkdir(exist_ok=True)
        shutil.copy2(p,dst/p.name)
        result.append(p.name)
    return result

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





def create_zip(pack,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():destination.unlink()
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in pack.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(pack))
    return destination


def wait_for_user(proc,message):
    if proc.poll() is not None:
        print('PPSSPP 프로세스가 이미 종료됐어.',flush=True);return False
    print('\n'+message,flush=True)
    try:input('준비되면 이 PowerShell 창에서 Enter를 눌러줘: ')
    except EOFError:return False
    return proc.poll() is None


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=str(ROOT))
    ap.add_argument('--iso',default=str(ISO))
    ap.add_argument('--exe',default=str(EXE))
    args=ap.parse_args()
    root=Path(args.root);iso=Path(args.iso);exe=Path(args.exe)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    print('=== SUB52Q FIX1 verified texture dump ===',flush=True)
    print('ISO는 변경하지 않고, 다른 PPSSPP 인스턴스도 제어하지 않아.',flush=True)
    if not iso.is_file():raise RuntimeError('Source ISO missing: '+str(iso))
    if not exe.is_file():raise RuntimeError('PPSSPP EXE missing: '+str(exe))
    realsha=sha256_file(iso)
    if iso==ISO and realsha!=ISO_SHA:raise RuntimeError('Source ISO SHA256 mismatch: '+realsha)
    ts=datetime.now().strftime('%Y%m%d_%H%M%S')
    work=Path(tempfile.gettempdir())/('naruto_sub52q_fix1_'+ts)
    work.mkdir(parents=True,exist_ok=False)
    pack=work/'pack';pack.mkdir()
    report={'stage':'SUB52Q_FIX1_VERIFIED_DUMP','source_iso':str(iso),
            'source_sha256':realsha,'source_unchanged':True,
            'other_ppsspp_controlled':False,'timestamp':datetime.now().isoformat()}
    proc=None;status='fail'
    mem=work/'memstick'
    try:
        mem,overlay=prepare_memstick(work,exe,report)
        port=select_port()
        cmd=[str(exe),'--windowed',f'--memstick={mem}',f'--debugger={port}',
             f'--appendconfig={overlay}',str(iso)]
        report['launched_command_args']=['--windowed','--memstick=<isolated>',
                                         '--debugger=<unique>', '--appendconfig=<isolated>',str(iso)]
        report['debugger_port']=port
        proc=subprocess.Popen(cmd,cwd=str(exe.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        report['launched_pid']=proc.pid
        print('독립 PPSSPP 실행 PID:',proc.pid,'포트:',port,flush=True)
        print('임시 MemoryStick:',mem,flush=True)
        snaps=[]
        if not wait_for_user(proc,'[1/3] 타이틀/메뉴가 뜨면 Enter. 지금은 전투로 진입하지 마.'):
            raise RuntimeError('PPSSPP exited before preflight')
        time.sleep(1)
        pre=snapshot(mem)
        snaps.append(dict(label='PREFLIGHT',**pre))
        report['initial_dump_files']=pre['files']
        for attempt in range(2):
            if pre['files']>0:break
            print('\n[검증 실패] 새 텍스처 PNG가 0개야. 지금 상태로 전투를 진행하지 마.',flush=True)
            print('PPSSPP 안에서 설정 > 도구 > 개발자 도구 > 텍스처 교체(교체/추출)로 이동해.',flush=True)
            print('`Save new textures` / `새 텍스처 저장`을 켜고 게임을 다시 시작(Reset)해.',flush=True)
            print('가능하면 `Create/Open textures.ini` 메뉴에서 게임용 ini도 확인해.',flush=True)
            if not wait_for_user(proc,'다시 타이틀 또는 메뉴가 표시되면 확인할게.'):
                raise RuntimeError('PPSSPP exited during texture dump preflight retry')
            time.sleep(1)
            pre=snapshot(mem)
            snaps.append(dict(label='PREFLIGHT_RETRY_'+str(attempt+1),**pre))
        if pre['files']==0:
            report['classification']='NO_TEXTURE_DUMP_AFTER_GUIDED_PREFLIGHT'
            raise RuntimeError('No PNGs after guided preflight. In-app texture dump setting or memstick path remains unverified.')
        print(f'[성공] 텍스처 덤프 활성화 확인: {pre["files"]}개, {pre["bytes"]//1024}KiB',flush=True)
        print('이제 전투 화면으로 진행해도 돼.',flush=True)
        if not wait_for_user(proc,'[2/3] 전투 HUD에서 シカマル/ヒナタ 같은 일본어 이름이 보일 때 Enter.'):
            raise RuntimeError('PPSSPP exited before HUD capture')
        time.sleep(.8)
        hud=snapshot(mem)
        snaps.append(dict(label='HUD',**hud))
        report['hud_new_textures']=hud['files']-pre['files']
        print(f'HUD 시점 덤프 총 {hud["files"]}개; 추가 {report["hud_new_textures"]}개',flush=True)
        if not wait_for_user(proc,'[3/3] 승리 화면 `勝者`가 보일 때 Enter. 스크린샷 키 1도 눌러주면 좋아.'):
            raise RuntimeError('PPSSPP exited before victory capture')
        time.sleep(.8)
        vic=snapshot(mem)
        snaps.append(dict(label='VICTORY',**vic))
        report['victory_new_textures']=vic['files']-hud['files']
        print(f'승리 시점 덤프 총 {vic["files"]}개; 추가 {report["victory_new_textures"]}개',flush=True)
        print('이번에 열린 PPSSPP 창만 닫아줘. 다른 PPSSPP는 그대로 두면 돼.',flush=True)
        while proc.poll() is None:
            total=snapshot(mem)['bytes']
            if total>MAX_DUMP_BYTES:
                print('주의: 임시 덤프가 300MiB를 넘었어. 이번 PPSSPP 창을 닫아줘.',flush=True)
            time.sleep(2)
        report['isolated_ppsspp_exit_code']=proc.returncode
        snaps.append(dict(label='EXIT',**snapshot(mem)))
        report['snapshots']=[{k:v for k,v in row.items() if k!='names'} for row in snaps]
        with (pack/'texture_dump_inventory.tsv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['path','size','sha256'],delimiter='\t')
            w.writeheader();w.writerows(inventory(texture_files(mem),mem))
        ref=Path(__file__).parent/'reference'
        for p in ref.glob('*.png'):
            d=pack/'reference';d.mkdir(exist_ok=True)
            shutil.copy2(p,d/p.name)
        collect_comparison(mem,snaps,pack,ref,report)
        report['collected_screenshots']=sample_screenshots(mem,pack)
        report['classification']='DUMP_COLLECTED_CANDIDATES_REQUIRE_VISUAL_QA'
        status='success'
    except Exception:
        report['error']=traceback.format_exc()
        if 'classification' not in report:report['classification']='CAPTURE_FAILED'
        print(report['error'],flush=True)
        (pack/'FAILURE.txt').write_text(report['error'],encoding='utf-8')
    finally:
        try:config_diagnostics(mem,pack,report)
        except Exception as e:report['settings_diag_error']=repr(e)
        (pack/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (pack/'README.txt').write_text(
            'PPSSPP texture dump provenance. Texture similarities are hypotheses, not runtime address proof. '
            'No existing PPSSPP process or source ISO was modified.\n',encoding='utf-8')
        dest=logs/(('' if status=='success' else 'fail_')+NAME+'_upload.zip')
        print('UPLOAD_ZIP='+str(create_zip(pack,dest)),flush=True)
        if proc is None or proc.poll() is not None:
            try:shutil.rmtree(work)
            except OSError:pass
        else:
            print('격리 PPSSPP가 실행 중이라 임시 폴더는 유지: '+str(work),flush=True)
    if status!='success':sys.exit(1)

if __name__=='__main__':main()
