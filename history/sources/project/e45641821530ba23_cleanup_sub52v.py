#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative, auditable Naruto PSP build-artifact cleanup (Python stdlib only)."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import traceback
from datetime import datetime, timezone

EXPECTED_CURRENT_SHA = '3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f'
CURRENT_ISO = Path('analysis/sub/sub52u_hud_remaining/Naruto_KR_MOV06E_SUB52U_HUDRemaining_Compact.iso')
STABLE_STAGE_TOKENS = ('SUB52J_', 'SUB52K_FIX2_', 'SUB52M_', 'SUB52N_FIX1_', 'SUB52T_', 'SUB52U_', 'SUB52D2_', 'SUB52E_')
# Only exact, historically obsolete/failing build ISO names can be deleted.
OBSOLETE_NAMES = {
    'naruto_kr_mov06e_sub52g_finalresidual.iso',
    'naruto_kr_mov06e_sub52g_fix1_finalresidual.iso',
    'naruto_kr_mov06e_sub52h_residualfix2.iso',
    'naruto_kr_mov06e_sub52h_fix3.iso',
    'naruto_kr_mov06e_sub52i_p0_rollback.iso',
    'naruto_kr_mov06e_sub52i_p0_rollback_fix1.iso',
    'naruto_kr_mov06e_sub52k_facenames.iso',
    'naruto_kr_mov06e_sub52k_fix1_compact.iso',
    'naruto_kr_mov06e_sub52n_rewardsafe.iso',
}
PARTIAL_PATTERNS = ('.partial', '.partial.iso', '.iso.partial', '.iso.part', '.part.iso', '.iso.tmp', '.tmp.iso', '.iso.incomplete')
OLD_SECONDS = 30 * 60


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def is_inside(path, base):
    try:
        path.resolve(strict=False).relative_to(base.resolve(strict=True))
        return True
    except (ValueError, FileNotFoundError, OSError):
        return False


def normal_path(path):
    return os.path.normcase(os.path.abspath(str(path)))


def byte_size(path):
    if path.is_file():
        return path.stat().st_size
    total = 0
    for cur, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(cur)/d).is_symlink()]
        for n in files:
            file = Path(cur)/n
            if file.is_symlink():
                continue
            try:
                total += file.stat().st_size
            except OSError:
                continue
    return total


def older_than(path, seconds):
    try:
        return path.stat().st_mtime < datetime.now().timestamp() - seconds
    except OSError:
        return False


def write_tsv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter='\t', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def is_safe_stage_dir(stage):
    # Restrict cleanup to named Stage52 build dirs, not arbitrary project dirs.
    return bool(re.match(r'^sub52[a-z](?:[0-9a-z_\-]*)$', stage.name, re.I)) and stage.is_dir() and not stage.is_symlink()


def permitted_obsolete_file(path, root, sub_root):
    if path.name.casefold() not in OBSOLETE_NAMES:
        return False
    if path.is_symlink():
        return False
    if path.parent.resolve() == root.resolve():
        return True
    if not is_inside(path, sub_root):
        return False
    rel = path.relative_to(sub_root)
    # ISO may be in a stage dir itself or its 'build' directory, but never deeper.
    if not 2 <= len(rel.parts) <= 3 or not re.match(r'^sub52', rel.parts[0], re.I):
        return False
    if len(rel.parts) == 3 and rel.parts[1].lower() not in ('build', 'output', 'outputs'):
        return False
    return True


