from __future__ import annotations
from pathlib import Path
import argparse, csv, hashlib, importlib.util, json, re, shutil, struct, sys
import sub44_base as h

SOURCE_SHA = "9c565369ac5cf6ccf5fb2898577503a5cac43ab0aec297482ba76698eeba3433"
SOURCE_REL = Path("analysis/sub/sub43_menu_images/Naruto_KR_MOV06E_SUB43_MenuImages.iso")
OUT_REL = Path("analysis/sub/sub44_ui_cleanup")
FINAL_NAME = "Naruto_KR_MOV06E_SUB44_UITextCleanup.iso"

# Fixed/known UI strings confirmed from the unchanged SUB40/SUB43 BOOT string area.
# Replacements are deliberately concise so they fit the original NUL-terminated slots.
FIXED_TEXT = [
    ("mode_desc_mugen",
     "<RED>無幻城<BLACK>では、ナルトが主役の物語を体験できます。",
     "<RED>무환성<BLACK>: 나루토의 이야기를 즐길 수 있습니다."),
    ("mode_desc_reverse",
     "<RED>裏・無幻城<BLACK>では、自来也が主役の物語を体験できます。",
     "<RED>이면 무환성<BLACK>: 지라이야의 이야기를 즐길 수 있습니다."),
    ("mode_desc_duel",
     "<RED>強敵との決闘<BLACK>では、キャラクターを自由に選んでＣＯＭと対戦できます。",
     "<RED>강적과의 결투<BLACK>: 캐릭터를 골라 COM과 대전합니다."),
    ("mode_desc_wireless",
     "<RED>通信対戦<BLACK>では、無線通信（アドホックモード）を使って友達と対戦できます。",
     "<RED>통신 대전<BLACK>: 무선 통신으로 친구와 대전합니다."),
    ("mode_desc_narup",
     "<RED>ナルＰロード<BLACK>では、ナルＰポイントを使って閲覧アイテムを入手できます。",
     "<RED>나루P 로드<BLACK>: 포인트로 감상 아이템을 얻습니다."),
    ("mode_desc_home",
     "<RED>ナルトの自宅<BLACK>では、入手したアイテムを閲覧できます。",
     "<RED>나루토의 집<BLACK>: 얻은 아이템을 감상합니다."),
    ("mode_desc_option",
     "<RED>設定の変更<BLACK>では、各種設定の変更ができます。",
     "<RED>설정 변경<BLACK>: 게임 설정을 변경합니다."),

    ("return_title_question", "タイトルへ戻りますか？", "타이틀로 돌아갈까요?"),
    ("return_mode_question", "ゲームモード選択に戻りますか？", "게임 모드 선택으로 돌아갈까요?"),
    ("save_question", "セーブしますか？", "저장할까요?"),
    ("data_save_question", "データをセーブしますか？", "데이터를 저장할까요?"),
    ("mode_exit_help", "このモードを終了します。", "이 모드를 종료합니다."),

    ("network_1p_setting", "<RED>１Ｐ<BLACK>が対戦の設定をしています。",
     "<RED>1P<BLACK>가 대전 설정 중입니다."),
    ("network_1p_map", "<RED>１Ｐ<BLACK>がマップを選択しています。",
     "<RED>1P<BLACK>가 장소를 선택 중입니다."),
    ("network_wait", "しばらくお待ちください。", "잠시 기다려 주세요."),
    ("select_fighter", "闘うキャラクターを選択してください。", "대전할 캐릭터를 선택하세요."),

    ("option_duel_help", "<RED>“強敵との決闘”<BLACK>でのＣＯＭの強さを設定できます。",
     "<RED>“강적과의 결투”<BLACK> COM 난이도를 설정합니다."),
    ("option_control_help", "ボタン操作の割り振りができます。", "버튼 조작을 설정합니다."),
    ("option_screen_help", "<ruby画面|がめん>の<ruby位置|いち>の<ruby調整|ちょうせい>ができます。",
     "화면 위치를 조정합니다."),
    ("option_volume_help", "音量の設定ができます。", "소리를 설정합니다."),
    ("option_guide_help", "<ruby案内忍|あんないにん>を<ruby指定|してい>することができます。",
     "안내 닌자를 지정합니다."),
    ("option_default_help", "<ruby難易度|なんいど>・<ruby案内忍|あんないにん>をデフォルトに<ruby戻|もど>します。",
     "난이도와 안내 닌자를 기본으로 되돌립니다."),
    ("option_cross_exit", "<iconCROSS><ruby終了|しゅうりょう>", "<iconCROSS>종료"),
    ("option_exit_help", "終了します。", "종료합니다."),
    ("option_default_done", "<ruby難易度|なんいど>・<ruby案内忍|あんないにん>をデフォルトに<ruby戻|もど>しました。",
     "난이도와 안내 닌자를 기본으로 되돌렸습니다."),

    # Runtime screen 06/07 cleanup. These are patched only when exact standalone
    # strings are found; broad substring data is not touched.
    ("waiting_room_enter", "待機所に入る", "대기실 입장"),
    ("waiting_room_label", "待機所", "대기실"),
    ("generic_end", "終了", "종료"),
    ("yes", "はい", "예"),
    ("no", "いいえ", "아니요"),
]

