from pathlib import Path
import struct
import csv
import re
import hashlib
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage8"

SHARE = OUT / "share"
TBL_OUT = OUT / "decoded_tbl"

for p in [
    OUT,
    SHARE,
    TBL_OUT / "kr",
    TBL_OUT / "us",
]:
    p.mkdir(parents=True, exist_ok=True)

KR_IDX = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.idx"
)

KR_DAT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.dat"
)

US_DAT = (
    BASE / "us_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.dat"
)


def u32(data, off):
    return struct.unpack_from(
        "<I", data, off
    )[0]


def cstring(data, off):

    if off >= len(data):
        return ""

    end = data.find(b"\0", off)

    if end < 0:
        end = len(data)

    return data[off:end].decode(
        "ascii",
        errors="replace"
    )


# ============================================================
# PIDX
# ============================================================

def parse_pidx(index_path):

    data = index_path.read_bytes()

    if data[:5] != b"PIDX0":
        raise RuntimeError(
            f"PIDX0 아님: {index_path}"
        )

    (
        packs_off,
        packs,
        info_off,
        files,
        dummy,
        offset2,
        offset2_size,
        names_off,
        names_size,
    ) = struct.unpack_from(
        "<9I",
        data,
        4
    )

    names = data[
        names_off:
        names_off + names_size
    ]

    entries = []

    for i in range(files):

        off = info_off + i * 24

        (
            is_folder,
            name_off,
            pack_name_off,
            data_off,
            size,
            zsize,
        ) = struct.unpack_from(
            "<6I",
            data,
            off
        )

        entries.append({
            "entry": i,
            "is_folder": is_folder,
            "name": cstring(
                names,
                name_off
            ),
            "pack_name": cstring(
                names,
                pack_name_off
            ),
            "offset": data_off,
            "size": size,
            "zsize": zsize,
        })

    return entries


# ============================================================
# 저장 블롭 읽기
# ============================================================

def stored_size(e):

    if (
        e["zsize"]
        and e["zsize"] < e["size"]
    ):
        return e["zsize"]

    return e["size"]


def read_entry(dat, e):

    n = stored_size(e)

    with dat.open("rb") as f:

        f.seek(
            e["offset"]
        )

        return f.read(n)


# ============================================================
# Naruto " 3;x" codec
# ============================================================

def decode_3x(blob):

    if len(blob) < 8:

        raise RuntimeError(
            "3;x header too short"
        )

    if blob[:3] != b" 3;":

        return blob, "raw"

    typ = blob[3]

    expected = u32(
        blob,
        4
    )

    # --------------------------------------------
    # 3;0 = XOR 0x72 raw
    # --------------------------------------------

    if typ == ord("0"):

        out = bytes(
            x ^ 0x72
            for x in blob[8:]
        )

        if len(out) != expected:

            raise RuntimeError(
                f"3;0 size mismatch: "
                f"{len(out)} != {expected}"
            )

        return out, "3;0"

    # --------------------------------------------
    # 3;1 = XOR 0x72 + LZSS
    # --------------------------------------------

    if typ != ord("1"):

        raise RuntimeError(
            f"unsupported 3;x type: "
            f"{chr(typ)!r}"
        )

    window = bytearray(
        0x1000
    )

    # game code:
    # ring position = 0xFEE
    r = 0xFEE

    src = 8
    flags = 0

    out = bytearray()

    while (
        src < len(blob)
        and len(out) < expected
    ):

        flags >>= 1

        if (
            flags & 0x100
        ) == 0:

            if src >= len(blob):
                break

            flags = (
                (blob[src] ^ 0x72)
                | 0xFF00
            )

            src += 1

        # literal
        if flags & 1:

            if src >= len(blob):
                break

            c = (
                blob[src]
                ^ 0x72
            )

            src += 1

            out.append(c)

            window[r] = c

            r = (
                r + 1
            ) & 0xFFF

        # back reference
        else:

            if src + 1 >= len(blob):
                break

            b1 = (
                blob[src]
                ^ 0x72
            )

            b2 = (
                blob[src + 1]
                ^ 0x72
            )

            src += 2

            pos = (
                b1
                |
                (
                    (b2 & 0xF0)
                    << 4
                )
            )

            length = (
                (b2 & 0x0F)
                + 3
            )

            for j in range(length):

                c = window[
                    (pos + j)
                    & 0xFFF
                ]

                out.append(c)

                window[r] = c

                r = (
                    r + 1
                ) & 0xFFF

                if len(out) >= expected:
                    break

    if len(out) != expected:

        raise RuntimeError(
            f"3;1 size mismatch: "
            f"{len(out)} != {expected}"
        )

    return bytes(out), "3;1"


