# 작업 이력 탐색

기록일: 2026-10-16. 아래 단계명은 파일명에서 추출한 **탐색용 분류**이며 실행 순서나 최신 성공 빌드를 뜻하지 않는다. 원문 보고서의 상태는 당시 결과다. 현재 기준은 PROJECT_STATE.md와 배포 manifest다.

대조 후보 1,779건: SANITIZED_ARCHIVE 577, ALREADY_PRESENT 531, DUPLICATE_ARCHIVED 666, WITHHELD_EXTERNAL_DEPENDENCY 5.

[전체 대조 목록](HISTORY_INVENTORY.json), [함수·import 탐색](SOURCE_MAP.json), [확인된 지식과 실패 기록](KNOWLEDGE_LEDGER.md)을 함께 읽는다.

공개된 history/는 개인 경로를 치환하고 큰 payload/민감 필드를 제외한 기록용 사본이다. **그대로 실행하거나 과거 인계 지시를 현재 지시로 적용하지 않는다.** 원본 SHA-256과 공개본 해시를 대조 목록에 구분했다.

| 분류 | 후보 수 | 보고서에 적힌 상태 (일부) | 근거 예시 |
|---|---:|---|---|
| OTHER | 213 | 명시 없음/코드만 있음 | [note](../history/evidence/project/d6ec3cb88c88b5e3_Naruto_PSP_translation_handoff_READM.md) · [note](../history/evidence/project/8251a2379256a6cf_SUMMARY.txt) |
| STAGE2 | 3 | 명시 없음/코드만 있음 | [source](../history/sources/project/b419b79acd728eb7_analyze_naruto_stage2.ps1) · [source](../history/sources/project/2d3bec223fee3415_organize_stage2.ps1) |
| STAGE3 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/dad988003d3f0612_analyze_naruto_stage3.ps1) · [source](../history/sources/project/79ef65917ae480c4_pidx_stage3.py) |
| STAGE4 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/cd95753d6a648b09_analyze_naruto_stage4.ps1) · [source](../history/sources/project/7512c8d0da833bb0_stage4_code_scan.py) |
| STAGE5 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/52994e0e8bdc539d_analyze_naruto_stage5.ps1) · [source](../history/sources/project/d2158776ba9242fc_stage5_mips_trace.py) |
| STAGE6 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/21b37d07fe2420cd_analyze_naruto_stage6.ps1) · [source](../history/sources/project/1e9b922fc180b3b0_stage6_pidx_trace.py) |
| STAGE7 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/9450ccf5d5a104ed_analyze_naruto_stage7.ps1) · [source](../history/sources/project/4e65c7905b4706f5_stage7_loader_trace.py) |
| STAGE8 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/dcde0ad302226a77_analyze_naruto_stage8.ps1) · [source](../history/sources/project/55e2e2df33c1177a_stage8_extract_text.py) |
| STAGE9 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/b87ac47d9ba21f99_analyze_naruto_stage9.ps1) · [source](../history/sources/project/57bec66116835eb1_stage9_full_extract.py) |
| STAGE10 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/30908a25dd3b76b7_analyze_naruto_stage10.ps1) · [source](../history/sources/project/b0bca8559dc21926_stage10_offset2.py) |
| STAGE11 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/f81fa0b296d90b68_analyze_naruto_stage11.ps1) · [source](../history/sources/project/f42feb0c42649939_stage11_fsts_map.py) |
| STAGE12 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/c862c761226b1362_analyze_naruto_stage12.ps1) · [source](../history/sources/project/52141d06ed39268d_stage12_storage_verify.py) |
| STAGE13 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/cfd9cfb48d2e443f_analyze_naruto_stage13.ps1) · [source](../history/sources/project/5edef029fe20a90c_stage13_roundtrip_rebuild.py) |
| STAGE14 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/0f98b7a08f22a979_run_naruto_stage14.ps1) · [source](../work/analysis/stage14/naruto_patcher.py) |
| STAGE15 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/82226e6d2c35dca3_run_naruto_stage15.ps1) · [source](../work/analysis/stage15/stage15_iso_patcher.py) |
| STAGE16 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/41d2637fea80bfd1_run_naruto_stage16.ps1) · [source](../history/sources/project/5ef0f53b23d64f2b_stage16_make_text_probe.py) |
| STAGE17 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/d60c55d1d45b1f86_run_naruto_stage17.ps1) · [source](../history/sources/project/779e95e4726afe6b_stage17_font_engine.py) |
| STAGE18 | 3 | 명시 없음/코드만 있음 | [source](../history/sources/project/9e240fc5233fa68a_run_naruto_stage18.ps1) · [source](../history/sources/project/c87439ed6cd6041f_stage18_font_trace.py) |
| STAGE19 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/fe806d243b81e0cd_run_naruto_stage19.ps1) · [source](../history/sources/project/df406e23ab44146b_stage19_converter_reverse.py) |
| STAGE20 | 3 | 명시 없음/코드만 있음 | [source](../history/sources/project/37e335affc34e6e2_run_naruto_stage20.ps1) · [source](../history/sources/project/84a5fbec8124e2ad_stage20_hangul_map.py) |
| STAGE21 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/b37ca4e5bd11b0bb_run_naruto_stage21.ps1) · [source](../history/sources/project/d484c26503c44987_stage21_trace_runtime_tables.py) |
| STAGE22 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/f3c5cd5c7d840b10_run_naruto_stage22.ps1) · [source](../history/sources/project/c0e9bdec3e54db14_stage22_probe_cptbl.py) |
| STAGE23 | 5 | 명시 없음/코드만 있음 | [source](../history/sources/project/ca6f84ff617fd7fe_run_naruto_stage23.ps1) · [source](../history/sources/project/14e2c7454ffef6eb_fix_stage23_loader_gap.py) |
| STAGE24 | 7 | 명시 없음/코드만 있음 | [source](../history/sources/project/279c48dd5c3a8309_repair_and_run_stage24.ps1) · [source](../history/sources/project/98dd579535dfdb0d_run_stage24_clean.ps1) |
| STAGE25 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/56b902b22f8a7be0_run_stage25_data_cave.ps1) · [source](../history/sources/project/3a4ac2719f849b64_stage25_driver.py) |
| STAGE26 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/5db1daa6964c275a_run_stage26_final_unicode_hook.ps1) · [source](../history/sources/project/a8cb26609eaedc02_stage26_final_unicode_hook.py) |
| STAGE27 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/e2ee11b4474f1c1c_run_stage27_font_diagnostic.ps1) · [source](../history/sources/project/f28624aec637e2eb_stage27_renderer_diagnostic.py) |
| STAGE28 | 3 | 명시 없음/코드만 있음 | [source](../history/sources/project/2a22eeddea046089_fix_and_run_stage28.ps1) · [source](../history/sources/project/5a145c5991c28da0_run_stage28_immediate_unicode_diag.ps1) |
| STAGE29 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/edc3a88a938aa5d4_run_stage29_utf16_buffer_hook.ps1) · [source](../history/sources/project/926bffd27d014d64_stage29_utf16_buffer_hook.py) |
| STAGE30 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/4a8e0813faefcb6b_run_stage30_utf16_introspection.ps1) · [source](../history/sources/project/1a71b9d561b2b03e_stage30_utf16_introspection.py) |
| STAGE31 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/478f3470296a32f1_run_stage31_text_hook.ps1) · [source](../history/sources/project/5fa51bad7cf8676d_stage31_text_hook.py) |
| STAGE32 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/0196468f93901bbf_run_stage32_split_diagnostic.ps1) · [source](../history/sources/project/860b0605ce2fdef8_stage32_split_diagnostic.py) |
| STAGE33 | 6 | 명시 없음/코드만 있음 | [report](../history/evidence/project/37b6e01ec1d13855_asset-manifest.json) · [report](../history/evidence/project/063d947d4301e1a2_manifest.json) |
| STAGE34 | 3 | 명시 없음/코드만 있음 | [report](../history/evidence/project/3e5b5b6d32573458_stage34_summary.json) · [source](../history/sources/project/23bc2a8e4049ed2e_stage34_build_test.py) |
| STAGE35 | 16 | status=ANALYSIS_ONLY | [report](../history/evidence/project/0e1a5487a25e9408_stage35_summary.json) · [report](../history/evidence/project/d62a23cf875f0e10_stage35r_summary.json) |
| STAGE35R | 3 | status=ANALYSIS_ONLY | [report](../history/evidence/project/d62a23cf875f0e10_stage35r_summary.json) · [source](../history/sources/project/b8132b9237f7099a_run_stage35r_allocator_fix.ps1) |
| STAGE36 | 3 | 명시 없음/코드만 있음 | [report](../history/evidence/project/68d1d84aae4ef4f2_stage36_summary.json) · [source](../history/sources/project/ea9bc74b312e1b1a_run_stage36_standard_donor_smoke.ps1) |
| STAGE36R | 3 | 명시 없음/코드만 있음 | [report](../history/evidence/project/3c91ff5f7055f1b1_stage36r_summary.json) · [source](../history/sources/project/6f7e0d425904c7b1_run_stage36r_low_standard_donor.ps1) |
| STAGE37 | 17 | 명시 없음/코드만 있음 | [note](../history/evidence/project/bafbf34f2f11f188_SUMMARY.txt) · [note](../history/evidence/project/1223483bac464af9_SUMMARY.txt) |
| STAGE37B | 3 | status=MULTIPART_FRAME_EXTRACTION_COMPLETE | [report](../history/evidence/project/cbe16d906551201f_stage37b_summary.json) · [source](../history/sources/project/ebc67878c0597fa2_run_stage37b_multipart_merge.ps1) |
| STAGE38A | 17 | 명시 없음/코드만 있음 | [report](../history/evidence/project/f2791cebf91389e8_stage38a_summary.json) · [report](../history/evidence/project/b1155042645b9e32_persistent30_summary.json) |
| STAGE38B | 6 | 명시 없음/코드만 있음 | [note](../history/evidence/project/66205436a0db3736_SUMMARY.txt) · [source](../history/sources/project/e73d11a665c35e5c_run_naruto_stage38b.ps1) |
| STAGE38C | 4 | 명시 없음/코드만 있음 | [note](../history/evidence/project/4a09d51c45166ba1_SUMMARY.txt) · [source](../history/sources/project/a093bf4e075d5b3b_run_naruto_stage38c_30.ps1) |
| STAGE38D | 2 | 명시 없음/코드만 있음 | [note](../history/evidence/project/a98c2f4afef4de7c_SUMMARY.txt) · [source](../history/sources/project/2218c4264cf1d5af_run_naruto_stage38d_prompt_ab.ps1) |
| STAGE38E | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/0e2704ee70f31280_SUMMARY.txt) · [source](../history/sources/project/73441376e241948f_run_naruto_stage38e_full_ocr.ps1) |
| STAGE38F | 2 | 명시 없음/코드만 있음 | [note](../history/evidence/project/69bbc2c6f495d87e_SUMMARY.txt) · [source](../history/sources/project/25070037c6b5bb0f_run_naruto_stage38f_movie_inventory.ps1) |
| SUB1 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/e39a5d98da4858b7_SUMMARY.txt) · [source](../work/naruto_sub01_ocr_cleanup.py) |
| SUB2 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/23b34ba7b10c49c5_SUMMARY.txt) · [source](../work/naruto_sub02_visual_review.py) |
| SUB3 | 5 | 명시 없음/코드만 있음 | [note](../history/evidence/project/56eaee4a2610cefb_SUMMARY.txt) · [source](../work/naruto_sub03_sequence_timeline.py) |
| SUB4 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/110579a2c8f36911_SUMMARY.txt) · [source](../work/naruto_sub04_rare_ocr_review.py) |
| SUB5 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/dabe1a34b319bc49_SUMMARY.txt) · [source](../work/naruto_sub05_corrected_anchors.py) |
| SUB6 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/5e1b97ec1824bccb_SUMMARY.txt) · [source](../work/naruto_sub06_common_ocr_review.py) |
| SUB7 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/84246ae7cf427652_SUMMARY.txt) · [source](../work/naruto_sub07_final_corpus.py) |
| SUB8 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/fc20e501f814f2ad_SUMMARY.txt) · [source](../work/naruto_sub08_speaker_audit.py) |
| SUB9 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/718322f48b9665de_SUMMARY.txt) · [source](../work/naruto_sub09_final_speaker_corpus.py) |
| SUB10 | 15 | status=ANALYSIS_ONLY | [report](../history/evidence/project/2044e9c8218fb4f7_sub10_mapping_manifest.json) · [report](../history/evidence/project/d62a23cf875f0e10_stage35r_summary.json) |
| SUB11 | 18 | status=ANALYSIS_ONLY | [report](../history/evidence/project/3e5b5b6d32573458_stage34_summary.json) · [report](../history/evidence/project/0e1a5487a25e9408_stage35_summary.json) |
| SUB12 | 8 | 명시 없음/코드만 있음 | [report](../history/evidence/project/b45258bc00ba58db_sub12_build_report.json) · [note](../history/evidence/project/db6851c1a254a4c0_SUMMARY.txt) |
| SUB13 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/55ea6c9d7d7f01a6_sub13_build_report.json) · [note](../history/evidence/project/9a459b022201994a_SUMMARY.txt) |
| SUB14 | 6 | 명시 없음/코드만 있음 | [report](../history/evidence/project/508e3a43b2d0c7d7_sub14_report.json) · [note](../history/evidence/project/fab73eba46fa0c7b_SUMMARY.txt) |
| SUB15 | 12 | 명시 없음/코드만 있음 | [report](../history/evidence/project/e55f66c38d29f97b_sub15_report.json) · [note](../history/evidence/project/f5aca3bbc9c70bcb_SUMMARY.txt) |
| SUB16 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/e4355d218fe4d444_sub16_report.json) · [note](../history/evidence/project/a6cd882f84400f56_SUMMARY.txt) |
| SUB17 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/069d16969cb36bb5_sub17_build_report.json) · [note](../history/evidence/project/7cf87960087aab4a_SUMMARY.txt) |
| SUB18 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/738e1a82b7169a3b_sub18_report.json) · [note](../history/evidence/project/f43475e54c412e23_SUMMARY.txt) |
| SUB18 FIX1 | 343 | 명시 없음/코드만 있음 | [source](../work/naruto_sub18_fix1_decode_discovery.py) · [source](../work/run_naruto_sub18_fix1_decode_discovery.ps1) |
| SUB18 FIX2 | 4 | 명시 없음/코드만 있음 | [source](../work/naruto_sub18_fix2_decode_discovery.py) · [source](../work/run_naruto_sub18_fix2_decode_discovery.ps1) |
| SUB18 FIX3 | 284 | 명시 없음/코드만 있음 | [report](../history/evidence/project/2e221aa732013899_sub18_fix1_report.json) · [note](../history/evidence/project/75597770b3e9eb91_SUMMARY.txt) |
| SUB19 | 2 | 명시 없음/코드만 있음 | [source](../work/naruto_sub19_decoded_event_inventory.py) · [source](../work/run_naruto_sub19_decoded_event_inventory.ps1) |
| SUB19 FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/fb8e117c59b8dda3_sub19_fix1_report.json) · [note](../history/evidence/project/7480ea6829cee38d_SUMMARY.txt) |
| SUB20 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/531918fe46ac4086_sub20_report.json) · [note](../history/evidence/project/a462b393e92a9679_SUMMARY.txt) |
| SUB20 FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/8cb2aec2658d2314_sub20_report.json) · [note](../history/evidence/project/bf2cea8f8fac34ff_SUMMARY.txt) |
| SUB21 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/44dc4a81441e6c10_sub21_report.json) · [note](../history/evidence/project/35c3cdb280c9e535_SUMMARY.txt) |
| SUB22 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/0a62df87d861a86a_sub22_report.json) · [note](../history/evidence/project/b9ae6af06df7dd34_SUMMARY.txt) |
| SUB23 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/ffbadaddccee2bc4_sub23_report.json) · [note](../history/evidence/project/61bffb07e0a8e1f4_SUMMARY.txt) |
| SUB24 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/21218695f607a379_sub24_report.json) · [note](../history/evidence/project/c3fe1363ca90b60d_SUMMARY.txt) |
| SUB25 | 2 | 명시 없음/코드만 있음 | [source](../work/naruto_sub25_voice_timeline_reconstruction.py) · [source](../work/run_naruto_sub25_voice_timeline_reconstruction.ps1) |
| SUB25 FIX1 | 2 | 명시 없음/코드만 있음 | [source](../work/naruto_sub25_fix1_voice_timeline_reconstruction.py) · [source](../work/run_naruto_sub25_fix1_voice_timeline_reconstruction.ps1) |
| SUB25 FIX2 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/3a975cfa090708a5_sub25_fix2_report.json) · [note](../history/evidence/project/f951a0300f3c9c04_SUMMARY.txt) |
| SUB26 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/2ffb5c43abaa9e5c_sub26_report.json) · [note](../history/evidence/project/38eb723bae13097c_SUMMARY.txt) |
| SUB27 | 2 | 명시 없음/코드만 있음 | [source](../work/naruto_sub27_semantic_topology_resolution.py) · [source](../work/run_naruto_sub27_semantic_topology_resolution.ps1) |
| SUB27 FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/0f974768e863ccca_sub27_report.json) · [note](../history/evidence/project/924da6c1e8c89345_SUMMARY.txt) |
| SUB28 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/bef52d81fdabbe81_sub28_report.json) · [note](../history/evidence/project/7f86a91a0061c694_SUMMARY.txt) |
| SUB29 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/66d7a115aef35df1_sub29_report.json) · [note](../history/evidence/project/d5b13c62c4a2243c_SUMMARY.txt) |
| SUB30 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/2c2c798d8176d60e_sub30_report.json) · [note](../history/evidence/project/550733a4fa97c4fb_SUMMARY.txt) |
| SUB30 FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/9631930dab952e01_sub30_fix1_report.json) · [note](../history/evidence/project/98e8b17a84878e07_SUMMARY.txt) |
| SUB30 FIX2 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/8c7fe1465d1ef676_sub30_fix2_report.json) · [note](../history/evidence/project/20970f5d9bf0ac17_SUMMARY.txt) |
| SUB31 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/7b0a3008b10802e3_sub31_report.json) · [note](../history/evidence/project/2818c71d3e40cfab_SUMMARY.txt) |
| SUB32 | 40 | 명시 없음/코드만 있음 | [report](../history/evidence/project/f8bc0289946a1d3a_sub32_10_report.json) · [report](../history/evidence/project/43b53fe79cfd274c_sub32_1_report.json) |
| SUB33 | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/7bd3617f344f96a9_sub33_source_manifest.json) · [report](../history/evidence/project/41374721d9a61a24_sub33_qa_report.json) |
| SUB34 | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/5e9378a620d89c16_sub34_integration_manifest.json) · [report](../history/evidence/project/2399a5754e6520b9_sub34_integration_report.json) |
| SUB35 | 7 | 명시 없음/코드만 있음 | [report](../history/evidence/project/ea8fe1f63708fb46_sub35_integration_manifest.json) · [report](../history/evidence/project/6786ab8afa90648b_sub35_layout_report.json) |
| SUB35 FIX1 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub35_fix1_23x2_final_integration.ps1) |
| SUB36 | 7 | 명시 없음/코드만 있음 | [report](../history/evidence/project/757dba786f7a3ec1_sub36_integration_manifest.json) · [report](../history/evidence/project/6fdc783ce4eb0ed5_sub36_semantic_qa_report.json) |
| SUB37 | 2 | 명시 없음/코드만 있음 | [source](../work/naruto_sub37_speaker_ui_discovery.py) · [source](../work/run_naruto_sub37_speaker_ui_discovery.ps1) |
| SUB37 FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/37ba8b910f1a2ed7_sub37_fix1_report.json) · [note](../history/evidence/project/63db6c678fd3aa84_SUMMARY.txt) |
| SUB38 | 8 | 명시 없음/코드만 있음 | [report](../history/evidence/project/5f3d6d9df0f3a229_sub38_report.json) · [report](../history/evidence/project/5f3d6d9df0f3a229_sub38_report.json) |
| SUB39 | 3 | runtime_verified=False | [report](../history/evidence/project/91739d807fd928fa_report.json) · [source](../work/codex_sub39_42/build_sub39.py) |
| SUB40 | 2 | runtime_verified=False | [report](../history/evidence/project/144d514d4a3b8093_report.json) · [source](../work/codex_sub39_42/build_sub40.py) |
| SUB41 | 5 | static_qa=PASS; runtime_qa=pending | [report](../history/evidence/project/886d4f815ca37707_verification.json) · [source](../history/sources/session-work/742fc45f2ec60584_advance_sub41.py) |
| SUB42 | 3 | static_qa=PASS; runtime_qa=pending | [report](../history/evidence/project/62492c6ce2e49c71_verification.json) · [source](../work/codex_sub39_42/build_sub42.py) |
| SUB43 | 9 | static_qa=PASS | [report](../history/evidence/project/a5818015fb80da71_SUB43_static_verification.json) · [report](../history/evidence/project/bce8cde046f346a2_replacement_manifest.json) |
| SUB43 FIX1 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub43_fix1_menu_images.ps1) |
| SUB44 | 7 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/7a62449bb3ef5eeb_SUB44_static_verification.json) · [report](../history/evidence/project/992025bc56adb373_runtime_qa_report.json) |
| SUB45 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/05411cf4439cf0b2_SUB45_static_verification.json) · [report](../history/evidence/project/1976fe154cd2d8bc_runtime_qa_report.json) |
| SUB46 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/5a4115c8c34901f3_SUB46_static_verification.json) · [report](../history/evidence/project/4425a862ad531b19_runtime_qa_report.json) |
| SUB47 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/dcefd6abe5761fd1_SUB47_static_verification.json) · [report](../history/evidence/project/1175243f517a5612_runtime_qa_report.json) |
| SUB48 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/db3c33450c19e7bc_SUB48_static_verification.json) · [report](../history/evidence/project/dde7eb7b076e60f1_runtime_qa_report.json) |
| SUB49 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/d375dc91564d69e7_SUB49_static_verification.json) · [report](../history/evidence/project/7da39940a09a07a4_runtime_qa_report.json) |
| SUB50 | 6 | static_qa=PASS; runtime_qa=REQUIRED | [report](../history/evidence/project/257ab11bb41f53ad_SUB50_static_verification.json) · [report](../history/evidence/project/eb0264be8a4253dd_runtime_qa_report.json) |
| SUB51A | 2 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51a_full_japanese_sweep.ps1) · [source](../history/sources/project/5a1b101d47d8ca73_scan_sub51a_full_japanese_sweep.py) |
| SUB51B | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/d0c473d097d8aaf8_collect_sub51b_exact_sources.py) · [source](../work/run_naruto_sub51b_exact_source_collection.ps1) |
| SUB51C | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/aee019817a145efe_SUB51C_CHATGPT_TRANSLATION_REPORT.json) · [source](../history/sources/project/4cca2fb7f3f93938_generate_sub51c_translation_candidat.py) |
| SUB51C FIX1 | 2 | 명시 없음/코드만 있음 | [source](../history/sources/project/ce90c6298df37a9b_export_sub51c_fix1_chatgpt_candidate.py) · [source](../work/run_naruto_sub51c_fix1_chatgpt_candidates.ps1) |
| SUB51D | 4 | runtime_qa=DEFERRED_UNTIL_UI_IMAGE_SWEEP_COMPLETE | [report](../history/evidence/project/c064eac8737dbf9c_SUB51D_static_verification.json) · [note](../history/evidence/project/7779085e7ed07efb_SUMMARY.txt) |
| SUB51D FIX1 | 2 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51d_fix1_full_text_apply.ps1) · [source](../history/sources/project/ab938bb60bfdaa02_sub51d_fix1_token_rule_selftest.py) |
| SUB51D FIX2 | 2 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51d_fix2_full_text_apply.ps1) · [source](../history/sources/project/f2690c4c654a7a3e_sub51d_fix2_builder_selftest.py) |
| SUB51E FIX1 | 3 | static_qa=PASS; runtime_qa=pending | [report](../history/evidence/project/886d4f815ca37707_verification.json) · [note](../history/evidence/project/77fc6022137ed32e_SUMMARY.txt) |
| SUB51E FIX2 | 5 | 명시 없음/코드만 있음 | [source](../history/sources/project/9cc10e44682d6f8f_recover_sub51e_fix2_pristine_sources.py) · [source](../work/run_naruto_sub51e_fix2_pristine_source_recovery.ps1) |
| SUB51E FIX3 | 9 | 명시 없음/코드만 있음 | [source](../history/sources/project/e95accc13512a8ce_recover_sub51e_fix3_pristine_sources.py) · [source](../work/run_naruto_sub51e_fix3_pristine_source_recovery.ps1) |
| SUB51F | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/3278e8bb0d821653_SUMMARY.json) · [note](../history/evidence/project/4541b71804cf42f0_SUMMARY.txt) |
| SUB51G | 4 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/7197f681c2aa8f45_SUB51G_static_verification.json) · [note](../history/evidence/project/4ca0f370392b0335_SUMMARY.txt) |
| SUB51H | 4 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/130bea1811f6ed3d_SUB51H_static_verification.json) · [note](../history/evidence/project/1082ad6112a49c92_SUMMARY.txt) |
| SUB51I | 4 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/9cdc0142c14f6c95_SUB51I_static_verification.json) · [note](../history/evidence/project/01d14fbb727f9bd8_SUMMARY.txt) |
| SUB51J | 4 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/f16d51917c24a33c_SUB51J_static_verification.json) · [note](../history/evidence/project/cb0449ea1b2fbbb1_SUMMARY.txt) |
| SUB51K | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/177b2494105c8dca_SUMMARY.json) · [note](../history/evidence/project/5d8b5d4e9b46b483_SUMMARY.txt) |
| SUB51L | 2 | 명시 없음/코드만 있음 | [source](../work/build_sub51l_residual_safe_ui.py) · [source](../work/run_naruto_sub51l_residual_safe_ui.ps1) |
| SUB51L FIX1 | 3 | 명시 없음/코드만 있음 | [source](../work/build_sub51l_fix1_consolidated_ui.py) · [source](../history/sources/project/a2a94e9f47ac9a8b_launch_sub51l_fix1.py) |
| SUB51L FIX2 | 5 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/bf30d9a2e7156ca9_SUB51L_FIX2_static_verification.json) · [note](../history/evidence/project/ecf537cc2d4c1764_SUMMARY.txt) |
| SUB51M | 2 | 명시 없음/코드만 있음 | [note](../history/evidence/project/6aa91455c4bc2bd1_SUMMARY.txt) · [source](../work/run_naruto_sub51m_final_runtime_qa.ps1) |
| SUB51N | 18 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/9ae0bcefa751c8e5_RESULT.json) · [report](../history/evidence/project/31b55c0c551bdf6d_SUB51N_static_verification.json) |
| SUB51N FIX1 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix1_pressed_runtime_qa.ps1) |
| SUB51N FIX2 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix2_pressed_runtime_qa.ps1) |
| SUB51N FIX3 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix3_pressed_runtime_qa.ps1) |
| SUB51N FIX4 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix4_pressed_runtime_qa.ps1) |
| SUB51N FIX5 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix5_pressed_runtime_qa.ps1) |
| SUB51N FIX6 | 1 | 명시 없음/코드만 있음 | [source](../work/run_naruto_sub51n_fix6_pressed_runtime_qa.ps1) |
| SUB51O | 28 | static_qa=PASS; runtime_qa=pending; runtime_qa=DEFERRED | [report](../history/evidence/project/886d4f815ca37707_verification.json) · [report](../history/evidence/project/bf30d9a2e7156ca9_SUB51L_FIX2_static_verification.json) |
| SUB51O FIX1 | 4 | 명시 없음/코드만 있음 | [source](../work/build_sub51o_fix1_menu_hint_polish.py) · [source](../history/sources/project/09616b0fe164b145_qa_sub51o_fix1_menu_hint_discovery.py) |
| SUB51O FIX2 | 8 | static_qa=PASS; runtime_qa=PENDING; runtime_qa=DEFERRED | [report](../history/evidence/project/042df077557c9da1_SUB51O_static_verification.json) · [report](../history/evidence/project/31b55c0c551bdf6d_SUB51N_static_verification.json) |
| SUB51O FIX3 | 7 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/039d9777189ca3e7_SUB51O_static_verification.json) · [note](../history/evidence/project/1c032b96f1dc391c_SUMMARY.txt) |
| SUB51O FIX4 | 3 | 명시 없음/코드만 있음 | [note](../history/evidence/project/4d0ab0c20686106e_SUMMARY.txt) · [source](../history/sources/project/da9010ae873f44b8_qa_sub51o_fix4_collect_contacts.py) |
| SUB51O FIX5 | 19 | static_qa=PASS; runtime_qa=DEFERRED | [report](../history/evidence/project/31b55c0c551bdf6d_SUB51N_static_verification.json) · [source](../history/sources/project/11c1b6478bbd2727_qa_sub51o_fix5_collect_exact_targets.py) |
| SUB51O FIX6 | 6 | 명시 없음/코드만 있음 | [source](../history/sources/project/68ccd02f736d59c5_qa_sub51o_fix6_extract_xpanel.py) · [source](../history/sources/project/49d57a4e76d497ae_qa_sub51o_fix6a_extract_xpanel.py) |
| SUB51P | 12 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/d4bb07971e2bb1be_SUB51O_static_verification.json) · [note](../history/evidence/project/cb7127087abb6cae_SUMMARY.txt) |
| SUB51P FIX1 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/177b2494105c8dca_SUMMARY.json) · [note](../history/evidence/project/5d8b5d4e9b46b483_SUMMARY.txt) |
| SUB51P FIX10 | 6 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/9e7b34b5bdc6e1ca_SUB51O_static_verification.json) · [note](../history/evidence/project/dd5fc3ce9fd346bf_SUMMARY.txt) |
| SUB51P FIX11 | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/320f75818b3ea002_SUB51O_static_verification.json) · [note](../history/evidence/project/77c2db313b28716b_SUMMARY.txt) |
| SUB51P FIX13 | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/b0dac4e376fb6d72_SUB51O_static_verification.json) · [note](../history/evidence/project/066220128bc060de_SUMMARY.txt) |
| SUB51P FIX2 | 2 | 명시 없음/코드만 있음 | [source](../work/build_sub51p_fix2_modesel_title_fix.py) · [source](../work/run_naruto_sub51p_fix2_modesel_title_fix.ps1) |
| SUB51P FIX4 | 2 | 명시 없음/코드만 있음 | [source](../work/build_sub51p_fix4_modesel_title_fix.py) · [source](../work/run_naruto_sub51p_fix4_modesel_title_fix.ps1) |
| SUB51P FIX5 | 2 | 명시 없음/코드만 있음 | [source](../work/build_sub51p_fix5_modesel_title_fix.py) · [source](../work/run_naruto_sub51p_fix5_modesel_title_fix.ps1) |
| SUB51P FIX6 | 2 | 명시 없음/코드만 있음 | [source](../work/build_sub51p_fix6_modesel_title_fix.py) · [source](../work/run_naruto_sub51p_fix6_modesel_title_fix.ps1) |
| SUB51P FIX7 | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/d1fd758f1acc0b66_SUB51O_static_verification.json) · [note](../history/evidence/project/20d56d9550a2de60_SUMMARY.txt) |
| SUB51P FIX8 | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/0ebb283b194ba731_SUB51O_static_verification.json) · [note](../history/evidence/project/e8ff837bedce95d2_SUMMARY.txt) |
| SUB52A | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/6cfd275f5ccb2177_SUMMARY.json) · [report](../history/evidence/project/362e84fe6af7d083_UPLOAD_MANIFEST.json) |
| SUB52B | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/fb7810c582a28e60_SUMMARY.json) · [note](../history/evidence/project/d806e0c3aea003c5_SUMMARY.txt) |
| SUB52C | 71 | runtime_qa=DEFERRED_UNTIL_UI_IMAGE_SWEEP_COMPLETE | [report](../history/evidence/project/aee019817a145efe_SUB51C_CHATGPT_TRANSLATION_REPORT.json) · [report](../history/evidence/project/aee019817a145efe_SUB51C_CHATGPT_TRANSLATION_REPORT.json) |
| SUB52D | 12 | static_qa=PASS; runtime_qa=DEFERRED_UNTIL_IMAGE_BATCH_COMPLETE | [report](../history/evidence/project/d89290adbe4a43ed_SUMMARY.json) · [report](../history/evidence/project/351a80375d8e0f55_SUB52D2_static_verification.json) |
| SUB52E | 5 | static_qa=PASS; runtime_qa=PENDING_FINAL_QA | [report](../history/evidence/project/188f542d0f57b56e_SUB52E_static_verification.json) · [report](../history/evidence/project/ec6418f4aa04ea1c_asset_manifest.json) |
| SUB52F | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/73f14f78e025e838_SUMMARY.json) · [note](../history/evidence/project/675be319c915209e_SUMMARY.txt) |
| SUB52F FIX1 | 2 | 명시 없음/코드만 있음 | [source](../work/sub52/history/qa_sub52f_fix1_final_static_residual_sweep.py) · [source](../work/sub52/history/run_naruto_sub52f_fix1_final_static_residual_sweep.ps1) |
| SUB52G | 7 | 명시 없음/코드만 있음 | [report](../history/evidence/project/941b9bc18b6af3d2_SUMMARY.json) · [report](../history/evidence/project/0429c2560893bba3_asset_manifest.json) |
| SUB52G FIX1 | 4 | static_qa=PASS; runtime_qa=READY_FOR_MANUAL_MENU_QA | [report](../history/evidence/project/0b1eb7822a52f44a_SUB52G_static_verification.json) · [note](../history/evidence/project/f50a839b028db1fd_SUMMARY.txt) |
| SUB52H | 8 | runtime_qa=READY_FOR_MANUAL_RUNTIME_QA | [report](../history/evidence/project/af15927faea2edbb_SUB52H_static_verification.json) · [report](../history/evidence/project/ffe0fcb5102ebdde_asset_manifest.json) |
| SUB52H FIX3 | 3 | 명시 없음/코드만 있음 | [source](../work/sub52/history/build_sub52h_fix3.py) · [source](../work/sub52/history/run_sub52h_fix3.ps1) |
| SUB52I | 6 | static_qa=PASS; runtime_qa=NOT_TESTED | [report](../history/evidence/project/6cd7294842b09c45_SUMMARY.json) · [note](../history/evidence/project/ea81d9c8e47045b1_SUMMARY.txt) |
| SUB52J | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/620c3c42361002f2_SUMMARY.json) · [note](../history/evidence/project/35f78ea405859042_SUMMARY.txt) |
| SUB52K | 9 | static_qa=PASS; runtime_qa=PENDING_FINAL_QA | [report](../history/evidence/project/48cd78f557e798d1_SUB52K_static_verification.json) · [report](../history/evidence/project/48cd78f557e798d1_SUB52K_static_verification.json) |
| SUB52K FIX1 | 2 | 명시 없음/코드만 있음 | [source](../work/sub52/history/build_sub52k_fix1_compact.py) · [source](../work/sub52/history/run_naruto_sub52k_fix1_compact.ps1) |
| SUB52K FIX2 | 4 | static_qa=PASS; runtime_qa=PENDING | [report](../history/evidence/project/82ca12dd2920d387_SUB52K_FIX2_verification.json) · [note](../history/evidence/project/6d38bf7eb550a5ad_SUMMARY.txt) |
| SUB52L | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/c91e036499bb17d1_SUMMARY.json) · [note](../history/evidence/project/cba6197eab0f1410_SUMMARY.txt) |
| SUB52M | 5 | status=STATIC_PASS_RUNTIME_UNVERIFIED | [report](../history/evidence/project/95970ccd53f32197_SUMMARY.json) · [note](../history/evidence/project/c46d9f716f361a7c_SUMMARY.txt) |
| SUB52N | 6 | status=FAIL; status=STATIC_PASS_RUNTIME_UNVERIFIED | [report](../history/evidence/project/33e2afff7b827cd0_SUMMARY.json) · [report](../history/evidence/project/0db63668bb97085b_SUMMARY.json) |
| SUB52O | 5 | 명시 없음/코드만 있음 | [report](../history/evidence/project/f8e460e3c4115f8e_SUMMARY.json) · [note](../history/evidence/project/5999b9f4016aef8d_SUMMARY.txt) |
| SUB52P | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/282b1f9bb58cc93e_SUMMARY.json) · [note](../history/evidence/project/7e5f2838d550160f_SUMMARY.txt) |
| SUB52Q | 2 | 명시 없음/코드만 있음 | [source](../work/sub52/history/run_naruto_sub52q_live_texture_probe.ps1) · [source](../work/sub52/history/sub52q_live_texture_probe.py) |
| SUB52Q FIX1 | 2 | 명시 없음/코드만 있음 | [source](../work/sub52/history/run_naruto_sub52q_fix1_verified_dump.ps1) · [source](../work/sub52/history/sub52q_fix1_verified_dump.py) |
| SUB52Q FIX2 | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/aa51d7d918becb44_SUMMARY.json) · [note](../history/evidence/project/428425ea6ec09916_RESULT.txt) |
| SUB52R | 4 | 명시 없음/코드만 있음 | [report](../history/evidence/project/84553ba4923d2637_SUMMARY.json) · [note](../history/evidence/project/cdd7593e86814c66_RESULT.txt) |
| SUB52S | 3 | status=PASS | [report](../history/evidence/project/c48196a15f3d73af_SUMMARY.json) · [source](../work/sub52/history/run_naruto_sub52s_full_dump.ps1) |
| SUB52T | 6 | 명시 없음/코드만 있음 | [report](../docs/verification/sub52/context_sub52t_gauge_hud_compact/SUMMARY.json) · [note](../history/evidence/project/38948e0c3f229d58_SUMMARY.txt) |
| SUB52U | 10 | 명시 없음/코드만 있음 | [report](../docs/verification/sub52/context_sub52u_hud_remaining/SUMMARY.json) · [report](../history/evidence/project/6d75ec2513469103_RESULT.json) |
| SUB52V | 7 | status=PASS | [report](../history/evidence/project/dfdf87b27f92a3c1_SUMMARY.json) · [report](../history/evidence/project/e3ddb2ad5c959270_RESULT.json) |
| SUB52W | 22 | status=PASS | [report](../history/evidence/project/f326ed44d9c1dde3_RESULT.json) · [note](../history/evidence/project/19cdae284cf50a78_SUMMARY.txt) |

