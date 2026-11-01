"""Generate once, validate in isolation, publish only checked reusable blocks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import uuid

import jinja2

from . import block_authoring, block_sandbox, blocks, llm, scenes


def prompt_for(description):
    examples = '\n'.join((blocks.BUILTIN_DIR / name / 'block.html').read_text()
                         for name in ('chapter', 'lower_third_rule'))
    return f'''Create a reusable Corkbored block for this description: {json.dumps(description)}
Return only a JSON object with keys "block.html" (string) and "block.json" (object).
Manifest schema: {blocks.SCHEMA.read_text()}
Scaffold: {block_authoring.TEMPLATE}
Two built-in examples (adapt their base to _base.html): {examples}
Motion table: {json.dumps(scenes.env.globals['motion_presets'])}
Tokens: --bg #0E0F11, --ink #F2F2F2, --accent #FF5A1F, --accent2 #6FB7FF.
Use local Inter /fonts/Inter-Medium.ttf. Labels and values minimum 44px at 1080.
Keep text in 10% title/5% action safe areas; portrait: top 15%, bottom 20%, right 15%.
Only extend _base.html, define head/body blocks, interpolate vars.x, width, height,
duration, data.x, simple if/for, literal-key subscripts and arithmetic. No calls,
filters, imports, includes, macros, assignments or other attribute access.
No scripts, iframe, event handlers, remote URLs, CSS escapes/imports or animations.
Use data-fit for app-owned fitting (never drops below 44px). Use one data-layer per
independently timed element, data-start/data-duration and data-motion presets only.
Word-by-word text is ONE wipe layer. At most 12 layers, budget:0, no capture windows,
one builder pass at 10 seconds. Pictures use data-media with local block assets.
Only block.html is emitted; assets must be empty and every aspect points to block.html.
Use range duration with min <=10 <=max so the check can test a ten-second block.
The checker tests max-length text, fit, contrast, safe areas and seek determinism.
'''


def describe(description, progress=lambda message: None):
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000:
        raise ValueError('describe a block in 1–4000 characters')
    description = description.strip()
    prompt = prompt_for(description)
    errors = []
    model = llm.MODEL_SCRIPT
    with llm.capture_usage() as usage:
        for attempt in range(3):
            progress(f'Creating block: attempt {attempt + 1}/3')
            reply = None
            try:
                reply = llm.complete_json(prompt, model=model, retries=0)
                if not isinstance(reply, dict) or set(reply) != {'block.html', 'block.json'}:
                    raise ValueError('return block.html and block.json only')
                source, meta = reply['block.html'], reply['block.json']
                if not isinstance(source, str) or len(source) > 100000 or not isinstance(meta, dict):
                    raise ValueError('invalid block output')
                block_sandbox.parse(source)
                blocks._check(meta, json.loads(blocks.SCHEMA.read_text()), 'block.json')
                if any(s.get('max_length', 0) > 4000 for s in meta['variables'].values()):
                    raise ValueError('text max_length must not exceed 4000')
                if meta['safe_areas']['title'] < .1 or meta['safe_areas']['action'] < .05:
                    raise ValueError('require at least 10% title / 5% action safe areas')
                slug = meta['id']
                if not re.fullmatch(r'[a-z0-9_][a-z0-9_-]*', slug):
                    raise ValueError('invalid block id')
                rule = meta['duration']
                if (meta.get('budget') != 0 or meta['assets'] or
                        set(meta['aspects'].values()) != {'block.html'} or rule['mode'] != 'range' or
                        not rule.get('min', 11) <= 10 <= rule.get('max', 0)):
                    raise ValueError('require budget:0, no assets, block.html aspects, and range duration including 10s')
                meta['duration']['default'] = 10
                meta['origin'] = dict(description=description, model=model, token_usage=usage,
                                      created_at=datetime.now(timezone.utc).isoformat())
                # The temporary registry is context-local: concurrent jobs/UI never see it.
                with tempfile.TemporaryDirectory(prefix='corkbored-block-') as work:
                    meta['id'] = 'draft_' + uuid.uuid4().hex
                    root = Path(work) / meta['id']
                    root.mkdir()
                    (root / 'block.html').write_text(source)
                    (root / 'block.json').write_text(json.dumps(meta, indent=2) + '\n')
                    token = blocks.STAGED.set((root,))
                    try:
                        reported = set()
                        def report(aspect, stats):
                            reported.add(aspect)
                            for key, limit in [('captured_frames', 0), ('layers', 12), ('passes', 1)]:
                                if key not in stats or stats[key] > limit:
                                    errors.append(f'{aspect}: builder {key}={stats.get(key)} (limit {limit})')
                        errors = block_authoring.lint('user/' + meta['id'])
                        if not errors:
                            errors = block_authoring.check('user/' + meta['id'], report=report) + errors
                            if reported != set(meta['aspects']):
                                errors.append('builder statistics missing for declared aspects')
                    finally:
                        blocks.STAGED.reset(token)
                    if not errors:
                        blocks.USER_DIR.mkdir(parents=True, exist_ok=True)
                        suffix = 1
                        while True:
                            target = blocks.USER_DIR / (slug if suffix == 1 else f'{slug}-{suffix}')
                            try:
                                target.mkdir(exist_ok=False)
                                break
                            except FileExistsError:
                                suffix += 1
                        meta['id'] = target.name
                        (target / 'block.html').write_text(source)
                        # Discovery sees the manifest only after the template is written.
                        with (target / '.block.json.tmp').open('x') as manifest:
                            json.dump(meta, manifest, indent=2)
                        (target / '.block.json.tmp').rename(target / 'block.json')
                        return dict(id='user/' + target.name, errors=[], usage=usage)
            except llm.LLMUnavailable:
                raise
            except (ValueError, jinja2.TemplateError, llm.LLMError) as exc:
                errors = [str(exc)]
            progress('Rejected: ' + '; '.join(errors))
            prompt = prompt_for(description) + '\nRejected output: ' + json.dumps(reply)
            prompt += '\nFix these exact check errors: ' + json.dumps(errors)
    return dict(id=None, errors=errors, usage=usage)
