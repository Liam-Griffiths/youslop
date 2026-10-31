# Renderer regression tests

Run from the repo root with the existing virtual environment:

```sh
.venv/bin/pytest tests/unit -q --durations=3
YS_VISUAL=1 .venv/bin/pytest tests/visual -q
CORKBORED_DATA="$(mktemp -d)" .venv/bin/python -c "import tests.stage.suite"
```

The shared conftest sets both data overrides before importing app and copies
only synthetic fixture files into temporary storage. No test calls an LLM.
The visual test encodes one silent 3 s segment at quarter size (480×270),
extracts the frame at 1 s and requires luma SSIM > 0.99. It is skipped by
default; the stage command above only imports the GPU suite.

Goldens: update deliberately, say why in the commit. Pass `--update-goldens`
to the corresponding pytest command to replace references after reviewing a
planned change. A missing visual reference is created on first run from the
single encoded frame; graph references require the explicit update option.
Text goldens normalize paths and put each graph branch on its own line.

The fixture is `fixtures/project_min/project.json`: three paragraphs, two
synthetic 2.5 s PCM takes and one test-pattern JPEG. Assets were generated
once with ffmpeg's `sine` (440/660 Hz, mono 16 kHz) and `testsrc2` (640×360)
filters. They contain no recorded audio or downloaded media.
