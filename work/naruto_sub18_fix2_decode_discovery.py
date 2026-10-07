#!/usr/bin/env python3
# Naruto PSP SUB18 FIX1 - Discover decoded event-script source / patcher decode path
#
# Read-only diagnostic.
# The original SUB18 incorrectly treated Stage3 extracted *.tbl as line-oriented
# text. Those files are binary/compressed game resources.
#
# This stage:
# - recursively inventories every *.tbl under analysis/
# - classifies which ones are decoded textual event scripts
# - finds all [EVENT] / "MSG =" textual sources
# - inspects analysis/stage14/naruto_patcher.py without executing it
# - extracts function inventory and relevant source snippets
# - searches analysis scripts/logs for event000_original.tbl, decompress/compress,
#   replacement, TBL extraction and related clues
#
# No game data is modified.

from __future__ import annotations
import argparse, ast, csv, hashlib, json, os, re, shutil, sys
from pathlib import Path

TEXT_EXTS={".py",".ps1",".txt",".log",".md",".json",".tsv",".csv"}
MAX_TEXT=6*1024*1024

KEYWORDS=[
    "event000_original.tbl",
    "naruto_patcher.py",
    "decompress",
    "compress",
    "unpack",
    "pack",
    "extract",
    "replace",
    "replacement",
    ".tbl",
    "MSG =",
    "[EVENT]",
    "event000.tbl",
]

