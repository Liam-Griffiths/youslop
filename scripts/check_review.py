"""One-segment review smoke check; leaves a temporary sheet for visual review.

Run from the repo: CORKBORED_DATA=$(mktemp -d) .venv/bin/python scripts/check_review.py
Then open the printed sheet path to check timecodes/reasons at 360px per tile.
No browser, network, real project, full render or LLM is used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from time import perf_counter


def main():
    repo = Path(__file__).resolve().parents[1]
    # Always create our own temp root, even if the caller points at real data.
    data = Path(tempfile.mkdtemp(prefix='corkbored-review-check-'))
    project = data / 'projects/ptest0001'
    shutil.copytree(repo / 'tests/fixtures/project_min', project)
    path = project / 'project.json'
    model = json.loads(path.read_text())
    model['slides'] = model['slides'][:1]
    model.update(use_intro=False, use_outro=False)
    path.write_text(json.dumps(model))
    env = dict(os.environ, CORKBORED_DATA=str(data), YOUSLOP_DATA=str(data),
               CORKBORED_ENCODER='cpu')
    command = [str(repo / '.venv/bin/python'), '-m', 'app.cli', 'snapshot', 'ptest0001', '--sheet']
    started = perf_counter()
    result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    print(result.stdout, end='')
    print(result.stderr, end='')
    if result.returncode:
        raise SystemExit(result.returncode)
    rows = json.loads((project / 'review/snaps.json').read_text())
    assert rows and len(rows) <= 48
    assert len(list((project / 'cache').glob('seg_*.webm'))) == 1
    assert all((project / row['path']).is_file() for row in rows)
    elapsed = perf_counter() - started
    print(f'PASS: {len(rows)} snapshots; 1 quarter-size segment; {elapsed:.2f}s')
    assert elapsed < 30, f'Snapshot CLI took {elapsed:.2f}s (budget: 30s)'
    print(f"Visual check: xdg-open '{project / 'review/sheet.png'}'")


if __name__ == '__main__':
    main()
