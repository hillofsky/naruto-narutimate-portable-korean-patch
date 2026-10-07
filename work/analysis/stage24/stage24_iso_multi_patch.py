from pathlib import Path
import argparse
import importlib.util
import os
import sys
import traceback


BASE = Path(r"D:\narutimate portable")

S15 = (
    BASE
    / "analysis"
    / "stage15"
    / "stage15_iso_patcher.py"
)


def load_stage15():

    spec = importlib.util.spec_from_file_location(
        "stage15",
        S15
    )

    mod = importlib.util.module_from_spec(
        spec
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

    source_iso = args.source_iso.resolve()
    out_iso = args.output_iso.resolve()

    dat = args.dat.resolve()
    idx = args.idx.resolve()
    boot = args.boot.resolve()

    report = args.report_dir.resolve()

    report.mkdir(
        parents=True,
        exist_ok=True
    )


    for p in (
        source_iso,
        dat,
        idx,
        boot
    ):

        if not p.exists():
            raise RuntimeError(
                f"필수 파일 없음: {p}"
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


    targets = {
        "naruto.dat": (
            [
                "PSP_GAME",
                "USRDIR",
                "naruto.dat",
            ],
            dat
        ),

        "naruto.idx": (
            [
                "PSP_GAME",
                "USRDIR",
                "naruto.idx",
            ],
            idx
        ),

        "BOOT.BIN": (
            [
                "PSP_GAME",
                "SYSDIR",
                "BOOT.BIN",
            ],
            boot
        ),

        "EBOOT.BIN": (
            [
                "PSP_GAME",
                "SYSDIR",
                "EBOOT.BIN",
            ],
            boot
        ),
    }


    with out_iso.open(
        "r+b"
    ) as iso:

        descs = (
            s15.read_volume_descriptors(
                iso
            )
        )


        records = {
            name: []
            for name in targets
        }


        for vd in descs:

            if vd["type"] not in (
                1,
                2
            ):
                continue


            for name, (
                path_parts,
                src
            ) in targets.items():

                rec = s15.find_path(
                    iso,
                    vd,
                    path_parts
                )

                if rec is not None:
                    records[
                        name
                    ].append(
                        rec
                    )


        for name, recs in (
            records.items()
        ):

            if not recs:
                raise RuntimeError(
                    f"ISO 경로 없음: {name}"
                )


        print(
            "[ISO] DAT append"
        )

        dat_ext = (
            s15.append_file_sector_aligned(
                iso,
                dat,
                "naruto.dat"
            )
        )


        print(
            "[ISO] IDX append"
        )

        idx_ext = (
            s15.append_file_sector_aligned(
                iso,
                idx,
                "naruto.idx"
            )
        )


        print(
            "[ISO] patched raw ELF append"
        )

        elf_ext = (
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
                elf_ext,

            "EBOOT.BIN":
                elf_ext,
        }


        for name, recs in (
            records.items()
        ):

            ext = extents[
                name
            ]

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


        if final_size % s15.SECTOR:
            raise RuntimeError(
                "ISO size not sector aligned"
            )


        s15.update_volume_space(
            iso,
            descs,
            final_size
            // s15.SECTOR
        )


        iso.flush()


    validation = []


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


        for name, (
            path_parts,
            source
        ) in targets.items():

            rec = s15.find_path(
                iso,
                pvd,
                path_parts
            )

            if rec is None:
                raise RuntimeError(
                    f"검증 경로 없음: {name}"
                )


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
                and expected == actual
            )


            validation.append({
                "target":
                    name,

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
                    f"ISO 검증 실패: {name}"
                )


    s15.write_tsv(
        report
        / "stage24_iso_validation.tsv",
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
        / "stage24_iso_summary.txt"
    ).write_text(
        "\n".join([
            "Naruto PSP Stage 24 ISO",
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
                "BOOT.BIN / EBOOT.BIN "
                "use the same patched raw ELF extent."
            ),
        ]),
        encoding="utf-8"
    )


    print()
    print(
        "STAGE24 ISO VALIDATION: PASS"
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
