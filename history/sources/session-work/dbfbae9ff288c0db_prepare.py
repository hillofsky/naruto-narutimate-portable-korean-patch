from pathlib import Path
import hashlib,json,subprocess,shutil,csv
root=Path(r'LOCAL_PATH')
project=Path(r'PROJECT_ROOT')
repo=root/'outputs'/'naruto-narutimate-portable-korean-patch'
for d in ['docs','data/dialogue','data/menu','data/font','work','patch','docs/verification']: (repo/d).mkdir(parents=True,exist_ok=True)
source=next((project/'kr').glob('*.iso'))
target=project/'Naruto_KR_MOV06E_SUB51P_FIX13_FullAtlas.iso'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
metadata={'version':'v0.1.0','build':'SUB51P_FIX13_FULL_ATLAS','source_name':source.name,'source_size':source.stat().st_size,'source_sha256':sha(source),'target_size':target.stat().st_size,'target_sha256':sha(target),'game_id':'ULKS46086','user_status':'1차 작업 완료 (2026-10-07)','static_qa':'PASS','full_playthrough_qa':'NOT_RECORDED','latest_runtime_qa':'PENDING_IN_BUILD_REPORT'}
assert metadata['target_sha256']=='1029c34956e23d4eee229a40e995f502fa8a2f249487f16de7fb72869d210cdb'
(repo/'patch/manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(root/'work/github-publish/build_paths.json').write_text(json.dumps({'source':str(source),'target':str(target),'repo':str(repo)}),encoding='utf-8')
for name in ['sub36_patcher_ready_1976_semanticqa_23x2.tsv','sub36_semantic_fixes_42.tsv']:
 shutil.copy2(project/name,repo/'data/dialogue'/name)
for name in ['sub51d_translation_candidates_chatgpt_translated.tsv','sub51d_translation_occurrences.tsv','sub51d_stage35r_slot_inventory.tsv']:
 shutil.copy2(project/name,repo/'data/menu'/name)
for p in (project/'analysis/sub/sub51d_full_text_apply').glob('*mapping*.tsv'):shutil.copy2(p,repo/'data/font'/p.name)
for p in (root/'outputs/분석').glob('*.tsv'):shutil.copy2(p,repo/'data/menu'/p.name)
# Preserve project-relative paths for historical build scripts. Inputs and intermediate game resources are external.
patterns=['build_sub*.py','naruto_sub*.py','sub44_base.py','run_naruto_sub*.ps1']
for pat in patterns:
 for p in project.glob(pat):shutil.copy2(p,repo/'work'/p.name)
for rel in ['analysis/stage14','analysis/stage15','analysis/shared']:
 for p in (project/rel).glob('*.py'):
  dest=repo/'work'/p.relative_to(project);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
for name in ['build_sub39.py','build_sub40.py','build_sub41.py','build_sub42.py','tutorial_ko.json','menu_text_ko.json']:
 p=root/'work'/name
 if p.exists():
  dest=repo/'work/codex_sub39_42'/name;dest.parent.mkdir(exist_ok=True);shutil.copy2(p,dest)
for rel in ['analysis/sub/sub51d_full_text_apply/SUB51D_static_verification.json','analysis/sub/sub51p_fix13_full_atlas/build/SUB51O_static_verification.json']:
 obj=json.loads((project/rel).read_text(encoding='utf-8-sig'));obj.pop('final_iso',None)
 (repo/'docs/verification'/Path(rel).name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(repo/'.gitignore').write_text('*.iso\n*.cso\n*.ppst\n*.dat\n*.idx\n*.ccs\n*.bin\n*.BIN\n*.pmf\n*.PMF\n__pycache__/\n*.pyc\n.env*\nlocal/\n',encoding='utf-8')
(repo/'.gitattributes').write_text('* text=auto\n*.xdelta binary\n*.png binary\n',encoding='utf-8')
print(json.dumps(metadata,ensure_ascii=False))
xdelta=Path(r'LOCAL_PATH')
patch=repo/'patch/naruto-korean-v0.1.0.xdelta'
subprocess.run([str(xdelta),'-e','-f','-s',str(source),str(target),str(patch)],check=True)
metadata.update(patch_name=patch.name,patch_size=patch.stat().st_size,patch_sha256=sha(patch))
(repo/'patch/manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('PATCH_CREATED',patch.stat().st_size,flush=True)
restored=root/'work/github-publish/roundtrip.iso'
subprocess.run([str(xdelta),'-d','-f','-s',str(source),str(patch),str(restored)],check=True)
assert sha(restored)==metadata['target_sha256'],'Round-trip mismatch'
metadata['patch_roundtrip_qa']='PASS'
(repo/'patch/manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
restored.unlink()
print('ROUNDTRIP_PASS',flush=True)