# ============================================================
# 보조
# ============================================================

def safe_name(name):

    return (
        name
        .replace("\\", "__")
        .replace("/", "__")
        .replace(":", "_")
    )


def sha256(data):

    return hashlib.sha256(
        data
    ).hexdigest()


def decode_tbl(data, region):

    if region == "KR":

        return data.decode(
            "cp932",
            errors="replace"
        )

    # US 파일에도 일본어 주석 존재
    return data.decode(
        "cp932",
        errors="replace"
    )


def write_tsv(path, rows, fields):

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
            quoting=csv.QUOTE_MINIMAL
        )

        w.writeheader()

        for r in rows:

            w.writerow({
                k: r.get(k, "")
                for k in fields
            })


def flat_text(s):

    return (
        s
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", " ")
    )


# ============================================================
# manifest
# ============================================================

kr_entries = parse_pidx(
    KR_IDX
)

us_entries = parse_pidx(
    US_DAT
)

regions = {
    "KR": (
        KR_DAT,
        kr_entries
    ),
    "US": (
        US_DAT,
        us_entries
    ),
}

print("=" * 72)
print("Naruto PSP Stage 8")
print("3;x decoder + translation extraction")
print("=" * 72)

print(
    "KR entries:",
    len(kr_entries)
)

print(
    "US entries:",
    len(us_entries)
)


# ============================================================
# 3;x 전체 헤더 조사
# 데이터 전체를 풀지 않고 8바이트만 읽음
# ============================================================

type_rows = []

for region, (
    dat,
    entries
) in regions.items():

    with dat.open("rb") as f:

        for e in entries:

            if e["is_folder"] != 0:
                continue

            n = stored_size(e)

            if n < 8:
                continue

            f.seek(
                e["offset"]
            )

            head = f.read(8)

            if head[:3] != b" 3;":
                continue

            type_rows.append({
                "region": region,
                "entry": e["entry"],
                "name": e["name"],
                "type":
                    chr(head[3]),
                "stored_size": n,
                "expected_size":
                    u32(head, 4),
            })

write_tsv(
    OUT / "three_x_containers.tsv",
    type_rows,
    [
        "region",
        "entry",
        "name",
        "type",
        "stored_size",
        "expected_size",
    ]
)


# ============================================================
# TBL 전부 디코드
# ============================================================

tbl_data = {
    "KR": {},
    "US": {},
}

validation = []

for region, (
    dat,
    entries
) in regions.items():

    for e in entries:

        if (
            e["is_folder"] != 0
            or not e["name"].lower()
                .endswith(".tbl")
        ):
            continue

        blob = read_entry(
            dat,
            e
        )

        decoded, mode = (
            decode_3x(blob)
        )

        text = decode_tbl(
            decoded,
            region
        )

        tbl_data[
            region
        ][e["name"].lower()] = {
            "entry": e,
            "data": decoded,
            "text": text,
            "mode": mode,
        }

        out = (
            TBL_OUT
            / region.lower()
            / safe_name(e["name"])
        )

        out.write_bytes(
            decoded
        )

        validation.append({
            "region": region,
            "entry": e["entry"],
            "name": e["name"],
            "mode": mode,
            "stored_size":
                len(blob),
            "decoded_size":
                len(decoded),
            "expected_size":
                (
                    u32(blob,4)
                    if blob[:3]
                    == b" 3;"
                    else len(decoded)
                ),
            "sha256":
                sha256(decoded),
        })


# ============================================================
# TBL 대응 요약
# ============================================================

