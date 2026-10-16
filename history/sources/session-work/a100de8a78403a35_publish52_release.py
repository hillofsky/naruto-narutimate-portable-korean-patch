from pathlib import Path
import json,shutil,subprocess,hashlib,urllib.request,urllib.parse,urllib.error,http.client
root=Path(r'LOCAL_PATH');repo=root/'outputs/naruto-narutimate-portable-korean-patch';out=root/'outputs/naruto-sub52-release'
m=json.loads((out/'manifest.json').read_text(encoding='utf-8'));assert m['patch_roundtrip_qa']=='PASS'
release_patch_files=[m['patch_name']]
if m['patch_size']>=2000*1024**2:
    release_patch_files=[];parts=[]
    with (out/m['patch_name']).open('rb') as stream:
        index=1
        while True:
            name=m['patch_name']+'.part'+str(index).zfill(3)
            h=hashlib.sha256();size=0
            with (out/name).open('wb') as f:
                while size<1800*1024**2:
                    b=stream.read(min(8*1024**2,1800*1024**2-size))
                    if not b:break
                    f.write(b);h.update(b);size+=len(b)
            if not size:
                (out/name).unlink();break
            parts.append({'name':name,'size':size,'sha256':h.hexdigest()});release_patch_files.append(name);index+=1
    m['patch_parts']=parts
    (out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'SHA256SUMS.txt').write_text(''.join(v['sha256']+'  '+v['name']+'\n' for v in parts)+m['patch_sha256']+'  '+m['patch_name']+'\n',encoding='ascii')
    shutil.copy2(root/'work/github-publish/join_patch.py',repo/'work/join_patch.py')
    shutil.copy2(root/'work/github-publish/join_patch.py',out/'join_patch.py')
    release_patch_files.append('join_patch.py')
meta=repo/'patch/sub52';meta.mkdir(exist_ok=True)
shutil.copy2(out/'manifest.json',meta/'manifest.json');shutil.copy2(out/'SHA256SUMS.txt',meta/'SHA256SUMS.txt')
readme=repo/'README.md';s=readme.read_text(encoding='utf-8')
s+='''
## SUB52 사전 릴리즈 (2026-10-15)

[v0.2.0-preview 다운로드](httpLOCAL_PATH SUB52U HUDRemaining을 포함한 후속 개발 빌드입니다. 기존 v0.1.0은 그대로 유지합니다. 최신 개발판의 정적 QA는 빌드 보고서 기준 PASS이고, 패치 적용 후 결과 ISO SHA-256 일치를 확인했습니다. 게임 런타임 QA는 PENDING이며 캐릭터 선택 이름 겹침은 미해결입니다. SUB52V/W 조사 결과 자체가 추가 게임 수정인 것은 아닙니다.

Release의 xdelta와 manifest.json을 `patch/sub52/`에 내려받아 적용하세요. 원본은 위에 기록한 동일한 한국판 ISO입니다. 이 패치는 원본에서 SUB52U까지 적용하는 누적 패치이므로 v0.1.0 결과 ISO 위에 적용하지 않습니다.

```powershell
python work/apply_patch.py --manifest patch/sub52/manifest.json --source "원본 한국판.iso" --output "Naruto_Korean_SUB52U.iso" --xdelta "xdelta3.exe"
```

결과 ISO는 4,292,155,392 bytes이며 4GiB까지 여유가 2,811,904 bytes입니다. 임시 출력과 결과 파일을 저장할 충분한 공간이 필요합니다. 실기 호환성/전체 플레이 검증은 기록되지 않았습니다.
'''
if m.get('patch_parts'):
 s+='\n패치가 분할되어 있으므로 Release의 .part 파일 전부, manifest.json과 join_patch.py를 같은 폴더에 받은 뒤 `python join_patch.py`로 합치세요. 조립된 xdelta와 manifest.json을 patch/sub52/에 두면 위 명령을 사용할 수 있습니다. 조립 시 각 조각과 완성 패치의 해시를 검사합니다.\n'
