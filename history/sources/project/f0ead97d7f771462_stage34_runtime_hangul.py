import base64
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


TRACER = Path(r"PROJECT_ROOT\analysis\stage33\stage33_trace_client.py")
OUT = Path(__file__).parent
FONT_BITMAP = 0x08BA0CB0
BYTES_PER_GLYPH = 162
SPECIAL_GLYPH_START = 0xD65
SPECIAL_COUNT = 0x146 // 2
CHARS = "한글테스트가나다라마"
NEXT_LINE = "うー…もうクタクタァ…。".encode("cp932")

spec = importlib.util.spec_from_file_location("stage33_trace_client", TRACER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.JSONL = OUT / "stage34_runtime_session.jsonl"


def read_bytes(client, address, size):
    response = client.request("memory.read", address=address, size=size)
    return base64.b64decode(response["base64"])


def write_bytes(client, address, data):
    response = client.request(
        "memory.write",
        address=address,
        base64=base64.b64encode(data).decode("ascii"),
    )
    if response.get("event") == "error":
        raise RuntimeError(response.get("message", "memory.write failed"))


def search_bytes(client, data):
    response = client.request(
        "memory.search",
        address=0x08800000,
        size=0x01800000,
        type="bytes",
        base64=base64.b64encode(data).decode("ascii"),
        align=1,
        maxResults=16,
    )
    return [int(address) for address in response.get("matches", [])]


def render_glyph(character, font):
    image = Image.new("L", (18, 18), 0)
    draw = ImageDraw.Draw(image)
    draw.text((1, -4), character, font=font, fill=255)
    values = [value // 17 for value in image.getdata()]
    packed = bytearray()
    for offset in range(0, len(values), 2):
        packed.append(values[offset] | (values[offset + 1] << 4))
    return bytes(packed), image


font = ImageFont.truetype(r"LOCAL_PATH", 16)
glyphs = []
preview = Image.new("L", (18 * len(CHARS), 18), 0)
for index, character in enumerate(CHARS):
    glyph, image = render_glyph(character, font)
    glyphs.append(glyph)
    preview.paste(image, (18 * index, 0))

glyph_blob = b"".join(glyphs)
glyph_index = SPECIAL_GLYPH_START + SPECIAL_COUNT - len(CHARS)
glyph_address = FONT_BITMAP + glyph_index * BYTES_PER_GLYPH
preview.resize((preview.width * 8, preview.height * 8), Image.Resampling.NEAREST).save(
    OUT / "stage34_hangul_preview.png"
)

ws = module.SimpleWebSocket("127.0.0.1", 26222)
ws.connect(timeout=15.0)
client = module.DebuggerClient(ws)

try:
    client.request("version", name="stage34-runtime-hangul", version="1.0")
    table = read_bytes(client, 0x08AE2910, 0x146)
    pairs = [table[index:index + 2] for index in range(len(table) - 20, len(table), 2)]
    line_matches = search_bytes(client, NEXT_LINE)
    if len(line_matches) != 1:
        raise RuntimeError(f"next dialogue match count: {len(line_matches)}")
    line_address = line_matches[0]

    original_glyphs = read_bytes(client, glyph_address, len(glyph_blob))
    original_line = read_bytes(client, line_address, len(NEXT_LINE) + 1)
    (OUT / "stage34_original_glyphs.bin").write_bytes(original_glyphs)
    (OUT / "stage34_original_line.bin").write_bytes(original_line)

    write_bytes(client, glyph_address, glyph_blob)
    encoded_test = b"".join(pairs[:5]) + b"\x00"
    write_bytes(client, line_address, encoded_test)

    report = {
        "font_bitmap": f"0x{FONT_BITMAP:08X}",
        "glyph_index_start": glyph_index,
        "glyph_address": f"0x{glyph_address:08X}",
        "characters": CHARS,
        "special_pairs": [pair.hex(" ") for pair in pairs],
        "dialogue_address": f"0x{line_address:08X}",
        "test_text": "한글테스트",
        "encoded_test": encoded_test.hex(" "),
    }
    (OUT / "stage34_runtime_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    client.request("input.buttons.press", button="circle", duration=2)
finally:
    client.close()
    ws.close()
