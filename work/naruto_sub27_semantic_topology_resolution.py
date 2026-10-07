#!/usr/bin/env python3
# Naruto PSP SUB27 - Manual semantic topology resolution
#
# Read-only. No game patching.
#
# This stage consumes the SUB26 exception bundle and applies a manually reviewed
# JP + US English + Korean semantic topology decision for all 177 exception blocks.
#
# IMPORTANT:
# - This resolves correspondence TOPOLOGY only.
# - It does NOT yet rewrite/split Korean text to max_bytes per individual game MSG.
# - It does NOT automatically discard game rows with no SUB09 counterpart.
#   Such rows are explicitly emitted for direct JP/EN -> KO translation later.

from __future__ import annotations
import argparse, csv, hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED = {
    "sub26_exception_blocks.tsv": "f0b3215eb235bd3e2e3e7c4142f69a095fd7b8bcc2bfd01bc609cde9cb614553",
    "sub26_block_subtitles.tsv": "fff7e8e624c3ca6d6718696182290dee083ce90205f8c72c76b13622de31d315",
    "sub26_block_game_candidates.tsv": "ddcf11bb5867f76389307999e662548b48334804fe23db083badf523b85bed1b",
    "sub26_stable_anchor_context.tsv": "886117fdcfad36d677b7eb8b7b9e71411a4e194308395cbf7d233242b3a885ed",
    "sub25_fix2_subtitle_voice_groups.tsv": "f672817978cc7e2045f711436af88871a1e7e451a79b7fe0abb54e3b7b3b32e9",
    "sub19_fix1_kr_display_messages.tsv": "aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54",
    "sub19_fix1_us_display_messages.tsv": "1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9",
    "sub09_final_sequence.tsv": "59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e",
}

EXPECTED_COUNTS = {
    "blocks": 177,
    "mapping_units": 253,
    "ocr_partial_drops": 6,
    "video_only_subtitles": 1,
    "anchor_override_units": 10,
    "stable_base_game_rows": 1417,
    "mapped_game_rows_total": 1672,
    "all_unmapped_game_rows": 304,
    "all_unmapped_voiced": 167,
    "all_unmapped_unvoiced": 137,
    "exception_candidate_unmapped": 162,
}

EXPECTED_RELATIONS = {
    "1G1S": 134,
    "1G_TO_2S": 78,
    "UNVOICED_1G1S": 16,
    "2G_TO_1S": 12,
    "ANCHOR_SPLIT_1G_TO_2S": 10,
    "1G_TO_3S": 3,
}

SPEAKER_ALLOWED = {
    "NRT":{"나루토"},"JRY":{"지라이야"},"KSU":{"카스미"},"KKS":{"카카시"},
    "KRH":{"키리히메"},"TND":{"츠나데"},"SKR":{"사쿠라"},"ORC":{"오로치마루"},
    "SIK":{"시카마루"},"KBT":{"카부토"},"SZN":{"시즈네"},"HNT":{"히나타"},
    "HKG":{"3대 호카게"},"NEJ":{"네지"},"ROC":{"리"},"HST":{"병사대장"},
    "GUY":{"가이"},"GAR":{"가아라"},"ONK":{"여자아이"},
    "SN1":{"사념제","사념체"},"KIB":{"키바"},"JJO":{"시녀"},"SIN":{"시도"},
    "TYO":{"쵸지"},"INO":{"이노"},"HIS":{"병사"},"TEN":{"텐텐"},
    "SNS":{"사념체","사념제"},"KSM":{"키사메"},"ITD":{"일동"},
    "JRS":{"일동"},"JT2":{"일동"},
}

