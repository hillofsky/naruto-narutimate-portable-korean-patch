import zipfile
from pathlib import Path
p=Path(r'LOCAL_PATH')
with zipfile.ZipFile(p) as z:
 for n in z.namelist():
  if n.lower().endswith(('.py','.ps1','.txt','.json','.md')):
   print(n,z.getinfo(n).file_size)
   if any(s in n.lower() for s in ['summary','report','readme','verification']):
    print(z.read(n).decode('utf-8-sig',errors='replace')[:9000])
