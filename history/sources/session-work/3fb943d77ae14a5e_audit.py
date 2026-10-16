from pathlib import Path
import json,csv,subprocess
root=Path(r'LOCAL_PATH');repo=root/'outputs/naruto-narutimate-portable-korean-patch';p=Path(r'PROJECT_ROOT')
for name in ['sub51o_movie_preservation.tsv','sub51o_core_verification.tsv','sub51o_fsts_rebuild.tsv','sub51o_texture_patch.tsv']:
 (repo/'docs/verification'/name).write_bytes((p/'analysis/sub/sub51p_fix13_full_atlas/build'/name).read_bytes())
for name in ['sub51d_boot_text_patch.tsv','sub51d_tbl_text_patch.tsv']:
 (repo/'data/menu'/name).write_bytes((p/'analysis/sub/sub51d_full_text_apply'/name).read_bytes())
files=[f for f in repo.rglob('*') if f.is_file() and '.git' not in f.relative_to(repo).parts and f.suffix!='.xdelta']
for f in files:
 assert f.suffix.lower() not in {'.iso','.bin','.ccs','.dat','.idx','.pmf','.ppst','.exe','.dll'},str(f)
 assert f.stat().st_size<50*1024*1024,str(f)
(repo/'PUBLISH_CONTENTS.txt').write_text('\n'.join(str(f.relative_to(repo)).replace('\\','/') for f in sorted(files))+'\n',encoding='utf-8')
# Reject a wrong original without creating output.
wrong=root/'work/github-publish/wrong.iso';wrong.write_bytes(b'wrong source')
result=subprocess.run(['py','-3.12',str(repo/'work/apply_patch.py'),'--source',str(wrong),'--output',str(root/'work/github-publish/must_not_exist.iso')],capture_output=True,text=True)
assert result.returncode==1
assert not (root/'work/github-publish/must_not_exist.iso').exists()
print('PUBLICATION_AUDIT_PASS',len(files),'WRONG_SOURCE_REJECTED')