tbl_names = sorted(
    set(tbl_data["KR"])
    | set(tbl_data["US"])
)

tbl_pairs = []

for name in tbl_names:

    k = tbl_data[
        "KR"
    ].get(name)

    u = tbl_data[
        "US"
    ].get(name)

    tbl_pairs.append({
        "name": name,

        "kr_present":
            bool(k),

        "us_present":
            bool(u),

        "kr_size":
            len(k["data"])
            if k else "",

        "us_size":
            len(u["data"])
            if u else "",

        "kr_entry":
            k["entry"]["entry"]
            if k else "",

        "us_entry":
            u["entry"]["entry"]
            if u else "",
    })

write_tsv(
    OUT / "tbl_pair_summary.tsv",
    tbl_pairs,
    [
        "name",
        "kr_present",
        "us_present",
        "kr_size",
        "us_size",
        "kr_entry",
        "us_entry",
    ]
)


# ============================================================
# event MSG 자동 대응
# ============================================================

def parse_msgs(text):

    rows = []

    for order, line in enumerate(
        text.splitlines()
    ):

        if not line.startswith(
            "MSG ="
        ):
            continue

        body = line[5:]

        parts = body.split(
            ",",
            2
        )

        if len(parts) < 3:
            continue

        speaker = parts[0]
        msgid = parts[1]
        message = parts[2]

        rows.append({
            "order": order,
            "speaker": speaker,
            "msg_id": msgid,
            "text": message,
        })

    return rows


event_rows = []

event_names = sorted(
    n
    for n in tbl_names
    if re.fullmatch(
        r"event\d+\.tbl",
        n
    )
)

for name in event_names:

    kr = tbl_data[
        "KR"
    ].get(name)

    us = tbl_data[
        "US"
    ].get(name)

    if not kr or not us:
        continue

    km = parse_msgs(
        kr["text"]
    )

    um = parse_msgs(
        us["text"]
    )

    # 우선 msg_id 기준
    u_by_id = {}

    for m in um:

        if m["msg_id"]:

            u_by_id.setdefault(
                m["msg_id"],
                []
            ).append(m)

    used = set()

    for i, k in enumerate(km):

        u = None

        if (
            k["msg_id"]
            and k["msg_id"]
            in u_by_id
        ):

            for candidate in (
                u_by_id[
                    k["msg_id"]
                ]
            ):

                key = id(candidate)

                if key not in used:

                    u = candidate
                    used.add(key)
                    break

        # ID 없는 메시지는 순서 보조
        if (
            u is None
            and i < len(um)
        ):

            candidate = um[i]

            key = id(candidate)

            if key not in used:

                u = candidate
                used.add(key)

        event_rows.append({
            "file": name,
            "sequence": i,

            "msg_id":
                k["msg_id"],

            "speaker_jp":
                k["speaker"],

            "speaker_en":
                u["speaker"]
                if u else "",

            "japanese":
                flat_text(
                    k["text"]
                ),

            "english":
                flat_text(
                    u["text"]
                )
                if u else "",
        })

write_tsv(
    OUT / "event_dialogue_pairs.tsv",
    event_rows,
    [
        "file",
        "sequence",
        "msg_id",
        "speaker_jp",
        "speaker_en",
        "japanese",
        "english",
    ]
)


# ============================================================
# quiz 대응
# ============================================================

def parse_hash_keys(text):

    result = {}

    for line in text.splitlines():

        m = re.match(
            r"^\s*#([^=]+?)\s*=(.*)$",
            line
        )

        if not m:
            continue

        result[
            m.group(1).strip()
        ] = m.group(2).strip()

    return result


quiz_rows = []

for name in (
    "quiz1.tbl",
    "quiz2.tbl",
):

    kr = tbl_data[
        "KR"
    ].get(name)

    us = tbl_data[
        "US"
    ].get(name)

    if not kr or not us:
        continue

    k = parse_hash_keys(
        kr["text"]
    )

    u = parse_hash_keys(
        us["text"]
    )

    keys = sorted(
        set(k) | set(u),
        key=lambda x: (
            len(x),
            x
        )
    )

    for key in keys:

        quiz_rows.append({
            "file": name,
            "key": key,

            "japanese":
                flat_text(
                    k.get(
                        key,
                        ""
                    )
                ),

            "english":
                flat_text(
                    u.get(
                        key,
                        ""
                    )
                ),
        })

