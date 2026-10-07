#!/usr/bin/env python3
# -*- coding: ascii -*-
from __future__ import annotations
import argparse,csv,hashlib,json,re,sys
from pathlib import Path
PACKET_SHA="07b921d30d1c2f88842771fd4bebd50a87e88bd58683741ddce632c0f8babcb6"
FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
EXPECTED_CHANGED=100
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
def rt(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f,delimiter="\t"))
def wt(p,rows,fields):
 with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader()
  for r in rows:w.writerow(r)
def ctl(s):return re.findall(r"<[^>]+>",s or "")
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--out",required=True);a=ap.parse_args()
 root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 src=root/"analysis"/"sub"/"sub31_full_semantic_review"/"sub31_review_0401_0600.tsv"
 font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
 rp=Path(__file__).with_name("sub32_3_revisions_0401_0600.json")
 if not src.exists() or sha(src)!=PACKET_SHA:raise RuntimeError("source packet missing/SHA mismatch")
 if not font.exists() or sha(font)!=FONT_SHA:raise RuntimeError("font mapping missing/SHA mismatch")
 rows=rt(src);blob=json.loads(rp.read_text(encoding="ascii"));rev={int(k):v for k,v in blob["revisions"].items()};notes={int(k):v for k,v in blob.get("notes",{}).items()}
 if len(rows)!=200 or set(rev)!=set(range(401,601)):raise RuntimeError("row/revision range mismatch")
 fc={r["hangul"] for r in rt(font) if r.get("hangul") and len(r["hangul"])==1}
 outrows=[];changed=[];bad=[];missing=set();jpleft=[]
 for r in rows:
  i=int(r["review_index"]);n=rev[i];o=r["current_sub29_korean"]
  if ctl(n)!=ctl(r["japanese"]):bad.append(i)
  missing|={c for c in n if 0xAC00<=ord(c)<=0xD7A3 and c not in fc}
  if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]",n):jpleft.append(i)
  q=dict(r);q["review_status"]="REVIEWED_JP_PRIMARY_EN_SECONDARY_OCR_REFERENCE_ONLY";q["revised_korean"]=n
  q["review_note"]=notes.get(i,"JP/EN semantic review; wording revised." if n!=o else "JP/EN semantic review; existing wording retained.");outrows.append(q)
  if n!=o:changed.append({"review_index":i,"game_key":r["game_key"],"speaker_code":r["speaker_code"],"japanese":r["japanese"],"english":r["english"],"ocr_korean_reference":r["ocr_korean_reference"],"before":o,"after":n,"review_note":q["review_note"]})
 if bad:raise RuntimeError(f"control mismatches: {bad}")
 if missing:raise RuntimeError("new Hangul glyphs: "+"".join(sorted(missing)))
 if jpleft:raise RuntimeError(f"Japanese letters remain: {jpleft}")
 if len(changed)!=EXPECTED_CHANGED:raise RuntimeError(f"changed={len(changed)} expected={EXPECTED_CHANGED}")
 wt(out/"sub32_3_review_0401_0600_completed.tsv",outrows,list(rows[0].keys()))
 wt(out/"sub32_3_changed_rows.tsv",changed,["review_index","game_key","speaker_code","japanese","english","ocr_korean_reference","before","after","review_note"])
 rep={"stage":"SUB32_3","rows_reviewed":200,"changed_rows":len(changed),"retained_rows":200-len(changed),"control_exact_rows":200,"control_mismatches":0,"new_hangul_required":0,"ocr_authoritative":False,"japanese_primary":True,"english_secondary":True,"game_files_modified":False}
 (out/"sub32_3_report.json").write_text(json.dumps(rep,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 s=["Naruto PSP SUB32-3 - Semantic Review 0401-0600","",f"RowsReviewed=200",f"ChangedRows={len(changed)}",f"RetainedRows={200-len(changed)}","ControlExactRows=200","ControlMismatches=0","NewHangulRequired=0","OCRAuthoritative=NO","JapanesePrimary=YES","EnglishSecondary=YES","","No game files were modified."]
 (out/"SUMMARY.txt").write_text("\n".join(s)+"\n",encoding="utf-8-sig");print("\n".join(s))
if __name__=="__main__":
 try:main()
 except Exception:
  import traceback;traceback.print_exc();sys.exit(1)