DYNAMIC_RULES = [
    ("waiting_room_desc", "待機所", "通信対戦", "대기실 상대와 통신 대전합니다."),
]


def load_mapping(root: Path):
    rows = []
    for p in (
        root / "analysis/shared/event_font_hangul_mapping.tsv",
        root / "analysis/sub/sub40_tutorial/new_glyph_mapping.tsv",
    ):
        if not p.exists():
            raise RuntimeError(f"Font mapping missing: {p}")
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            rows.extend(csv.DictReader(f, delimiter="\t"))
    mp = {}
    for r in rows:
        ch = r.get("hangul", "")
        hx = r.get("donor_sjis_hex", "")
        if ch and hx:
            mp[ch] = bytes.fromhex(hx)
    return mp


def enc_ko(s: str, mp: dict[str, bytes]) -> bytes:
    out = bytearray()
    for c in s:
        if c in mp:
            out += mp[c]
        elif c == " ":
            out += b"\xA0"
        else:
            out += c.encode("cp932")
    return bytes(out)


def iter_nul_strings(data: bytes, min_len=2):
    start = 0
    n = len(data)
    while start < n:
        end = data.find(b"\0", start)
        if end < 0:
            break
        if end - start >= min_len:
            raw = data[start:end]
            try:
                s = raw.decode("cp932")
            except UnicodeDecodeError:
                s = None
            if s is not None:
                yield start, end, raw, s
        start = end + 1


def patch_exact_nul(b: bytearray, label: str, jp: str, kr: str, mp, rows):
    old = jp.encode("cp932")
    new = enc_ko(kr, mp)
    if len(new) > len(old):
        rows.append({
            "label": label, "japanese": jp, "korean": kr, "offset_hex": "",
            "old_bytes": len(old), "new_bytes": len(new), "status": "SKIP_TOO_LONG",
        })
        return 0
    count = 0
    pos = 0
    original = bytes(b)
    while True:
        i = original.find(old, pos)
        if i < 0:
            break
        pos = i + 1
        # Exact C string only: NUL after source. Requiring a separator before it
        # avoids changing substrings embedded in longer UI strings.
        before_ok = i == 0 or original[i-1] == 0
        after = i + len(old)
        after_ok = after < len(original) and original[after] == 0
        if before_ok and after_ok:
            b[i:i+len(old)] = new + bytes(len(old) - len(new))
            rows.append({
                "label": label, "japanese": jp, "korean": kr,
                "offset_hex": hex(i), "old_bytes": len(old), "new_bytes": len(new),
                "status": "PATCHED",
            })
            count += 1
    if count == 0:
        rows.append({
            "label": label, "japanese": jp, "korean": kr, "offset_hex": "",
            "old_bytes": len(old), "new_bytes": len(new), "status": "NOT_FOUND",
        })
    return count


