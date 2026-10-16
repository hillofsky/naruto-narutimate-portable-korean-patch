import time,json,subprocess
from pathlib import Path
p=Path('outputs/naruto-sub52-release/manifest.json')
while True:
 if p.exists():
  try:
   if json.loads(p.read_text(encoding='utf-8')).get('patch_roundtrip_qa')=='PASS':break
  except (ValueError,OSError):pass
 time.sleep(3)
print('VERIFIED_BUILD_READY; STARTING_PUBLICATION',flush=True)
subprocess.run(['py','-3.12','-u','work/github-publish/publish52_release.py'],check=True)
