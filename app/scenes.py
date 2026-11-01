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
import tempfile
from urllib.parse import quote, unquote, urlsplit

import jinja2
from jinja2 import meta

from . import channels, cuts, ffutil, sanitise, stage, store, themes
from .config import FPS, HEIGHT, STATIC_DIR, WIDTH
from .schema import FrameSpec, Style

SCENE_VERSION = 5
SCENE_DIR = STATIC_DIR / "scene"
VENDOR_GSAP = STATIC_DIR / "vendor/gsap/gsap.min.js"
ASSETS_URLS = {kind: f"/scene/{{token}}/{kind}/" for kind in ('project', 'channel')}


class _BlockLoader(jinja2.BaseLoader):
    def get_source(self, environment, template):
        from .blocks import Loader
        return Loader().get_source(environment, template)


env = jinja2.Environment(loader=jinja2.ChoiceLoader([
    _BlockLoader(), jinja2.FileSystemLoader(SCENE_DIR)]),
                         autoescape=True, undefined=jinja2.StrictUndefined)
env.filters['clean_html'] = sanitise.clean
env.globals['motion_presets'] = json.loads((SCENE_DIR / 'motion.json').read_text())
log = logging.getLogger(__name__)


def context_base(project=None, channel=None) -> dict:
    if channel is None and project is not None and project.channel_id:
        channel = channels.load_or_none(project.channel_id)
    style = project.style if project else channel.style if channel else Style()
    frame = project.frame if project else channel.frame if channel else FrameSpec()
    from .variables import variables
    resolved = variables(project, channel)
    copy = {k: v["value"] for k, v in resolved["copy"].items()}
    pal = asdict(themes.palette(style))
    for key in ("accent", "accent2", "ground", "ink"):
        pal[key] = "#" + "".join(f"{c:02x}" for c in pal[key][:3])
    frame_values = {**frame.to_dict(), **{k: v["value"] for k, v in resolved["frame"].items()}}
    return dict(frame=frame_values, palette=pal, copy=copy,
                vars=dict(**{f"copy.{k}": v for k, v in copy.items()},
                          **{k: v["value"] for k, v in resolved["colors"].items()},
                          channel_name=copy["channel_name"],
                          tagline=copy["tagline"],
                          title=project.title if project else "Scene capture",
                          subtitle=project.subtitle if project else ""),
                fonts={"Inter": "/fonts/Inter-Medium.ttf",
                       "Archivo": "/fonts/ArchivoNarrow-Bold.ttf",
                       "EB Garamond": "/fonts/EBGaramond-Regular.ttf",
                       "JetBrains Mono": "/fonts/JetBrainsMono-Regular.ttf"},
                assets_url="/scene/{token}/assets/",
                assets_urls=dict(ASSETS_URLS),
                asset_roots=dict(project_root=str(store.project_dir(project.id)) if project else None,
                                 channel_root=str(channels.CHANNELS_DIR / channel.id)
                                 if channel and channel.id else None),
                width=1920, height=1080,
                duration=5, fps=30)


def _template_context(template: str, ctx: dict) -> dict:
    if template.startswith('sponsor/') and template.endswith('_vertical.html'):
        return {**ctx, 'width': 1080, 'height': 1920}
    return ctx


def render_html(template: str, ctx: dict) -> str:
    ctx = _template_context(template, ctx)
    if template.startswith('sponsor/'):
        from .sponsors import scene_context
        ctx = {**ctx, **scene_context(ctx)}
    html = env.get_template(template).render(**ctx)
    # Cached HTML lives elsewhere; resolve relative component/script URLs as
    # they were authored in the template directory.
    parent = Path(template).parent.as_posix()
    base = ('/scene/{token}/assets/' if template.startswith('_blocks/') else
            '/static/scene/' + (quote(parent) + '/' if parent != '.' else ''))
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


