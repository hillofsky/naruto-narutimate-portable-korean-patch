#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,shutil,struct,sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont

SECTOR=2048
SOURCE_SHA="d3db7466c1bd0df72e093e81f02fcc200a22e23ffc25ab7ce84307e9230d6c07"
SOURCE_REL=Path("analysis/sub/sub46_ui_cleanup_discovery/Naruto_KR_MOV06E_SUB46_UICleanup.iso")
BASE_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
BASE_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub47_network_option_home")
FINAL_NAME="Naruto_KR_MOV06E_SUB47_Network_Option_Home.iso"

BOOT_RULES=[
 # Naru-P Road first tutorial/help page and nearby static UI.
 ("narup_intro_1","　木ノ葉隠れの里をナルトで散歩しよう！！","　나루토를 이동시키자!!"),
 ("narup_intro_2","　現在持っているナルＰポイントの分だけ","　나루P 포인트만큼 이동합니다."),
 ("narup_intro_3","　ナルトが前に進んでいくぞ！","　나루토가 이동합니다!"),
 ("narup_intro_4","　道に落ちているアイテムを手に入れながら","　아이템을 얻으며 이동합니다."),
 ("narup_intro_5","　ゴールを目指そう！！","　앞으로 이동하자!!"),
 ("narup_intro_6","　手に入れたアイテムは<RED>“ナルトの自宅”<BLACK>で",
                  "　얻은 아이템은<RED>“나루토의 집”<BLACK>에서"),
 ("narup_intro_7","　見る事ができるぞ！","　확인할 수 있습니다!"),
 ("narup_step","　ナルＰポイントが１００Ｐたまるごとに<br>　ナルトが１０ｍずつ進んでいきます。",
               "　나루P 포인트 100P마다<br>　나루토가 10m 이동합니다."),
 ("narup_points_label","　ナルＰポイント","　나루P 포인트"),
 ("narup_position","　ナルトの現在地","　나루토 위치"),
 ("narup_destination","　目的地","　다음 위치"),
 ("narup_no_points","　ナルＰポイントが足りません。<br>　ゲームモード選択に戻ります。",
                    "　나루P 포인트가 부족합니다.<br>　모드 선택으로 돌아갑니다."),
 ("narup_remaining","　ゴールまで残り","　남은 거리"),
 ("narup_scroll_select","　巻物を１つ選択してください。","　두루마리 1개를 선택하세요."),
 ("narup_points_label2","ナルＰポイント","나루P 포인트"),
 ("narup_points_gain","ナルＰポイントを<BLUE>%dＰ<BLACK>入手しました。",
                      "나루P 포인트 <BLUE>%dP<BLACK> 획득!"),
 ("narup_all_items","あなたは全ての閲覧アイテムを入手しました.","모든 감상 아이템을 얻었습니다."),
 ("narup_finish","これで<RED>“ナルＰロード”<BLACK>は終了です。<br>お疲れ様でした。",
                 "이것으로<RED>“나루P 로드”<BLACK> 종료!<br>수고했습니다."),
 ("narup_finish_return","<RED>“ナルＰロード”<BLACK>は終了しました。<br>ゲームモード選択に戻ります。",
                        "<RED>“나루P 로드”<BLACK>를 종료합니다.<br>모드 선택으로 돌아갑니다."),
 ("narup_reward1","よく来たな。<br>拙者からお前に褒美をやろう！","잘 왔다.<br>내가 보상을 주마!"),
 ("narup_reward2","最後まで頑張れよ！<br>ではさらばだ！","끝까지 힘내라!<br>그럼 잘 가라!"),
 ("narup_reward3","またあったな。<br>拙者からお前に褒美をやろう！","또 만났군.<br>내가 보상을 주마!"),
 ("narup_reward4","これからも頑張れよ！<br>ではさらばだ！","앞으로도 힘내라!<br>그럼 잘 가라!"),
 ("narup_gain_image","「<BLUE>%s<BLACK>」の画像を入手しました。","「<BLUE>%s<BLACK>」 이미지 획득!"),
 ("narup_gain_music","「<BLUE>%s<BLACK>」の音楽を入手しました。","「<BLUE>%s<BLACK>」 음악 획득!"),
 ("narup_gain_movie","「<BLUE>%s<BLACK>」の映像を入手しました。","「<BLUE>%s<BLACK>」 영상 획득!"),
 ("narup_gain_photo","「<BLUE>%s<BLACK>」の写真を入手しました。","「<BLUE>%s<BLACK>」 사진 획득!"),

 # Naruto's Home main menu.
 ("home_image","画像を見る","이미지"),
 ("home_music","音楽を聴く","음악"),
 ("home_movie","映像を見る","영상"),
 ("home_photo","写真を見る","사진"),
 ("home_image_desc","画像を見る事ができます。","이미지를 봅니다."),
 ("home_music_desc","音楽を聴く事ができます。","음악을 듣습니다."),
 ("home_movie_desc","映像を見る事ができます。","영상을 봅니다."),
 ("home_photo_desc","写真を見る事ができます。","사진을 봅니다."),
 ("home_image_select","見たい画像を選択してください。","이미지를 선택하세요."),
 ("home_music_select","聴きたい音楽を選択してください。","음악을 선택하세요."),
 ("home_playing","再生中…","재생중"),
 ("home_movie_select","見たい映像を選択してください。","영상을 선택하세요."),
 ("home_photo_select","見たい写真を選択してください。","사진을 선택하세요."),

 # SUB46 could not fit this line; use a shorter equivalent.
 ("net_return_lobby","対戦を終了して待機所に戻ります。","대전 종료 후 대기실로 갑니다."),
]

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:raise RuntimeError(f"Cannot import {path}")
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("Bad ISO")
    r=p[156:190];return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
    with Path(iso).open("rb") as f:f.seek(lba*SECTOR);data=f.read(size)
    out=[];pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:pos=((pos//SECTOR)+1)*SECTOR;continue
        r=data[pos:pos+ln]
        if len(r)<34:break
        nb=r[33:33+r[32]]
        name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
        out.append(dict(name=name,lba=int.from_bytes(r[2:6],"little"),size=int.from_bytes(r[10:14],"little"),is_dir=bool(r[25]&2)))
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso);cur=dict(lba=lba,size=size,is_dir=True)
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"]) if e["name"].casefold()==part.casefold()),None)
        if not hit:raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath);Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b:raise RuntimeError("EOF")
            fo.write(b);rem-=len(b)

