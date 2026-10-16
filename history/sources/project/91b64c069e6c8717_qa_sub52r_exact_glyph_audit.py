#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Naruto SUB52R: read-only comparison of captured small textures and name glyphs.
No ISO changes, no PPSSPP launch, no original dump deletion.
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, hashlib, json, os, shutil, subprocess, sys, traceback, zipfile
from pathlib import Path

GAME='ULKS46086'
STAGE='naruto_sub52r_exact_glyph_audit'
FOLDER=Path(r'LOCAL_PATH')
MAX_FILES=30000
MAX_IMAGE_PIXELS=4_000_000
MAX_COPY_BYTES=5_000_000

def ensure_pillow():
    try:
        from PIL import Image,ImageOps,ImageDraw,ImageChops
        return Image,ImageOps,ImageDraw,ImageChops
    except ImportError:
        r=subprocess.run([sys.executable,'-m','pip','install','--user','--disable-pip-version-check','Pillow'],capture_output=True,text=True)
        if r.returncode:
            raise RuntimeError('Pillow installation failed: '+r.stderr[-1000:])
        from PIL import Image,ImageOps,ImageDraw,ImageChops
        return Image,ImageOps,ImageDraw,ImageChops

def csv_out(p,fields,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore'); w.writeheader();w.writerows(rows)

def package(out,zip_path):
    if zip_path.exists():zip_path.unlink()
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file(): z.write(p,p.relative_to(out))

def transform_list(image):
    from PIL import Image
    return [('none',image),('flip_vertical',image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)),
            ('flip_horizontal',image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)),
            ('rotate180',image.transpose(Image.Transpose.ROTATE_180))]

def compare_exact(image,refs):
    """For equal-size RGBA images, report MAE, RGB equivalence and alpha delta."""
    rs=[]
    from PIL import ImageChops
    for label,ref in refs.items():
        if image.size!=ref.size:continue
        for operation,im in transform_list(image):
            dif=ImageChops.difference(im,ref).convert('RGBA')
            ext=dif.getextrema()
            n=ref.width*ref.height*4
            h=dif.histogram()
            mean=sum(v*h[channel*256+v] for channel in range(4) for v in range(256))/n
            max_rgb=max(ext[c][1] for c in range(3))
            max_alpha=ext[3][1]
            rs.append({'reference':label,'transform':operation,'mean_abs_error':round(mean,8),
                       'max_rgb_delta':max_rgb,'max_alpha_delta':max_alpha})
    return rs

