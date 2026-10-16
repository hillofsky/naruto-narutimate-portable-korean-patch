from pathlib import Path
import argparse
import importlib.util
import os
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")

STAGE15 = (
    BASE
    / "analysis"
    / "stage15"
    / "stage15_iso_patcher.py"
)


def load_stage15():
    spec = (
        importlib.util
        .spec_from_file_location(
            "stage15",
            STAGE15
        )
    )

    mod = (
        importlib.util
        .module_from_spec(spec)
    )

    spec.loader.exec_module(mod)

    return mod


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--source-iso",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--dat",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--idx",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--boot",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--output-iso",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--report-dir",
        type=Path,
        required=True
    )

    args = ap.parse_args()

    s15 = load_stage15()

    source_iso = (
        args.source_iso.resolve()
    )

    out_iso = (
        args.output_iso.resolve()
    )

    dat = args.dat.resolve()
    idx = args.idx.resolve()
    boot = args.boot.resolve()

    report = (
        args.report_dir.resolve()
    )

    report.mkdir(
        parents=True,
        exist_ok=True
    )

    if out_iso.exists():
        out_iso.unlink()

    print(
        "[ISO] 원본 복사"
    )

    s15.copy_iso(
        source_iso,
        out_iso
    )

    paths = {
        "naruto.dat": [
            "PSP_GAME",
            "USRDIR",
            "naruto.dat",
        ],

        "naruto.idx": [
            "PSP_GAME",
            "USRDIR",
            "naruto.idx",
        ],

        "BOOT.BIN": [
            "PSP_GAME",
            "SYSDIR",
            "BOOT.BIN",
        ],

        "EBOOT.BIN": [
            "PSP_GAME",
            "SYSDIR",
            "EBOOT.BIN",
        ],
    }

    replacements = {
        "naruto.dat":
            dat,

        "naruto.idx":
            idx,

        "BOOT.BIN":
            boot,

        "EBOOT.BIN":
            boot,
    }

    validation = []

    with out_iso.open(
        "r+b"
    ) as iso:

        descs = (
            s15.read_volume_descriptors(
                iso
            )
        )

        records = {
            k: []
            for k in paths
        }

        for vd in descs:
            if vd["type"] not in (
                1, 2
            ):
                continue

            for key, path in (
                paths.items()
            ):
                rec = s15.find_path(
                    iso,
                    vd,
                    path
                )

                if rec is not None:
                    records[key].append(
                        rec
                    )

        for key in paths:
            if not records[key]:
                raise RuntimeError(
                    f"ISO path 없음: "
                    f"{key}"
                )

        print(
            "[ISO] DAT 추가"
        )

        dat_ext = (
            s15.append_file_sector_aligned(
                iso,
                dat,
                "naruto.dat"
            )
        )

        print(
            "[ISO] IDX 추가"
        )

        idx_ext = (
            s15.append_file_sector_aligned(
                iso,
                idx,
                "naruto.idx"
            )
        )

        # One physical ELF extent is shared by
        # both BOOT.BIN and EBOOT.BIN.
        print(
            "[ISO] patched ELF 추가"
        )

        exe_ext = (
            s15.append_file_sector_aligned(
                iso,
                boot,
                "patched ELF"
            )
        )

        extents = {
            "naruto.dat":
                dat_ext,

            "naruto.idx":
                idx_ext,

            "BOOT.BIN":
                exe_ext,

            "EBOOT.BIN":
                exe_ext,
        }

        print(
            "[ISO] 디렉터리 레코드 갱신"
        )

        for key, recs in records.items():
            ext = extents[key]

            for rec in recs:
                s15.patch_directory_record(
                    iso,
                    rec["record_offset"],
                    ext["lba"],
                    ext["size"]
                )

        iso.seek(
            0,
            os.SEEK_END
        )

        final_size = iso.tell()

        if (
            final_size
            % s15.SECTOR
        ):
            raise RuntimeError(
                "ISO final size "
                "not sector aligned"
            )

        s15.update_volume_space(
            iso,
            descs,
            final_size
            // s15.SECTOR
        )

        iso.flush()

    # ========================================================
    # Re-open and verify all four paths.
    # ========================================================

    with out_iso.open(
        "rb"
    ) as iso:

        descs = (
            s15.read_volume_descriptors(
                iso
            )
        )

        pvd = next(
            x
            for x in descs
            if x["type"] == 1
        )

        for key, path in (
            paths.items()
        ):
            rec = s15.find_path(
                iso,
                pvd,
                path
            )

            if rec is None:
                raise RuntimeError(
                    f"검증 경로 없음: {key}"
                )

            source = replacements[
                key
            ]

            expected = (
                s15.sha256_file(
                    source
                )
            )

            actual = (
                s15.sha256_extent(
                    iso,
                    rec["extent"],
                    rec["size"]
                )
            )

            ok = (
                rec["size"]
                == source.stat().st_size
                and
                expected == actual
            )

            validation.append({
                "target":
                    key,

                "lba":
                    rec["extent"],

                "size":
                    rec["size"],

                "expected_sha256":
                    expected,

                "actual_sha256":
                    actual,

                "ok":
                    ok,
            })

            if not ok:
                raise RuntimeError(
                    f"ISO validation failed: "
                    f"{key}"
                )

    s15.write_tsv(
        report
        / "stage20_iso_validation.tsv",
        validation,
        [
            "target",
            "lba",
            "size",
            "expected_sha256",
            "actual_sha256",
            "ok",
        ]
    )

    (
        report
        / "stage20_iso_summary.txt"
    ).write_text(
        "\n".join([
            "Naruto PSP Stage20 ISO",
            "=" * 72,
            "",
            f"Output: {out_iso}",
            f"Size: {out_iso.stat().st_size}",
            "",
            "naruto.dat: PASS",
            "naruto.idx: PASS",
            "BOOT.BIN: PASS",
            "EBOOT.BIN: PASS",
            "",
            (
                "BOOT.BIN and EBOOT.BIN "
                "share the same patched ELF extent."
            ),
        ]),
        encoding="utf-8"
    )

    print()
    print(
        "STAGE20 ISO VALIDATION: PASS"
    )

    print(
        "Output:",
        out_iso
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