write_tsv(
    OUT / "quiz_pairs.tsv",
    quiz_rows,
    [
        "file",
        "key",
        "japanese",
        "english",
    ]
)


# ============================================================
# US text*.bin
# ============================================================

lang_names = {
    "en": "text.bin",
    "fr": "text_f.bin",
    "de": "text_g.bin",
    "it": "text_i.bin",
    "es": "text_s.bin",
}

us_by_name = {
    e["name"].lower(): e
    for e in us_entries
    if e["is_folder"] == 0
}

text_bins = {}

text_meta = {}

for lang, name in (
    lang_names.items()
):

    e = us_by_name.get(
        name
    )

    if e is None:
        raise RuntimeError(
            f"US {name} 없음"
        )

    blob = read_entry(
        US_DAT,
        e
    )

    decoded, mode = (
        decode_3x(blob)
    )

    table_size = u32(
        decoded,
        0
    )

    if (
        table_size % 4
        or table_size
        > len(decoded)
    ):

        raise RuntimeError(
            f"{name}: "
            "invalid pointer table"
        )

    count = (
        table_size // 4
    )

    ptrs = [
        u32(
            decoded,
            i * 4
        )
        for i in range(count)
    ]

    strings = []

    for ptr in ptrs:

        if ptr >= len(decoded):

            strings.append(
                b""
            )

            continue

        end = decoded.find(
            b"\0",
            ptr
        )

        if end < 0:
            end = len(decoded)

        strings.append(
            decoded[
                ptr:end
            ]
        )

    text_bins[lang] = (
        ptrs,
        strings,
        decoded
    )

    text_meta[lang] = {
        "file": name,
        "count": count,
        "table_size":
            table_size,
        "decoded_size":
            len(decoded),
        "mode": mode,
    }

    validation.append({
        "region": "US",
        "entry": e["entry"],
        "name": name,
        "mode": mode,
        "stored_size":
            len(blob),
        "decoded_size":
            len(decoded),
        "expected_size":
            u32(blob,4),
        "sha256":
            sha256(decoded),
    })


counts = {
    meta["count"]
    for meta
    in text_meta.values()
}

if len(counts) != 1:

    raise RuntimeError(
        f"text.bin slot counts differ: "
        f"{counts}"
    )

slot_count = next(
    iter(counts)
)


def decode_western(raw):

    return raw.decode(
        "cp1252",
        errors="replace"
    )


text_rows = []

for i in range(slot_count):

    row = {
        "id": i
    }

    for lang in (
        "en",
        "fr",
        "de",
        "it",
        "es",
    ):

        ptrs, strings, data = (
            text_bins[lang]
        )

        row[
            f"{lang}_offset"
        ] = f"0x{ptrs[i]:X}"

        row[lang] = flat_text(
            decode_western(
                strings[i]
            )
        )

    text_rows.append(row)


write_tsv(
    OUT / "text_multilang.tsv",
    text_rows,
    [
        "id",

        "en_offset",
        "en",

        "fr_offset",
        "fr",

        "de_offset",
        "de",

        "it_offset",
        "it",

        "es_offset",
        "es",
    ]
)


# ============================================================
# 검증
# ============================================================

write_tsv(
    OUT / "codec_validation.tsv",
    validation,
    [
        "region",
        "entry",
        "name",
        "mode",
        "stored_size",
        "decoded_size",
        "expected_size",
        "sha256",
    ]
)


# ============================================================
# 공유용 파일
# ============================================================

share_targets = [
    ("KR", "event000.tbl"),
    ("US", "event000.tbl"),

    ("KR", "event100.tbl"),
    ("US", "event100.tbl"),

    ("KR", "quiz1.tbl"),
    ("US", "quiz1.tbl"),
]

for region, name in share_targets:

    obj = tbl_data[
        region
    ].get(name)

    if not obj:
        continue

    (
        SHARE
        / f"{region}__{name}"
    ).write_bytes(
        obj["data"]
    )