def _local_file(url: str, base: Path, asset_root=None) -> Path:
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        raise ValueError(f"non-local component: {url}")
    path = unquote(parts.path)
    if asset_root and path.startswith('/scene/{token}/assets/'):
        root = Path(asset_root).resolve()
        target = (root / path[len('/scene/{token}/assets/'):]).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f'component outside block directory: {url}')
        return target
    from .catalog import CATALOG_DIR
    if path.startswith('/catalog/'):
        target = (CATALOG_DIR / path[len('/catalog/'):]).resolve()
        if not target.is_relative_to(CATALOG_DIR.resolve()) or '_index' in target.parts:
            raise ValueError(f"component outside catalog directory: {url}")
        relative = target.relative_to(CATALOG_DIR.resolve())
        if relative.parts:
            source = CATALOG_DIR / relative.parts[0] / 'SOURCE.json'
            if source.is_file():
                failures = json.loads(source.read_text()).get('lint', [])
                if failures:
                    raise ValueError('Catalog lint: ' + '; '.join(failures))
        return target
    target = (STATIC_DIR / path[len('/static/'):] if path.startswith('/static/')
              else base / path).resolve()
    if not (target.is_relative_to(SCENE_DIR.resolve()) or
            target.is_relative_to(CATALOG_DIR.resolve()) or
            asset_root and target.is_relative_to(Path(asset_root).resolve())):
        raise ValueError(f"component outside scene directory: {url}")
    return target


def _scan(html, base, seen, errors, contract=False, asset_root=None):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    parser = _Contract()
    parser.feed(html)
    if parser.base:
        try:
            base = _local_file(parser.base, base, asset_root)
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
    if asset_root and re.search(r"(?:https?:)?//", ' '.join(re.findall(
            r'''(?:url\(\s*['\"]?|(?:src|href)\s*=\s*['\"]|@import\s+['\"])([^'\"\s)>]+)''', html, re.I))):
        errors.append('remote block resource is forbidden')
    for url in parser.mounts:
        try:
            path = _local_file(url, base, asset_root)
            if path not in seen:
                seen.add(path)
                _scan(path.read_text(), path.parent, seen, errors, asset_root=asset_root)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))


def lint_component(html: str, base: Path) -> list[str]:
    errors = []
    _scan(html, base, set(), errors)
    return errors


def lint(html: str, *, asset_root=None) -> list[str]:
    errors = []
    _scan(html, SCENE_DIR, set(), errors, contract=True, asset_root=asset_root)
    return errors


def _asset_hash() -> str:
    h = hashlib.sha1()
    # Templates link their own stylesheets (e.g. cuts/loudmouth.css), so every
    # scene stylesheet is part of the key, not just the base one.
    for path in (SCENE_DIR / 'runtime.js', SCENE_DIR / 'motion.json', VENDOR_GSAP,
                 *sorted(SCENE_DIR.rglob('*.css'))):
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
    _scan(html, SCENE_DIR, mounted, errors, contract=True, asset_root=ctx.get('block_assets_root'))
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
    ctx = _template_context(template, {**ctx, 'duration': seconds, 'fps': fps})
    key, html = _key(template, ctx, seconds, size, fps, key_extra)
    directory = _directory(project)
    path = directory / f'{key}.html'
    path.write_text(html, encoding='utf-8')
    return key, path, ctx


def _sweep(directory, keep):
    files = sorted([*directory.glob('*.mp4'), *directory.glob('*.mov')],
                   key=lambda p: p.stat().st_mtime)
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
            **ctx.get('asset_roots', {}),
            assets_root=ctx.get('block_assets_root', str(html.parent.parent)), url_path=f'/scene/{{token}}/{html.name}',
            W=ctx['width'], H=ctx['height'], fps=fps,
            frames=max(2, round(seconds * fps)), size=size)], html.parent)
        if made.get(key) != out:
            raise stage.StageError('Scene did not render')
    _sweep(html.parent, out)
    return out


