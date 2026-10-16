from pathlib import Path
import struct, hashlib, importlib.util, json, zipfile, traceback, zlib, binascii

ROOT = Path(r"PROJECT_ROOT")
SOURCE = ROOT / r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso"
EXPECTED_SHA256 = "8a4ddc795e6f5287f6ed54018bd48c3c881a4e7343fb7ca31d60e0e8afa32081"
OUT = ROOT / r"analysis\sub\sub51p_texred_original"
LOGS = ROOT / "logs"
SECTOR = 2048

def sha256_file(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    if not s or not s.loader:
        raise RuntimeError("Cannot import " + str(path))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16 * SECTOR)
        p = f.read(SECTOR)
    if len(p) != SECTOR or p[0] != 1 or p[1:6] != b"CD001":
        raise RuntimeError("Bad ISO")
    r = p[156:190]
    return int.from_bytes(r[2:6], "little"), int.from_bytes(r[10:14], "little")

def dirents(iso, lba, size):
    with Path(iso).open("rb") as f:
        f.seek(lba * SECTOR)
        data = f.read(size)
    out = []
    pos = 0
    while pos < len(data):
        ln = data[pos]
        if ln == 0:
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue
        r = data[pos:pos+ln]
        if len(r) < 34:
            break
        nb = r[33:33+r[32]]
        name = "." if nb == b"\0" else (".." if nb == b"\1" else nb.decode("ascii", "replace").split(";", 1)[0])
        out.append({
            "name": name,
            "lba": int.from_bytes(r[2:6], "little"),
            "size": int.from_bytes(r[10:14], "little"),
            "is_dir": bool(r[25] & 2),
        })
        pos += ln
    return out

def findiso(iso, path):
    lba, size = iso_root(iso)
    cur = {"lba": lba, "size": size, "is_dir": True}
    for part in [x for x in path.replace("\\", "/").split("/") if x]:
        hit = next((e for e in dirents(iso, cur["lba"], cur["size"]) if e["name"].casefold() == part.casefold()), None)
        if not hit:
            raise RuntimeError("ISO missing " + path)
        cur = hit
    return cur

def extract(iso, ipath, out):
    e = findiso(iso, ipath)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with Path(iso).open("rb") as fi, Path(out).open("wb") as fo:
        fi.seek(e["lba"] * SECTOR)
        rem = e["size"]
        while rem:
            b = fi.read(min(rem, 1024*1024))
            if not b:
                raise RuntimeError("EOF")
            fo.write(b)
            rem -= len(b)

def ccs_names(b):
    pc, nc = struct.unpack_from("<II", b, 0x44)
    no = 0x4C + 32 * pc
    if pc > 10000 or nc > 20000 or no + 32 * nc > len(b):
        raise RuntimeError(f"Bad CCS header pc={pc} nc={nc}")
    return [
        b[no+32*i:no+32*i+30].split(b"\0", 1)[0].decode("cp932", errors="replace")
        for i in range(nc)
    ]

def find_palette(b, palid):
    magic = bytes.fromhex("0004cccc")
    for o in range(0, len(b)-28, 4):
        if b[o:o+4] != magic:
            continue
        if struct.unpack_from("<I", b, o+8)[0] != palid:
            continue
        n = struct.unpack_from("<I", b, o+24)[0]
        if n not in (16, 256) or o + 28 + n*4 > len(b):
            continue
        pal = []
        for i in range(n):
            bo, go, ro, ao = struct.unpack_from("BBBB", b, o+28+i*4)
            pal.append((ro, go, bo, min(ao*2, 255)))
        return pal
    raise RuntimeError(f"Palette missing id={palid}")

def find_texture(b, name):
    names = ccs_names(b)
    if name not in names:
        raise RuntimeError("Texture missing " + name)
    wanted = names.index(name)
    magic = bytes.fromhex("0003cccc")
    for o in range(0, len(b)-36, 4):
        if b[o:o+4] != magic:
            continue
        if struct.unpack_from("<I", b, o+8)[0] != wanted:
            continue
        palid = struct.unpack_from("<I", b, o+12)[0]
        typ = b[o+21]
        we, he = b[o+24:o+26]
        if typ not in (0x13, 0x14) or we > 12 or he > 12:
            continue
        w, h = 1 << we, 1 << he
        dl = w*h if typ == 0x13 else w*h//2
        if o + 36 + dl <= len(b):
            return {
                "offset": o,
                "palette": palid,
                "type": typ,
                "width": w,
                "height": h,
                "data_len": dl,
            }
    raise RuntimeError("Texture record missing " + name)

def decode_indices(b, t):
    raw = b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    w, h = t["width"], t["height"]
    vals = []
    if t["type"] == 0x13:
        vals = list(raw)
    else:
        for v in raw:
            vals.extend((v & 0x0F, (v >> 4) & 0x0F))
    if len(vals) != w*h:
        raise RuntimeError("Index payload size mismatch")
    rows = [vals[y*w:(y+1)*w] for y in range(h)]
    rows.reverse()
    return rows

def png_chunk(kind, data):
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xffffffff
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

