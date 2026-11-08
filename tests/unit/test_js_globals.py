"""Classic scripts share a lexical scope and must all load before boot."""
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
import re


STATIC = Path(__file__).resolve().parents[2] / "static"
# Column zero is the top-level declaration convention in these source files.
# Include $ (the shared DOM helper), async functions and arrow-function bindings.
DECL = re.compile(
    r"^(?:async\s+)?function\s+([\w$]+)|^(?:const|let|var)\s+([\w$]+)", re.M
)


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.tags.append(dict(attrs))


def script_tags():
    parser = Scripts()
    parser.feed((STATIC / "index.html").read_text())
    return parser.tags


def test_global_declarations_are_unique():
    declarations = defaultdict(list)
    for path in sorted((STATIC / "js").rglob("*.js")):
        for match in DECL.finditer(path.read_text()):
            declarations[match[1] or match[2]].append(str(path.relative_to(STATIC)))
    assert declarations, "No global declarations found"
    assert not {name: paths for name, paths in declarations.items() if len(paths) > 1}


def test_index_loads_every_script_once():
    sources = [tag["src"] for tag in script_tags() if tag.get("src", "").startswith("/static/js/")]
    expected = {"/static/" + str(path.relative_to(STATIC)) for path in (STATIC / "js").rglob("*.js")}
    assert expected
    assert set(sources) == expected
    assert len(sources) == len(expected)
    assert not {"/static/app.js", "/static/timeline.js"} & {tag.get("src") for tag in script_tags()}


def test_classic_script_dependency_order():
    tags = script_tags()
    scripts = [tag for tag in tags if tag.get("src", "").startswith("/static/js/")]
    assert all(tag.get("type", "text/javascript") == "text/javascript" for tag in scripts)
    assert all("async" not in tag and "defer" not in tag for tag in scripts)
    sources = [tag["src"].removeprefix("/static/js/") for tag in scripts]
    assert sources[0] == "core.js"
    assert sources[-1] == "boot.js"
    timeline = sources.index("timeline/core.js")
    assert all(source.startswith("tabs/") for source in sources[1:timeline])
    assert sources[-2] == "shell.js"
    assert sources[-4:-2] == ["palette.js", "jobs.js"]
    assert all(source.startswith("timeline/") for source in sources[timeline:-4])
    assert next(i for i, tag in enumerate(tags) if tag.get("src") == "/static/vendor/leaflet/leaflet.js") < tags.index(scripts[0])
