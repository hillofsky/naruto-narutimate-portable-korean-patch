from pathlib import Path
import csv, re, json, zipfile, traceback

ROOT=Path(r"D:\narutimate portable")
OUT=ROOT/r"analysis\sub\sub52d1_translation_validation"
LOGS=ROOT/"logs"
SRC=ROOT/r"analysis\sub\sub52c_static_patch_sources\target_tables"
TSV=ROOT/"sub52d1_residual_text_translated.tsv"

TABLE_FILES={
    "bunshin.tbl":"0323__bunshin.tbl.bin",
    "mugen.tbl":"0374__mugen.tbl.bin",
    "nazonazo.tbl":"0375__nazonazo.tbl.bin",
    "quiz1.tbl":"0376__quiz1.tbl.bin",
    "quiz2.tbl":"0377__quiz2.tbl.bin",
}
ACTIVE={"TRANSLATED_CHATGPT","TRANSLATED_EXISTING"}
TOKEN_RE=re.compile(r"<[^>]+>|%[-+0-9.#]*[sdif]")

def read_tsv(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def line_at(data,off):
    end=len(data)
    for sep in (b"\r\n",b"\n",b"\r"):
        x=data.find(sep,off)
        if x>=0:end=min(end,x)
    return data[off:end]

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    if not TSV.exists(): raise RuntimeError("Translation TSV missing: "+str(TSV))
    rows=read_tsv(TSV)

    table_data={}
    for entry,fn in TABLE_FILES.items():
        p=SRC/fn
        if not p.exists(): raise RuntimeError("Source table missing: "+str(p))
        table_data[entry]=p.read_bytes()

    report=[]
    errors=[]
    active_count=0
    unique_sources=set()
    unique_korean=set()
    hangul=set()

    for i,r in enumerate(rows,1):
        st=r["status"]
        if st not in ACTIVE:
            continue
        active_count+=1
        entry=r["entry"]
        off=int(r["offset"])
        raw=r["raw_record"]
        src=r["source_japanese"]
        ko=r["korean"]
        unique_sources.add(src); unique_korean.add(ko)
        hangul.update(ch for ch in ko if "\uac00"<=ch<="\ud7a3")

        data=table_data.get(entry)
        if data is None:
            errors.append(f"row {i}: unknown table {entry}")
            continue

        expected=raw.encode("cp932")
        actual=line_at(data,off)
        exact=(actual==expected)
        tok_src=TOKEN_RE.findall(src)
        tok_ko=TOKEN_RE.findall(ko)
        tokens_ok=(tok_src==tok_ko)
        jp_left=bool(re.search(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]",ko))

        status="PASS"
        reason=[]
        if not exact:
            status="FAIL"; reason.append("source_offset_mismatch")
        if not ko:
            status="FAIL"; reason.append("blank_korean")
        if not tokens_ok:
            status="FAIL"; reason.append("control_token_mismatch")
        if jp_left:
            status="FAIL"; reason.append("japanese_remains")

        report.append({
            "entry":entry,"offset":off,"source":src,"korean":ko,
            "source_exact":"1" if exact else "0",
            "tokens_ok":"1" if tokens_ok else "0",
            "japanese_remains":"1" if jp_left else "0",
            "status":status,"reason":";".join(reason)
        })
        if status=="FAIL":
            errors.append(f"{entry}@0x{off:X}: "+",".join(reason))

    import csv
    rp=OUT/"validation.tsv"
    with rp.open("w",encoding="utf-8-sig",newline="") as f:
        fields=["entry","offset","source","korean","source_exact","tokens_ok","japanese_remains","status","reason"]
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t")
        w.writeheader();w.writerows(report)

    summary={
        "stage":"SUB52D1_TRANSLATION_VALIDATION",
        "rows_total":len(rows),
        "active_rows":active_count,
        "active_unique_sources":len(unique_sources),
        "active_unique_korean":len(unique_korean),
        "required_hangul_unique":len(hangul),
        "pass_rows":sum(1 for r in report if r["status"]=="PASS"),
        "fail_rows":sum(1 for r in report if r["status"]=="FAIL"),
        "keep_custom_encoded":sum(1 for r in rows if r["status"]=="KEEP_CUSTOM_ENCODED"),
        "skip_comment":sum(1 for r in rows if r["status"]=="SKIP_COMMENT"),
    }
    (OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "\n".join(f"{k}={v}" for k,v in summary.items())+
        ("\n\nERRORS:\n"+"\n".join(errors[:100]) if errors else "\n\nVALIDATION=PASS\n"),
        encoding="utf-8-sig"
    )
    (OUT/"required_hangul.txt").write_text("".join(sorted(hangul)),encoding="utf-8")

    z=LOGS/"naruto_sub52d1_translation_validation_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file(): zz.write(p,p.name)
        zz.write(TSV,TSV.name)

    print("SUMMARY="+json.dumps(summary,ensure_ascii=False),flush=True)
    print("UPLOAD_ZIP="+str(z),flush=True)
    if errors:
        raise RuntimeError(f"Validation failed: {len(errors)} row(s)")

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        if not (OUT/"FAILURE.txt").exists():
            (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub52d1_translation_validation_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
            if TSV.exists(): zz.write(TSV,TSV.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