def patch_dynamic_nul(b: bytearray, mp, rows):
    # Snapshot strings before mutation.
    strings = list(iter_nul_strings(bytes(b), 4))
    patched_offsets = set()
    for label, must1, must2, kr in DYNAMIC_RULES:
        for start, end, raw, s in strings:
            if must1 not in s or must2 not in s:
                continue
            # Ignore already-Korean/mixed unrelated strings and only touch a
            # reasonably short UI sentence.
            if len(raw) > 160:
                continue
            new = enc_ko(kr, mp)
            if len(new) > len(raw):
                rows.append({
                    "label": label, "japanese": s, "korean": kr,
                    "offset_hex": hex(start), "old_bytes": len(raw),
                    "new_bytes": len(new), "status": "SKIP_TOO_LONG_DYNAMIC",
                })
                continue
            if start in patched_offsets:
                continue
            b[start:end] = new + bytes(len(raw) - len(new))
            rows.append({
                "label": label, "japanese": s, "korean": kr,
                "offset_hex": hex(start), "old_bytes": len(raw),
                "new_bytes": len(new), "status": "PATCHED_DYNAMIC",
            })
            patched_offsets.add(start)


def validate_boot_changes(old: bytes, new: bytes, rows):
    if len(old) != len(new):
        raise RuntimeError("BOOT size changed")
    allowed = []
    for r in rows:
        if not r["status"].startswith("PATCHED") or not r["offset_hex"]:
            continue
        off = int(r["offset_hex"], 16)
        allowed.append((off, off + int(r["old_bytes"])))
    for i, (a, b) in enumerate(zip(old, new)):
        if a == b:
            continue
        if not any(lo <= i < hi for lo, hi in allowed):
            raise RuntimeError(f"Unexpected BOOT byte change at 0x{i:X}")