## 보존 범위와 공백

원본/결과 ISO, 추출 게임 자산, 영상·음원·이미지, 세이브, 개인 실행 로그, 인증정보, 외부 패키지는 포함하지 않았다. 큰 보고서(2MB 초과)는 제외 목록에 남겼다. JSON의 긴 필드·큰 배열·민감 필드는 삭제/축약될 수 있다. 전체 대화 원문은 이번 범위가 아니다.

동일 내용의 중복 파일은 공개본 하나로 연결했다. ALREADY_PRESENT는 이미 저장소에 같은 정규화 내용이 있다는 뜻이고, DUPLICATE_ARCHIVED는 이번 보관본을 공유한다는 뜻이다. 어느 쪽도 실행 성공을 뜻하지 않는다.

심볼릭 링크/재분석 지점은 따라가지 않았고 중첩 깊이 제한이 있다. 디스크 전체 작업의 완전한 보존을 주장하지 않는다. 확인하지 못했거나 제외한 항목은 HISTORY_INVENTORY.json의 disposition과 scope warnings를 확인한다.

검사: `python tools/check_history.py`. 이 검사는 인덱스와 공개본의 무결성만 검사한다.

외부 라이브러리/참조 소스는 별도 제외했다. 원래 배포처와 라이선스를 확인해 설치하며 프로젝트 자체 개발 코드로 재배포하지 않는다.
