import subprocess,json,urllib.request
p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,timeout=15)
c=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
if not c.get('password'): print('GITHUB_AUTH_UNAVAILABLE');raise SystemExit()
req=urllib.request.Request('httpLOCAL_PATH',headers={'Authorization':'Bearer '+c['password'],'User-Agent':'Codex-patch-publish'})
try:
 with urllib.request.urlopen(req,timeout=20) as r: print('GITHUB_USER='+json.load(r)['login'])
except Exception as e: print(type(e).__name__,str(e))
