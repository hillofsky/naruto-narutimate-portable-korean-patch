#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52Q FIX2: READ-ONLY audit of already existing PPSSPP texture dumps.

No PPSSPP launch, no ISO modification, no screenshots of private content,
no cleanup of original texture cache. Only selected game textures may be
copied into a small diagnostic ZIP for inspection.
"""
from __future__ import annotations
import argparse, collections, csv, hashlib, json, math, os, re, shutil, subprocess, sys, traceback, zipfile
from datetime import datetime
from pathlib import Path

GAME = 'ULKS46086'
TITLE = 'SUB52Q_FIX2_EXISTING_TEXTURE_DUMP_AUDIT'
OUTPUT_NAME = 'naruto_sub52q_fix2_existing_dumps_upload.zip'
FAIL_NAME = 'fail_naruto_sub52q_fix2_existing_dumps_upload.zip'
MAX_COPY_BYTES = 18*1024*1024
MAX_TEXTURE_BYTES = 12*1024*1024
MAX_TEXTURES = 25000
MAX_SCAN_BY_ROOT = 100000
TOP_PER_REFERENCE = 20
MAX_SELECTED = 64


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def write_tsv(dest,fields,rows):
    with Path(dest).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        w.writeheader();w.writerows(rows)


def ensure_pillow():
    try:
        from PIL import Image,ImageDraw,ImageOps,ImageFilter
        return Image,ImageDraw,ImageOps,ImageFilter
    except ImportError:
        print('[dependency] Installing Pillow (missing)...',flush=True)
        r=subprocess.run([sys.executable,'-m','pip','install','--user','--disable-pip-version-check','Pillow'],capture_output=True,text=True)
        if r.returncode:
            raise RuntimeError('Pillow install failed: '+r.stderr[-1500:])
        from PIL import Image,ImageDraw,ImageOps,ImageFilter
        return Image,ImageDraw,ImageOps,ImageFilter


def candidate_roots():
    pp=Path(r'C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp')
    roots=[pp/'memstick'/'PSP'/'TEXTURES',pp/'PSP'/'TEXTURES']
    user=Path.home();roots.extend([user/'Documents'/'PPSSPP'/'PSP'/'TEXTURES'])
    appdata=os.environ.get('APPDATA','')
    if appdata:roots.append(Path(appdata)/'PPSSPP'/'PSP'/'TEXTURES')
    dedup=[];seen=set()
    for p in roots:
        key=str(p).lower()
        if key not in seen:seen.add(key);dedup.append(p)
    return dedup


def scan_roots(roots,report):
    details=[];game=[];observed=set();limit_reached=False
    for root in roots:
        row={'root':str(root),'exists':root.is_dir(),'all_png':0,'game_png':0,
             'game_new_png':0,'top_level_counts':{},'error':''}
        if not root.is_dir():details.append(row);continue
        by_top=collections.Counter()
        try:
            counter=0
            for p in root.rglob('*'):
                if not p.is_file() or p.suffix.lower()!='.png':continue
                counter+=1
                if counter>MAX_SCAN_BY_ROOT:
                    limit_reached=True;break
                row['all_png']+=1
                rel=p.relative_to(root)
                by_top[rel.parts[0] if rel.parts else '<root>']+=1
                if not any(GAME.lower() in part.lower() for part in rel.parts):continue
                row['game_png']+=1
                if any(part.lower()=='new' for part in rel.parts):row['game_new_png']+=1
                key=str(p).lower()
                if key not in observed:
                    observed.add(key);game.append((root,p))
        except OSError as exc: row['error']=str(exc)
        row['top_level_counts']=dict(by_top.most_common(20))
        details.append(row)
        print('[inventory]',row['all_png'],'PNG in',root,'Naruto',row['game_png'],'(new:',row['game_new_png'],')',flush=True)
    report['texture_roots']=details
    report['total_png_across_roots']=sum(r['all_png'] for r in details)
    report['naruto_game_png']=len(game)
    report['root_scan_limit_reached']=limit_reached
    return game


def prepare_ref(template_dir, Image,ImageOps):
    refs=[]
    for p in template_dir.iterdir():
        if p.suffix.lower() not in ('.png','.jpg','.jpeg'):continue
        try:
            with Image.open(p) as im:
                rgba=im.convert('RGBA')
                if 'WINNER' in p.name:
                    # User-confirmed screen crop. Isolate the top "勝者" label.
                    rgba=rgba.crop((55,48,408,218))
                rgba=ImageOps.autocontrast(ImageOps.grayscale(rgba)) if p.suffix.lower()!='.png' else rgba
                refs.append({'name':p.name,'image':rgba,'width':rgba.width,'height':rgba.height})
        except Exception as exc:print('[warn] reference skipped:',p,exc,flush=True)
    return refs


def make_binary(im,Image,ImageOps,ImageFilter,inverted=False):
    rgba=im.convert('RGBA')
    if 'A' in rgba.getbands():
        # Transparent PNGs can store arbitrary color values in transparent areas.
        alpha=rgba.getchannel('A'); bbox=alpha.point(lambda x:255 if x>35 else 0).getbbox()
        if bbox and bbox[2]-bbox[0]>=8 and bbox[3]-bbox[1]>=5:
            rgba=rgba.crop(bbox)
        bg=Image.new('RGBA',rgba.size,(255,255,255,255))
        bg.alpha_composite(rgba)
        gray=ImageOps.grayscale(bg.convert('RGB'))
    else:gray=ImageOps.grayscale(rgba)
    gray=ImageOps.autocontrast(gray)
    gray=gray.resize((96,32),Image.Resampling.BICUBIC)
    if inverted:gray=ImageOps.invert(gray)
    return gray.point(lambda x:255 if x<128 else 0).tobytes()


def score_bytes(a,b):
    n=len(a)
    if n!=len(b) or n==0:return 0
    onA=sum(v>0 for v in a);onB=sum(v>0 for v in b)
    if min(onA,onB)<int(n*.012):return 0
    # Dice + density penalty; low scores are not evidence of a match.
    overlap=sum(x>0 and y>0 for x,y in zip(a,b))
    dice=2*overlap/(onA+onB)
    penalty=min(onA,onB)/max(onA,onB)
    return dice*math.sqrt(penalty)


def audit_candidates(game,pack,refs,Image,ImageDraw,ImageOps,ImageFilter,report):
    if not game:return
    ref_features=[]
    for ref in refs:
        ref_features.append((ref,make_binary(ref['image'],Image,ImageOps,ImageFilter)))
    inventory=[];rank=[];skip=collections.Counter();dims=collections.Counter()
    for k,(root,p) in enumerate(game[:MAX_TEXTURES],1):
        try:
            size=p.stat().st_size
            if size>MAX_TEXTURE_BYTES:
                skip['too_large']+=1;continue
            with Image.open(p) as im:
                w,h=im.size
                dims[f'{w}x{h}']+=1
                if w>4096 or h>4096 or w*h>2000000:
                    skip['large_dimensions']+=1;continue
                rgba=im.convert('RGBA')
            relative=str(p.relative_to(root))
            is_new=any(n.lower()=='new' for n in p.relative_to(root).parts)
            item={'path':str(p),'rel':relative,'root':str(root),'bytes':size,'width':w,'height':h,'in_new_folder':is_new}
            inventory.append(item)
            if 16<=w<=1024 and 8<=h<=1024:
                direct=make_binary(rgba,Image,ImageOps,ImageFilter)
                flipped=make_binary(rgba,Image,ImageOps,ImageFilter,inverted=True)
                for ref,refbin in ref_features:
                    # Allow source texture to have padding; reject extreme aspect differences.
                    aspect=(w/h)/(ref['width']/ref['height'])
                    if aspect<.18 or aspect>5.5:continue
                    sc=max(score_bytes(direct,refbin),score_bytes(flipped,refbin))
                    if sc>=.25:
                        rank.append(dict(score=round(sc,5),reference=ref['name'],texture_relative=relative,
                          original_path=str(p),root=str(root),width=w,height=h,bytes=size,
                          in_new_folder=is_new))
        except Exception as exc:
            skip[type(exc).__name__]+=1
        if k%500==0:print('[scan] processed',k,'/',len(game),flush=True)
    rank.sort(key=lambda r:r['score'],reverse=True)
    # Choose top matches for EACH reference, then unique candidate textures.
    select=[];selected_paths=set()
    for ref in refs:
        for r in [x for x in rank if x['reference']==ref['name']][:TOP_PER_REFERENCE]:
            if r['original_path'] not in selected_paths:
                select.append(r);selected_paths.add(r['original_path'])
    select.sort(key=lambda r:r['score'],reverse=True)
    select=select[:MAX_SELECTED]
    write_tsv(pack/'candidate_rankings.tsv',
              ['score','reference','texture_relative','width','height','bytes','in_new_folder','original_path'],rank[:500])
    write_tsv(pack/'game_dump_inventory.tsv',
              ['rel','root','bytes','width','height','in_new_folder'],inventory)
    report['game_png_processed']=len(inventory)
    report['game_dump_dimensions_top']=dims.most_common(20)
    report['skipped']=dict(skip)
    report['number_ranked_pairs']=len(rank)
    report['number_selected_candidates']=len(select)
    dest=pack/'selected_texture_png';dest.mkdir(exist_ok=True)
    copied=0;contact=[];used_names=set()
    for i,r in enumerate(select):
        p=Path(r['original_path']);sz=p.stat().st_size
        if sz>4*1024*1024 or copied+sz>MAX_COPY_BYTES:continue
        h=sha(p)[:12];base=f'{i:03d}__{r["score"]:.3f}__{h}.png'
        if base in used_names:continue
        used_names.add(base)
        shutil.copyfile(p,dest/base);copied+=sz
        with Image.open(p) as im:
            rgba=im.convert('RGBA');background=Image.new('RGBA',rgba.size,(232,232,232,255));background.alpha_composite(rgba)
            thumb=ImageOps.contain(background.convert('RGB'),(285,125))
            contact.append((r,thumb,base))
    report['copied_png_count']=len(contact)
    report['copied_png_bytes']=copied
    for n in range(0,len(contact),20):
        part=contact[n:n+20];cols=4;rows=(len(part)+cols-1)//cols
        sheet=Image.new('RGB',(cols*310,rows*185),(255,255,255));d=ImageDraw.Draw(sheet)
        for j,(r,im,base) in enumerate(part):
            x=(j%4)*310;y=(j//4)*185
            sheet.paste(im,(x+(310-im.width)//2,y+4))
            d.text((x+5,y+135),f"{r['score']:.3f} {r['reference'][:29]}",fill=(0,0,0))
            d.text((x+5,y+152),Path(r['texture_relative']).name[:42],fill=(0,0,0))
            d.text((x+5,y+169),base[:30],fill=(0,0,0))
        sheet.save(pack/f'candidate_contact_{n//20+1:02d}.jpg',quality=85)


def zip_dir(pack,dst):
    if dst.exists():dst.unlink()
    with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(pack.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(pack))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=r'D:\narutimate portable')
    ap.add_argument('--texture-root',default=None,
        help='For controlled testing only: one PSP/TEXTURES root. Does not modify files.')
    args=ap.parse_args()
    root=Path(args.root);logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    report={'stage':TITLE,'timestamp':datetime.now().isoformat(),'game_id':GAME,'read_only':True,
       'iso_modified':False,'ppsspp_launched':False,'ppsspp_process_controlled':False,
       'original_png_deleted':False,'notes':'Similarity scores produce candidates, NOT runtime source proof.'}
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    output=root/'analysis'/'sub'/'sub52q_fix2_existing_dump_scan'/stamp
    output.mkdir(parents=True,exist_ok=True)
    status='success'
    try:
        print('=== SUB52Q FIX2 read-only historical texture scan ===',flush=True)
        print('No PPSSPP launch / No ISO writing / No deletion',flush=True)
        roots=[Path(args.texture_root)] if args.texture_root else candidate_roots()
        game=scan_roots(roots,report)
        report['classification']='PENDING'
        if len(game)==0:
            report['classification']='NO_ULKS46086_PNG_IN_EXISTING_TEXTURE_FOLDERS'
            print('[result] Existing PNG files belong to other IDs or are not under ULKS46086.',flush=True)
        else:
            Image,ImageDraw,ImageOps,ImageFilter=ensure_pillow()
            refdir=Path(__file__).parent/'reference'
            refs=prepare_ref(refdir,Image,ImageOps)
            if not refs:raise RuntimeError('Reference images missing from package')
            report['reference_images']=[p['name'] for p in refs]
            print('[match] game PNG',len(game),'reference',len(refs),flush=True)
            audit_candidates(game,output,refs,Image,ImageDraw,ImageOps,ImageFilter,report)
            report['classification']='EXISTING_NARUTO_TEXTURE_CANDIDATES_EXTRACTED'
        (output/'RESULT.txt').write_text('\n'.join([
            'Naruto SUB52Q FIX2 — read-only texture history audit',
            'Existing PNGs are historical; no candidate proves current runtime loading.',
            'Game ID: '+GAME,
            'Classification: '+str(report['classification']),
            'Naruto game PNGs: '+str(report['naruto_game_png']),
            'Candidate ranking requires manual validation.'
        ])+'\n',encoding='utf-8-sig')
    except Exception:
        status='fail'
        report['classification']='SCAN_ERROR'
        report['error']=traceback.format_exc()
        print(report['error'],flush=True)
        (output/'FAILURE.txt').write_text(report['error'],encoding='utf-8')
    finally:
        (output/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        dest=logs/(OUTPUT_NAME if status=='success' else FAIL_NAME)
        zip_dir(output,dest)
        print('UPLOAD_ZIP='+str(dest),flush=True)
        print('CLASSIFICATION='+str(report['classification']),flush=True)
    if status!='success':sys.exit(1)


if __name__=='__main__':main()
