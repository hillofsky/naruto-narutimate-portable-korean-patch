import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path(r"PROJECT_ROOT")
STAGE = BASE / "analysis" / "stage34"
SOURCE_ISO = BASE / "kr" / "Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
SOURCE_BOOT = BASE / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN"
SOURCE_TBL = BASE / "analysis" / "stage33" / "event000_stage33.tbl"
PATCHER = BASE / "analysis" / "stage14" / "naruto_patcher.py"
ISO_PATCHER = BASE / "analysis" / "stage24" / "stage24_iso_multi_patch.py"
OUTPUT_ISO = BASE / "Naruto - Stage34 Hangul Event Test.iso"

FONT_FILE_OFFSET = 0x39CD04
BYTES_PER_GLYPH = 162
SPECIAL_GLYPH_START = 0xD65
SPECIAL_COUNT = 0x146 // 2
CHARS = "한글테스트가나다라마"
SPECIAL_PAIRS = bytes.fromhex(
    "e1 c9 e5 bf e7 b2 9d df fb fc e2 90 9e 8a e1 65 e1 8f 9c b1"
)
OLD_LINE = "うー…もうクタクタァ…。".encode("cp932")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_glyph(character, font):
    image = Image.new("L", (18, 18), 0)
    ImageDraw.Draw(image).text((1, -4), character, font=font, fill=255)
    values = [value // 17 for value in image.getdata()]
    packed = bytearray()
    for offset in range(0, len(values), 2):
        packed.append(values[offset] | (values[offset + 1] << 4))
    return bytes(packed)


STAGE.mkdir(parents=True, exist_ok=True)
PATCH = STAGE / "patch"
ISO_REPORT = STAGE / "iso"
for directory in (PATCH, ISO_REPORT):
    if directory.exists():
        shutil.rmtree(directory)

font = ImageFont.truetype(r"LOCAL_PATH", 16)
glyph_blob = b"".join(render_glyph(character, font) for character in CHARS)
glyph_index = SPECIAL_GLYPH_START + SPECIAL_COUNT - len(CHARS)
glyph_offset = FONT_FILE_OFFSET + glyph_index * BYTES_PER_GLYPH

boot = bytearray(SOURCE_BOOT.read_bytes())
original_glyphs = bytes(boot[glyph_offset:glyph_offset + len(glyph_blob)])
(STAGE / "original_glyphs.bin").write_bytes(original_glyphs)
boot[glyph_offset:glyph_offset + len(glyph_blob)] = glyph_blob
patched_boot = STAGE / "BOOT_stage34.bin"
patched_boot.write_bytes(boot)

table = SOURCE_TBL.read_bytes()
if table.count(OLD_LINE) != 1:
    raise RuntimeError(f"expected one dialogue line, found {table.count(OLD_LINE)}")
encoded_test = SPECIAL_PAIRS[:10]
table = table.replace(OLD_LINE, encoded_test, 1)
patched_tbl = STAGE / "event000_stage34.tbl"
patched_tbl.write_bytes(table)

subprocess.run(
    [
        "python", str(PATCHER), "--root", str(BASE), "--output", str(PATCH),
        "--replace", f"event000.tbl={patched_tbl}", "--force",
    ],
    check=True,
)

if OUTPUT_ISO.exists():
    OUTPUT_ISO.unlink()
subprocess.run(
    [
        "python", str(ISO_PATCHER), "--source-iso", str(SOURCE_ISO),
        "--dat", str(PATCH / "naruto.dat"), "--idx", str(PATCH / "naruto.idx"),
        "--boot", str(patched_boot), "--output-iso", str(OUTPUT_ISO),
        "--report-dir", str(ISO_REPORT),
    ],
    check=True,
)

report = {
    "stage": 34,
    "purpose": "Persistent event-dialogue Hangul bitmap proof",
    "characters": CHARS,
    "test_text": "한글테스트",
    "special_pairs": [SPECIAL_PAIRS[i:i + 2].hex(" ") for i in range(0, 20, 2)],
    "font_file_offset": f"0x{FONT_FILE_OFFSET:X}",
    "glyph_index_start": glyph_index,
    "glyph_patch_offset": f"0x{glyph_offset:X}",
    "bytes_per_glyph": BYTES_PER_GLYPH,
    "boot_source_sha256": sha256(SOURCE_BOOT),
    "boot_patched_sha256": sha256(patched_boot),
    "iso_sha256": sha256(OUTPUT_ISO),
    "output_iso": str(OUTPUT_ISO),
}
(STAGE / "stage34_summary.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=True, indent=2))