MANUAL_DECISIONS = {"1":{"units":[{"subs":[29],"games":["event000.tbl#011","event000.tbl#012"],"relation":"2G_TO_1S","note":"감탄+질문을 한 한국어 항목으로 병합"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"2":{"units":[{"subs":[31],"games":["event000.tbl#014"],"relation":"1G1S","note":""},{"subs":[32],"games":["event000.tbl#015"],"relation":"1G1S","note":""},{"subs":[33],"games":["event000.tbl#016"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"3":{"units":[{"subs":[35],"games":["event000.tbl#018"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event000#019 '응?'은 SUB09에 별도 항목 없음","confidence":"HIGH"},"4":{"units":[{"subs":[37],"games":["event000.tbl#022"],"relation":"1G1S","note":""},{"subs":[38,39],"games":["event000.tbl#023"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event000#021 '나루토…?'는 별도 한국어 없음","confidence":"HIGH"},"5":{"units":[{"subs":[44],"games":["event000.tbl#029","event000.tbl#030"],"relation":"2G_TO_1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"6":{"units":[{"subs":[58],"games":["event000.tbl#044","event000.tbl#045"],"relation":"2G_TO_1S","note":""},{"subs":[59],"games":["event000.tbl#046","event000.tbl#047"],"relation":"2G_TO_1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"7":{"units":[{"subs":[70],"games":["event000.tbl#058","event000.tbl#059"],"relation":"2G_TO_1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"8":{"units":[{"subs":[96],"games":["event001.tbl#009"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event001#008 웃음은 별도 한국어 없음","confidence":"HIGH"},"9":{"units":[{"subs":[102],"games":["event002.tbl#006"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event002#005 경고 대사는 SUB09에서 누락","confidence":"HIGH"},"10":{"units":[{"subs":[120],"games":["event002.tbl#024"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"11":{"units":[{"subs":[122],"games":["event003.tbl#001"],"relation":"1G1S","note":""},{"subs":[123],"games":["event003.tbl#002"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"12":{"units":[{"subs":[135],"games":["event003.tbl#017"],"relation":"1G1S","note":""},{"subs":[136],"games":["event003.tbl#018"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event003#015-016은 별도 게임 대사","confidence":"HIGH"},"13":{"units":[{"subs":[168],"games":["event003.tbl#051"],"relation":"1G1S","note":""},{"subs":[169],"games":["event005.tbl#001"],"relation":"1G1S","note":""},{"subs":[171],"games":["event005.tbl#004"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event004 전 구간과 event005#003 등은 영상 SUB09에서 대응 항목 없음","confidence":"HIGH"},"14":{"units":[{"subs":[180],"games":["event005.tbl#013"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"15":{"units":[{"subs":[189],"games":["event005.tbl#023"],"relation":"1G1S","note":""},{"subs":[192],"games":["event005.tbl#025"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event005#022,#024,#026은 별도 게임 대사","confidence":"HIGH"},"16":{"units":[{"subs":[210],"games":["event006.tbl#004"],"relation":"1G1S","note":""},{"subs":[211],"games":["event006.tbl#005"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"17":{"units":[{"subs":[215],"games":["event006.tbl#010","event006.tbl#011"],"relation":"2G_TO_1S","note":"선행 감탄 포함"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"18":{"units":[{"subs":[218],"games":["event006.tbl#016"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event006#015 침묵은 별도","confidence":"HIGH"},"19":{"units":[{"subs":[238],"games":["event006.tbl#037"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"편지 본문 event006#032-036은 SUB09 항목에 직접 대응하지 않음","confidence":"HIGH"},"20":{"units":[{"subs":[257],"games":["event006.tbl#059"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event006#058 '기다려', #060 침묵은 별도","confidence":"HIGH"},"21":{"units":[{"subs":[275],"games":["event008.tbl#003"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event007 전체 및 event008#001-002는 SUB09에서 직접 대응 없음","confidence":"HIGH"},"22":{"units":[{"subs":[280],"games":["event008.tbl#008"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event008#007 '아직…' 별도","confidence":"HIGH"},"23":{"units":[{"subs":[288],"games":["event008.tbl#016"],"relation":"1G1S","note":""},{"subs":[289,290],"games":["event008.tbl#017"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event008#014 감탄, #015 무음 반응은 별도","confidence":"HIGH"},"24":{"units":[{"subs":[295,296],"games":["event008.tbl#023"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event008#022 시카마루 응답은 별도","confidence":"HIGH"},"25":{"units":[{"subs":[298],"games":["event008.tbl#026","event008.tbl#027"],"relation":"2G_TO_1S","note":"선행 반응 포함"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"26":{"units":[{"subs":[300,301],"games":["event008.tbl#030"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"27":{"units":[{"subs":[315],"games":["event009.tbl#005","event009.tbl#006"],"relation":"2G_TO_1S","note":"선행 감탄 포함"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"28":{"units":[{"subs":[351],"games":["event010.tbl#006"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"29":{"units":[{"subs":[365],"games":["event010.tbl#022","event010.tbl#023"],"relation":"2G_TO_1S","note":"선행 반응 포함"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"30":{"units":[{"subs":[400],"games":["event010.tbl#063"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"31":{"units":[{"subs":[448],"games":["event011.tbl#021"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"32":{"units":[{"subs":[504],"games":["event012.tbl#040"],"relation":"1G1S","note":""},{"subs":[505],"games":["event012.tbl#041"],"relation":"UNVOICED_1G1S","note":""},{"subs":[506],"games":["event012.tbl#042"],"relation":"1G1S","note":""},{"subs":[508],"games":["event012.tbl#044"],"relation":"1G1S","note":""}],"drops":[507],"video":[],"note":"S507 '알'은 S508의 진행중 OCR 조각; event012#039,#043 침묵 별도","confidence":"HIGH"},"33":{"units":[{"subs":[532],"games":["event013.tbl#019"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"34":{"units":[{"subs":[538],"games":["event013.tbl#025"],"relation":"1G1S","note":""},{"subs":[539],"games":["event013.tbl#026"],"relation":"1G1S","note":""},{"subs":[540],"games":["event013.tbl#028"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event013#027 '공주!'는 별도","confidence":"HIGH"},"35":{"units":[{"subs":[543],"games":["event013.tbl#031"],"relation":"1G1S","note":""}],"drops":[542],"video":[],"note":"S542 '바,'는 S543의 OCR 조각; #030 침묵 별도","confidence":"HIGH"},"36":{"units":[{"subs":[546],"games":["event013.tbl#034"],"relation":"1G1S","note":""},{"subs":[549],"games":["event013.tbl#037"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event013#033,#035,#036은 별도 음성 대사","confidence":"HIGH"},"37":{"units":[{"subs":[561],"games":["event013.tbl#051"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event013#049-050은 별도 대사","confidence":"HIGH"},"38":{"units":[{"subs":[573],"games":["event014.tbl#006"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event014#003-005는 별도 반응/대사","confidence":"HIGH"},"39":{"units":[{"subs":[576],"games":["event014.tbl#009"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"40":{"units":[{"subs":[580],"games":["event014.tbl#014"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event014#012 침묵, #013 별도 대사","confidence":"HIGH"},"41":{"units":[{"subs":[594],"games":["event014.tbl#030"],"relation":"1G1S","note":""},{"subs":[596],"games":["event014.tbl#032"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event014#029,#031은 오로치마루의 별도 대사","confidence":"HIGH"},"42":{"units":[{"subs":[601,602],"games":["event014.tbl#037"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""},{"subs":[603],"games":["event014.tbl#038"],"relation":"1G1S","note":""},{"subs":[604,605],"games":["event014.tbl#039"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"S602는 이전 안정 앵커 event014#037의 후반부","confidence":"HIGH"},"43":{"units":[{"subs":[612,613],"games":["event014.tbl#046"],"relation":"1G_TO_2S","note":""},{"subs":[614],"games":["event014.tbl#048"],"relation":"1G1S","note":""},{"subs":[615],"games":["event014.tbl#049"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event014#047 충격 반응은 별도","confidence":"HIGH"},"44":{"units":[{"subs":[618],"games":["event014.tbl#052"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"45":{"units":[{"subs":[621,622],"games":["event014.tbl#055"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"S622는 이전 안정 앵커의 후반부","confidence":"HIGH"},"46":{"units":[{"subs":[624,625],"games":["event014.tbl#057"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"47":{"units":[{"subs":[627,628],"games":["event014.tbl#059"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"48":{"units":[{"subs":[631,632],"games":["event014.tbl#062"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event014#063 침묵 별도","confidence":"HIGH"},"49":{"units":[{"subs":[634],"games":["event014.tbl#065"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"50":{"units":[{"subs":[642,643],"games":["event014.tbl#074"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"51":{"units":[{"subs":[653],"games":["event014.tbl#087"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event014#086 '젠장…!' 별도","confidence":"HIGH"},"52":{"units":[{"subs":[665],"games":["event014.tbl#100"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"53":{"units":[{"subs":[707],"games":["event015.tbl#036"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event015#035 '기다려', #037 무음 반응 별도","confidence":"HIGH"},"54":{"units":[{"subs":[722,723],"games":["event015.tbl#054"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"55":{"units":[{"subs":[776],"games":["event018.tbl#013"],"relation":"1G1S","note":""},{"subs":[777],"games":["event018.tbl#014"],"relation":"1G1S","note":""},{"subs":[778,779],"games":["event018.tbl#015"],"relation":"1G_TO_2S","note":""}],"drops":[775],"video":[],"note":"S775 '난… 누'는 S776의 OCR 조각; #012 침묵 별도","confidence":"HIGH"},"56":{"units":[{"subs":[794],"games":["event018.tbl#031"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"57":{"units":[{"subs":[800],"games":["event018.tbl#037"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event018#038-040은 별도 반응","confidence":"HIGH"},"58":{"units":[{"subs":[807,808],"games":["event018.tbl#047"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"59":{"units":[{"subs":[814,815,816],"games":["event018.tbl#054"],"relation":"1G_TO_3S","note":""},{"subs":[817],"games":["event018.tbl#055"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event018#053 침묵 별도","confidence":"HIGH"},"60":{"units":[{"subs":[821],"games":["event019.tbl#005"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event019#004 나루토 '여기는…' 별도","confidence":"HIGH"},"61":{"units":[{"subs":[827],"games":["event019.tbl#014"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event019#013 다른 사념의 '언니를…', #015 침묵 별도","confidence":"HIGH"},"62":{"units":[{"subs":[835],"games":["event019.tbl#024"],"relation":"1G1S","note":""}],"drops":[834],"video":[],"note":"S834 '저'는 S835의 OCR 조각; #023 침묵 별도","confidence":"HIGH"},"63":{"units":[{"subs":[840],"games":["event019.tbl#030","event019.tbl#031"],"relation":"2G_TO_1S","note":""},{"subs":[841],"games":["event019.tbl#032"],"relation":"1G1S","note":""},{"subs":[842],"games":["event019.tbl#033"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"64":{"units":[{"subs":[845],"games":["event019.tbl#037"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event019#036 과거 음성은 별도","confidence":"HIGH"},"65":{"units":[{"subs":[850],"games":["event019.tbl#042"],"relation":"1G1S","note":""},{"subs":[853],"games":["event019.tbl#045"],"relation":"1G1S","note":""},{"subs":[855],"games":["event019.tbl#047"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event019#040-041,#044,#046 및 event020#001-002는 별도 게임 대사/반응","confidence":"HIGH"},"66":{"units":[{"subs":[859],"games":["event020.tbl#005"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event020#006 침묵, #007 나루토 반응 별도","confidence":"HIGH"},"67":{"units":[{"subs":[887,888],"games":["event020.tbl#037"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"68":{"units":[{"subs":[892],"games":["event020.tbl#042"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event020#041 과거 사념 음성은 별도","confidence":"HIGH"},"69":{"units":[{"subs":[909,910],"games":["event021.tbl#004"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event021#002-003 과거/회상 음성은 별도","confidence":"HIGH"},"70":{"units":[{"subs":[915],"games":["event021.tbl#010"],"relation":"1G1S","note":""},{"subs":[916,917],"games":["event021.tbl#012"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event021#009 실망 대사와 #011 침묵 별도","confidence":"HIGH"},"71":{"units":[{"subs":[921],"games":["event021.tbl#016"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"72":{"units":[{"subs":[925],"games":["event021.tbl#020"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"73":{"units":[{"subs":[928,929],"games":["event021.tbl#023"],"relation":"1G_TO_2S","note":""},{"subs":[930,931],"games":["event021.tbl#024"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"74":{"units":[{"subs":[934],"games":["event021.tbl#027"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"75":{"units":[{"subs":[954],"games":["event021.tbl#049"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"76":{"units":[{"subs":[958],"games":["event021.tbl#056"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"77":{"units":[{"subs":[962,963],"games":["event021.tbl#060"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"78":{"units":[{"subs":[967,968],"games":["event021.tbl#065"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"79":{"units":[{"subs":[971],"games":["event021.tbl#071"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event021#068-070은 침묵/카부토 별도 대사","confidence":"HIGH"},"80":{"units":[{"subs":[986],"games":["event021.tbl#088","event021.tbl#089"],"relation":"2G_TO_1S","note":"충격 반응+대사"}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"81":{"units":[{"subs":[989],"games":["event021.tbl#092"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"82":{"units":[{"subs":[991],"games":["event021.tbl#096"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event021#094 '봉인술…', #095 나루토 외침은 별도","confidence":"HIGH"},"83":{"units":[{"subs":[995],"games":["event021.tbl#101"],"relation":"1G1S","note":""},{"subs":[996],"games":["event021.tbl#102"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event021#103 키리히메 반응 별도","confidence":"HIGH"},"84":{"units":[{"subs":[1014],"games":["event021.tbl#116"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event021#115 가아라 침묵 별도","confidence":"HIGH"},"85":{"units":[{"subs":[1025],"games":["event021.tbl#132"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event021#128-131은 침묵/나루토 회상 음성 별도","confidence":"HIGH"},"86":{"units":[{"subs":[1041,1042],"games":["event022.tbl#005"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"87":{"units":[{"subs":[1070],"games":["event022.tbl#036"],"relation":"1G1S","note":""},{"subs":[1071],"games":["event022.tbl#039"],"relation":"1G1S","note":""},{"subs":[1072],"games":["event022.tbl#040"],"relation":"1G1S","note":""},{"subs":[1073,1074],"games":["event022.tbl#041"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event022#037,#042 침묵, #038 나루토 '누나…' 별도","confidence":"HIGH"},"88":{"units":[{"subs":[1087],"games":["event022.tbl#065"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event022#061-063 사념들의 인사와 #060/#064 침묵은 별도","confidence":"HIGH"},"89":{"units":[{"subs":[1093],"games":["event022.tbl#073"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event022#072 나루토 웃음, #071 침묵 별도","confidence":"HIGH"},"90":{"units":[{"subs":[1100],"games":["event023.tbl#001"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"91":{"units":[{"subs":[1105],"games":["event023.tbl#006"],"relation":"1G1S","note":""},{"subs":[1106],"games":["event023.tbl#007"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"92":{"units":[{"subs":[1112],"games":["event024.tbl#003"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event024#002 카부토 인사 별도","confidence":"HIGH"},"93":{"units":[{"subs":[1124],"games":["event024.tbl#016"],"relation":"1G1S","note":""},{"subs":[1125],"games":["event024.tbl#017"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"94":{"units":[{"subs":[1144],"games":["event024.tbl#036"],"relation":"1G1S","note":""},{"subs":[1145],"games":["event024.tbl#037"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"95":{"units":[{"subs":[1150],"games":["event024.tbl#043"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event024#042 웃음 별도","confidence":"HIGH"},"96":{"units":[{"subs":[1153],"games":["event025.tbl#004"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event025#003 나루토 감탄 별도","confidence":"HIGH"},"97":{"units":[{"subs":[1161],"games":["event025.tbl#012"],"relation":"1G1S","note":""},{"subs":[1162],"games":["event025.tbl#014"],"relation":"1G1S","note":""},{"subs":[1163],"games":["event025.tbl#016"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event025#013/#015 침묵, #017 카스미 '응…' 별도","confidence":"HIGH"},"98":{"units":[{"subs":[1174,1175],"games":["event025.tbl#030"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"99":{"units":[{"subs":[1179,1180],"games":["event025.tbl#034"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"100":{"units":[{"subs":[1182,1183],"games":["event025.tbl#036"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"101":{"units":[{"subs":[1210],"games":["event025.tbl#065"],"relation":"1G1S","note":""},{"subs":[1211],"games":["event025.tbl#067"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event025#066 침묵 별도","confidence":"HIGH"},"102":{"units":[{"subs":[1213],"games":["event025.tbl#069"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"103":{"units":[{"subs":[1216],"games":["event025.tbl#072"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"104":{"units":[{"subs":[1218],"games":["event025.tbl#074"],"relation":"1G1S","note":""},{"subs":[1219],"games":["event025.tbl#075"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"105":{"units":[{"subs":[1223,1224],"games":["event025.tbl#079"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"106":{"units":[{"subs":[1233,1234],"games":["event025.tbl#088"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"107":{"units":[{"subs":[1244],"games":["event025.tbl#098"],"relation":"1G1S","note":""},{"subs":[1245],"games":["event025.tbl#099"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"108":{"units":[{"subs":[1249],"games":["event025.tbl#103"],"relation":"1G1S","note":""},{"subs":[1250],"games":["event025.tbl#104"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"109":{"units":[{"subs":[1254],"games":["event025.tbl#109"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"110":{"units":[{"subs":[1258],"games":["event025.tbl#115"],"relation":"1G1S","note":""},{"subs":[1259,1260],"games":["event025.tbl#116"],"relation":"1G_TO_2S","note":""},{"subs":[1261,1262],"games":["event025.tbl#117"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event025#114 나루토 '어…', #118 침묵 별도","confidence":"HIGH"},"111":{"units":[{"subs":[1266],"games":["event025.tbl#123"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"112":{"units":[{"subs":[1277],"games":["event025.tbl#134"],"relation":"1G1S","note":""},{"subs":[1278],"games":["event025.tbl#135"],"relation":"1G1S","note":""},{"subs":[1279],"games":["event025.tbl#136"],"relation":"1G1S","note":""},{"subs":[1280],"games":["event025.tbl#137"],"relation":"1G1S","note":""},{"subs":[1281,1282],"games":["event025.tbl#139"],"relation":"1G_TO_2S","note":""},{"subs":[1283,1284,1285],"games":["event025.tbl#140"],"relation":"1G_TO_3S","note":""},{"subs":[1286,1287],"games":["event025.tbl#142"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event025#133 카스미 '나루토…', #138 나루토 '응…', #141 침묵 별도","confidence":"HIGH"},"113":{"units":[{"subs":[1291,1292],"games":["event025.tbl#146"],"relation":"1G_TO_2S","note":""},{"subs":[1293],"games":["event025.tbl#147"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"114":{"units":[{"subs":[1298],"games":["event025.tbl#154"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"event025#153 나루토 '약속이다!' 별도","confidence":"HIGH"},"115":{"units":[{"subs":[1307],"games":["event025.tbl#167"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event025#165 '잘 해냈구나', #166 침묵, #168 '탈출이다'는 별도","confidence":"HIGH"},"116":{"units":[{"subs":[1329],"games":["event025.tbl#191"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"117":{"units":[],"drops":[],"video":[1337],"note":"S1337은 영상 전용/연출 구간. event025#197 나루토 감탄과 event100#001 침묵은 별도 게임 행","confidence":"HIGH"},"118":{"units":[{"subs":[1353,1354],"games":["event100.tbl#004"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"119":{"units":[{"subs":[1365],"games":["event100.tbl#015"],"relation":"1G1S","note":""},{"subs":[1366],"games":["event100.tbl#016"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"120":{"units":[{"subs":[1372,1373],"games":["event100.tbl#022"],"relation":"1G_TO_2S","note":""},{"subs":[1374,1375],"games":["event100.tbl#023"],"relation":"1G_TO_2S","note":""},{"subs":[1376,1377],"games":["event100.tbl#024"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"121":{"units":[{"subs":[1382,1383],"games":["event100.tbl#029"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"122":{"units":[{"subs":[1385,1386],"games":["event100.tbl#031"],"relation":"1G_TO_2S","note":""},{"subs":[1387,1388],"games":["event100.tbl#032"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"123":{"units":[{"subs":[1392,1393],"games":["event100.tbl#036"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"124":{"units":[{"subs":[1400,1401],"games":["event100.tbl#043"],"relation":"1G_TO_2S","note":""},{"subs":[1402],"games":["event100.tbl#044"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"125":{"units":[{"subs":[1404,1405],"games":["event100.tbl#046"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"126":{"units":[{"subs":[1415],"games":["event100.tbl#059"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"127":{"units":[{"subs":[1424],"games":["event100.tbl#070"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event100#069 정체불명 음성 '어라? 거기 있는 사람은…누구?' 별도","confidence":"HIGH"},"128":{"units":[{"subs":[1438,1439],"games":["event100.tbl#085"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"129":{"units":[{"subs":[1449],"games":["event100.tbl#096"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event100#095 '라이…야…' 별도 음성","confidence":"HIGH"},"130":{"units":[{"subs":[1456,1457],"games":["event100.tbl#103"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event100#104 지라이야 침묵 별도","confidence":"HIGH"},"131":{"units":[{"subs":[1459,1460],"games":["event100.tbl#106"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"132":{"units":[{"subs":[1463],"games":["event101.tbl#001"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"133":{"units":[{"subs":[1468,1469],"games":["event101.tbl#007"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"134":{"units":[{"subs":[1478,1479],"games":["event102.tbl#007"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"135":{"units":[{"subs":[1495,1496],"games":["event102.tbl#024"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"136":{"units":[{"subs":[1520],"games":["event104.tbl#009"],"relation":"1G1S","note":""},{"subs":[1521],"games":["event104.tbl#010"],"relation":"1G1S","note":""}],"drops":[1519],"video":[],"note":"S1519 '뭐, 아'는 S1520의 진행중 OCR 조각; event104#008 지라이야 침묵 별도","confidence":"HIGH"},"137":{"units":[{"subs":[1526,1527],"games":["event104.tbl#016"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"138":{"units":[{"subs":[1529,1530],"games":["event104.tbl#018"],"relation":"1G_TO_2S","note":""},{"subs":[1531,1532],"games":["event104.tbl#019"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"139":{"units":[{"subs":[1541,1542],"games":["event104.tbl#029"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"140":{"units":[{"subs":[1559,1560],"games":["event104.tbl#047"],"relation":"1G_TO_2S","note":""},{"subs":[1561],"games":["event104.tbl#048"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"141":{"units":[{"subs":[1563,1564],"games":["event104.tbl#050"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"142":{"units":[{"subs":[1577,1578],"games":["event104.tbl#065"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event104#064 카카시 침묵 별도","confidence":"HIGH"},"143":{"units":[{"subs":[1581,1582],"games":["event104.tbl#068"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"144":{"units":[{"subs":[1592],"games":["event105.tbl#007"],"relation":"1G1S","note":"SUB09 화자 라벨은 카카시지만 의미/원문 화자는 지라이야"},{"subs":[1593],"games":["event105.tbl#008"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"S1592 화자 라벨 오류를 의미 기준으로 교정","confidence":"HIGH"},"145":{"units":[{"subs":[1595,1596],"games":["event105.tbl#010"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"146":{"units":[{"subs":[1600,1601],"games":["event105.tbl#014"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"147":{"units":[{"subs":[1607],"games":["event105.tbl#019"],"relation":"UNVOICED_1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"148":{"units":[{"subs":[1634,1635],"games":["event106.tbl#009"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"149":{"units":[{"subs":[1638],"games":["event107.tbl#001","event107.tbl#002"],"relation":"2G_TO_1S","note":"선행 감탄 포함"}],"drops":[],"video":[],"note":"event107#003 키사메 침묵 별도","confidence":"HIGH"},"150":{"units":[{"subs":[1649],"games":["event108.tbl#004"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event108#003 카부토 대사 별도","confidence":"HIGH"},"151":{"units":[{"subs":[1652,1653],"games":["event108.tbl#007"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"152":{"units":[{"subs":[1658,1659],"games":["event108.tbl#012"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"153":{"units":[{"subs":[1670],"games":["event108.tbl#023"],"relation":"1G1S","note":""},{"subs":[1672],"games":["event108.tbl#025"],"relation":"1G1S","note":""},{"subs":[1673,1674],"games":["event108.tbl#026"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event108#021-022 카부토/오로치마루 계열 음성, #024 웃음은 별도","confidence":"HIGH"},"154":{"units":[{"subs":[1695,1696],"games":["event109.tbl#022"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"155":{"units":[{"subs":[1698,1699],"games":["event109.tbl#024"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"156":{"units":[{"subs":[1701,1702],"games":["event109.tbl#026"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"157":{"units":[{"subs":[1707,1708],"games":["event109.tbl#031"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event110#001 지라이야 무음 반응 별도","confidence":"HIGH"},"158":{"units":[{"subs":[1713,1714],"games":["event110.tbl#006"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""},{"subs":[1715],"games":["event110.tbl#007"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"S1714는 이전 안정 앵커 event110#006의 후반부","confidence":"HIGH"},"159":{"units":[{"subs":[1717,1718],"games":["event110.tbl#009"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"160":{"units":[{"subs":[1722,1723],"games":["event110.tbl#014"],"relation":"1G_TO_2S","note":""},{"subs":[1724],"games":["event110.tbl#015"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"161":{"units":[{"subs":[1725,1726],"games":["event110.tbl#016"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""},{"subs":[1727],"games":["event110.tbl#017"],"relation":"1G1S","note":""},{"subs":[1728,1729],"games":["event110.tbl#018"],"relation":"1G_TO_2S","note":""},{"subs":[1730],"games":["event110.tbl#019"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"S1726은 이전 안정 앵커의 후반부","confidence":"HIGH"},"162":{"units":[{"subs":[1743,1744],"games":["event111.tbl#006"],"relation":"1G_TO_2S","note":""},{"subs":[1747],"games":["event111.tbl#009"],"relation":"1G1S","note":""}],"drops":[1746],"video":[],"note":"S1746 '그게 오'는 S1747의 OCR 조각; event111#007 회상 음성, #008 지라이야 반응, #005 침묵 별도","confidence":"HIGH"},"163":{"units":[{"subs":[1755,1756],"games":["event112.tbl#004"],"relation":"1G_TO_2S","note":""},{"subs":[1757,1758],"games":["event112.tbl#005"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"164":{"units":[{"subs":[1770,1771],"games":["event112.tbl#018"],"relation":"1G_TO_2S","note":""},{"subs":[1772],"games":["event112.tbl#019"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"165":{"units":[{"subs":[1775,1776],"games":["event112.tbl#022"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"166":{"units":[{"subs":[1780,1781],"games":["event112.tbl#026"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"167":{"units":[{"subs":[1797,1798],"games":["event112.tbl#043"],"relation":"1G_TO_2S","note":""},{"subs":[1799],"games":["event112.tbl#044"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"168":{"units":[{"subs":[1801,1802],"games":["event112.tbl#046"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"169":{"units":[{"subs":[1808,1809],"games":["event112.tbl#053"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"event112#052 '아니…'는 별도 대사","confidence":"HIGH"},"170":{"units":[{"subs":[1811,1812],"games":["event112.tbl#055"],"relation":"1G_TO_2S","note":""},{"subs":[1813,1814],"games":["event112.tbl#056"],"relation":"1G_TO_2S","note":""},{"subs":[1815],"games":["event112.tbl#058"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event112#057 지라이야 침묵 별도","confidence":"HIGH"},"171":{"units":[{"subs":[1819],"games":["event112.tbl#062"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event112#063 지라이야 '큭…' 별도","confidence":"HIGH"},"172":{"units":[{"subs":[1825,1826],"games":["event112.tbl#069"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"173":{"units":[{"subs":[1833,1834],"games":["event112.tbl#076"],"relation":"1G_TO_2S","note":""},{"subs":[1835],"games":["event112.tbl#077"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"174":{"units":[{"subs":[1840,1841,1842],"games":["event112.tbl#082"],"relation":"1G_TO_3S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"175":{"units":[{"subs":[1861,1862],"games":["event112.tbl#094"],"relation":"1G_TO_2S","note":""}],"drops":[],"video":[],"note":"","confidence":"HIGH"},"176":{"units":[{"subs":[1868,1869],"games":["event112.tbl#101"],"relation":"ANCHOR_SPLIT_1G_TO_2S","note":""},{"subs":[1870],"games":["event112.tbl#102"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"S1869는 이전 안정 앵커 event112#101의 후반부","confidence":"HIGH"},"177":{"units":[{"subs":[1878],"games":["event112.tbl#115"],"relation":"1G1S","note":""}],"drops":[],"video":[],"note":"event112#110,#111,#113은 지라이야 별도 대사; #112/#114/#116 침묵","confidence":"HIGH"}}

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path:Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path:Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def pin(path:Path, expected:str, name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def stable_group(r):
    return (
        int(r["assigned_game_count"])==1
        and int(r["speaker_incompatible_count"])==0
        and r["potential_1G_2S_split"]=="NO"
    )

def mapping_spec(units):
    chunks=[]
    for u in units:
        ss="+".join("S"+str(x) for x in u["subs"])
        gg="+".join(u["games"])
        chunks.append(f"{ss}=>{gg}[{u['relation']}]")
    return "; ".join(chunks)

def joined_korean(sub_by_seq, seqs):
    return " / ".join(sub_by_seq[s]["text"] for s in seqs if s in sub_by_seq)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p_blocks=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_exception_blocks.tsv"
    p_subs=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_block_subtitles.tsv"
    p_cands=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_block_game_candidates.tsv"
    p_anchors=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_stable_anchor_context.tsv"
    p_groups=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_subtitle_voice_groups.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned inputs", flush=True)
    blocks=pin(p_blocks, EXPECTED[p_blocks.name], "SUB26 blocks")
    block_subs=pin(p_subs, EXPECTED[p_subs.name], "SUB26 block subtitles")
    candidates=pin(p_cands, EXPECTED[p_cands.name], "SUB26 game candidates")
    anchors=pin(p_anchors, EXPECTED[p_anchors.name], "SUB26 stable anchors")
    groups=pin(p_groups, EXPECTED[p_groups.name], "SUB25 FIX2 groups")
    kr=pin(p_kr, EXPECTED[p_kr.name], "SUB19 KR")
    us=pin(p_us, EXPECTED[p_us.name], "SUB19 US")
    sub09=pin(p_sub09, EXPECTED[p_sub09.name], "SUB09")

    if len(blocks)!=EXPECTED_COUNTS["blocks"]:
        raise RuntimeError(f"block count={len(blocks)}")

    sub_by_seq={int(r["sequence"]):r for r in sub09}
    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    game_by_key={game_key(r):r for r in game}
    game_pos={game_key(r):i for i,r in enumerate(game)}

    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:
            us_by[(r["event_file"], r["voice_id"])].append(r)

    subs_by_block=defaultdict(list)
    for r in block_subs:
        subs_by_block[int(r["block_id"])].append(r)
    cands_by_block=defaultdict(list)
    for r in candidates:
        cands_by_block[int(r["block_id"])].append(r)
    anchors_by_block=defaultdict(list)
    for r in anchors:
        anchors_by_block[int(r["block_id"])].append(r)

    print("[2/7] Validate 177 manual semantic decisions", flush=True)
    if set(map(int,MANUAL_DECISIONS.keys())) != set(range(1,178)):
        raise RuntimeError("manual decision block ids are incomplete")

    mapping_rows=[]
    block_rows=[]
    exclusion_rows=[]
    anchor_override_rows=[]
    relation_counts=Counter()
    mapped_overlay_games=set()
    exception_candidate_unmapped=[]

    intentional_speaker_mismatches=[]

    for bid in range(1,178):
        d=MANUAL_DECISIONS[str(bid)] if str(bid) in MANUAL_DECISIONS else MANUAL_DECISIONS[bid]
        exception_seqs={int(r["sub09_sequence"]) for r in subs_by_block[bid]}

        covered=set(d.get("drops",[])) | set(d.get("video",[]))
        allowed_games={r["game_key"] for r in cands_by_block[bid]}
        allowed_games |= {r["game_key"] for r in anchors_by_block[bid]}

        mapped_here=set()

        for unit_index,u in enumerate(d["units"],1):
            subs=[int(x) for x in u["subs"]]
            games=list(u["games"])
            relation=u["relation"]
            note=u.get("note","")

            covered |= (set(subs) & exception_seqs)

            for g in games:
                if g not in allowed_games:
                    raise RuntimeError(f"block {bid}: game outside candidate/anchor scope: {g}")
                if g not in game_by_key:
                    raise RuntimeError(f"block {bid}: unknown game key: {g}")

            # monotonic semantic ordering is checked later globally
            relation_counts[relation]+=1
            mapped_here.update(games)
            mapped_overlay_games.update(games)

            subtitle_speakers=sorted({sub_by_seq[s]["speaker"] for s in subs if s in sub_by_seq})
            game_codes=sorted({game_by_key[g]["speaker_code"] for g in games if game_by_key[g]["speaker_code"]})
            allowed_names=set()
            for gc in game_codes:
                allowed_names |= SPEAKER_ALLOWED.get(gc,set())
            normalized_speakers={"이노" if x=="이도" else x for x in subtitle_speakers}
            speaker_mismatch=bool(allowed_names and not normalized_speakers.issubset(allowed_names))
            if speaker_mismatch:
                intentional_speaker_mismatches.append((bid,subs,games,subtitle_speakers,game_codes))

            game_meta=[]
            for g in games:
                gr=game_by_key[g]
                hits=us_by.get((gr["event_file"],gr["voice_id"]),[])
                game_meta.append({
                    "key":g,
                    "speaker_code":gr["speaker_code"],
                    "voice_id":gr["voice_id"],
                    "jp":gr["text"],
                    "en":" || ".join(x["text"] for x in hits),
                })

            mapping_rows.append({
                "block_id":bid,
                "unit_index":unit_index,
                "relation":relation,
                "subtitle_sequences":" ".join(map(str,subs)),
                "subtitle_speakers":" | ".join(subtitle_speakers),
                "korean_joined":joined_korean(sub_by_seq,subs),
                "game_keys":" | ".join(games),
                "game_speaker_codes":" | ".join(x["speaker_code"] or "<BLANK>" for x in game_meta),
                "voice_ids":" | ".join(x["voice_id"] or "<NO-VOICE>" for x in game_meta),
                "japanese_joined":" || ".join(x["jp"] for x in game_meta),
                "english_joined":" || ".join(x["en"] for x in game_meta),
                "speaker_mismatch":"YES" if speaker_mismatch else "NO",
                "note":note,
            })

            if relation=="ANCHOR_SPLIT_1G_TO_2S":
                anchor_override_rows.append(mapping_rows[-1].copy())

        if covered != exception_seqs:
            raise RuntimeError(
                f"block {bid}: subtitle coverage mismatch expected={sorted(exception_seqs)} got={sorted(covered)}"
            )

        for s in d.get("drops",[]):
            exclusion_rows.append({
                "block_id":bid,
                "sub09_sequence":s,
                "type":"OCR_PARTIAL_DROP",
                "speaker":sub_by_seq[s]["speaker"],
                "korean":sub_by_seq[s]["text"],
                "reason":"진행 중 OCR 조각/중복 프레임으로 의미 단위에서 제외",
            })
        for s in d.get("video",[]):
            exclusion_rows.append({
                "block_id":bid,
                "sub09_sequence":s,
                "type":"VIDEO_ONLY_NO_GAME_MSG",
                "speaker":sub_by_seq[s]["speaker"],
                "korean":sub_by_seq[s]["text"],
                "reason":"영상/연출 자막으로 확인되어 해당 이벤트 TBL MSG와 의미 대응 없음",
            })

        candidate_keys={r["game_key"] for r in cands_by_block[bid]}
        for g in sorted(candidate_keys-mapped_here, key=lambda x:game_pos[x]):
            gr=game_by_key[g]
            hits=us_by.get((gr["event_file"],gr["voice_id"]),[])
            exception_candidate_unmapped.append({
                "block_id":bid,
                "game_key":g,
                "game_global_dialogue_index":game_pos[g]+1,
                "event_file":gr["event_file"],
                "event_display_index":gr["event_display_index"],
                "command":gr["command"],
                "speaker_code":gr["speaker_code"],
                "voice_id":gr["voice_id"],
                "japanese":gr["text"],
                "english":" || ".join(x["text"] for x in hits),
                "reason":"NO_SUB09_SEMANTIC_COUNTERPART_IN_EXCEPTION_BLOCK",
                "next_action":"DIRECT_TRANSLATE_JP_EN_TO_KO_LATER",
            })

        block_rows.append({
            "block_id":bid,
            "first_sub09_sequence":blocks[bid-1]["first_sub09_sequence"],
            "last_sub09_sequence":blocks[bid-1]["last_sub09_sequence"],
            "semantic_status":"RESOLVED_TOPOLOGY",
            "confidence":d.get("confidence","HIGH"),
            "decision_types":" | ".join(sorted({u["relation"] for u in d["units"]})) or "NO_GAME_MAPPING",
            "final_mapping_spec":mapping_spec(d["units"]),
            "ocr_partial_drop_sequences":" ".join(map(str,d.get("drops",[]))),
            "video_only_sequences":" ".join(map(str,d.get("video",[]))),
            "unmapped_candidate_game_count":len(candidate_keys-mapped_here),
            "unmapped_candidate_game_keys":" | ".join(
                sorted(candidate_keys-mapped_here,key=lambda x:game_pos[x])
            ),
            "review_notes":d.get("note",""),
        })

    if len(mapping_rows)!=EXPECTED_COUNTS["mapping_units"]:
        raise RuntimeError(f"mapping units={len(mapping_rows)}")
    if relation_counts != Counter(EXPECTED_RELATIONS):
        raise RuntimeError(f"relation counts={dict(relation_counts)}")
    if len(exclusion_rows)!=EXPECTED_COUNTS["ocr_partial_drops"]+EXPECTED_COUNTS["video_only_subtitles"]:
        raise RuntimeError(f"exclusion rows={len(exclusion_rows)}")
    if len(anchor_override_rows)!=EXPECTED_COUNTS["anchor_override_units"]:
        raise RuntimeError(f"anchor overrides={len(anchor_override_rows)}")
    if len(exception_candidate_unmapped)!=EXPECTED_COUNTS["exception_candidate_unmapped"]:
        raise RuntimeError(f"exception candidate unmapped={len(exception_candidate_unmapped)}")

    # Only one manual mapping intentionally crosses the SUB09 speaker label:
    # block 144 S1592 is labeled Kakashi in OCR but the actual line is Jiraiya.
    if len(intentional_speaker_mismatches)!=1 or intentional_speaker_mismatches[0][0]!=144:
        raise RuntimeError(
            f"unexpected semantic speaker mismatches: {intentional_speaker_mismatches[:10]}"
        )

    print("[3/7] Build full game-row semantic coverage", flush=True)
    stable_rows=[r for r in groups if stable_group(r)]
    base_stable_games={r["assigned_game_keys"].strip() for r in stable_rows if r["assigned_game_keys"].strip()}
    if len(base_stable_games)!=EXPECTED_COUNTS["stable_base_game_rows"]:
        raise RuntimeError(f"stable base games={len(base_stable_games)}")

    mapped_all=base_stable_games | mapped_overlay_games
    if len(mapped_all)!=EXPECTED_COUNTS["mapped_game_rows_total"]:
        raise RuntimeError(f"mapped game rows={len(mapped_all)}")

    all_unmapped=[]
    for g in game:
        k=game_key(g)
        if k in mapped_all:
            continue
        hits=us_by.get((g["event_file"],g["voice_id"]),[])
        all_unmapped.append({
            "game_key":k,
            "game_global_dialogue_index":game_pos[k]+1,
            "event_file":g["event_file"],
            "event_display_index":g["event_display_index"],
            "command":g["command"],
            "speaker_code":g["speaker_code"],
            "voice_id":g["voice_id"],
            "voiced":"YES" if g["voice_id"] else "NO",
            "japanese":g["text"],
            "english":" || ".join(x["text"] for x in hits),
            "status":"NO_SUB09_SEMANTIC_MAPPING",
            "next_action":"DIRECT_TRANSLATE_JP_EN_TO_KO_LATER",
        })

    if len(all_unmapped)!=EXPECTED_COUNTS["all_unmapped_game_rows"]:
        raise RuntimeError(f"all unmapped game rows={len(all_unmapped)}")
    voiced=sum(r["voiced"]=="YES" for r in all_unmapped)
    unvoiced=len(all_unmapped)-voiced
    if voiced!=EXPECTED_COUNTS["all_unmapped_voiced"] or unvoiced!=EXPECTED_COUNTS["all_unmapped_unvoiced"]:
        raise RuntimeError(f"unmapped voiced/unvoiced={voiced}/{unvoiced}")

    print("[4/7] Check global ordering of manual mappings", flush=True)
    # Check within each block by semantic unit order.
    for bid in range(1,178):
        rows=[r for r in mapping_rows if int(r["block_id"])==bid]
        last=-1
        for r in rows:
            gs=[x.strip() for x in r["game_keys"].split("|") if x.strip()]
            if not gs:
                continue
            lo=min(game_pos[x] for x in gs)
            hi=max(game_pos[x] for x in gs)
            if lo<last:
                raise RuntimeError(f"block {bid}: semantic mapping game order reversal")
            last=hi

    print("[5/7] Write normalized semantic outputs", flush=True)
    write_tsv(
        out/"sub27_semantic_block_resolution.tsv",
        block_rows,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence",
            "semantic_status","confidence","decision_types","final_mapping_spec",
            "ocr_partial_drop_sequences","video_only_sequences",
            "unmapped_candidate_game_count","unmapped_candidate_game_keys",
            "review_notes"
        ]
    )
    write_tsv(
        out/"sub27_mapping_units.tsv",
        mapping_rows,
        [
            "block_id","unit_index","relation","subtitle_sequences",
            "subtitle_speakers","korean_joined","game_keys","game_speaker_codes",
            "voice_ids","japanese_joined","english_joined","speaker_mismatch","note"
        ]
    )
    write_tsv(
        out/"sub27_anchor_overrides.tsv",
        anchor_override_rows,
        [
            "block_id","unit_index","relation","subtitle_sequences",
            "subtitle_speakers","korean_joined","game_keys","game_speaker_codes",
            "voice_ids","japanese_joined","english_joined","speaker_mismatch","note"
        ]
    )
    write_tsv(
        out/"sub27_subtitle_exclusions.tsv",
        exclusion_rows,
        ["block_id","sub09_sequence","type","speaker","korean","reason"]
    )
    write_tsv(
        out/"sub27_exception_game_only_rows.tsv",
        exception_candidate_unmapped,
        [
            "block_id","game_key","game_global_dialogue_index","event_file",
            "event_display_index","command","speaker_code","voice_id",
            "japanese","english","reason","next_action"
        ]
    )
    write_tsv(
        out/"sub27_all_unmapped_game_rows.tsv",
        all_unmapped,
        [
            "game_key","game_global_dialogue_index","event_file","event_display_index",
            "command","speaker_code","voice_id","voiced","japanese","english",
            "status","next_action"
        ]
    )

    # Fill the original SUB26-shaped resolution template.
    filled=[]
    by_bid={int(r["block_id"]):r for r in block_rows}
    for bid in range(1,178):
        r=by_bid[bid]
        filled.append({
            "block_id":bid,
            "first_sub09_sequence":r["first_sub09_sequence"],
            "last_sub09_sequence":r["last_sub09_sequence"],
            "review_hints":blocks[bid-1]["review_hints"],
            "semantic_status":"RESOLVED_TOPOLOGY",
            "decision_type":r["decision_types"],
            "final_mapping_spec":r["final_mapping_spec"],
            "game_rows_to_skip":"",
            "korean_split_or_merge_notes":"Per-MSG Korean text split is deferred to next stage; see sub27_mapping_units.tsv",
            "review_notes":r["review_notes"],
        })
    write_tsv(
        out/"sub27_semantic_resolution_filled.tsv",
        filled,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence","review_hints",
            "semantic_status","decision_type","final_mapping_spec",
            "game_rows_to_skip","korean_split_or_merge_notes","review_notes"
        ]
    )

    print("[6/7] Build audit packet", flush=True)
    packet=[
        "Naruto PSP SUB27 - Manual Semantic Topology Resolution",
        "="*110,
        "",
        "All 177 SUB26 exception blocks were reviewed using KO + JP + US EN context.",
        "This is topology resolution only; byte-budgeted per-MSG Korean rewriting is deferred.",
        "",
    ]
    for bid in range(1,178):
        br=by_bid[bid]
        packet += [
            "",
            "#"*110,
            f"BLOCK {bid:03d}  SUB09 {br['first_sub09_sequence']}..{br['last_sub09_sequence']}",
            f"STATUS={br['semantic_status']}  TYPE={br['decision_types']}",
            f"MAP: {br['final_mapping_spec'] or '(no game mapping)'}",
        ]
        if br["ocr_partial_drop_sequences"]:
            packet.append(f"OCR PARTIAL DROP: {br['ocr_partial_drop_sequences']}")
        if br["video_only_sequences"]:
            packet.append(f"VIDEO ONLY: {br['video_only_sequences']}")
        if br["unmapped_candidate_game_keys"]:
            packet.append(f"GAME-ONLY/DIRECT-TRANSLATE: {br['unmapped_candidate_game_keys']}")
        if br["review_notes"]:
            packet.append(f"NOTE: {br['review_notes']}")
        for mr in [x for x in mapping_rows if int(x["block_id"])==bid]:
            packet += [
                f"  {mr['relation']}: S[{mr['subtitle_sequences']}] -> {mr['game_keys']}",
                f"    KO: {mr['korean_joined']}",
                f"    JP: {mr['japanese_joined']}",
                f"    EN: {mr['english_joined']}",
            ]
    (out/"sub27_semantic_audit_packet.txt").write_text(
        "\n".join(packet)+"\n", encoding="utf-8-sig"
    )

    print("[7/7] Report / deterministic checks", flush=True)
    report={
        "stage":"SUB27",
        "mode":"READ_ONLY_MANUAL_SEMANTIC_TOPOLOGY_RESOLUTION",
        "exception_blocks_resolved":len(block_rows),
        "mapping_units":len(mapping_rows),
        "relation_counts":dict(relation_counts),
        "ocr_partial_subtitle_drops":sum(r["type"]=="OCR_PARTIAL_DROP" for r in exclusion_rows),
        "video_only_subtitles":sum(r["type"]=="VIDEO_ONLY_NO_GAME_MSG" for r in exclusion_rows),
        "anchor_override_units":len(anchor_override_rows),
        "stable_base_game_rows":len(base_stable_games),
        "mapped_game_rows_total":len(mapped_all),
        "all_game_rows":len(game),
        "all_unmapped_game_rows":len(all_unmapped),
        "all_unmapped_voiced":voiced,
        "all_unmapped_unvoiced":unvoiced,
        "exception_candidate_unmapped":len(exception_candidate_unmapped),
        "intentional_speaker_label_corrections":[
            {
                "block_id":x[0],
                "subtitle_sequences":x[1],
                "game_keys":x[2],
                "subtitle_speakers":x[3],
                "game_speaker_codes":x[4],
            }
            for x in intentional_speaker_mismatches
        ],
        "semantic_topology_resolved":True,
        "per_msg_korean_text_finalized":False,
        "direct_translation_of_unmapped_rows_completed":False,
        "game_files_modified":False,
    }
    (out/"sub27_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB27 - Manual Semantic Topology Resolution",
        "",
        f"ExceptionBlocksResolved={len(block_rows)}",
        f"MappingUnits={len(mapping_rows)}",
        "RelationCounts="+json.dumps(dict(relation_counts),ensure_ascii=False,sort_keys=True),
        f"OCRPartialDrops={sum(r['type']=='OCR_PARTIAL_DROP' for r in exclusion_rows)}",
        f"VideoOnlySubtitles={sum(r['type']=='VIDEO_ONLY_NO_GAME_MSG' for r in exclusion_rows)}",
        f"AnchorOverrideUnits={len(anchor_override_rows)}",
        "",
        f"StableBaseGameRows={len(base_stable_games)}",
        f"MappedGameRowsTotal={len(mapped_all)}/{len(game)}",
        f"UnmappedGameRows={len(all_unmapped)}",
        f"UnmappedVoiced={voiced}",
        f"UnmappedUnvoiced={unvoiced}",
        f"ExceptionCandidateUnmapped={len(exception_candidate_unmapped)}",
        "",
        "Intentional speaker-label correction:",
        "  SUB09 #1592 is labeled Kakashi in OCR, but JP/EN/game speaker proves Jiraiya.",
        "",
        "IMPORTANT:",
        "  All 177 exception blocks now have semantic topology decisions.",
        "  This stage does NOT yet split/merge Korean wording into final per-MSG text",
        "  and does NOT translate the 304 game rows without a SUB09 semantic mapping.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