def write_tsv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"D:\narutimate portable")
    ap.add_argument("--assets", default=None)
    args = ap.parse_args()
    root = Path(args.root)
    script_dir = Path(__file__).resolve().parent
    assets = Path(args.assets) if args.assets else script_dir / "sub44_assets"
    source_iso = root / SOURCE_REL
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    final_iso = out / FINAL_NAME

    if not source_iso.exists():
        raise RuntimeError(f"SUB43 source ISO missing: {source_iso}")
    got = h.sha256_file(source_iso)
    if got != SOURCE_SHA:
        raise RuntimeError(f"SUB43 source ISO SHA256 mismatch: {got}")

    p14 = root / "analysis/stage14/naruto_patcher.py"
    p15 = root / "analysis/stage15/stage15_iso_patcher.py"
    if not p14.exists() or not p15.exists():
        raise RuntimeError("Stage14/Stage15 helpers missing")
    m = h.mod("sub44_p14", p14)
    iso = h.mod("sub44_p15", p15)

    print("[1/8] Extract exact SUB43 DAT/IDX/BOOT", flush=True)
    src_dat = out / "source_sub43_naruto.dat"
    src_idx = out / "source_sub43_naruto.idx"
    src_boot = out / "source_sub43_BOOT.bin"
    dat = out / "naruto.dat"
    idx = out / "naruto.idx"
    boot = out / "BOOT.bin"
    h.extract_iso_file(source_iso, "PSP_GAME/USRDIR/naruto.dat", src_dat)
    h.extract_iso_file(source_iso, "PSP_GAME/USRDIR/naruto.idx", src_idx)
    h.extract_iso_file(source_iso, "PSP_GAME/SYSDIR/BOOT.BIN", src_boot)
    shutil.copyfile(src_dat, dat)
    shutil.copyfile(src_idx, idx)

    print("[2/8] Patch runtime UI strings in BOOT/EBOOT image", flush=True)
    mp = load_mapping(root)
    # Validate every Hangul char in the planned translations before touching data.
    missing = sorted({
        c for _, _, kr in FIXED_TEXT for c in kr if "가" <= c <= "힣" and c not in mp
    } | {
        c for _, _, _, kr in DYNAMIC_RULES for c in kr if "가" <= c <= "힣" and c not in mp
    })
    if missing:
        raise RuntimeError("New Hangul glyphs would be required: " + "".join(missing))

    old_boot = src_boot.read_bytes()
    bb = bytearray(old_boot)
    text_rows = []
    for label, jp, kr in FIXED_TEXT:
        patch_exact_nul(bb, label, jp, kr, mp, text_rows)
    patch_dynamic_nul(bb, mp, text_rows)
    new_boot = bytes(bb)
    validate_boot_changes(old_boot, new_boot, text_rows)
    boot.write_bytes(new_boot)
    patched_text_count = sum(r["status"].startswith("PATCHED") for r in text_rows)
    print(f"  patched UI C-strings: {patched_text_count}", flush=True)

    print("[3/8] Patch compact difficulty labels in option.ccs", flush=True)
    src_eb = m.read_embedded_index(src_dat)
    src_xb = src_idx.read_bytes()
    src_ei = m.parse_pidx(src_eb, "sub43-src")
    eb = bytearray(m.read_embedded_index(dat))
    xb = bytearray(idx.read_bytes())
    ei = m.parse_pidx(eb, "sub44-embedded")
    xi = m.parse_pidx(xb, "sub44-external")

    target = "option.ccs"
    rec = next((e for e in ei["primary"] if e["name"] == target), None)
    if not rec:
        raise RuntimeError("option.ccs missing")
    with dat.open("rb") as f:
        f.seek(rec["offset"])
        stored = f.read(rec["zsize"] or rec["size"])
    original_ccs = m.decode_stored(stored, rec["size"], rec["zsize"])
    b = bytearray(original_ccs)
    png = assets / "option_compact_ko.png"
    if not png.exists():
        raise RuntimeError(f"Option replacement missing: {png}")
    texrow = h.patch_texture(b, "TEX_option01", png)
    new_ccs = bytes(b)
    if len(new_ccs) != len(original_ccs):
        raise RuntimeError("option.ccs decoded size changed")
    encoded = m.encode_3_0(new_ccs)
    if m.decode_3x(encoded) != new_ccs:
        raise RuntimeError("option.ccs encode/decode self-check failed")

    print("[4/8] Append option.ccs + update PIDX / FSTS", flush=True)
    with dat.open("ab") as f:
        off = m.align_up(f.tell())
        if off > f.tell():
            f.write(bytes(off - f.tell()))
        f.write(encoded)
    for blob, table in ((eb, ei), (xb, xi)):
        q = next(q for q in table["primary"] if q["name"] == target)
        struct.pack_into("<III", blob, q["record_off"] + 12, off, len(new_ccs), len(encoded))

    changed_bundles = []
    fsts_repl = {target: {
        "original_sha256": m.sha256(original_ccs),
        "new_decoded": new_ccs,
    }}
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"])
            bundle = f.read(r["file_size"])
            rebuilt, changes = m.rebuild_fsts(bundle, r["name"], fsts_repl)
            if not changes:
                continue
            f.seek(0, 2)
            boff = m.align_up(f.tell())
            if boff > f.tell():
                f.write(bytes(boff - f.tell()))
            f.write(rebuilt)
            for blob, table in ((eb, ei), (xb, xi)):
                q = next(q for q in table["offset2_rows"] if q["index"] == r["index"])
                struct.pack_into("<II", blob, q["record_abs"] + 8, boff, len(rebuilt))
            changed_bundles.append({"bundle": r["name"], "members": changes})
        f.seek(0)
        f.write(eb)
    idx.write_bytes(xb)

    print("[5/8] Build SUB44 from exact SUB43 ISO", flush=True)
    if final_iso.exists():
        final_iso.unlink()
    shutil.copyfile(source_iso, final_iso)
    with final_iso.open("r+b") as f:
        vds = iso.read_volume_descriptors(f)
        for ipath, host in (
            ("PSP_GAME/USRDIR/naruto.dat", dat),
            ("PSP_GAME/USRDIR/naruto.idx", idx),
            ("PSP_GAME/SYSDIR/BOOT.BIN", boot),
            ("PSP_GAME/SYSDIR/EBOOT.BIN", boot),
        ):
            recs = [iso.find_path(f, vd, ipath.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext = iso.append_file_sector_aligned(f, host, host.name)
            for r in recs:
                if r:
                    iso.patch_directory_record(f, r["record_offset"], ext["lba"], ext["size"])
        f.seek(0, 2)
        iso.update_volume_space(f, vds, (f.tell()+2047)//2048)

    print("[6/8] Static regression verification", flush=True)
    core_rows = []
    for ipath, host in (
        ("PSP_GAME/USRDIR/naruto.dat", dat),
        ("PSP_GAME/USRDIR/naruto.idx", idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN", boot),
        ("PSP_GAME/SYSDIR/EBOOT.BIN", boot),
    ):
        sz, hs = h.iso_segsha(final_iso, ipath)
        hh = h.sha256_file(host)
        ok = hs == hh
        core_rows.append({"iso_path":ipath,"size":sz,"iso_sha256":hs,"host_sha256":hh,"match":"YES" if ok else "NO"})
        if not ok:
            raise RuntimeError(f"ISO core verification failed: {ipath}")

    # All primary resources except option.ccs must remain stored-byte-identical.
    final_ei = m.parse_pidx(m.read_embedded_index(dat), "sub44-final")
    preserved_primary = 0
    with src_dat.open("rb") as sf, dat.open("rb") as ff:
        for sr, fr in zip(src_ei["primary"], final_ei["primary"]):
            if sr["name"] != fr["name"]:
                raise RuntimeError("Primary order/name changed")
            if sr["is_folder"] or sr["name"] == target:
                continue
            sf.seek(sr["offset"]); sb = sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]); fb = ff.read(fr["zsize"] or fr["size"])
            if sb != fb:
                raise RuntimeError(f"Untargeted primary resource changed: {sr['name']}")
            preserved_primary += 1

        src_fsts = {r["index"]:r for r in src_ei["offset2_rows"]}
        fin_fsts = {r["index"]:r for r in final_ei["offset2_rows"]}
        preserved_fsts_members = 0
        for k in src_fsts:
            sr=src_fsts[k]; fr=fin_fsts[k]
            sf.seek(sr["file_off"]); sb=sf.read(sr["file_size"])
            ff.seek(fr["file_off"]); fb=ff.read(fr["file_size"])
            if sb == fb:
                continue
            sa=m.parse_fsts(sb,"sub43"); fa=m.parse_fsts(fb,"sub44")
            if len(sa["members"]) != len(fa["members"]):
                raise RuntimeError(f"FSTS member count changed: {sr['name']}")
            for sx,fx in zip(sa["members"],fa["members"]):
                if sx["name"] != fx["name"]:
                    raise RuntimeError(f"FSTS member order changed: {sr['name']}")
                if sx["basename"] != target:
                    if sx["stored"] != fx["stored"]:
                        raise RuntimeError(f"Untargeted FSTS member changed: {sr['name']} / {sx['name']}")
                    preserved_fsts_members += 1

    pmfs = h.walk_iso_pmfs(source_iso)
    movie_rows=[]
    for ip in pmfs:
        ss,sh=h.iso_segsha(source_iso,ip); fs,fh=h.iso_segsha(final_iso,ip)
        ok=ss==fs and sh==fh
        movie_rows.append({"iso_path":ip,"source_sha256":sh,"sub44_sha256":fh,"match":"YES" if ok else "NO"})
        if not ok:
            raise RuntimeError(f"PMF changed: {ip}")

    print("[7/8] Write discovery/patch reports", flush=True)
    write_tsv(out/"sub44_ui_text_patch.tsv", text_rows,
              ["label","japanese","korean","offset_hex","old_bytes","new_bytes","status"])
    write_tsv(out/"sub44_iso_core_verification.tsv", core_rows,
              ["iso_path","size","iso_sha256","host_sha256","match"])
    write_tsv(out/"sub44_movie_preservation.tsv", movie_rows,
              ["iso_path","source_sha256","sub44_sha256","match"])
    write_tsv(out/"sub44_texture_patch.tsv", [{
        **texrow, "resource":"option.ccs"
    }], ["resource","texture","width","height","format","palette","changed_pixels","replacement"])

    # Search remaining Japanese strings containing keywords after patching; this is
    # diagnostic only and prevents us from claiming a complete menu translation.
    remaining=[]
    for off,end,raw,s in iter_nul_strings(new_boot, 4):
        if any(k in s for k in ("待機所","通信対戦","ゲームモード選択","強敵との決闘","設定の変更","無幻城")):
            if any("\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff" for c in s):
                remaining.append({"offset_hex":hex(off),"text":s,"bytes":len(raw)})
    write_tsv(out/"sub44_remaining_ui_japanese.tsv", remaining,
              ["offset_hex","text","bytes"])

    report = {
        "stage":"SUB44_UI_TEXT_CLEANUP",
        "source_iso":str(source_iso),
        "source_iso_sha256":SOURCE_SHA,
        "final_iso":str(final_iso),
        "final_iso_size":final_iso.stat().st_size,
        "final_iso_sha256":h.sha256_file(final_iso),
        "boot_ui_strings_patched":patched_text_count,
        "boot_text_not_found":sum(r["status"]=="NOT_FOUND" for r in text_rows),
        "option_texture_changed_pixels":texrow["changed_pixels"],
        "changed_fsts_bundles":[x["bundle"] for x in changed_bundles],
        "preserved_non_target_primary_resources":preserved_primary,
        "preserved_non_target_fsts_members":preserved_fsts_members,
        "pmf_movies_preserved":len(movie_rows),
        "font_mapping_preserved":"694+17",
        "new_glyphs_added":0,
        "remaining_keyword_japanese_strings":len(remaining),
        "static_qa":"PASS",
        "runtime_qa":"REQUIRED",
        "notes":[
            "SUB43 runtime showed Japanese/mixed donor-glyph text in mode descriptions, option help, wireless menu, and exit prompt.",
            "This stage patches only exact NUL-terminated BOOT UI strings that safely fit their original slots.",
            "Unmapped/unknown menu images such as mugen mission-card artwork and other non-selected UI remain pending.",
        ],
    }
    (out/"SUB44_static_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    launcher=out/"SUB44_run.cmd"
    ppsspp=root/"tools/ppsspp-stage33-2314/PPSSPPWindows64.exe"
    launcher.write_text("@echo off\r\nchcp 65001 >nul\r\n"+f'"{ppsspp}" "{final_iso}"\r\n',encoding="utf-8-sig")

    print("[8/8] Done", flush=True)
    summary=[
        "Naruto PSP SUB44 - UI Text Cleanup",
        "",
        f"SourceSHA256={SOURCE_SHA}",
        f"FinalISO={final_iso}",
        f"FinalSHA256={report['final_iso_sha256']}",
        f"BOOTUIStringsPatched={patched_text_count}",
        f"OptionChangedPixels={texrow['changed_pixels']}",
        f"FSTSChangedBundles={len(changed_bundles)}",
        f"PreservedPrimaryResources={preserved_primary}",
        f"PreservedPMFs={len(movie_rows)}",
        "ExistingFontMappingPreserved=694+17",
        "NewGlyphsAdded=0",
        "StaticQA=PASS",
        "RuntimeQA=REQUIRED",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary), flush=True)


if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
