"""Apply release patch and verify original and resulting SHA-256."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--patch', type=Path, default=ROOT / 'patch/naruto-korean-v0.1.0.xdelta')
    p.add_argument('--manifest', type=Path, default=ROOT / 'patch/manifest.json')
    p.add_argument('--xdelta', default='xdelta3')
    a = p.parse_args()
    m = json.loads(a.manifest.read_text(encoding='utf-8-sig'))
    if a.output.exists():
        raise ValueError('Output already exists; choose a new filename.')
    for path, size_key, hash_key in [(a.source, 'source_size', 'source_sha256'),
                                     (a.patch, 'patch_size', 'patch_sha256')]:
        if path.stat().st_size != m[size_key] or sha256(path) != m[hash_key]:
            raise ValueError('Input verification failed: ' + str(path))
    exe = shutil.which(a.xdelta)
    if not exe:
        raise FileNotFoundError('xdelta3 executable not found.')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.output.with_name(a.output.name + '.partial')
    if temporary.exists():
        raise ValueError('Temporary output already exists: ' + str(temporary))
    try:
        subprocess.run([exe, '-d', '-s', str(a.source), str(a.patch), str(temporary)], check=True)
        if temporary.stat().st_size != m['target_size'] or sha256(temporary) != m['target_sha256']:
            raise ValueError('Result verification failed.')
        temporary.rename(a.output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print('Verified patch applied: ' + str(a.output))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ERROR: ' + str(e), file=sys.stderr)
        sys.exit(1)
