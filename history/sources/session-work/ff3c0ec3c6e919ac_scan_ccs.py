from pathlib import Path
import re,struct,json
root=Path(r'PROJECT_ROOT\analysis\stage9\extracted\kr')
for p in root.glob('*.ccs'):
 b=p.read_bytes()
 hits=[(hex(m.start()),m.group().decode('ascii')) for m in re.finditer(rb'[A-Za-z_][A-Za-z_0-9./ -]{3,60}',b) if re.search(rb'(?i)msg|window|name|help|menu|guide',m.group())]
 if hits: print(p.name,json.dumps(hits[:40]))
for name in ['entry0191__mcmn.ccs','entry0187__home.ccs']:
 p=root/name;b=p.read_bytes(); print(name,b[:160].hex(' '))