def segsha(iso,ipath):
    e=findiso(iso,ipath);h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=f.read(min(rem,1024*1024));h.update(b);rem-=len(b)
    return e["size"],h.hexdigest()

def walk_pmfs(iso,path="PSP_GAME/USRDIR"):
    out=[]
    def walk(p):
        d=findiso(iso,p)
        for e in dirents(iso,d["lba"],d["size"]):
            if e["name"] in (".",".."):continue
            q=p+"/"+e["name"]
            if e["is_dir"]:walk(q)
            elif e["name"].lower().endswith(".pmf"):out.append(q)
    walk(path);return sorted(out)

def load_mapping(root):
    mp={}
    for p in (root/"analysis/shared/event_font_hangul_mapping.tsv",
              root/"analysis/sub/sub40_tutorial/new_glyph_mapping.tsv"):
        if not p.exists():raise RuntimeError("Font mapping missing: "+str(p))
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                if r.get("hangul") and r.get("donor_sjis_hex"):
                    mp[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
    return mp

def enc(s,mp):
    out=bytearray()
    for c in s:
        if c in mp:out+=mp[c]
        elif c==" ":out+=b"\xA0"
        else:out+=c.encode("cp932")
    return bytes(out)

def missing(s,mp):
    return sorted({c for c in s if "가"<=c<="힣" and c not in mp})

def patch_cstr(b,label,jp,kr,mp,rows):
    old=jp.encode("cp932");miss=missing(kr,mp)
    if miss:
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes="",status="SKIP_UNMAPPED",missing="".join(miss)))
        return 0
    new=enc(kr,mp)
    if len(new)>len(old):
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="SKIP_TOO_LONG",missing=""))
        return 0
    original=bytes(b);pos=0;count=0
    while True:
        i=original.find(old,pos)
        if i<0:break
        pos=i+1;after=i+len(old)
        if (i==0 or original[i-1]==0) and after<len(original) and original[after]==0:
            b[i:after]=new+bytes(len(old)-len(new));count+=1
            rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex=hex(i),old_bytes=len(old),new_bytes=len(new),status="PATCHED",missing=""))
    if count==0:
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="NOT_FOUND",missing=""))
    return count