def contact_pages(items, output, label, Image,ImageDraw,ImageOps, kind, tiles_per_page=288):
    if not items:return []
    cols=18;rows=16;tile_w=90;tile_h=78
    pages=[]
    for page,start in enumerate(range(0,len(items),tiles_per_page),1):
        part=items[start:start+tiles_per_page]
        sheet=Image.new('RGB',(cols*tile_w,rows*tile_h+35),(250,250,250)); d=ImageDraw.Draw(sheet)
        d.text((8,6),f'{label} - page {page} ({start+1}..{start+len(part)} of {len(items)})',fill=(0,0,0))
        for j,(path,w,h) in enumerate(part):
            x=(j%cols)*tile_w;y=(j//cols)*tile_h+35
            try:
                with Image.open(path) as im:
                    rgba=im.convert('RGBA')
                    if rgba.width*rgba.height>MAX_IMAGE_PIXELS:continue
                    checker=Image.new('RGBA',rgba.size,(222,222,222,255));checker.alpha_composite(rgba)
                    thumb=ImageOps.contain(checker.convert('RGB'),(tile_w-10,tile_h-20))
                sheet.paste(thumb,(x+(tile_w-thumb.width)//2,y+2))
            except Exception:continue
            n=path.stem
            d.text((x+2,y+tile_h-16),n[:11],fill=(30,30,30))
        dest=output/f'{kind}_page_{page:02d}.jpg';sheet.save(dest,quality=83,optimize=True);pages.append(dest.name)
    return pages

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=r'PROJECT_ROOT')
    ap.add_argument('--texture-dir',default=str(FOLDER))
    args=ap.parse_args()
    root=Path(args.root);logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    out=root/'analysis'/'sub'/'sub52r_exact_glyph_audit'/dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=True)
    result='success'
    summary={'stage':STAGE,'read_only':True,'iso_modified':False,'ppsspp_launched':False,
             'original_textures_deleted':False,'texture_dir':args.texture_dir}
    try:
        Image,ImageOps,ImageDraw,ImageChops=ensure_pillow()
        texroot=Path(args.texture_dir)
        if not texroot.is_dir(): raise RuntimeError('Existing Naruto dump directory missing: '+str(texroot))
        files=sorted(p for p in texroot.rglob('*.png') if p.is_file())
        if len(files)>MAX_FILES:raise RuntimeError(f'Too many PNGs ({len(files)} > {MAX_FILES})')
        print(f'[1/5] Found {len(files)} PNGs under {texroot}',flush=True)
        refs={}
        for p in (Path(__file__).parent/'reference').glob('*.png'):
            with Image.open(p) as im: refs[p.name]=im.convert('RGBA').copy()
        if len(refs)<4:raise RuntimeError('Four reference PNGs required')
        rows=[];matches=[];categorized={'small':[],'other':[]};mtime_days=collections.Counter()
        for i,p in enumerate(files,1):
            try:
                with Image.open(p) as im:
                    w,h=im.size
                    if w*h>MAX_IMAGE_PIXELS:continue
                    rgba=im.convert('RGBA')
                st=p.stat()
                utc=dt.datetime.fromtimestamp(st.st_mtime,dt.timezone.utc)
                mtime_days[utc.strftime('%Y-%m-%d')]+=1
                row={'filename':p.name,'width':w,'height':h,'bytes':st.st_size,'mtime_utc':utc.isoformat(),
                     'relative_path':str(p.relative_to(texroot))}
                rows.append(row)
                if (w,h) in ((16,32),(32,32)):categorized['small'].append((p,w,h))
                else: categorized['other'].append((p,w,h))
                for m in compare_exact(rgba,refs):
                    matches.append(dict(**row,**m))
            except Exception as exc:
                print('[warn]',p,exc,flush=True)
            if i%500==0:print(f'[scan] {i}/{len(files)}',flush=True)
        print('[2/5] Exact names / transforms',flush=True)
        matches.sort(key=lambda r:(r['reference'],r['mean_abs_error']))
        csv_out(out/'exact_name_matches.tsv',
                ['reference','filename','transform','mean_abs_error','max_rgb_delta','max_alpha_delta','width','height','mtime_utc','relative_path'],matches)
        csv_out(out/'dump_inventory_with_dates.tsv',
                ['filename','width','height','bytes','mtime_utc','relative_path'],rows)
        best=[]
        for ref in refs:
            rr=[r for r in matches if r['reference']==ref]
            best.extend(rr[:8])
        csv_out(out/'best_name_matches.tsv',
                ['reference','filename','transform','mean_abs_error','max_rgb_delta','max_alpha_delta','width','height','mtime_utc','relative_path'],best)
        print('[3/5] Building full small-texture visual catalog',flush=True)
        # All small textures included as thumbnails in address/filename order.
        # They may be font glyphs, so do not discard based on flawed pixel-similarity scores.
        glyph_pages=contact_pages(categorized['small'],out,'16x32 and 32x32 all images',Image,ImageDraw,ImageOps,'small')
        other_pages=contact_pages(categorized['other'],out,'All other dimensions',Image,ImageDraw,ImageOps,'other')
        print('[4/5] Copying compact useful standalone images',flush=True)
        copied=0;selected=[];dest=out/'matching_png';dest.mkdir(exist_ok=True)
        for row in best:
            p=texroot/row['relative_path']
            if not p.exists() or p.stat().st_size>2_000_000 or copied+p.stat().st_size>MAX_COPY_BYTES:continue
            name=p.name
            if (dest/name).exists():continue
            shutil.copyfile(p,dest/name);copied+=p.stat().st_size;selected.append(name)
        # Extract short text-like sized textures for manual source review
        extra=out/'small_name_sizes';extra.mkdir(exist_ok=True)
        for p,w,h in categorized['other']:
            if (w,h) not in ((128,32),(128,64),(64,32),(256,64)):continue
            if p.stat().st_size>2_000_000 or copied+p.stat().st_size>MAX_COPY_BYTES:continue
            if not (extra/p.name).exists():shutil.copyfile(p,extra/p.name);copied+=p.stat().st_size
        summary.update(total_png=len(files),enumerated_png=len(rows),small_texture_png=len(categorized['small']),
                       other_texture_png=len(categorized['other']),
                       reference_names=list(refs),
                       closest_per_reference=[dict(reference=x['reference'],filename=x['filename'],
                                                  transform=x['transform'],mean_abs_error=x['mean_abs_error'],
                                                  max_rgb_delta=x['max_rgb_delta'],max_alpha_delta=x['max_alpha_delta']) for x in best[:32]],
                       mtime_days=dict(sorted(mtime_days.items())),
                       full_small_contact_pages=glyph_pages,full_other_contact_pages=other_pages,
                       copied_name_match_png=selected)
        (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'RESULT.txt').write_text('SUB52R: read-only historical dump inspection.\n'
         'An exact flipped Korean name dump confirms this image existed in PPSSPP textures at some time.\n'
         'It does NOT prove the current Japanese HUD uses that image.\n'
         'Small 16x32/32x32 textures are catalogued for glyph review, not labeled as proven fonts.\n',encoding='utf-8-sig')
        print('[5/5] Packaging',flush=True)
    except Exception:
        result='fail';summary['error']=traceback.format_exc()
        (out/'FAILURE.txt').write_text(summary['error'],encoding='utf-8')
        print(summary['error'],flush=True)
    finally:
        (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        z=logs/(('' if result=='success' else 'fail_')+STAGE+'_upload.zip')
        package(out,z)
        print('UPLOAD_ZIP='+str(z),flush=True)
    return 0 if result=='success' else 1

if __name__=='__main__':sys.exit(main())