def find_candidates(root, sub_root, active_lines, active_verified):
    candidates = []
    ignored = []
    seen = set()
    def add(path, kind, reason, age_guard=True):
        try:
            if path.is_symlink() or not is_inside(path, root):
                ignored.append(dict(path=str(path), reason='reparse/outside project'))
                return
            p = normal_path(path)
            if p in seen:
                return
            seen.add(p)
            if age_guard and not older_than(path, OLD_SECONDS):
                ignored.append(dict(path=str(path), reason='recent modification (<30 minutes)'))
                return
            if path.is_dir() and kind=='finished_scratch':
                # A directory's own timestamp can be old while a nested file is active.
                for walk_root, subdirs, filenames in os.walk(path, followlinks=False):
                    subdirs[:] = [d for d in subdirs if not (Path(walk_root)/d).is_symlink()]
                    if any(not older_than(Path(walk_root)/n, OLD_SECONDS) for n in filenames):
                        ignored.append(dict(path=str(path), reason='scratch contains recently modified files'))
                        return
            if path.is_file() and kind == 'obsolete_iso':
                if any(s.lower() in path.name.lower() for s in STABLE_STAGE_TOKENS):
                    ignored.append(dict(path=str(path), reason='stable stage name protected'))
                    return
                if not active_verified:
                    ignored.append(dict(path=str(path), reason='PPSSPP process inspection unavailable: ISO protected'))
                    return
                if any(path.name.lower() in line.lower() or str(path).lower() in line.lower() for line in active_lines):
                    ignored.append(dict(path=str(path), reason='currently referenced by PPSSPP command line'))
                    return
            candidates.append(dict(path=str(path), kind=kind, reason=reason, size_bytes=byte_size(path), age_guard=age_guard))
        except OSError as exc:
            ignored.append(dict(path=str(path), reason=f'stat error: {exc}'))

    stages = []
    if sub_root.is_dir() and not sub_root.is_symlink():
        stages = [d for d in sub_root.iterdir() if is_safe_stage_dir(d)]
    # Retired build ISO: exact filename, precise location.
    places = [root]
    for stage in stages:
        places.append(stage)
        for sub in ('build', 'output', 'outputs'):
            child = stage/sub
            if child.is_dir() and not child.is_symlink():
                places.append(child)
    for parent in places:
        try:
            items = parent.iterdir()
            for f in items:
                if f.is_file() and permitted_obsolete_file(f, root, sub_root):
                    add(f, 'obsolete_iso', 'explicitly allowlisted obsolete/failed generated ISO')
        except PermissionError as exc:
            ignored.append(dict(path=str(parent), reason=f'listing denied: {exc}'))

    # Scratch dirs and partial images ONLY, never assets, scripts, source, or logs.
    for stage in stages:
        for name in ('_work', '_scratch', '_temp_build'):
            d = stage/name
            if d.is_dir() and not d.is_symlink():
                # A stage must have a terminal report; do not delete active/incomplete work.
                terminal = any((stage/f).exists() for f in ('SUMMARY.json', 'SUMMARY.txt', 'FAILURE.txt'))
                if terminal:
                    add(d, 'finished_scratch', f'finished stage {stage.name}/{name}')
                else:
                    ignored.append(dict(path=str(d), reason='no terminal report: keep unfinished work'))
        for folder in (stage, stage/'build'):
            if not folder.is_dir() or folder.is_symlink():
                continue
            for f in folder.iterdir():
                if f.is_file() and not f.is_symlink() and '.iso' in f.name.lower() and any(f.name.lower().endswith(s) for s in PARTIAL_PATTERNS):
                    add(f, 'failed_partial', f'old partial ISO or failed copy in {stage.name}')
    return candidates, ignored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--report', required=True)
    ap.add_argument('--target-free-gib', type=float, default=16.0)
    ap.add_argument('--active-file', default='')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--test-mode', action='store_true', help='Unit testing only: bypass full ISO hash')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    report_dir = Path(args.report).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise RuntimeError('Project root missing: '+str(root))
    if not is_inside(report_dir, root):
        raise RuntimeError('Report must stay inside project root')
    sub_root = root/'analysis'/'sub'
    current = root/CURRENT_ISO
    if not current.is_file():
        raise RuntimeError('Verified SUB52U ISO not found: '+str(current))
    if not args.test_mode:
        got = sha256(current)
        if got.lower() != EXPECTED_CURRENT_SHA:
            raise RuntimeError('SUB52U ISO checksum mismatch, cleanup refused: '+got)
    else:
        got = 'TEST_MODE_CHECKSUM_NOT_CHECKED'

    active_verified=False
    active_lines=[]
    if args.active_file:
        payload = json.loads(Path(args.active_file).read_text(encoding='utf-8-sig'))
        active_verified=bool(payload.get('inspection_success'))
        active_lines=payload.get('command_lines',[]) or []
    before=shutil.disk_usage(root).free
    target=round(args.target_free_gib*1024**3)
    candidates, ignored = find_candidates(root, sub_root, active_lines, active_verified)
    # Delete finished scratch and failed partials first; stale ISOs if needed.
    rank={'finished_scratch':0, 'failed_partial':1, 'obsolete_iso':2}
    candidates.sort(key=lambda x:(rank[x['kind']],-x['size_bytes'], x['path'].lower()))
    write_tsv(report_dir/'candidates.tsv', candidates, ['path','kind','reason','size_bytes','age_guard'])
    write_tsv(report_dir/'skipped.tsv', ignored, ['path','reason'])
    print(f'[inventory] {len(candidates)} allowed candidates, {len(ignored)} protected/skipped')
    print(f'[free before] {before/1024**3:.2f} GiB, target {args.target_free_gib:.2f} GiB')
    print(f'[verified SUB52U SHA256] {got}',flush=True)

    actions=[]
    for c in candidates:
        p=Path(c['path'])
        kind=c['kind']
        if kind=='obsolete_iso' and shutil.disk_usage(root).free>=target:
            actions.append({**c, 'action':'KEPT_TARGET_REACHED','actual_removed_bytes':0,'error':''})
            continue
        if not p.exists():
            actions.append({**c, 'action':'SKIPPED_MISSING','actual_removed_bytes':0,'error':''})
            continue
        if args.dry_run:
            actions.append({**c, 'action':'DRY_RUN','actual_removed_bytes':0,'error':''})
            continue
        # Defense in depth against list/race/path changes.
        if p.is_symlink() or not is_inside(p,root):
            actions.append({**c, 'action':'SKIPPED_PATH_CHANGED','actual_removed_bytes':0,'error':''})
            continue
        if kind=='obsolete_iso' and not permitted_obsolete_file(p,root,sub_root):
            actions.append({**c, 'action':'SKIPPED_NOT_ALLOWLISTED','actual_removed_bytes':0,'error':''})
            continue
        try:
            if p.is_dir():
                if p.name not in ('_work','_scratch','_temp_build'):
                    raise RuntimeError('Unexpected directory name')
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
            else:
                raise RuntimeError('Candidate is no longer regular file/directory')
            actions.append({**c, 'action':'DELETED','actual_removed_bytes':c['size_bytes'],'error':''})
            print(f'[deleted] {c["size_bytes"]/1024**3:.3f} GiB | {p}',flush=True)
        except Exception as exc:
            actions.append({**c, 'action':'FAILED','actual_removed_bytes':0,'error':str(exc)})
            print(f'[skip] {p}: {exc}',flush=True)
        # Stream incremental results to survive interrupted cleanup.
        write_tsv(report_dir/'cleanup_actions.tsv', actions, ['path','kind','reason','size_bytes','age_guard','action','actual_removed_bytes','error'])

    write_tsv(report_dir/'cleanup_actions.tsv', actions, ['path','kind','reason','size_bytes','age_guard','action','actual_removed_bytes','error'])
    write_tsv(report_dir/'cleanup_deleted_files.tsv', [a for a in actions if a['action']=='DELETED'],
              ['path','kind','reason','size_bytes','actual_removed_bytes'])
    protected=[]
    for p in [CURRENT_ISO, Path('analysis/sub/sub52t_gauge_hud_compact/Naruto_KR_MOV06E_SUB52T_GaugeHUD_Compact.iso'),
              Path('analysis/sub/sub52n_reward_safe_fix1/Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso'),
              Path('analysis/sub/sub52m_safe_boot_patch/Naruto_KR_MOV06E_SUB52M_SafeBoot.iso'),
              Path('analysis/sub/sub52j_safe_atlas/Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso'),
              Path('analysis/sub/sub52k_fix2_compact/Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso')]:
        protected.append({'path':str(root/p), 'exists':(root/p).is_file()})
    write_tsv(report_dir/'protected_baselines.tsv', protected, ['path','exists'])
    after=shutil.disk_usage(root).free
    summary={
      'stage':'SUB52V_DISK_CLEANUP',
      'dry_run':args.dry_run,
      'source_iso':str(current),
      'source_sha256':got,
      'protected_stages':list(STABLE_STAGE_TOKENS),
      'target_free_gib':args.target_free_gib,
      'free_before_bytes':before,
      'free_after_bytes':after,
      'free_delta_bytes':after-before,
      'removed_listed_bytes':sum(a['actual_removed_bytes'] for a in actions if a['action']=='DELETED'),
      'files_and_dirs_deleted':sum(a['action']=='DELETED' for a in actions),
      'obsolete_iso_deleted':sum(a['action']=='DELETED' and a['kind']=='obsolete_iso' for a in actions),
      'candidate_count':len(candidates),
      'skipped_or_protected':len(ignored),
      'target_reached':after>=target,
      'status':'PASS' if not any(a['action']=='FAILED' for a in actions) else 'PARTIAL',
      'notes':'No source/game ISO, stable SUB52J/KFIX2/M/NFIX1/T/U, assets, scripts or logs are eligible for deletion.',
    }
    (report_dir/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (report_dir/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in summary.items())+'\n',encoding='utf-8-sig')
    print(f'[complete] deleted {summary["files_and_dirs_deleted"]} items, reclaimed {summary["free_delta_bytes"]/1024**3:.2f} GiB (free now {after/1024**3:.2f} GiB)',flush=True)
    if not summary['target_reached']:
        print('[notice] No more allowed obsolete files; protected files left untouched.',flush=True)
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
