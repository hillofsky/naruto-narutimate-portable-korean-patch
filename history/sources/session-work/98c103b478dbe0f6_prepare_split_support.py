from pathlib import Path
p=Path('work/github-publish/publish52_release.py')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("assert m['patch_size']<2*1024**3,'Split release asset before publishing: exceeds GitHub file size limit'",'''release_patch_files=[m['patch_name']]
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
    (out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')
    (out/'SHA256SUMS.txt').write_text(''.join(v['sha256']+'  '+v['name']+'\\n' for v in parts)+m['patch_sha256']+'  '+m['patch_name']+'\\n',encoding='ascii')
    shutil.copy2(root/'work/github-publish/join_patch.py',repo/'work/join_patch.py')
    shutil.copy2(root/'work/github-publish/join_patch.py',out/'join_patch.py')
    release_patch_files.append('join_patch.py')''')
s=s.replace("readme.write_text(s,encoding='utf-8')",'''if m.get('patch_parts'):
 s+='\\n패치가 분할되어 있으므로 Release의 .part 파일 전부, manifest.json과 join_patch.py를 같은 폴더에 받은 뒤 `python join_patch.py`로 합치세요. 조립된 xdelta와 manifest.json을 patch/sub52/에 두면 위 명령을 사용할 수 있습니다. 조립 시 각 조각과 완성 패치의 해시를 검사합니다.\\n'
readme.write_text(s,encoding='utf-8')''')
s=s.replace("'patch/sub52','work/apply_patch.py'","'patch/sub52','work'")
s=s.replace("r=api(base+'/releases',",'''if m.get('patch_parts'):
 notes+='\\n\\n## 분할 파일 합치기\\nGitHub 단일 파일 크기 제한 때문에 패치를 분할했습니다. 모든 .part 파일, manifest.json, join_patch.py를 같은 폴더에 다운로드하고 `python join_patch.py`를 실행하세요. 각 조각 및 완성 xdelta의 해시를 검사합니다. 합쳐진 xdelta에 위 적용 명령을 사용하세요. 조각과 조립된 패치를 함께 저장할 추가 디스크 공간이 필요합니다.'
r=api(base+'/releases',''')
s=s.replace("for name in [m['patch_name'],'manifest.json','SHA256SUMS.txt']:","for name in release_patch_files+['manifest.json','SHA256SUMS.txt']:")
p.write_text(s,encoding='utf-8')