def caption_plates(project, ctx, *, size, render=True, fps=FPS) -> Path:
    """Prepare/cache one transparent builder clip for the segment's captions."""
    from . import scene_builder, titles
    seconds = ctx.get('duration', max(p['t1'] for p in ctx['phrases']))
    ctx = dict(ctx, caption_size=titles.CAPTION_CAP, caption_lines=titles.CAPTION_LINES,
               builder_alpha=True)
    key, html, _ = _prepare(project, 'essay/captions.html', ctx, seconds, size, fps,
                            ('builder-captions-v1', scene_builder.MOTIONS))
    out = html.with_suffix('.mov')
    if render and (not out.exists() or not out.stat().st_size):
        # Parallel workers publish complete clips atomically.
        with tempfile.TemporaryDirectory(dir=out.parent, prefix='captions-') as tmp:
            clip = scene_builder.render(project, 'essay/captions.html', ctx,
                Path(tmp) / 'captions.mov', seconds=seconds, size=size, fps=fps, crf=17)
            clip.path.replace(out)
    return out


def measure_captions(project, texts, *, render=True) -> list[dict | None]:
    """Measure settled caption text, retaining the legacy metrics field names."""
    from . import titles
    ctx = context_base(project)
    ctx.update(caption_size=titles.CAPTION_CAP, caption_lines=titles.CAPTION_LINES, settled=True)
    requests = [('essay/captions.html',
                 dict(ctx, phrases=[dict(text=text, t0=0, t1=5)]), 0) for text in texts]
    rows = measure_many(project, requests, render=render)
    return [dict(page[0], size=page[0]['px']) if page else None for page in rows]


def measure_many(project, requests, *, render=True):
    """Cache scene geometry by clip content and time; batch all missing pages.

    Requests are (template, context, earliest_time). render=False reads only
    cached results, so Timeline checks never start Chromium.
    """
    paths, items, roots = [], {}, None
    for template, ctx, t in requests:
        if not math.isfinite(t) or t < 0:
            raise ValueError('measurement time must be finite and nonnegative')
        key, html, prepared = _prepare(project, template, ctx, ctx.get('duration', 5),
                                       (ctx['width'], ctx['height']), ctx.get('fps', FPS))
        cached = html.with_name(f'{key}_{t}.text-v1.json')
        paths.append(cached)
        if render and not cached.exists():
            clip = cached.stem
            items[clip] = dict(clip=clip, url_path=f'/scene/{{token}}/{html.name}',
                               W=prepared['width'], H=prepared['height'],
                               size=(prepared['width'] / 4, prepared['height'] / 4), t=t)
            current = dict(prepared.get('asset_roots', {}),
                           assets_root=prepared.get('block_assets_root', str(html.parent.parent)))
            if roots is not None and roots != current:
                raise ValueError('measurement pages must share asset roots')
            roots = current
    if items:
        directory = paths[0].parent
        measured = stage.measure_many(list(items.values()), directory, **roots)
        for clip, rows in measured.items():
            with tempfile.NamedTemporaryFile(mode='w', dir=directory, suffix='.part', delete=False) as f:
                temporary = Path(f.name)
                json.dump(rows, f)
            temporary.replace(directory / (clip + '.json'))
        if any(not path.exists() for path in paths):
            raise stage.StageError('Scene text measurements missing')
    return [json.loads(path.read_text()) if path.exists() else [] for path in paths]


def measure(project, template, ctx, t):
    return measure_many(project, [(template, ctx, t)])[0]


def capture(project, template, ctx, *, t, size) -> bytes:
    if not math.isfinite(t) or t < 0:
        raise ValueError('capture time must be finite and nonnegative')
    key, html, ctx = _prepare(project, template, ctx, ctx.get('duration', 5), size, ctx.get('fps', 30))
    png = html.with_name(f'{key}_{t}.png')
    if not png.exists():
        data = stage.capture_one(html, ctx['width'], ctx['height'], t, size,
                                 assets_root=ctx.get('block_assets_root', html.parent.parent), **ctx.get('asset_roots', {}))
        png.write_bytes(data)
    return png.read_bytes()


def handles_cut(key: str) -> bool:
    return key in {"loudmouth", "flameboat", "ticker"} and (SCENE_DIR / "cuts" / f"{key}.html").is_file()


