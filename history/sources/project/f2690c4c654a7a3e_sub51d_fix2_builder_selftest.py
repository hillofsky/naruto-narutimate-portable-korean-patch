from pathlib import Path
import runpy

p=Path(__file__).with_name("build_sub51d_full_text_apply.py")
ns=runpy.run_path(str(p),run_name="sub51d_fix2_import_test")
R=ns["TOKEN_RE"]

assert R.findall("お<ruby色気|いろけ>の<ruby術|じゅつ>")==[]
assert R.findall("<RED>値%d<BLACK>")==["<RED>","%d","<BLACK>"]
assert R.findall("ABC<br>DEF")==["<br>"]
assert R.findall("<KOFF>（<KON>文<KOFF>）<KON>")==["<KOFF>","<KON>","<KOFF>","<KON>"]

# Also prove the special separator path is safe ASCII, not a CP932 donor code.
encoded=ns["encode_text"]("서기·점프", {"서":"8140","기":"8141","점":"8142","프":"8143"})
assert b"/" in encoded

print("SUB51D FIX2 builder import/token/encoding self-test: PASS")
