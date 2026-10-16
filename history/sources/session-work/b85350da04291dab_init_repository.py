import urllib.request,urllib.error,json,subprocess
from pathlib import Path
p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,check=True)
c=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
token=c['password'];headers={'Authorization':'Bearer '+token,'User-Agent':'Codex-patch-publish','Accept':'application/vnd.github+json'}
def api(path,body=None):
 req=urllib.request.Request('httpLOCAL_PATH'+path,headers=headers,data=None if body is None else json.dumps(body).encode())
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
u=api('/user');name='naruto-narutimate-portable-korean-patch'
try:r=api('/repos/hillofsky/'+name);print('REPO_EXISTS',r['html_url'])
except urllib.error.HTTPError as e:
 if e.code!=404:raise
 r=api('/user/repos',{'name':name,'description':'PSP 나루토 나루티밋 포터블 — 무환성의 권(ULKS46086) 비공식 한국어화. 1차 작업 완료: 번역 패치, 작업 도구 및 인계 문서.','private':False,'auto_init':False});print('REPO_CREATED',r['html_url'])
repo=Path(r'LOCAL_PATH')
subprocess.run(['git','init','-b','main'],cwd=repo,check=True)
subprocess.run(['git','config','user.name',u.get('name') or u['login']],cwd=repo,check=True)
subprocess.run(['git','config','user.email',str(u['id'])+'+'+u['login']+'@users.noreply.github.com'],cwd=repo,check=True)
subprocess.run(['git','remote','add','origin',r['clone_url']],cwd=repo,check=True)
print('REPOSITORY_INITIALIZED')
