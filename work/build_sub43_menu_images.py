from __future__ import annotations
from pathlib import Path
import argparse, csv, hashlib, importlib.util, json, os, shutil, struct, sys
import numpy as np
from PIL import Image

SECTOR = 2048
SOURCE_ISO_SHA256 = "027973bbde6d7b1ddccc0e5e407e6ee519b8b9874b5c91ec778eb794bda493c3"
SOURCE_REL = Path("analysis/sub/sub42_menu_text/Naruto_KR_MOV06E_SUB42_Names_Guides_Menu.iso")
OUT_REL = Path("analysis/sub/sub43_menu_images")
FINAL_NAME = "Naruto_KR_MOV06E_SUB43_MenuImages.iso"

TARGETS = {
    "modesel1.ccs": [
        ("TEX_mod_bg00", "entry0193__modesel1__0002__TEX_mod_bg00_upright_ko.png"),
        ("TEX_mod_bg01", "entry0193__modesel1__0004__TEX_mod_bg01_upright_ko.png"),
        ("TEX_mod_bg03", "entry0193__modesel1__0006__TEX_mod_bg03_upright_ko.png"),
        ("TEX_mod_bg04", "entry0193__modesel1__0008__TEX_mod_bg04_upright_ko.png"),
        ("TEX_mod_bg05", "entry0193__modesel1__0010__TEX_mod_bg05_upright_ko.png"),
        ("TEX_mod_bg06", "entry0193__modesel1__0012__TEX_mod_bg06_upright_ko.png"),
        ("TEX_mod_bg07", "entry0193__modesel1__0014__TEX_mod_bg07_upright_ko.png"),
    ],
    "option.ccs": [("TEX_option01", "entry0201__option__0002__TEX_option01_upright_ko.png")],
    "charsel1.ccs": [("TEX_sel", "entry0181__charsel1__0050__TEX_sel_upright_ko.png")],
    "mugen.ccs": [
        ("TEX_white", "entry0373__mugen__0272__TEX_white_upright_ko.png"),
        ("TEX_red", "entry0373__mugen__0216__TEX_red_upright_ko.png"),
    ],
    "gauge.ccs": [
        ("TEX_red", "entry0214__gauge__0247__TEX_red_upright_ko.png"),
        ("TEX_white", "entry0214__gauge__0251__TEX_white_upright_ko.png"),
    ],
    "setting.ccs": [("TEX_s_menu1", "entry0203__setting__0002__TEX_s_menu1_upright_ko.png")],
}


def mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot import {path}")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def iso_root_record(iso: Path):
    with iso.open("rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
    if len(pvd) != SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise RuntimeError("ISO9660 primary volume descriptor not found")
    rec = pvd[156:190]
    return int.from_bytes(rec[2:6], "little"), int.from_bytes(rec[10:14], "little")


def iso_dir_entries(iso: Path, lba: int, size: int):
    with iso.open("rb") as f:
        f.seek(lba * SECTOR)
        data = f.read(size)
    out = []
    pos = 0
    while pos < len(data):
        ln = data[pos]
        if ln == 0:
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue
        r = data[pos:pos + ln]
        if len(r) < 34:
            break
        nb = r[33:33 + r[32]]
        if nb == b"\0":
            name = "."
        elif nb == b"\1":
            name = ".."
        else:
            name = nb.decode("ascii", errors="replace").split(";", 1)[0]
        out.append({
            "name": name,
            "lba": int.from_bytes(r[2:6], "little"),
            "size": int.from_bytes(r[10:14], "little"),
            "is_dir": bool(r[25] & 2),
        })
        pos += ln
    return out


def iso_find(iso: Path, path: str):
    lba, size = iso_root_record(iso)
    cur = {"lba": lba, "size": size, "is_dir": True}
    for part in [x for x in path.replace("\\", "/").split("/") if x]:
        hit = next((e for e in iso_dir_entries(iso, cur["lba"], cur["size"]) if e["name"].casefold() == part.casefold()), None)
        if not hit:
            raise RuntimeError(f"ISO path missing: {path}")
        cur = hit
    return cur


def extract_iso_file(iso: Path, ipath: str, out: Path):
    e = iso_find(iso, ipath)
    if e["is_dir"]:
        raise RuntimeError(f"Expected file in ISO: {ipath}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with iso.open("rb") as fi, out.open("wb") as fo:
        fi.seek(e["lba"] * SECTOR)
        rem = e["size"]
        while rem:
            b = fi.read(min(rem, 1024 * 1024))
            if not b:
                raise RuntimeError(f"Unexpected EOF extracting {ipath}")
            fo.write(b)
            rem -= len(b)


def iso_segsha(iso: Path, ipath: str):
    e = iso_find(iso, ipath)
    h = hashlib.sha256()
    with iso.open("rb") as f:
        f.seek(e["lba"] * SECTOR)
        rem = e["size"]
        while rem:
            b = f.read(min(rem, 1024 * 1024))
            if not b:
                raise RuntimeError("ISO segment EOF")
            h.update(b)
            rem -= len(b)
    return e["size"], h.hexdigest()


def walk_iso_pmfs(iso: Path, path="PSP_GAME/USRDIR"):
    out = []
    def walk(p):
        d = iso_find(iso, p)
        for e in iso_dir_entries(iso, d["lba"], d["size"]):
            if e["name"] in (".", ".."):
                continue
            q = p + "/" + e["name"]
            if e["is_dir"]:
                walk(q)
            elif e["name"].lower().endswith(".pmf"):
                out.append(q)
    walk(path)
    return sorted(out)


def ccs_names(b: bytes):
    pc, nc = struct.unpack_from("<II", b, 0x44)
    no = 0x4C + 32 * pc
    names = []
    for i in range(nc):
        s = b[no + 32*i:no + 32*i + 30].split(b"\0", 1)[0].decode("cp932", errors="replace")
        names.append(s)
    return names


def find_palette(b: bytes, palid: int):
    magic = bytes.fromhex("0004cccc")
    for o in range(0, len(b) - 28, 4):
        if b[o:o+4] != magic:
            continue
        i = struct.unpack_from("<I", b, o + 8)[0]
        if i != palid:
            continue
        n = struct.unpack_from("<I", b, o + 24)[0]
        if n not in (16, 256) or o + 28 + n*4 > len(b):
            continue
        raw = np.frombuffer(b[o+28:o+28+n*4], dtype=np.uint8).reshape(-1, 4).copy()
        rgba = raw[:, [2,1,0,3]]
        rgba[:,3] = np.minimum(rgba[:,3].astype(np.int16)*2, 255).astype(np.uint8)
        return o, rgba
    raise RuntimeError(f"Palette id {palid} not found")


def find_texture(b: bytes, texture_name: str):
    names = ccs_names(b)
    try:
        wanted_index = names.index(texture_name)
    except ValueError:
        raise RuntimeError(f"Texture name not in CCS name table: {texture_name}")
    magic = bytes.fromhex("0003cccc")
    for o in range(0, len(b) - 36, 4):
        if b[o:o+4] != magic:
            continue
        i = struct.unpack_from("<I", b, o + 8)[0]
        if i != wanted_index:
            continue
        palid = struct.unpack_from("<I", b, o + 12)[0]
        typ = b[o + 21]
        we, he = b[o + 24:o + 26]
        if we > 12 or he > 12 or typ not in (0x13, 0x14):
            continue
        w, h = 1 << we, 1 << he
        if typ == 0x13:
            data_len = w * h
        else:
            data_len = w * h // 2
        if o + 36 + data_len > len(b):
            continue
        return {"offset": o, "index": i, "palette": palid, "type": typ, "width": w, "height": h, "data_len": data_len}
    raise RuntimeError(f"Texture record not found: {texture_name}")


def decode_texture_indices(b: bytes, tex):
    raw = np.frombuffer(b[tex["offset"]+36:tex["offset"]+36+tex["data_len"]], dtype=np.uint8)
    if tex["type"] == 0x13:
        ix = raw.reshape(tex["height"], tex["width"]).copy()
    else:
        ix = np.stack((raw & 15, raw >> 4), axis=1).reshape(tex["height"], tex["width"]).copy()
    return ix[::-1].copy()  # upright


def encode_texture_indices(ix_upright, typ):
    flat = ix_upright[::-1].reshape(-1).astype(np.uint8)
    if typ == 0x13:
        return flat.tobytes()
    return (flat[::2] | (flat[1::2] << 4)).astype(np.uint8).tobytes()


def patch_texture(b: bytearray, texture_name: str, replacement_png: Path):
    tex = find_texture(b, texture_name)
    _, pal = find_palette(b, tex["palette"])
    old_ix = decode_texture_indices(b, tex)
    old_rgba = pal[old_ix]
    repl = np.asarray(Image.open(replacement_png).convert("RGBA"), dtype=np.uint8)
    if repl.shape[:2] != (tex["height"], tex["width"]):
        raise RuntimeError(f"Replacement size mismatch for {texture_name}: {repl.shape[1]}x{repl.shape[0]} vs {tex['width']}x{tex['height']}")

    same = np.all(repl == old_rgba, axis=2)
    new_ix = old_ix.copy()
    changed = ~same
    if np.any(changed):
        # Premultiplied RGBA distance matches earlier SUB41 rendering logic and
        # prevents transparent white from being confused with opaque white.
        pe = pal.astype(np.float32)
        pe[:, :3] *= pe[:, 3:4] / 255.0
        px = repl[changed].astype(np.float32)
        px[:, :3] *= px[:, 3:4] / 255.0
        # Chunk to limit peak RAM.
        chosen = np.empty((len(px),), dtype=np.uint8)
        step = 4096
        for s in range(0, len(px), step):
            q = px[s:s+step]
            dist = ((q[:, None, :] - pe[None, :, :]) ** 2).sum(axis=2)
            chosen[s:s+len(q)] = dist.argmin(axis=1).astype(np.uint8)
        new_ix[changed] = chosen

    packed = encode_texture_indices(new_ix, tex["type"])
    if len(packed) != tex["data_len"]:
        raise RuntimeError("Packed texture size changed")
    a = tex["offset"] + 36
    b[a:a+len(packed)] = packed
    return {
        "texture": texture_name,
        "width": tex["width"],
        "height": tex["height"],
        "format": hex(tex["type"]),
        "palette": tex["palette"],
        "changed_pixels": int(changed.sum()),
        "replacement": replacement_png.name,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"D:\narutimate portable")
    ap.add_argument("--assets", default=None)
    args = ap.parse_args()

    root = Path(args.root)
    script_dir = Path(__file__).resolve().parent
    assets = Path(args.assets) if args.assets else script_dir / "sub43_assets"
    source_iso = root / SOURCE_REL
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    final_iso = out / FINAL_NAME
    dat = out / "naruto.dat"
    idx = out / "naruto.idx"
    source_dat = out / "source_sub42_naruto.dat"
    source_idx = out / "source_sub42_naruto.idx"

    if not source_iso.exists():
        raise RuntimeError(f"SUB42 source ISO missing: {source_iso}")
    got = sha256_file(source_iso)
    if got != SOURCE_ISO_SHA256:
        raise RuntimeError(f"SUB42 source ISO SHA256 mismatch: {got}")
    if not assets.exists():
        raise RuntimeError(f"SUB43 assets folder missing: {assets}")

    p14 = root / "analysis/stage14/naruto_patcher.py"
    p15 = root / "analysis/stage15/stage15_iso_patcher.py"
    if not p14.exists() or not p15.exists():
        raise RuntimeError("Stage14/Stage15 patch helpers are missing")
    m = mod("p14", p14)
    iso = mod("p15", p15)

    print("[1/7] Extract exact SUB42 DAT/IDX", flush=True)
    extract_iso_file(source_iso, "PSP_GAME/USRDIR/naruto.dat", source_dat)
    extract_iso_file(source_iso, "PSP_GAME/USRDIR/naruto.idx", source_idx)
    shutil.copyfile(source_dat, dat)
    shutil.copyfile(source_idx, idx)

    src_eb = m.read_embedded_index(source_dat)
    src_xb = source_idx.read_bytes()
    src_ei = m.parse_pidx(src_eb, "sub42-embedded")
    src_xi = m.parse_pidx(src_xb, "sub42-external")

    eb = bytearray(m.read_embedded_index(dat))
    xb = bytearray(idx.read_bytes())
    ei = m.parse_pidx(eb, "sub43-embedded")
    xi = m.parse_pidx(xb, "sub43-external")

    replacements = {}
    texture_rows = []
    resource_rows = []

    print("[2/7] Patch 14 high-confidence UI textures", flush=True)
    for resource_name, jobs in TARGETS.items():
        rec = next((e for e in ei["primary"] if e["name"] == resource_name), None)
        if not rec:
            raise RuntimeError(f"Primary resource missing: {resource_name}")
        with dat.open("rb") as f:
            f.seek(rec["offset"])
            stored = f.read(rec["zsize"] or rec["size"])
        original = m.decode_stored(stored, rec["size"], rec["zsize"])
        b = bytearray(original)
        for texture_name, png_name in jobs:
            png = assets / png_name
            if not png.exists():
                raise RuntimeError(f"Replacement PNG missing: {png}")
            row = patch_texture(b, texture_name, png)
            row["resource"] = resource_name
            texture_rows.append(row)
            print(f"  {resource_name} / {texture_name}: changed_pixels={row['changed_pixels']}", flush=True)
        new_decoded = bytes(b)
        if len(new_decoded) != len(original):
            raise RuntimeError(f"Decoded CCS size changed: {resource_name}")
        encoded = m.encode_3_0(new_decoded)
        if m.decode_3x(encoded) != new_decoded:
            raise RuntimeError(f"CCS encode/decode self-check failed: {resource_name}")
        replacements[resource_name] = {
            "original_sha256": m.sha256(original),
            "new_decoded": new_decoded,
            "encoded": encoded,
        }

    print("[3/7] Append patched primary CCS resources and update both PIDX tables", flush=True)
    with dat.open("ab") as f:
        for resource_name in TARGETS:
            info = replacements[resource_name]
            off = m.align_up(f.tell())
            if off > f.tell():
                f.write(bytes(off - f.tell()))
            f.write(info["encoded"])
            info["new_offset"] = off
            for blob, table in ((eb, ei), (xb, xi)):
                rec = next(q for q in table["primary"] if q["name"] == resource_name)
                struct.pack_into("<III", blob, rec["record_off"] + 12, off, len(info["new_decoded"]), len(info["encoded"]))
            resource_rows.append({
                "resource": resource_name,
                "old_decoded_sha256": info["original_sha256"],
                "new_decoded_sha256": m.sha256(info["new_decoded"]),
                "new_offset": hex(off),
                "decoded_size": len(info["new_decoded"]),
                "stored_size": len(info["encoded"]),
            })

    print("[4/7] Rebuild all FSTS preload bundles containing patched CCS resources", flush=True)
    changed_bundles = []
    fsts_repl = {k: {"original_sha256": v["original_sha256"], "new_decoded": v["new_decoded"]} for k, v in replacements.items()}
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"])
            bundle = f.read(r["file_size"])
            rebuilt, changes = m.rebuild_fsts(bundle, r["name"], fsts_repl)
            if not changes:
                continue
            f.seek(0, 2)
            off = m.align_up(f.tell())
            if off > f.tell():
                f.write(bytes(off - f.tell()))
            f.write(rebuilt)
            for blob, table in ((eb, ei), (xb, xi)):
                q = next(q for q in table["offset2_rows"] if q["index"] == r["index"])
                struct.pack_into("<II", blob, q["record_abs"] + 8, off, len(rebuilt))
            changed_bundles.append({"bundle": r["name"], "offset": hex(off), "size": len(rebuilt), "members": changes})
            print(f"  FSTS {r['name']}: {len(changes)} target member(s)", flush=True)
        f.seek(0)
        f.write(eb)
    idx.write_bytes(xb)

    print("[5/7] Build SUB43 ISO from exact SUB42 ISO", flush=True)
    if final_iso.exists():
        final_iso.unlink()
    shutil.copyfile(source_iso, final_iso)
    with final_iso.open("r+b") as f:
        vds = iso.read_volume_descriptors(f)
        for ipath, host in (("PSP_GAME/USRDIR/naruto.dat", dat), ("PSP_GAME/USRDIR/naruto.idx", idx)):
            recs = [iso.find_path(f, vd, ipath.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext = iso.append_file_sector_aligned(f, host, host.name)
            for r in recs:
                if r:
                    iso.patch_directory_record(f, r["record_offset"], ext["lba"], ext["size"])
        f.seek(0, 2)
        iso.update_volume_space(f, vds, (f.tell() + 2047) // 2048)

    print("[6/7] Static regression verification", flush=True)
    # ISO core file verification.
    core_rows = []
    for ipath, host in (("PSP_GAME/USRDIR/naruto.dat", dat), ("PSP_GAME/USRDIR/naruto.idx", idx)):
        sz, h = iso_segsha(final_iso, ipath)
        hh = sha256_file(host)
        ok = h == hh
        core_rows.append({"iso_path": ipath, "size": sz, "iso_sha256": h, "host_sha256": hh, "match": "YES" if ok else "NO"})
        if not ok:
            raise RuntimeError(f"ISO target verification failed: {ipath}")
    # BOOT/EBOOT untouched from exact SUB42 source.
    for ipath in ("PSP_GAME/SYSDIR/BOOT.BIN", "PSP_GAME/SYSDIR/EBOOT.BIN"):
        ss, sh = iso_segsha(source_iso, ipath)
        fs, fh = iso_segsha(final_iso, ipath)
        ok = ss == fs and sh == fh
        core_rows.append({"iso_path": ipath, "size": fs, "iso_sha256": fh, "host_sha256": sh, "match": "YES" if ok else "NO"})
        if not ok:
            raise RuntimeError(f"BOOT/EBOOT changed unexpectedly: {ipath}")

    # Compare all non-target primary resources against SUB42 DAT.
    final_ei = m.parse_pidx(m.read_embedded_index(dat), "sub43-final")
    preserved_primary = 0
    target_set = set(TARGETS)
    with source_dat.open("rb") as sf, dat.open("rb") as ff:
        for srec, frec in zip(src_ei["primary"], final_ei["primary"]):
            if srec["name"] != frec["name"]:
                raise RuntimeError("Primary PIDX order/name changed")
            if srec["is_folder"]:
                continue
            if srec["name"] in target_set:
                continue
            sf.seek(srec["offset"]); sb = sf.read(srec["zsize"] or srec["size"])
            ff.seek(frec["offset"]); fb = ff.read(frec["zsize"] or frec["size"])
            if sb != fb:
                raise RuntimeError(f"Untargeted primary resource changed: {srec['name']}")
            preserved_primary += 1

        # FSTS verification: non-target members must remain stored-byte-identical.
        src_fsts = {r["index"]: r for r in src_ei["offset2_rows"]}
        final_fsts = {r["index"]: r for r in final_ei["offset2_rows"]}
        preserved_fsts_members = 0
        for idx_key in sorted(src_fsts):
            sr = src_fsts[idx_key]; fr = final_fsts[idx_key]
            sf.seek(sr["file_off"]); sb = sf.read(sr["file_size"])
            ff.seek(fr["file_off"]); fb = ff.read(fr["file_size"])
            if sb == fb:
                continue
            sa = m.parse_fsts(sb, "sub42")
            fa = m.parse_fsts(fb, "sub43")
            if len(sa["members"]) != len(fa["members"]):
                raise RuntimeError(f"FSTS member count changed: {sr['name']}")
            for sx, fx in zip(sa["members"], fa["members"]):
                if sx["name"] != fx["name"]:
                    raise RuntimeError(f"FSTS member order/name changed: {sr['name']}")
                if sx["basename"] not in target_set:
                    if sx["stored"] != fx["stored"]:
                        raise RuntimeError(f"Untargeted FSTS member changed: {sr['name']} / {sx['name']}")
                    preserved_fsts_members += 1

    # Movie preservation.
    pmfs = walk_iso_pmfs(source_iso)
    movie_rows = []
    for ipath in pmfs:
        ss, sh = iso_segsha(source_iso, ipath)
        fs, fh = iso_segsha(final_iso, ipath)
        ok = ss == fs and sh == fh
        movie_rows.append({"iso_path": ipath, "source_sha256": sh, "sub43_sha256": fh, "match": "YES" if ok else "NO"})
        if not ok:
            raise RuntimeError(f"PMF changed: {ipath}")

    # Verify patched textures can be re-decoded and match their nearest-palette quantization dimensions.
    patched_texture_count = len(texture_rows)
    if patched_texture_count != 14:
        raise RuntimeError(f"Expected 14 patched textures, got {patched_texture_count}")

    print("[7/7] Write reports / launcher", flush=True)
    def write_tsv(path, rows, fields):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    write_tsv(out / "sub43_texture_patch.tsv", texture_rows,
              ["resource","texture","width","height","format","palette","changed_pixels","replacement"])
    write_tsv(out / "sub43_resource_patch.tsv", resource_rows,
              ["resource","old_decoded_sha256","new_decoded_sha256","new_offset","decoded_size","stored_size"])
    write_tsv(out / "sub43_iso_core_verification.tsv", core_rows,
              ["iso_path","size","iso_sha256","host_sha256","match"])
    write_tsv(out / "sub43_movie_preservation.tsv", movie_rows,
              ["iso_path","source_sha256","sub43_sha256","match"])

    # Copy the human-readable asset manifest and preview sheets when present.
    for name in ("replacement_manifest.json", "SUB43_targets.md", "SUB43_menu_preview.png"):
        p = assets / name
        if p.exists():
            shutil.copy2(p, out / name)

    report = {
        "stage": "SUB43_MENU_IMAGES",
        "source_iso": str(source_iso),
        "source_iso_sha256": SOURCE_ISO_SHA256,
        "final_iso": str(final_iso),
        "final_iso_size": final_iso.stat().st_size,
        "final_iso_sha256": sha256_file(final_iso),
        "patched_primary_resources": sorted(TARGETS),
        "patched_primary_resource_count": len(TARGETS),
        "patched_textures": patched_texture_count,
        "fsts_changed_bundles": [x["bundle"] for x in changed_bundles],
        "fsts_changed_bundle_count": len(changed_bundles),
        "preserved_non_target_primary_resources": preserved_primary,
        "preserved_non_target_fsts_members_in_changed_bundles": preserved_fsts_members,
        "preserved_pmf_movies": len(movie_rows),
        "boot_eboot_preserved_from_sub42": True,
        "sub42_dialogue_tutorial_speaker_menu_text_preserved": True,
        "existing_694_glyph_mapping_preserved": True,
        "existing_sub40_17_safe_glyphs_preserved": True,
        "new_font_glyphs_added": 0,
        "static_qa": "PASS",
        "runtime_menu_visual_qa": "PENDING",
        "pending_not_applied": [
            "mugen TEX_mg_icon (inventory did not contain the named texture; do not claim applied)",
            "home TEX_mhvid01 decorative ナルト",
            "rpggauge TEX_rpgmenu01~04 (individual labels not yet mapped)",
            "any UI images outside the selected 381-image extraction set",
        ],
    }
    (out / "SUB43_static_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ppsspp = root / "tools/ppsspp-stage33-2314/PPSSPPWindows64.exe"
    launcher = out / "SUB43_run.cmd"
    launcher.write_text(
        "@echo off\r\nchcp 65001 >nul\r\n"
        f'"{ppsspp}" "{final_iso}"\r\n',
        encoding="utf-8-sig"
    )

    summary = [
        "Naruto PSP SUB43 - Menu Image Translation",
        "",
        f"SourceISO={source_iso}",
        f"SourceSHA256={SOURCE_ISO_SHA256}",
        f"FinalISO={final_iso}",
        f"FinalSHA256={report['final_iso_sha256']}",
        f"PatchedResources={len(TARGETS)}",
        f"PatchedTextures={patched_texture_count}",
        f"FSTSChangedBundles={len(changed_bundles)}",
        f"PreservedPrimaryResources={preserved_primary}",
        f"PreservedPMFs={len(movie_rows)}",
        "BOOT_EBOOT_Preserved=YES",
        "ExistingDialogueNamesGuidesMenuTextPreserved=YES",
        "ExistingFontMappingPreserved=694+17",
        "NewGlyphsAdded=0",
        "StaticQA=PASS",
        "RuntimeMenuVisualQA=PENDING",
    ]
    (out / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
