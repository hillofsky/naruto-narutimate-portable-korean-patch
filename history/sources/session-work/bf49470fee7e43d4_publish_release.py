import urllib.request,urllib.parse,urllib.error,http.client,json,subprocess,time
from pathlib import Path
repo=Path(r'LOCAL_PATH')
p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,check=True)
c=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x);token=c['password']
headers={'Authorization':'Bearer '+token,'User-Agent':'Codex-patch-publish','Accept':'application/vnd.github+json'}
base='/repos/hillofsky/naruto-narutimate-portable-korean-patch'
def api(path,body=None,method=None):
 req=urllib.request.Request('httpLOCAL_PATH'+path,headers=headers,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),method=method)
 with urllib.request.urlopen(req,timeout=40) as r:return json.load(r)
m=json.loads((repo/'patch/manifest.json').read_text(encoding='utf-8'))
assert m['patch_roundtrip_qa']=='PASS'
body='''1차 작업 완료판입니다. 배포 기준은 MOV06E + SUB51P FIX13 FullAtlas입니다.

- 스토리 대사 1,976행 의미/레이아웃 검수, 영상 자막 통합
- 화자명·안내문·메뉴 및 추가 번역 후보 1,140개 적용
- 타이틀/모드 선택/설정/자택/스킬 등의 UI 보완
- 한국판 원본에 xdelta 적용 후 최종 ISO SHA-256 일치 검증 완료

원본은 한국판 ULKS46086 ISO이며, 일본판/북미판/이전 패치본에는 적용할 수 없습니다. 원본과 결과 해시는 manifest.json을 확인하세요.

다운로드: naruto-korean-v0.1.0.xdelta와 manifest.json. 저장소 README의 xdelta3 명령 또는 work/apply_patch.py로 적용합니다. 원본·결과 ISO는 배포하지 않습니다.

최신 빌드의 정적 QA는 PASS입니다. 빌드 보고서에는 런타임 QA가 PENDING으로 남아 있고 전체 플레이 검증은 기록되지 않았습니다. 이는 1차 작업 완료 마일스톤이며 모든 분기/실기의 검증 완료를 뜻하지 않습니다. docs/KNOWN_ISSUES.md를 참고하세요.

세이브스테이트는 이전 메모리와 이미지를 복원합니다. 최신 ISO를 일반 실행하고 일반 저장 데이터를 불러와 확인하세요.'''
r=api(base+'/releases',{'tag_name':'v0.1.0','target_commitish':'main','name':'v0.1.0 — 한국어화 1차 작업 완료','body':body,'draft':True,'prerelease':False})
print('DRAFT_RELEASE_CREATED',r['id'],flush=True)
(repo.parent.parent/'work/github-publish/release_state.json').write_text(json.dumps({'id':r['id'],'url':r['html_url']}))
for filename in [m['patch_name'],'manifest.json']:
 f=repo/'patch'/filename
 url=r['upload_url'].split('{')[0]+'?'+urllib.parse.urlencode({'name':filename})
 u=urllib.parse.urlsplit(url);conn=http.client.HTTPSConnection(u.hostname,timeout=600)
 conn.putrequest('POST',u.path+'?'+u.query)
 for k,v in headers.items():conn.putheader(k,v)
 conn.putheader('Content-Type','application/octet-stream');conn.putheader('Content-Length',str(f.stat().st_size));conn.endheaders()
 sent=0;last=0
 with f.open('rb') as stream:
  while True:
   chunk=stream.read(2*1024*1024)
   if not chunk:break
   conn.send(chunk);sent+=len(chunk)
   if sent-last>=64*1024*1024:
    print('UPLOAD_PROGRESS',filename,round(100*sent/f.stat().st_size,1),flush=True);last=sent
 response=conn.getresponse();payload=response.read();conn.close()
 if response.status not in [200,201]:raise RuntimeError('Upload failed HTTP '+str(response.status)+': '+payload[:600].decode())
 asset=json.loads(payload)
 assert asset['size']==f.stat().st_size
 if filename==m['patch_name'] and asset.get('digest'):assert asset['digest']=='sha256:'+m['patch_sha256']
 print('ASSET_VERIFIED',filename,asset['size'],flush=True)
r=api(base+'/releases/'+str(r['id']),{'draft':False},method='PATCH')
print('RELEASE_PUBLISHED',r['html_url'],flush=True)
(repo.parent.parent/'work/github-publish/release_state.json').write_text(json.dumps({'id':r['id'],'url':r['html_url'],'published':True}))

