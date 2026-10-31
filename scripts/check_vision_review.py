"""Offline CLI smoke check: synthetic frames, isolated data, mocked model.

Run from the repository: .venv/bin/python scripts/check_vision_review.py
No renderer, browser, audio processing or external service is used.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='corkbored-vision-check-') as data:
        os.environ['CORKBORED_DATA'] = os.environ['YOUSLOP_DATA'] = data
        from PIL import Image
        from app import cli, llm, review, store
        from tests._fixtures import load_project

        project = load_project()
        root = store.project_dir(project.id)
        frames = []
        for i in range(18):
            path = root / 'review/snaps' / f'{i}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (640, 360), 'white').save(path)
            frames.append(dict(t=round(i * .6, 3), why='chapter',
                               slide_id=project.slides[0].id,
                               path=path.relative_to(root).as_posix()))
        (root / 'review/snaps.json').write_text(json.dumps(dict(
            storyboard_hash=review._storyboard_hash(project), snaps=frames)))
        reply = dict(notes=[dict(t=0, severity='P1', see='A white frame.',
                     problem='No opening title.', fix=dict(kind='title',
                     slide_id=project.slides[0].id, hint='Add an opening title.'))],
                     weakest=dict(t=0, why='The opening is empty.'))
        with patch.object(llm, 'complete_json', return_value=reply) as model:
            status = cli.main(['review', project.id, '--json'])
            assert model.call_count == 1
            assert len(model.call_args.kwargs['images']) <= 12
            assert (root / 'review/REVIEW.md').is_file()
            return status


if __name__ == '__main__':
    raise SystemExit(main())