PATCHER_FUNCTION_TERMS=[
    "tbl","compress","decompress","pack","unpack","extract",
    "patch","replace","entry","idx","dat","event"
]

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def write_tsv(path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def safe_rel(root,p):
    try:return str(p.relative_to(root))
    except:return str(p)


def iter_files_safe(base:Path, exclude_roots=()):
    """
    Iterative Windows-safe tree walk.
    - does not follow symlinks/junction-like links
    - excludes current stage output so evidence copies cannot recursively rescan themselves
    """
    base=base.resolve()
    excludes=[]
    for x in exclude_roots:
        try:
            excludes.append(Path(x).resolve())
        except Exception:
            excludes.append(Path(x))

    def is_excluded(p:Path):
        try:
            rp=p.resolve()
        except Exception:
            rp=p
        for ex in excludes:
            try:
                rp.relative_to(ex)
                return True
            except Exception:
                pass
        return False

    for dirpath,dirnames,filenames in os.walk(str(base),topdown=True,followlinks=False):
        d=Path(dirpath)

        kept=[]
        for name in dirnames:
            child=d/name
            if is_excluded(child):
                continue
            try:
                if child.is_symlink():
                    continue
            except Exception:
                pass
            kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            p=d/name
            if is_excluded(p):
                continue
            yield p

def printable_ratio(data:bytes):
    if not data:return 0.0
    ok=sum(1 for b in data if b in (9,10,13) or 0x20<=b<=0x7E or b>=0x80)
    return ok/len(data)

def classify_tbl(path:Path,root:Path):
    data=path.read_bytes()
    event_count=data.count(b"[EVENT]")
    msg_count=data.count(b"MSG =")
    eq_count=data.count(b" =")
    nul=data.count(0)
    crlf=data.count(b"\r\n")
    lf=data.count(b"\n")
    head=data[:64]

    textual=(event_count>0 or msg_count>0) and nul==0
    try:
        text=data.decode("cp932","strict") if textual else ""
        strict="YES" if textual else ""
    except UnicodeDecodeError:
        text=data.decode("cp932","replace") if textual else ""
        strict="NO" if textual else ""

    return {
        "path":safe_rel(root,path),
        "bytes":len(data),
        "sha256":sha256_file(path),
        "event_marker_count":event_count,
        "msg_token_count":msg_count,
        "assignment_token_count":eq_count,
        "nul_bytes":nul,
        "crlf_count":crlf,
        "lf_count":lf,
        "printable_like_ratio":f"{printable_ratio(data):.6f}",
        "classified_text_event":"YES" if textual else "NO",
        "cp932_strict":strict,
        "head_hex":head.hex(" "),
        "head_text":text[:160].replace("\r","\\r").replace("\n","\\n") if text else "",
    }

def inspect_patcher(path:Path,out:Path,root:Path):
    src=path.read_text(encoding="utf-8-sig",errors="replace")
    lines=src.splitlines()
    rows=[]
    try:
        tree=ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                name=n.name
                low=name.lower()
                score=sum(1 for t in PATCHER_FUNCTION_TERMS if t in low)
                if score:
                    start=n.lineno
                    end=getattr(n,"end_lineno",start)
                    rows.append({
                        "function":name,
                        "line_start":start,
                        "line_end":end,
                        "keyword_score":score,
                        "signature":lines[start-1].strip() if start-1<len(lines) else "",
                    })
    except SyntaxError as e:
        rows.append({
            "function":"<AST_PARSE_FAILED>",
            "line_start":"",
            "line_end":"",
            "keyword_score":"",
            "signature":str(e),
        })

    rows.sort(key=lambda r:(-int(r["keyword_score"] or 0),int(r["line_start"] or 0)))
    write_tsv(
        out/"sub18_fix1_patcher_function_inventory.tsv",
        rows,
        ["function","line_start","line_end","keyword_score","signature"]
    )

    # Source snippets around relevant functions and important string occurrences.
    snippets=[]
    covered=set()
    for r in rows[:80]:
        if r["function"]=="<AST_PARSE_FAILED>":
            continue
        start=max(1,int(r["line_start"])-4)
        end=min(len(lines),int(r["line_end"])+4)
        key=(start,end)
        if key in covered:continue
        covered.add(key)
        snippet="\n".join(f"{i:5d}: {lines[i-1]}" for i in range(start,end+1))
        snippets.append({
            "kind":"FUNCTION",
            "name":r["function"],
            "line_start":start,
            "line_end":end,
            "snippet":snippet[:16000],
        })

    search_terms=[
        "event000_original.tbl","event000.tbl",
        "--replace","replacement","decompress","compress",
        "tbl","extract","test_patch"
    ]
    low=src.lower()
    for term in search_terms:
        pos=0
        occurrence=0
        while occurrence<12:
            pos=low.find(term.lower(),pos)
            if pos<0:break
            line_no=src.count("\n",0,pos)+1
            start=max(1,line_no-8)
            end=min(len(lines),line_no+12)
            key=(start,end)
            if key not in covered:
                covered.add(key)
                snippet="\n".join(f"{i:5d}: {lines[i-1]}" for i in range(start,end+1))
                snippets.append({
                    "kind":"TERM",
                    "name":term,
                    "line_start":start,
                    "line_end":end,
                    "snippet":snippet[:16000],
                })
            occurrence+=1
            pos+=len(term)

    write_tsv(
        out/"sub18_fix1_patcher_snippets.tsv",
        snippets,
        ["kind","name","line_start","line_end","snippet"]
    )

    # Copy patcher source as evidence.
    ev=out/"evidence"
    ev.mkdir(exist_ok=True)
    shutil.copy2(path,ev/"naruto_patcher.py")
    return rows,snippets

def search_analysis_text(root:Path,out:Path):
    analysis=root/"analysis"
    rows=[]
    ev=out/"evidence"/"related_text"
    ev.mkdir(parents=True,exist_ok=True)

    if not analysis.exists():
        return rows

    for p in iter_files_safe(analysis,exclude_roots=(out,)):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            if p.stat().st_size>MAX_TEXT:continue
            txt=p.read_text(encoding="utf-8-sig",errors="replace")
        except Exception:
            continue
        low=txt.lower()
        hits=[k for k in KEYWORDS if k.lower() in low]
        if not hits:continue

        contexts=[]
        for h in hits[:10]:
            pos=low.find(h.lower())
            if pos<0:continue
            line=txt.count("\n",0,pos)+1
            ls=txt.splitlines()
            s=max(0,line-6)
            e=min(len(ls),line+9)
            contexts.append(
                f"### {h} @ line {line}\n"+
                "\n".join(f"{i+1:5d}: {ls[i]}" for i in range(s,e))
            )
        rel=safe_rel(root,p)
        rows.append({
            "path":rel,
            "bytes":p.stat().st_size,
            "hits":"|".join(hits),
            "context":"\n---\n".join(contexts)[:16000],
        })

        # Copy only high-value scripts, not huge logs/TSVs.
        if p.suffix.lower() in {".py",".ps1"}:
            dst=ev/rel.replace(":","_")
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dst)

    write_tsv(
        out/"sub18_fix1_related_text_hits.tsv",
        rows,
        ["path","bytes","hits","context"]
    )
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    analysis=root/"analysis"
    patcher=root/"analysis"/"stage14"/"naruto_patcher.py"
    known_text=root/"analysis"/"stage14"/"test_patch"/"event000_original.tbl"

    if not analysis.exists():
        raise RuntimeError(f"analysis directory missing: {analysis}")
    if not patcher.exists():
        raise RuntimeError(f"stage14 patcher missing: {patcher}")

    tbls=sorted(
        (p for p in iter_files_safe(analysis,exclude_roots=(out,))
         if p.is_file() and p.suffix.lower()==".tbl"),
        key=lambda p:str(p).lower()
    )
    tbl_rows=[classify_tbl(p,root) for p in tbls]
    write_tsv(
        out/"sub18_fix1_all_tbl_inventory.tsv",
        tbl_rows,
        [
            "path","bytes","sha256","event_marker_count","msg_token_count",
            "assignment_token_count","nul_bytes","crlf_count","lf_count",
            "printable_like_ratio","classified_text_event","cp932_strict",
            "head_hex","head_text"
        ]
    )

    decoded=[r for r in tbl_rows if r["classified_text_event"]=="YES"]
    write_tsv(
        out/"sub18_fix1_decoded_tbl_candidates.tsv",
        decoded,
        [
            "path","bytes","sha256","event_marker_count","msg_token_count",
            "assignment_token_count","nul_bytes","crlf_count","lf_count",
            "printable_like_ratio","classified_text_event","cp932_strict",
            "head_hex","head_text"
        ]
    )

    # Copy decoded textual TBLs if small.
    decdir=out/"evidence"/"decoded_tbl"
    decdir.mkdir(parents=True,exist_ok=True)
    for r in decoded:
        p=root/r["path"]
        if p.exists() and p.stat().st_size<=2*1024*1024:
            dst=decdir/r["path"].replace(":","_")
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dst)

    funcs,snips=inspect_patcher(patcher,out,root)
    hits=search_analysis_text(root,out)

    known_info={}
    if known_text.exists():
        d=known_text.read_bytes()
        known_info={
            "path":str(known_text),
            "bytes":len(d),
            "sha256":sha256_file(known_text),
            "event_markers":d.count(b"[EVENT]"),
            "msg_tokens":d.count(b"MSG ="),
        }

    # Diagnose why original SUB18 was invalid.
    stage3=root/"analysis"/"stage3"/"extracted"/"kr"
    stage3_tbls=sorted(stage3.glob("*.tbl")) if stage3.exists() else []
    stage3_textual=0
    stage3_msg_tokens=0
    stage3_nuls=0
    for p in stage3_tbls:
        d=p.read_bytes()
        stage3_msg_tokens+=d.count(b"MSG =")
        stage3_nuls+=d.count(0)
        if b"[EVENT]" in d or b"MSG =" in d:
            if d.count(0)==0:
                stage3_textual+=1

    report={
        "stage":"SUB18_FIX1",
        "mode":"READ_ONLY_DECODE_PATH_DISCOVERY",
        "all_analysis_tbl_files":len(tbls),
        "decoded_text_tbl_candidates":len(decoded),
        "stage3_tbl_files":len(stage3_tbls),
        "stage3_textual_tbl_files":stage3_textual,
        "stage3_total_msg_token_hits":stage3_msg_tokens,
        "stage3_total_nul_bytes":stage3_nuls,
        "known_stage14_event000":known_info,
        "patcher_path":str(patcher),
        "patcher_sha256":sha256_file(patcher),
        "relevant_patcher_functions":len(funcs),
        "patcher_snippets":len(snips),
        "related_analysis_text_files":len(hits),
        "original_sub18_diagnosis":"Stage3 extracted TBLs are binary resources, not decoded line-oriented event scripts.",
        "self_output_excluded":True,
        "walk_followlinks":False,
        "game_files_modified":False,
    }
    (out/"sub18_fix1_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB18 FIX1 - Decoded Event Source Discovery",
        "",
        f"AllAnalysisTBLFiles={len(tbls)}",
        f"DecodedTextTBLCandidates={len(decoded)}",
        f"Stage3TBLFiles={len(stage3_tbls)}",
        f"Stage3TextualTBLFiles={stage3_textual}",
        f"Stage3RawMSGTokenHits={stage3_msg_tokens}",
        f"PatcherRelevantFunctions={len(funcs)}",
        f"PatcherSnippets={len(snips)}",
        f"RelatedAnalysisTextFiles={len(hits)}",
        "",
        "Diagnosis:",
        "  Original SUB18 scanned binary/compressed Stage3 TBL resources.",
        "  Its GameMSGLikeRows=1 result is invalid and must be discarded.",
        "",
        "Known decoded script:",
        f"  {known_info.get('path','NOT FOUND')}",
        f"  MSG tokens: {known_info.get('msg_tokens','')}",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
