"""Read-only handoff integrity check; does not verify game or release assets."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = json.loads((ROOT / 'docs/resume_baseline.json').read_text(encoding='utf-8'))
    errors = []
    for rel in ['AGENTS.md', 'PROJECT_STATE.md', 'HANDOFF.md', 'docs/OPERATIONS.md']:
        if not (ROOT / rel).is_file():
            errors.append('Missing document: ' + rel)
    for rel, expected in spec['files'].items():
        path = (ROOT / rel).resolve()
        if ROOT not in path.parents:
            errors.append('Path outside repository: ' + rel)
            continue
        if not path.is_file():
            errors.append('Missing baseline file: ' + rel)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append('Baseline changed; review before continuing: ' + rel)
    for message in errors:
        print('FAIL: ' + message)
    if errors:
        return 1
    print('PASS: handoff documents present and pinned repository files unchanged.')
    print('Inspected commit: ' + spec['inspected_commit'])
    print('ISO / xdelta decode / runtime QA: NOT_RUN by this check.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        sys.exit(1)