def write_rgba_png(path, w, h, rgba):
    if len(rgba) != w*h*4:
        raise RuntimeError("RGBA length mismatch")
    raw = bytearray()
    stride = w*4
    for y in range(h):
        raw.append(0)
        raw.extend(rgba[y*stride:(y+1)*stride])
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    data = sig + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + png_chunk(b"IEND", b"")
    Path(path).write_bytes(data)

def rows_to_rgba(rows, pal):
    out = bytearray()
    for row in rows:
        for idx in row:
            if idx >= len(pal):
                raise RuntimeError(f"Palette index {idx} out of range")
            out.extend(bytes(pal[idx]))
    return bytes(out)

def make_grid_rgba(rgba, w, h, step=16):
    b = bytearray(rgba)
    # red grid, semi-transparent-looking via direct blend
    for y in range(h):
        for x in range(w):
            if x % step == 0 or y % step == 0:
                off = (y*w+x)*4
                r,g,bb,a = b[off:off+4]
                # Only draw where visible OR on fully transparent pixels using faint alpha.
                if a == 0:
                    b[off:off+4] = bytes((255, 0, 0, 96))
                else:
                    b[off:off+4] = bytes((255, min(g,80), min(bb,80), 255))
    return bytes(b)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    print("=== SUB51P TEX_red ORIGINAL EXTRACT ===", flush=True)
    if not SOURCE.exists():
        raise RuntimeError("SUB51N source ISO missing: " + str(SOURCE))

    actual_sha = sha256_file(SOURCE)
    print("Source SHA256:", actual_sha, flush=True)
    if actual_sha != EXPECTED_SHA256:
        raise RuntimeError("SUB51N source SHA mismatch")

    p14path = ROOT / r"analysis\stage14\naruto_patcher.py"
    if not p14path.exists():
        raise RuntimeError("stage14 naruto_patcher.py missing: " + str(p14path))
    p14 = mod("sub51p_texred_p14", p14path)

    work = OUT / "_work"
    work.mkdir(exist_ok=True)
    dat = work / "naruto.dat"

    print("[1/4] Extract naruto.dat", flush=True)
    extract(SOURCE, "PSP_GAME/USRDIR/naruto.dat", dat)

    print("[2/4] Decode gauge.ccs", flush=True)
    table = p14.parse_pidx(p14.read_embedded_index(dat), "src")
    r = next((x for x in table["primary"] if x["name"] == "gauge.ccs"), None)
    if not r:
        raise RuntimeError("gauge.ccs primary missing")
    with dat.open("rb") as f:
        f.seek(r["offset"])
        stored = f.read(r["zsize"] or r["size"])
    ccs = p14.decode_stored(stored, r["size"], r["zsize"])
    (OUT / "gauge.ccs.decoded.bin").write_bytes(ccs)

    print("[3/4] Extract exact TEX_red", flush=True)
    t = find_texture(ccs, "TEX_red")
    pal = find_palette(ccs, t["palette"])
    rows = decode_indices(ccs, t)
    rgba = rows_to_rgba(rows, pal)

    original = OUT / "gauge.ccs_TEX_red_ORIGINAL.png"
    grid = OUT / "gauge.ccs_TEX_red_ORIGINAL_grid16.png"
    write_rgba_png(original, t["width"], t["height"], rgba)
    write_rgba_png(grid, t["width"], t["height"], make_grid_rgba(rgba, t["width"], t["height"], 16))

    info = {
        "source_iso": str(SOURCE),
        "source_iso_sha256": actual_sha,
        "resource": "gauge.ccs",
        "texture": "TEX_red",
        "width": t["width"],
        "height": t["height"],
        "type": hex(t["type"]),
        "palette_id": t["palette"],
        "palette_entries": len(pal),
        "data_len": t["data_len"],
        "texture_record_offset": t["offset"],
        "original_png_sha256": sha256_file(original),
    }
    (OUT / "TEX_red_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUT / "README.txt").write_text(
        "SUB51P TEX_red original extraction\n\n"
        "This is the exact TEX_red decoded from the verified SUB51N ISO.\n"
        "No game files were modified.\n\n"
        "FileLOCAL_PATH"
        "- gauge.ccs_TEX_red_ORIGINAL.png : exact decoded original texture\n"
        "- gauge.ccs_TEX_red_ORIGINAL_grid16.png : same image with 16px grid overlay\n"
        "- gauge.ccs.decoded.bin : decoded gauge.ccs\n"
        "- TEX_red_info.json : dimensions/palette/offset metadata\n",
        encoding="utf-8-sig"
    )

    print("[4/4] Package result", flush=True)
    z = LOGS / "naruto_sub51p_texred_original_extract_upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file():
                zz.write(p, p.name)

    print("ORIGINAL_PNG=" + str(original), flush=True)
    print("GRID_PNG=" + str(grid), flush=True)
    print("UPLOAD_ZIP=" + str(z), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        err = traceback.format_exc()
        (OUT / "FAILURE.txt").write_text(err, encoding="utf-8")
        z = LOGS / "fail_naruto_sub51p_texred_original_extract_upload.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file():
                    zz.write(p, p.name)
        print(err, flush=True)
        print("UPLOAD_ZIP=" + str(z), flush=True)
        raise