def handles(fmt: str) -> bool:
    path = (SCENE_DIR / fmt / 'segment.html').resolve()
    return path.is_relative_to(SCENE_DIR.resolve()) and path.is_file()


def _encode(clip, out, seconds, size, fps, crf):
    out.parent.mkdir(parents=True, exist_ok=True)
    ffutil.run(["-i", str(clip), "-vf", f"scale={size[0]}:{size[1]}",
                "-t", f"{seconds:.3f}", "-r", str(fps),
                *ffutil.video_args(out, crf=crf),
                "-pix_fmt", "yuv420p", "-an", str(out)])


def render_segment(project, group, seg_len, out, *, size=(WIDTH, HEIGHT),
                   fps=FPS, crf=18, chapter=None, lead_in=0.0, hold=0.0,
                   channel=None, hide=frozenset()) -> Path:
    """Render a group on the full composition, then encode at the output size."""
    ctx = context_base(project, channel)
    ctx.update(slides=[{**asdict(slide), "duration": dur} for slide, dur in group],
               narration="\n\n".join(slide.narration for slide, _ in group),
               titles=[slide.title for slide, _ in group],
               cues=(cuts.timed_cues(project, group, seg_len, lead_in)
                     if cuts.is_cut(project.style.format) else []),
               chapter=chapter, lead_in=lead_in, hold=hold)
    if 'cues' in hide:
        ctx['cues'] = []
    if 'titles' in hide:
        ctx['titles'] = []
        for slide in ctx['slides']:
            slide['title'] = ''
    clip = ensure_clip(project, f"{project.style.format}/segment.html", ctx,
                       seconds=seg_len, size=(ctx['width'], ctx['height']), fps=fps)
    _encode(clip, out, seg_len, size, fps, crf)
    return out


def render_card(kind, name, channel, video_title, out_path,
                progress=lambda m: None) -> float:
    """Shared scene dispatch for channel, standalone and preview cards."""
    if kind not in ("intro", "outro"):
        raise ValueError("unknown scene card kind")
    # Card names are local template names, never arbitrary paths.
    if not re.fullmatch(r"[\w-]+", name):
        raise ValueError("invalid scene card name")
    spec = getattr(channel, kind)
    bounds = (2.5, 12.0) if kind == 'intro' else (5.0, 20.0)
    seconds = max(bounds[0], min(bounds[1], spec.duration))
    ctx = context_base(channel=channel)
    ctx.update(card=asdict(spec), kind=kind)
    ctx['vars']['title'] = video_title
    if kind == 'outro' and name in ('outro_twoup', 'outro_quiet'):
        ctx.update(outro_context(channel))
    if kind == 'intro':
        ctx.update(intro_context(channel))
    # Keeping this cache alongside the output also covers synthetic solo channels.
    from . import scene_builder
    scene_builder.render(out_path.parent, f"cards/{name}.html", ctx, out_path,
                         seconds=seconds, size=(WIDTH, HEIGHT), fps=FPS, crf=18)
    progress(f"Scene {kind}: {seconds:.1f}s")
    return seconds


def intro_context(channel) -> dict:
    """Resolve the first available channel portrait without fetching a cast."""
    root = (channels.CHANNELS_DIR / channel.id).resolve()
    for rel in channel.intro.images:
        path = (root / rel).resolve()
        if rel and '..' not in rel and path.is_relative_to(root) and path.is_file():
            return dict(portrait_url=ASSETS_URLS['channel'] + quote(rel, safe='/'),
                        portrait_hash=hashlib.sha1(path.read_bytes()).hexdigest())
    return dict(portrait_url='', portrait_hash='')


def outro_context(channel) -> dict:
    """Card variables and pixel geometry, also usable by scene-preview fixtures."""
    from . import outro

    key = channel.outro.template.removeprefix('scene:outro_')
    return dict(card=asdict(channel.outro),
                plates=outro.plate_rects(key, channel.outro.slots),
                cta=outro._cta(channel, key))