readme.write_text(s,encoding='utf-8')
p=repo/'docs/SUB52_PROGRESS.md';s=p.read_text(encoding='utf-8');s=s.replace('SUB52U용 새 xdelta 릴리즈는 생성하지 않았습니다. 최신 개발 상태를 기존 배포 패치에 반영된 것으로 해석하지 마세요.','2026-10-15 v0.2.0-preview로 SUB52U 누적 xdelta를 추가했습니다. 새 메타데이터는 patch/sub52/manifest.json입니다. 원본에서 재적용한 결과의 크기와 SHA-256이 SUB52U와 일치함을 검증했습니다. 기존 v0.1.0 패치는 변경하지 않았습니다.')
p.write_text(s,encoding='utf-8')
p=repo/'docs/KNOWN_ISSUES.md'
with p.open('a',encoding='utf-8') as f:f.write('\n## v0.2.0-preview (SUB52U)\n\nSUB52U 정적 QA는 보고서 기준 PASS, 누적 xdelta 왕복 검증은 PASS입니다. 런타임 QA는 PENDING이며 캐릭터 선택 이름 겹침은 NOT FIXED입니다. SUB52W의 ISO9660 PASS는 구조 조사 성공이며 게임 화면 검증을 대신하지 않습니다.\n')
p=repo/'docs/WORK_LOG.md'
with p.open('a',encoding='utf-8') as f:f.write('\n## v0.2.0-preview 배포 — 2026-10-15\n\n한국판 원본과 기존 SUB52U ISO 해시를 직접 확인하고 누적 xdelta를 생성했습니다. 원본에 다시 적용한 결과의 크기·SHA-256이 SUB52U와 일치했습니다. ISO 자체는 다시 빌드하지 않았습니다. 기존 v0.1.0의 패치와 메타데이터는 유지합니다.\n')
files=sorted(str(p.relative_to(repo)).replace('\\','/') for p in repo.rglob('*') if p.is_file() and '.git' not in p.relative_to(repo).parts and p.suffix!='.xdelta')
(repo/'PUBLISH_CONTENTS.txt').write_text('\n'.join(files)+'\n',encoding='utf-8')
# The application tool rejects an incorrect source for the new manifest without writing output.
wrong=root/'work/github-publish/wrong.iso';wrong.write_bytes(b'wrong source')
a=subprocess.run(['py','-3.12',str(repo/'work/apply_patch.py'),'--manifest',str(meta/'manifest.json'),'--source',str(wrong),'--output',str(root/'work/github-publish/invalid52.iso')],capture_output=True)
assert a.returncode==1 and not (root/'work/github-publish/invalid52.iso').exists()
subprocess.run(['git','add','README.md','PUBLISH_CONTENTS.txt','docs/SUB52_PROGRESS.md','docs/KNOWN_ISSUES.md','docs/WORK_LOG.md','patch/sub52','work'],cwd=repo,check=True)
subprocess.run(['git','diff','--cached','--check'],cwd=repo,check=True)
subprocess.run(['git','commit','-q','-m','Prepare verified SUB52U cumulative preview release'],cwd=repo,check=True)
subprocess.run(['git','push','origin','main'],cwd=repo,check=True)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,check=True)
c=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
headers={'Authorization':'Bearer '+c['password'],'User-Agent':'Codex-patch-publish','Accept':'application/vnd.github+json'}
base='/repos/hillofsky/naruto-narutimate-portable-korean-patch'
def api(path,body=None,method=None):
 req=urllib.request.Request('httpLOCAL_PATH'+path,headers=headers,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),method=method)
 with urllib.request.urlopen(req,timeout=40) as response:return json.load(response)
