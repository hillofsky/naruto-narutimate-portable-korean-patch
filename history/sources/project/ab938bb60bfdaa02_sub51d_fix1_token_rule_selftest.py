import re
R=re.compile(r"<(?!ruby)[^>]+>|%[-+0-9.#]*[sdif]")
assert R.findall("お<ruby色気|いろけ>の<ruby術|じゅつ>")==[]
assert R.findall("<RED>値%d<BLACK>")==["<RED>","%d","<BLACK>"]
assert R.findall("ABC<br>DEF")==["<br>"]
print("SUB51D FIX1 token-rule self-test: PASS")
