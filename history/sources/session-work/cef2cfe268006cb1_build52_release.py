from pathlib import Path
import hashlib,json,subprocess,time
root=Path(r'LOCAL_PATH');repo=root/'outputs/naruto-narutimate-portable-korean-patch';out=root/'outputs/naruto-sub52-release';out.mkdir(exist_ok=True)
source=next(Path(r'PROJECT_ROOT\kr').glob('*.iso'))
target=Path(r'PROJECT_ROOT\analysis\sub\sub52u_hud_remaining\Naruto_KR_MOV06E_SUB52U_HUDRemaining_Compact.iso')
xdelta=Path(r'LOCAL_PATH')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
 return h.hexdigest()
print('VERIFYING_SOURCE_AND_TARGET',flush=True)
assert sha(source)=='6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7'
assert sha(target)=='3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f'
patch=out/'naruto-korean-v0.2.0-preview-sub52u.xdelta'
print('ENCODING_PATCH',flush=True)
subprocess.run([str(xdelta),'-e','-f','-s',str(source),str(target),str(patch)],check=True)
print('PATCH_ENCODED',patch.stat().st_size,flush=True)
m={'version':'v0.2.0-preview','build':'SUB52U_HUD_NAMES_COMPACT','game_id':'ULKS46086','source_name':source.name,'source_size':source.stat().st_size,'source_sha256':'6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7','target_size':target.stat().st_size,'target_sha256':'3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f','patch_name':patch.name,'patch_size':patch.stat().st_size,'patch_sha256':sha(patch),'static_qa':'PASS_PER_BUILD_REPORT','runtime_qa':'PENDING','full_playthrough_qa':'NOT_RECORDED','character_select_name_overlap':'NOT_FIXED','note':'SUB52V/W are cleanup and read-only investigation; latest game build is SUB52U.'}
(out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('DECODING_ROUNDTRIP',flush=True)
restored=root/'work/github-publish/sub52-roundtrip.iso'
subprocess.run([str(xdelta),'-d','-f','-s',str(source),str(patch),str(restored)],check=True)
assert restored.stat().st_size==m['target_size'] and sha(restored)==m['target_sha256']
restored.unlink();m['patch_roundtrip_qa']='PASS'
(out/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(out/'SHA256SUMS.txt').write_text(m['patch_sha256']+'  '+patch.name+'\n',encoding='ascii')
print('ROUNDTRIP_PASS',flush=True)
