"""Generated skill references must follow their Python contracts."""
import os
import subprocess

from app import doctrine


def test_generated_references(tmp_path):
    output = tmp_path / 'motion.md'
    process = subprocess.run(['.venv/bin/python', '-m', 'app.cli', 'doctrine', '--write', str(output)],
                             env=dict(os.environ, CORKBORED_DATA=str(tmp_path / 'data')),
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert output.read_text() == (doctrine.REFERENCES / 'motion.md').read_text()
    assert doctrine.patch() == (doctrine.REFERENCES / 'storyboard.md').read_text()


def test_cli_smoke(tmp_path):
    env = dict(os.environ, CORKBORED_DATA=str(tmp_path / 'data'))
    for command in ('list', 'doctrine'):
        process = subprocess.run(['.venv/bin/python', '-m', 'app.cli', command],
                                 env=env, capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        if command == 'doctrine':
            assert process.stdout == doctrine.motion()
