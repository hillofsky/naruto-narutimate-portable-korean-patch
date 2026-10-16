"""Verify and combine release patch parts next to manifest.json. Requires Python 3."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
m=json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
parts=m.get('patch_parts')
if not parts:raise SystemExit('This release is not split; use the full xdelta directly.')
output=root/m['patch_name'];temporary=output.with_name(output.name+'.joining')
if output.exists() or temporary.exists():raise SystemExit('Output or temporary file already exists. Choose a clean download folder.')
whole=hashlib.sha256()
try:
 with temporary.open('xb') as destination:
  for part in parts:
   source=root/part['name']
   if source.stat().st_size!=part['size']:raise ValueError('Wrong part size: '+part['name'])
   h=hashlib.sha256()
   with source.open('rb') as stream:
    for b in iter(lambda:stream.read(8*1024*1024),b''):
     destination.write(b);h.update(b);whole.update(b)
   if h.hexdigest()!=part['sha256']:raise ValueError('Part hash mismatch: '+part['name'])
   print('Verified',part['name'])
 if temporary.stat().st_size!=m['patch_size'] or whole.hexdigest()!=m['patch_sha256']:raise ValueError('Combined patch verification failed')
 temporary.rename(output)
except Exception:
 temporary.unlink(missing_ok=True)
 raise
print('Verified patch ready:',output.name)