# English decoded text.bin
(
    SHARE / "US__text.bin.dec"
).write_bytes(
    text_bins[
        "en"
    ][2]
)


# ============================================================
# Codec notes
# ============================================================

notes = r"""Naruto PSP " 3;x" container codec

Header:
  +0x00 4 bytes  " 3;0" or " 3;1"
  +0x04 u32 LE   decompressed size
  +0x08          payload

Type 0:
  output = payload XOR 0x72

Type 1:
  XOR 0x72 is applied to every compressed-stream byte.
  LZSS window size = 0x1000
  initial ring write position = 0xFEE
  initial dictionary bytes before 0xFEE = 0

Flags:
  flags are processed LSB first.
  when exhausted:
      flags = (next_byte XOR 0x72) | 0xFF00

flag bit 1:
  literal byte

flag bit 0:
  two-byte match token after XOR:
      offset = b1 | ((b2 & 0xF0) << 4)
      length = (b2 & 0x0F) + 3

US BOOT:
  parser      0x0005F240
  size reader 0x0005F304
  dispatcher  0x0005F374
  type 0      0x0005F460
  type 1      0x0005F594

KR corresponding engine code:
  size reader 0x0021C4E4
  type 0      0x0021C640
  type 1      0x0021C774
"""

(
    OUT / "codec_notes.txt"
).write_text(
    notes,
    encoding="utf-8"
)


# ============================================================
# Summary
# ============================================================

type_counts = {}

for r in type_rows:

    key = (
        r["region"],
        r["type"]
    )

    type_counts[key] = (
        type_counts.get(
            key,
            0
        ) + 1
    )


summary = (
    OUT / "stage8_summary.txt"
)

with summary.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "Naruto PSP Stage 8\n"
    )

    f.write(
        "=" * 72
        + "\n\n"
    )

    f.write(
        f"KR PIDX entries: "
        f"{len(kr_entries)}\n"
    )

    f.write(
        f"US PIDX entries: "
        f"{len(us_entries)}\n"
    )

    f.write(
        f"3;x containers: "
        f"{len(type_rows)}\n"
    )

    for key in sorted(
        type_counts
    ):

        f.write(
            f"  {key[0]} "
            f"type {key[1]}: "
            f"{type_counts[key]}\n"
        )

    f.write("\n")

    f.write(
        f"KR TBL files: "
        f"{len(tbl_data['KR'])}\n"
    )

    f.write(
        f"US TBL files: "
        f"{len(tbl_data['US'])}\n"
    )

    f.write(
        f"Event dialogue pairs: "
        f"{len(event_rows)}\n"
    )

    f.write(
        f"Quiz pairs: "
        f"{len(quiz_rows)}\n"
    )

    f.write(
        f"text.bin slot count: "
        f"{slot_count}\n\n"
    )

    for lang in (
        "en",
        "fr",
        "de",
        "it",
        "es"
    ):

        meta = text_meta[lang]

        empty = sum(
            1
            for x in
            text_bins[
                lang
            ][1]
            if not x
        )

        f.write(
            f"{lang}: "
            f"size={meta['decoded_size']} "
            f"slots={meta['count']} "
            f"empty={empty}\n"
        )

    f.write("\n")

    f.write(
        "Generated translation datasetLOCAL_PATH"
    )

    f.write(
        " event_dialogue_pairs.tsv\n"
    )

    f.write(
        " quiz_pairs.tsv\n"
    )

    f.write(
        " text_multilang.tsv\n"
    )


print()
print("=" * 72)
print("STAGE 8 COMPLETE")
print("=" * 72)

print(
    "3;x containers :",
    len(type_rows)
)

print(
    "KR TBL         :",
    len(tbl_data["KR"])
)

print(
    "US TBL         :",
    len(tbl_data["US"])
)

print(
    "Event pairs    :",
    len(event_rows)
)

print(
    "Quiz pairs     :",
    len(quiz_rows)
)

print(
    "text.bin slots :",
    slot_count
)

print(
    "Output         :",
    OUT
)
