"""Strict, deterministic HTML scenes and their project-local render cache."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from html.parser import HTMLParser
import json
import logging
import math
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

import jinja2
from jinja2 import meta

from . import channels, stage, store, themes
from .config import STATIC_DIR
from .schema import FrameSpec, Style

SCENE_VERSION = 1
SCENE_DIR = STATIC_DIR / "scene"
VENDOR_GSAP = STATIC_DIR / "vendor/gsap/gsap.min.js"
env = jinja2.Environment(loader=jinja2.FileSystemLoader(SCENE_DIR),
                         autoescape=True, undefined=jinja2.StrictUndefined)
log = logging.getLogger(__name__)


def context_base(project=None, channel=None) -> dict:
    if channel is None and project is not None and project.channel_id:
        channel = channels.load_or_none(project.channel_id)
    style = project.style if project else channel.style if channel else Style()
    frame = project.frame if project else channel.frame if channel else FrameSpec()
    pal = asdict(themes.palette(style))
    for key in ("accent", "accent2", "ground", "ink"):
        pal[key] = "#" + "".join(f"{c:02x}" for c in pal[key][:3])
    return dict(frame=frame.to_dict(), palette=pal,
                vars=dict(channel_name=channel.name if channel else "",
                          tagline=channel.tagline if channel else "",
                          accent=style.accent, accent2=style.accent2,
                          title=project.title if project else "Scene capture",
                          subtitle=project.subtitle if project else ""),
                fonts={"Inter": "/fonts/Inter-Medium.ttf",
                       "Archivo": "/fonts/ArchivoNarrow-Bold.ttf",
                       "JetBrains Mono": "/fonts/JetBrainsMono-Regular.ttf"},
                assets_url="/scene/{token}/assets/", width=1920, height=1080,
                duration=5, fps=30)


def render_html(template: str, ctx: dict) -> str:
    html = env.get_template(template).render(**ctx)
    # Cached HTML lives elsewhere; resolve relative component/script URLs as
    # they were authored in the template directory.
    parent = Path(template).parent.as_posix()
    base = '/static/scene/' + (quote(parent) + '/' if parent != '.' else '')
    return re.sub(r'<head\s*>', lambda m: m[0] + f'<base href="{base}">', html,
                  count=1, flags=re.I)


class _Contract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.roots, self.clips, self.mounts = [], [], []
        self.errors = []
        self.base = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'base':
            self.base = attrs.get('href')
        if "data-composition-id" in attrs:
            self.roots.append(attrs)
        if "clip" in attrs.get("class", "").split():
            self.clips.append(attrs)
        if "data-composition-src" in attrs:
            self.mounts.append(attrs["data-composition-src"])
        if tag == "script" and re.match(r"(?:https?:)?//", attrs.get("src", ""), re.I):
            self.errors.append("remote script is forbidden")


_BANNED = [
    (r"\bDate\s*\.\s*now\s*\(", "Date.now() is forbidden"),
    (r"\bMath\s*\.\s*random\s*\(", "Math.random() is forbidden"),
    (r"\bsetTimeout\s*\(", "setTimeout() is forbidden"),
    (r"\brepeat\s*:\s*-1\b", "infinite repeat is forbidden"),
    (r"\.\s*play\s*\(", ".play() is forbidden; use paused timelines"),
    (r"\bnavigator\s*\.\s*gpu\b", "WebGPU is unsupported"),
]


def _local_file(url: str, base: Path) -> Path:
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        raise ValueError(f"non-local component: {url}")
    path = unquote(parts.path)
    target = (STATIC_DIR / path[len('/static/'):] if path.startswith('/static/')
              else base / path).resolve()
    if not target.is_relative_to(SCENE_DIR.resolve()):
        raise ValueError(f"component outside scene directory: {url}")
    return target


def _scan(html, base, seen, errors, contract=False):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    parser = _Contract()
    parser.feed(html)
    if parser.base:
        try:
            base = _local_file(parser.base, base)
        except ValueError as exc:
            errors.append(str(exc))
    errors.extend(parser.errors)
    if contract:
        if len(parser.roots) != 1:
            errors.append("one composition root required")
        for root in parser.roots:
            for key in ('data-composition-id', 'data-width', 'data-height', 'data-duration'):
                if not root.get(key):
                    errors.append(f"root missing {key}")
    for clip in parser.clips:
        for key in ('data-start', 'data-duration'):
            if not clip.get(key):
                errors.append(f"clip missing {key}")
    for pattern, message in _BANNED:
        if re.search(pattern, html):
            errors.append(message)
    for url in re.findall(r"\bfetch\s*\(\s*['\"]([^'\"]+)", html):
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            errors.append(f"non-local fetch: {url}")
    for url in parser.mounts:
        try:
            path = _local_file(url, base)
            if path not in seen:
                seen.add(path)
                _scan(path.read_text(), path.parent, seen, errors)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))


def lint(html: str) -> list[str]:
    errors = []
    _scan(html, SCENE_DIR, set(), errors, contract=True)
    return errors


def _asset_hash() -> str:
    h = hashlib.sha1()
    for path in (SCENE_DIR / 'runtime.js', SCENE_DIR / '_base.css', VENDOR_GSAP):
        h.update(path.read_bytes())
    return h.hexdigest()


def _key(template, ctx, seconds, size, fps, key_extra=()):
    sources = {}

    def visit(name):
        if name in sources:
            return
        source = env.loader.get_source(env, name)[0]
        sources[name] = source
        for dep in meta.find_referenced_templates(env.parse(source)):
            if dep is None:
                raise ValueError("scene template dependencies must use literal names")
            visit(dep)
    visit(template)
    # Rendered output also captures mounted component paths driven by context.
    html = render_html(template, ctx)
    mounted, errors = set(), []
    _scan(html, SCENE_DIR, mounted, errors, contract=True)
    if errors:
        raise ValueError("Scene lint: " + "; ".join(errors))
    sources.update({str(p): p.read_text() for p in mounted})
    spec = [SCENE_VERSION, _asset_hash(), template, sources, ctx,
            seconds, size, fps, *key_extra]
    return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest(), html


def _directory(project):
    root = Path(project) if isinstance(project, (str, Path)) else store.project_dir(project.id)
    directory = root / 'scenes'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _prepare(project, template, ctx, seconds, size, fps, key_extra=()):
    if not math.isfinite(seconds) or seconds <= 0 or fps <= 0 or min(size) <= 0:
        raise ValueError("positive duration, fps and size required")
    ctx = {**ctx, 'duration': seconds, 'fps': fps}
    key, html = _key(template, ctx, seconds, size, fps, key_extra)
    directory = _directory(project)
    path = directory / f'{key}.html'
    path.write_text(html, encoding='utf-8')
    return key, path, ctx


def _sweep(directory, keep):
    files = sorted(directory.glob('*.mp4'), key=lambda p: p.stat().st_mtime)
    for path in files[:max(0, len(files) - 400)]:
        if path != keep:
            path.unlink(missing_ok=True)
            path.with_suffix('.html').unlink(missing_ok=True)
            for png in directory.glob(f'{path.stem}_*.png'):
                png.unlink(missing_ok=True)


def ensure_clip(project, template, ctx, *, seconds, size, fps, key_extra=()) -> Path:
    key, html, ctx = _prepare(project, template, ctx, seconds, size, fps, key_extra)
    out = html.with_suffix('.mp4')
    if out.exists() and out.stat().st_size:
        log.info('scene cache hit: %s', key)
    else:
        made = stage.render_scene([dict(clip=key, scene_root=str(html.parent),
            assets_root=str(html.parent.parent), url_path=f'/scene/{{token}}/{html.name}',
            W=ctx['width'], H=ctx['height'], fps=fps,
            frames=max(2, round(seconds * fps)), size=size)], html.parent)
        if made.get(key) != out:
            raise stage.StageError('Scene did not render')
    _sweep(html.parent, out)
    return out


def capture(project, template, ctx, *, t, size) -> bytes:
    if not math.isfinite(t) or t < 0:
        raise ValueError('capture time must be finite and nonnegative')
    key, html, ctx = _prepare(project, template, ctx, ctx.get('duration', 5), size, ctx.get('fps', 30))
    png = html.with_name(f'{key}_{t}.png')
    if not png.exists():
        data = stage.capture_one(html, ctx['width'], ctx['height'], t, size,
                                 assets_root=html.parent.parent)
        png.write_bytes(data)
    return png.read_bytes()


def handles(fmt: str) -> bool:
    path = (SCENE_DIR / fmt / 'segment.html').resolve()
    return path.is_relative_to(SCENE_DIR.resolve()) and path.is_file()
