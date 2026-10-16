from pathlib import Path
import zipfile,json
for p in [Path(r'LOCAL_PATH'),Path(r'LOCAL_PATH')]:
 with zipfile.ZipFile(p) as z:
  print(p.name)
  for n in z.namelist():
   if n.endswith(('SUMMARY.txt','RESULT.json')): print(n,z.read(n).decode('utf-8-sig',errors='replace')[:7000])
  print('SCRIPTS',[(n,z.getinfo(n).file_size) for n in z.namelist() if n.endswith(('.py','.ps1'))])
