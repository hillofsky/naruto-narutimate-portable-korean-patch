from pathlib import Path
import subprocess,json,urllib.request,urllib.error,urllib.parse,hashlib
root=Path(r'LOCAL_PATH')
patch=Path(r'LOCAL_PATH')
p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,check=True)
c=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
headers={'Authorization':'Bearer '+c['password'],'User-Agent':'Codex-release-publish','Accept':'application/vnd.github+json'}
base='/repos/hillofsky/musou-orochi-2-special-korean-patch'
def api(path,body=None,method=None):
 req=urllib.request.Request('httpLOCAL_PATH'+path,headers=headers,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),method=method)
 with urllib.request.urlopen(req,timeout=40) as r:return json.load(r)
# Release precisely the current repository artifact, rather than a different local build.
entry=api(base+'/contents/patch/preview.xdelta')
with urllib.request.urlopen(entry['download_url'],timeout=30) as response:remote=response.read()
blob=patch.read_bytes();digest=hashlib.sha256(blob).hexdigest()
assert remote==blob,'Local patch differs from current repository'
commit=api(base+'/commits/main')['sha']
manifest={'version':'v0.1.0-preview','status':'unfinished_preview','game_id':'ULJM06097','source_size':1798832128,'source_sha256':'d5bf03a9647f0583f6cf334841b7063f6567591db0ddf4e9ca369c4076625a9f','patch_name':'preview.xdelta','patch_size':len(blob),'patch_sha256':digest,'repository_commit':commit,'verification':'Release asset matches existing repository patch; no new ISO round-trip performed in this release operation.'}
out=root/'outputs/musou-orochi-2-special-release';out.mkdir(exist_ok=True)
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(out/'SHA256SUMS.txt').write_text(digest+'  preview.xdelta\n',encoding='ascii')
notes='''현재 저장소의 기존 `patch/preview.xdelta`를 다운로드하기 쉽게 등록한 미리보기 릴리즈입니다. 새로운 번역 수정이 추가된 빌드는 아닙니다.

## 적용 대상
PSP 일본판 『無双OROCHI 2 Special』, ULJM06097.
원본 크기: 1,798,832,128 bytes.
원본 SHA-256: `D5BF03A9647F0583F6CF334841B7063F6567591DB0DDF4E9CA369C4076625A9F`.

## 적용 방법
`preview.xdelta`를 다운로드하고 본인이 보유한 일치하는 원본에 xdelta3를 적용합니다.
```powershell
xdelta3 -d -s "Musou Orochi 2 Special (Japan).iso" "preview.xdelta" "Musou Orochi 2 Special Korean preview.iso"
```
PPSSPP에서 결과 ISO를 새로 실행하고 일반 저장 데이터를 불러와 확인하세요. 예전 세이브스테이트는 이전 RAM을 복원할 수 있습니다.

## 남은 문제
최근 PPSSPP 슬롯 1·2에서 확인한 미번역 대사는 아직 반영되지 않았습니다. 상인 인사말, 일부 메뉴 겹침, 이름 표시 등의 확인 필요 사항과 전체 플레이 미검증 범위가 남아 있습니다. 정식 완료판이 아닙니다. 자세한 내용은 저장소 README와 docs/AI_HANDOFF.md를 참고하세요.

## 파일 검증
첨부한 manifest.json과 SHA256SUMS.txt로 패치 해시를 확인할 수 있습니다. 릴리즈 파일은 현재 저장소 패치와 바이트 일치를 확인했습니다. 이번 등록 작업에서 새로운 ISO 재빌드나 전체 플레이 검증은 수행하지 않았습니다.
원본/결과 ISO는 배포하지 않습니다.'''
tag='v0.1.0-preview'
try:
 release=api(base+'/releases/tags/'+tag)
 print('EXISTING_RELEASE',release['html_url'],flush=True)
except urllib.error.HTTPError as e:
 if e.code!=404:raise
 release=api(base+'/releases',{'tag_name':tag,'target_commitish':commit,'name':'v0.1.0-preview — 한국어화 미리보기 패치','body':notes,'prerelease':True,'draft':True})
assets={a['name']:a for a in release.get('assets',[])}
for name,data in [('preview.xdelta',blob),('manifest.json',(out/'manifest.json').read_bytes()),('SHA256SUMS.txt',(out/'SHA256SUMS.txt').read_bytes())]:
 if name in assets:
  assert assets[name]['size']==len(data)
  continue
 url=release['upload_url'].split('{')[0]+'?'+urllib.parse.urlencode({'name':name})
 req=urllib.request.Request(url,data=data,headers={**headers,'Content-Type':'application/octet-stream'})
 with urllib.request.urlopen(req,timeout=90) as response:asset=json.load(response)
 assert asset['size']==len(data)
 if name=='preview.xdelta' and asset.get('digest'):assert asset['digest']=='sha256:'+digest
 print('UPLOADED',name,len(data),flush=True)
release=api(base+'/releases/'+str(release['id']),{'draft':False,'prerelease':True},method='PATCH')
verify=api(base+'/releases/tags/'+tag)
assert not verify['draft'] and verify['prerelease']
assert any(a['name']=='preview.xdelta' and a['state']=='uploaded' for a in verify['assets'])
print('RELEASE_PUBLISHED',verify['html_url'])
(out/'publication.json').write_text(json.dumps({'release':verify['html_url'],'commit':commit,'patch_sha256':digest},indent=2)+'\n',encoding='utf-8')