notes='''SUB52U HUDRemaining 기준 후속 개발 사전 릴리즈입니다. SUB52V/W는 정리 및 읽기 전용 조사 단계이며, 최신 게임 수정 기준은 SUB52U입니다.

- SUB52 단계의 추가 텍스트·UI 작업을 누적한 빌드
- 최종 SUB52U에서는 HUD 이름 TEX_xgauge5의 검증된 영역 21개를 번역하고 FSTS 묶음 1개 재구축
- 원본/결과 ISO 해시 확인, 누적 xdelta 적용 후 결과 크기·SHA-256 일치 검증 PASS
- 정적 QA는 기존 빌드 보고서 기준 PASS. 런타임 QA PENDING, 캐릭터 선택 이름 겹침 NOT FIXED. 전체 플레이/실기 호환성 검증은 기록되지 않았습니다.

## 다운로드와 적용
xdelta 파일, manifest.json, SHA256SUMS.txt를 받으세요. 한국판 원본 ULKS46086에 적용하는 누적 패치이며 기존 v0.1.0 패치 결과에 적용하면 안 됩니다.
원본 SHA-256: 6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7
원본 크기: 634,257,408 bytes.

```powershell
xdelta3 -d -s "원본 한국판.iso" "naruto-korean-v0.2.0-preview-sub52u.xdelta" "Naruto_Korean_SUB52U.iso"
```

해시를 자동 검증하려면 저장소 work/apply_patch.py에 --manifest patch/sub52/manifest.json을 지정하세요. 자세한 방법은 README와 docs/SUB52_PROGRESS.md에 있습니다.

결과 ISO 크기: 4,292,155,392 bytes. SHA-256: 3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f.
최신 ISO를 일반 실행하고 일반 저장 데이터를 사용해 확인하세요. 세이브스테이트는 이전 메모리/이미지를 복원할 수 있습니다.

기존 v0.1.0은 유지합니다. 원본·완성 ISO는 배포하지 않습니다.'''
if m.get('patch_parts'):
 notes+='\n\n## 분할 파일 합치기\nGitHub 단일 파일 크기 제한 때문에 패치를 분할했습니다. 모든 .part 파일, manifest.json, join_patch.py를 같은 폴더에 다운로드하고 `python join_patch.py`를 실행하세요. 각 조각 및 완성 xdelta의 해시를 검사합니다. 합쳐진 xdelta에 위 적용 명령을 사용하세요. 조각과 조립된 패치를 함께 저장할 추가 디스크 공간이 필요합니다.'
r=api(base+'/releases',{'tag_name':'v0.2.0-preview','target_commitish':commit,'name':'v0.2.0-preview — SUB52U HUD·추가 번역','body':notes,'draft':True,'prerelease':True})
(out/'release_state.json').write_text(json.dumps({'id':r['id'],'url':r['html_url']}),encoding='utf-8')
print('RELEASE_DRAFT_CREATED',r['id'],flush=True)
for name in release_patch_files+['manifest.json','SHA256SUMS.txt']:
 f=out/name;u=urllib.parse.urlsplit(r['upload_url'].split('{')[0]+'?'+urllib.parse.urlencode({'name':name}))
 conn=http.client.HTTPSConnection(u.hostname,timeout=600);conn.putrequest('POST',u.path+'?'+u.query)
 for k,v in headers.items():conn.putheader(k,v)
 conn.putheader('Content-Type','application/octet-stream');conn.putheader('Content-Length',str(f.stat().st_size));conn.endheaders()
 sent=0;last=0
 with f.open('rb') as stream:
  for b in iter(lambda:stream.read(2*1024*1024),b''):
   conn.send(b);sent+=len(b)
   if sent-last>=128*1024*1024:print('UPLOAD_PROGRESS',name,round(100*sent/f.stat().st_size,1),flush=True);last=sent
 response=conn.getresponse();data=response.read();conn.close()
 assert response.status in [200,201],str(response.status)+data[:300].decode()
 asset=json.loads(data);assert asset['size']==f.stat().st_size
 if asset.get('digest'):
  expected=m['patch_sha256'] if name==m['patch_name'] else next((v['sha256'] for v in m.get('patch_parts',[]) if v['name']==name),None)
  if expected:assert asset['digest']=='sha256:'+expected
 print('ASSET_VERIFIED',name,flush=True)
r=api(base+'/releases/'+str(r['id']),{'draft':False,'prerelease':True},method='PATCH')
verified=api(base+'/releases/tags/v0.2.0-preview');assert not verified['draft'] and verified['prerelease']
(out/'release_state.json').write_text(json.dumps({'id':r['id'],'url':r['html_url'],'published':True,'commit':commit},indent=2),encoding='utf-8')
print('PUBLISHED',r['html_url'],flush=True)

