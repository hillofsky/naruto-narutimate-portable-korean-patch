"""Read-only validation of the published historical evidence index."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 spec=json.loads((ROOT/'docs/HISTORY_INVENTORY.json').read_text(encoding='utf-8'))
 failures=[];checked={}
 for rec in spec['records']:
  rel=rec.get('published_path')
  if not rel:continue
  path=(ROOT/rel).resolve()
  if ROOT not in path.parents:
   failures.append('Outside repository: '+rel);continue
  if not path.is_file():failures.append('Missing: '+rel);continue
  if rel not in checked:checked[rel]=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
  if checked[rel]!=rec['published_sha256']:failures.append('Changed: '+rel)
 for error in failures[:30]:print('FAIL:',error)
 if failures:return 1
 print('PASS:',len(spec['records']),'inventory records;',len(checked),'unique published files verified.')
 print('Archived scripts NOT_EXECUTED; game/runtime verification NOT_RUN. See exclusions and scope warnings.')
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except (OSError,ValueError,KeyError) as exc:print('FAIL:',exc,file=sys.stderr);sys.exit(1)
