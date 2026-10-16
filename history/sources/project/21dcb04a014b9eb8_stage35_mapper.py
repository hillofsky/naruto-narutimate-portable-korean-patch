from pathlib import Path
import json


class NarutoHangulMapper:
    def __init__(self, mapping_json):
        path = Path(mapping_json)

        self.mapping = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        self.char_to_bytes = {
            ch: bytes.fromhex(
                info["sjis_hex"]
            )
            for ch, info
            in self.mapping.items()
        }

    def encode_text(self, text):
        out = bytearray()

        for ch in text:
            custom = self.char_to_bytes.get(ch)

            if custom is not None:
                out.extend(custom)
                continue

            try:
                out.extend(
                    ch.encode(
                        "cp932",
                        errors="strict",
                    )
                )
            except UnicodeEncodeError as exc:
                raise UnicodeEncodeError(
                    exc.encoding,
                    exc.object,
                    exc.start,
                    exc.end,
                    (
                        "character not present in "
                        "Stage35 custom mapping: "
                        f"{ch!r} U+{ord(ch):04X}"
                    ),
                )

        return bytes(out)

    def encode_tbl_file(
        self,
        source_utf8,
        destination,
    ):
        source_utf8 = Path(source_utf8)
        destination = Path(destination)

        text = source_utf8.read_text(
            encoding="utf-8-sig"
        )

        raw = self.encode_text(text)

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_bytes(raw)
        return destination
