"""Keep the plain-script inspector contract aligned with the slide PATCH route."""
import re
from pathlib import Path

import pytest

from app import edits, main
from app.schema import Slide

FIELDS = {
    "paragraph": ["gap_override"],
    "title": ["title", "title_at", "title_hold"],
    "cue": ["cues"],
    "chapter": ["chapter", "chapter_hold"],
    "picture": ["title", "focal"],
}
VALUES = {
    "gap_override": 0.4, "title": "Inspector title", "title_at": 1.2,
    "title_hold": 2.0, "chapter": "A chapter", "chapter_hold": 1.5,
    "cues": {"loudmouth": [{"kind": "phrase", "text": "hello world", "at": 1.2}]},
    "focal": [0.2, 0.8],
}


def test_field_contract():
    source = Path("static/js/timeline/fields.js").read_text()
    parsed = {kind: re.findall(r"'([^']+)'", fields)
              for kind, fields in re.findall(r"(\w+):\s*\[([^]]*)\]", source)}
    assert parsed == FIELDS
    assert set(VALUES) == {key for fields in FIELDS.values() for key in fields}
    assert set(VALUES) <= edits.EDITABLE
    html = Path("static/index.html").read_text()
    assert html.index("timeline/fields.js") < html.index("timeline/inspect.js")


@pytest.mark.parametrize("key", VALUES)
def test_patch_route_accepts_inspector_field(project, monkeypatch, key):
    slide = Slide(candidates=[{"id": "image", "focal": [0.5, 0.5]}], chosen_id="image")
    project.slides = [slide]
    saved = []
    monkeypatch.setattr(main, "_load", lambda pid: project)
    monkeypatch.setattr(main.store, "save", lambda p: saved.append(p))
    result = main.patch_slide(project.id, slide.id, {key: VALUES[key]})
    assert saved == [project]
    if key == "focal":
        assert result["candidates"][0]["focal"] == VALUES[key]
    elif key == "cues":
        assert result["cues"]["loudmouth"][0]["at"] == 1.2
        assert result["cues"]["loudmouth"][0]["text"] == "hello world"
    else:
        assert result[key] == VALUES[key]