# CCS texture helpers.
def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def find_palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=palid:continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b):continue
        raw=np.frombuffer(b[o+28:o+28+n*4],dtype=np.uint8).reshape(-1,4).copy()
        rgba=raw[:,[2,1,0,3]]
        rgba[:,3]=np.minimum(rgba[:,3].astype(np.int16)*2,255).astype(np.uint8)
        return o,rgba
    raise RuntimeError("Palette missing")

def find_texture(b,name):
    names=ccs_names(b);wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture missing "+name)

def decode_indices(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    return ix[::-1].copy()

def encode_indices(ix,typ):
    flat=ix[::-1].reshape(-1).astype(np.uint8)
    if typ==0x13:return flat.tobytes()
    return (flat[::2]|(flat[1::2]<<4)).astype(np.uint8).tobytes()

def patch_texture(b,name,png):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"]);oldix=decode_indices(b,t);oldrgba=pal[oldix]
    repl=np.asarray(Image.open(png).convert("RGBA"),dtype=np.uint8)
    if repl.shape[:2]!=(t["height"],t["width"]):raise RuntimeError("Texture size mismatch "+name)
    same=np.all(repl==oldrgba,axis=2);newix=oldix.copy();chg=~same
    if np.any(chg):
        pe=pal.astype(np.float32);pe[:,:3]*=pe[:,3:4]/255.0
        px=repl[chg].astype(np.float32);px[:,:3]*=px[:,3:4]/255.0
        chosen=np.empty(len(px),dtype=np.uint8)
        for s in range(0,len(px),4096):
            q=px[s:s+4096];dist=((q[:,None,:]-pe[None,:,:])**2).sum(axis=2)
            chosen[s:s+len(q)]=dist.argmin(axis=1)
        newix[chg]=chosen
    packed=encode_indices(newix,t["type"]);a=t["offset"]+36;b[a:a+len(packed)]=packed
    return dict(texture=name,width=t["width"],height=t["height"],changed_pixels=int(chg.sum()))

def decode_texture_png(b,name,path):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"]);ix=decode_indices(b,t)
    Image.fromarray(pal[ix],"RGBA").save(path)

def font_path():
    for p in (Path(r"C:\Windows\Fonts\malgunbd.ttf"),Path(r"C:\Windows\Fonts\malgun.ttf")):
        if p.exists():return p
    raise RuntimeError("Malgun Gothic font not found")

def centered(draw,rect,text,font,fill,stroke=0):
    x0,y0,x1,y1=rect
    box=draw.textbbox((0,0),text,font=font,stroke_width=stroke)
    w=box[2]-box[0];h=box[3]-box[1]
    draw.text(((x0+x1-w)/2-box[0],(y0+y1-h)/2-box[1]),text,font=font,fill=fill,
              stroke_width=stroke,stroke_fill=(0,0,0,255))

def make_network(src,dst):
    im=Image.open(src).convert("RGBA");d=ImageDraw.Draw(im)
    # Exact Japanese-text area in TEX_network; digits and frame art remain untouched.
    d.rectangle((0,96,191,181),fill=(0,0,0,0))
    fp=font_path()
    f15=ImageFont.truetype(str(fp),15);f14=ImageFont.truetype(str(fp),14)
    white=(255,255,255,255);blue=(24,68,255,255)
    centered(d,(0,96,132,116),"대기실 입장",f15,white,1)
    centered(d,(140,96,192,116),"종료",f15,white,1)
    centered(d,(0,119,132,139),"대기실 입장",f15,blue,1)
    centered(d,(140,119,192,139),"종료",f15,blue,1)
    centered(d,(0,143,82,160),"대전 상대",f14,white,1)
    centered(d,(0,163,76,181),"접속 인원",f14,white,1)
    centered(d,(77,163,181,181),"내 이름",f14,white,1)
    im.save(dst)

def make_option(src,dst):
    im=Image.open(src).convert("RGBA");d=ImageDraw.Draw(im)
    # Clear only original JP glyph cells; preserve arrow/buttons/star/panels.
    for r in [(0,0,110,31),(110,0,221,31),(222,0,290,31),(290,0,344,31),
              (0,32,110,63),(110,32,221,63),(0,64,110,95),(110,64,221,95),
              (0,96,440,129)]:
        d.rectangle(r,fill=(0,0,0,0))
    fp=font_path();f18=ImageFont.truetype(str(fp),18);f17=ImageFont.truetype(str(fp),17)
    black=(0,0,0,255);blue=(24,68,255,255)
    centered(d,(0,0,110,31),"난이도 설정",f18,black)
    centered(d,(110,0,221,31),"난이도 설정",f18,blue)
    centered(d,(222,0,290,31),"종료",f18,black)
    centered(d,(290,0,344,31),"종료",f18,blue)
    centered(d,(0,32,110,63),"조작 설정",f18,black)
    centered(d,(110,32,221,63),"조작 설정",f18,blue)
    centered(d,(0,64,110,95),"음량 설정",f18,black)
    centered(d,(110,64,221,95),"음량 설정",f18,blue)
    vals=[((0,96,110,129),"쉬움"),((110,96,220,129),"보통"),
          ((220,96,330,129),"어려움"),((330,96,440,129),"매우 어려움")]
    for r,s in vals:centered(d,r,s,f17,blue)
    im.save(dst)

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=r"D:\narutimate portable");ap.add_argument("--assets",required=True)
    a=ap.parse_args();root=Path(a.root);assets=Path(a.assets);source=root/SOURCE_REL;base=root/BASE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB46 authority ISO missing/SHA mismatch")
    if not base.exists() or sha256_file(base)!=BASE_SHA:raise RuntimeError("SUB36 compact baseline missing/SHA mismatch")
    m=mod("sub47_p14",root/"analysis/stage14/naruto_patcher.py")
    iso=mod("sub47_p15",root/"analysis/stage15/stage15_iso_patcher.py")
    mp=load_mapping(root)

    print("[1/10] Extract exact SUB46 DAT/IDX/BOOT",flush=True)
    srcdat=out/"source_sub46_naruto.dat";srcidx=out/"source_sub46_naruto.idx";srcboot=out/"source_sub46_BOOT.bin"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat);extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx);extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    shutil.copyfile(srcdat,dat);shutil.copyfile(srcidx,idx)

    print("[2/10] Patch Naru-P Road + Naruto Home static strings",flush=True)
    bb=bytearray(srcboot.read_bytes());text_rows=[]
    for r in BOOT_RULES:patch_cstr(bb,*r,mp,text_rows)
    boot.write_bytes(bb)
    print("  patched:",sum(r["status"]=="PATCHED" for r in text_rows),
          " skipped unmapped:",sum(r["status"]=="SKIP_UNMAPPED" for r in text_rows),
          " skipped too long:",sum(r["status"]=="SKIP_TOO_LONG" for r in text_rows),flush=True)

    print("[3/10] Generate clean Korean network/option atlases",flush=True)
    netpng=out/"TEX_network_ko.png";optpng=out/"TEX_option01_clean_ko.png"
    make_network(assets/"network_source.png",netpng)
    make_option(assets/"option_original_upright.png",optpng)

    print("[4/10] Patch network.ccs + option.ccs",flush=True)
    src_ei=m.parse_pidx(m.read_embedded_index(srcdat),"sub46-src")
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub47-embedded");xi=m.parse_pidx(xb,"sub47-external")
    replacements={};texrows=[]
    plans={"network.ccs":[("TEX_network",netpng)],"option.ccs":[("TEX_option01",optpng)]}
    with dat.open("rb") as f:
        for name,pls in plans.items():
            r=next(q for q in ei["primary"] if q["name"]==name)
            f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"]);old=m.decode_stored(st,r["size"],r["zsize"])
            b=bytearray(old)
            for t,png in pls:
                row=patch_texture(b,t,png);row["resource"]=name;texrows.append(row)
            new=bytes(b)
            if len(new)!=len(old):raise RuntimeError("CCS decoded size changed "+name)
            replacements[name]=dict(original_sha256=m.sha256(old),new_decoded=new)

    print("[5/10] Append changed CCS resources + update PIDX",flush=True)
    with dat.open("ab") as f:
        for name,rr in replacements.items():
            encoded=m.encode_3_0(rr["new_decoded"])
            if m.decode_3x(encoded)!=rr["new_decoded"]:raise RuntimeError("Encode check failed "+name)
            off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["primary"] if q["name"]==name)
                struct.pack_into("<III",blob,q["record_off"]+12,off,len(rr["new_decoded"]),len(encoded))

    print("[6/10] Patch FSTS preload duplicates",flush=True)
    bundles=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]);bundle=f.read(r["file_size"]);rebuilt,changes=m.rebuild_fsts(bundle,r["name"],replacements)
            if not changes:continue
            f.seek(0,2);off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,off,len(rebuilt))
            members=";".join(str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x) if isinstance(x,dict) else str(x) for x in changes)
            bundles.append(dict(bundle=r["name"],members=members))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)

    print("[7/10] Extract pending gauge/rpggauge atlases for next stage",flush=True)
    disc=out/"discovery_textures";disc.mkdir(exist_ok=True);discrows=[]
    vei=m.parse_pidx(m.read_embedded_index(dat),"disc")
    wanted={
      "gauge.ccs":["TEX_red","TEX_white","TEX_xtext","TEX_xmenu","TEX_xselect","TEX_xselect2","TEX_xselect5"],
      "rpggauge.ccs":["TEX_rpgmenu01","TEX_rpgmenu02","TEX_rpgmenu03","TEX_rpgmenu04","TEX_konoha"],
    }
    with dat.open("rb") as f:
        for res,ts in wanted.items():
            r=next((q for q in vei["primary"] if q["name"]==res),None)
            if not r:continue
            f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"]);dec=m.decode_stored(st,r["size"],r["zsize"])
            for t in ts:
                try:
                    fn=f"{res.replace('.','_')}__{t}.png";decode_texture_png(dec,t,disc/fn)
                    tex=find_texture(dec,t);discrows.append(dict(resource=res,texture=t,width=tex["width"],height=tex["height"],png=fn,status="EXTRACTED"))
                except Exception as e:
                    discrows.append(dict(resource=res,texture=t,width="",height="",png="",status="ERROR:"+str(e)))

    print("[8/10] Build compact SUB47 ISO",flush=True)
    if final.exists():final.unlink()
    shutil.copyfile(base,final)
    with final.open("r+b") as f:
        vds=iso.read_volume_descriptors(f)
        for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot)):
            recs=[iso.find_path(f,vd,ip.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext=iso.append_file_sector_aligned(f,host,host.name)
            for q in recs:
                if q:iso.patch_directory_record(f,q["record_offset"],ext["lba"],ext["size"])
        f.seek(0,2);iso.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print("[9/10] Static regression verification",flush=True)
    core=[]
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                    ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot)):
        sz,hs=segsha(final,ip);ok=hs==sha256_file(host);core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verify fail "+ip)

    fin_ei=m.parse_pidx(m.read_embedded_index(dat),"final");target=set(replacements)
    preserved_primary=0;preserved_fsts=0
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(src_ei["primary"],fin_ei["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in target:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed "+sr["name"])
            preserved_primary+=1
        srcf={r["index"]:r for r in src_ei["offset2_rows"]};finf={r["index"]:r for r in fin_ei["offset2_rows"]}
        for k,sr in srcf.items():
            fr=finf[k];sf.seek(sr["file_off"]);sb=sf.read(sr["file_size"]);ff.seek(fr["file_off"]);fb=ff.read(fr["file_size"])
            if sb==fb:continue
            sa=m.parse_fsts(sb,"s");fa=m.parse_fsts(fb,"f")
            for sx,fx in zip(sa["members"],fa["members"]):
                if sx["name"]!=fx["name"]:raise RuntimeError("FSTS order changed")
                if sx["basename"] not in target:
                    if sx["stored"]!=fx["stored"]:raise RuntimeError(f"Untargeted FSTS changed {sr['name']} / {sx['name']}")
                    preserved_fsts+=1

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub47_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)

    write_tsv(out/"sub47_text_patch.tsv",text_rows,["label","japanese","korean","offset_hex","old_bytes","new_bytes","status","missing"])
    write_tsv(out/"sub47_texture_patch.tsv",texrows,["resource","texture","width","height","changed_pixels"])
    write_tsv(out/"sub47_fsts_changes.tsv",bundles,["bundle","members"])
    write_tsv(out/"sub47_discovery_inventory.tsv",discrows,["resource","texture","width","height","png","status"])
    write_tsv(out/"sub47_core_verification.tsv",core,["iso_path","size","sha256","match"])
    write_tsv(out/"sub47_movie_preservation.tsv",movies,["iso_path","source_sha256","sub47_sha256","match"])

    report=dict(
      stage="SUB47_NETWORK_OPTION_HOME",
      source_iso_sha256=SOURCE_SHA,final_iso=str(final),final_iso_size=final.stat().st_size,final_iso_sha256=sha256_file(final),
      text_patched=sum(r["status"]=="PATCHED" for r in text_rows),
      text_skipped_unmapped=sum(r["status"]=="SKIP_UNMAPPED" for r in text_rows),
      text_skipped_too_long=sum(r["status"]=="SKIP_TOO_LONG" for r in text_rows),
      changed_resources=sorted(target),fsts_bundles_changed=[r["bundle"] for r in bundles],
      texture_patches=texrows,preserved_non_target_primary_resources=preserved_primary,
      preserved_non_target_fsts_members=preserved_fsts,pmf_movies_preserved=len(movies),
      font_mapping_preserved="694+17",new_glyphs_added=0,compact_rebuild=True,static_qa="PASS",runtime_qa="REQUIRED"
    )
    (out/"SUB47_static_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
      "Naruto PSP SUB47 - Network / Option / Home\n\n"
      f"SourceSHA256={SOURCE_SHA}\nFinalISO={final}\nFinalSHA256={report['final_iso_sha256']}\nFinalSize={report['final_iso_size']}\n"
      f"TextPatched={report['text_patched']}\nTextSkippedUnmapped={report['text_skipped_unmapped']}\nTextSkippedTooLong={report['text_skipped_too_long']}\n"
      f"ChangedResources={','.join(sorted(target))}\nFSTSChangedBundles={len(bundles)}\nPreservedPrimaryResources={preserved_primary}\n"
      f"PMFsPreserved={len(movies)}\nFontMappingPreserved=694+17\nNewGlyphsAdded=0\nCompactRebuild=YES\nStaticQA=PASS\nRuntimeQA=REQUIRED\n",
      encoding="utf-8-sig"
    )
    print("[10/10] Done",flush=True);print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
