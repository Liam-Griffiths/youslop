"""Production CLI: use HTTP jobs while the app is open, synchronous ops otherwise."""
import httpx

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from . import edits, ffutil, llm, ops, render, review, store, storyboard
from .config import CACHE_DIR, ensure_dirs


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _guard_write():
    path = CACHE_DIR / "server.json"
    try:
        server = json.loads(path.read_text())
    except FileNotFoundError:
        return
    pid = server.get("pid")
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid server.json pid; cannot safely write")
    if _alive(pid):
        raise ValueError("the app is open; close it or use the UI")
    path.unlink(missing_ok=True)


def _operation(name, pid, payload):
    try:
        server = json.loads((CACHE_DIR / "server.json").read_text())
    except FileNotFoundError:
        server = None
    if server is not None and (not isinstance(server, dict) or
                               type(server.get('pid')) is not int or server['pid'] <= 0):
        raise ValueError('Invalid server.json pid; cannot safely write')
    if server and _alive(server['pid']):
        port = server.get('port')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("the app is open; close it or use the UI (invalid server port)")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}",
                          headers={'x-vb-token': server.get('token', '')}, timeout=30) as client:
            health = client.get('/api/health')
            health.raise_for_status()
            if health.json() != {'ok': True, 'pid': server['pid']}:
                raise ValueError("Server identity mismatch; refusing local writes")
            base = f'/api/projects/{pid}'
            method, path = {
                'create': ('POST', '/api/projects'), 'plan': ('POST', base + '/script'),
                'research': ('POST', base + '/research'),
                'render': ('POST', base + '/slides/' + str(payload['section']) + '/preview'
                           if payload.get('section') else base + '/render'),
                'publish': ('POST', base + '/youtube/upload'), 'check': ('GET', base + '/check'),
                'snapshot': ('POST', base + '/review/snapshots'),
                'review': ('POST', base + '/review'),
                'fix': ('POST', base + '/review/' + str(payload.get('note_id', ''))),
            }[name]
            response = client.request(method, path, **({'json': payload} if method == 'POST' else {}))
            response.raise_for_status()
            result = response.json()
            initial = result
            since = 0
            while 'job' in initial:
                response = client.get(f"/api/jobs/{initial['job']}", params={'since': since})
                response.raise_for_status()
                job = response.json()
                for row in job['log']:
                    print(row['m'], file=sys.stderr, flush=True)
                since = job['log_total']
                if job['state'] == 'error':
                    raise ValueError(job['error'])
                if job['state'] == 'done':
                    result = job['result']
                    break
                time.sleep(.2)
            return {'project': initial['project']} if name == 'create' else result
    if name != 'check':
        _guard_write()
    return getattr(ops, name)(pid, payload, lambda msg: print(msg, file=sys.stderr, flush=True))


def cmd_render(args):
    if not args.section and not (args.full and args.yes):
        raise ValueError("Full renders require --full --yes; use --section SID for one preview.")
    print("One quarter-size segment preview." if args.section else
          "Full render: up to 6 segments at a time, limited by available memory; "
          "heavy on this machine (ffmpeg threads capped).", file=sys.stderr, flush=True)
    result = _operation('render', args.pid, {'section': args.section, 'force': args.force})
    _print_json(result)
    return int('error' in result)


def cmd_publish(args):
    _print_json(_operation('publish', args.pid, {
        'channel_id': args.channel, 'privacy': args.privacy,
        'title': args.title, 'description': args.description,
        'tags': args.tag, 'category_id': args.category_id}))


def cmd_new(args):
    result = _operation('create', '', {'idea': args.idea, 'test': args.test})
    print(result['project']['id'])


def cmd_plan(args):
    _print_json(_operation(args.cmd, args.pid, {'fresh': args.fresh} if args.cmd == 'plan' else {}))


def _print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def cmd_list(args):
    for p in store.list_projects():
        print(f"{p['id']}\t{p['title']}\t{p['format']}\t{p['status']}")


def cmd_timeline(args):
    result = render.timeline(store.load(args.pid))
    if args.json:
        _print_json(result)
    else:
        print("REF\tTYPE\tSTART\tDURATION\tPARAGRAPHS")
        for seg in result["segments"]:
            print(f"{seg['ref']}\t{seg['type']}\t{seg['start']:.3f}\t"
                  f"{seg['duration']:.3f}\t{','.join(p['id'] for p in seg['paragraphs'])}")


def cmd_storyboard(args):
    _print_json(storyboard.build(store.load(args.pid)))


def cmd_check(args):
    result = _operation('check', args.pid, {})
    if args.json:
        _print_json(result)
    else:
        for level in ("P0", "P1", "P2"):
            print(f"{level} ({result['counts'][level]})")
            for finding in result["findings"]:
                if finding["level"] == level:
                    print(f"  {finding['t']:.3f}s  {finding['msg']}")
    return 1 if result["counts"]["P0"] else 0


def cmd_snapshot(args):
    result = _operation('snapshot', args.pid, {'sheet': args.sheet})
    root = store.project_dir(args.pid)
    print(root / result['manifest'])
    if args.sheet:
        print(root / result['sheet'])


def cmd_review(args):
    result = _operation('review', args.pid, {'mode': 'full' if args.full else 'targeted'})
    if args.json:
        _print_json(result)
    else:
        print(store.project_dir(args.pid) / 'review/REVIEW.md')
    return int(any(n['severity'] == 'P0' and n.get('state', 'open') == 'open'
                   for n in result['notes']))


def cmd_fix(args):
    proposal = _operation('fix', args.pid, {'note_id': args.note_id, 'action': 'fix'})
    _print_json(proposal)
    if args.apply and not proposal.get('unsupported') and not proposal.get('proposal', {}).get('search'):
        _print_json(_operation('fix', args.pid, {'note_id': args.note_id, 'action': 'apply'}))


def cmd_apply(args):
    _guard_write()
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    with store.lock_for(args.pid):
        project = store.load(args.pid)
        changed = storyboard.apply(project, patch)
        store.save(project)
    _print_json(changed)


def cmd_ask(args):
    _guard_write()  # Even --copy writes a frame beside the project.
    result = review.ask(store.load(args.pid), args.t, {}, args.intent,
                        mode='copy' if args.copy else 'ask')
    if args.copy:
        print(result['prompt'])
        return
    _print_json(result['patch'])
    print(json.dumps(result['diff'], indent=2, ensure_ascii=False), file=sys.stderr)
    if args.apply:
        review.apply_ask(args.pid, result)


def cmd_scene_check(args):
    """Render the template and lint its contract; requires no Chromium."""
    from . import scenes
    ctx = scenes.context_base()
    if args.ctx:
        override = json.loads(Path(args.ctx).read_text(encoding="utf-8"))
        ctx = {**ctx, **override, 'vars': {**ctx['vars'], **override.get('vars', {})}}
    errors = scenes.lint(scenes.render_html(args.template, ctx))
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"{args.template}: lint OK")
    return 1 if errors else 0


def cmd_scene_preview(args):
    from . import scenes

    project = store.load(args.project) if args.project else None
    ctx = scenes.context_base(project)
    if args.ctx:
        override = json.loads(Path(args.ctx).read_text(encoding="utf-8"))
        ctx = {**ctx, **override, 'vars': {**ctx['vars'], **override.get('vars', {})}}
    ctx = scenes._template_context(args.template, ctx)
    size = (270, 480) if ctx["width"] < ctx["height"] else (480, 270)
    out = Path(args.out or ("scene.mp4" if args.mp4 else "frame.png"))
    # Keep temporary inputs alive until Chromium has finished reading them.
    with tempfile.TemporaryDirectory(prefix="corkbored-scene-") as temporary:
        root = project if project else Path(temporary)
        if args.mp4:
            clip = scenes.ensure_clip(root, args.template, ctx,
                                      seconds=args.seconds, size=size, fps=30)
            out.write_bytes(clip.read_bytes())
        else:
            out.write_bytes(scenes.capture(root, args.template, ctx,
                                          t=args.t, size=size))
    print(out)


def cmd_catalog(args):
    from . import catalog
    if args.catalog_cmd == 'search':
        print('WebGPU items excluded.', file=sys.stderr)
        _print_json(catalog.search(args.query))
    elif args.catalog_cmd == 'fetch':
        path = catalog.fetch(args.name)
        print(path)
        source = json.loads((path / 'SOURCE.json').read_text())
        for error in source['lint']:
            print('Lint: ' + error, file=sys.stderr)
    else:
        _print_json(catalog.installed())


def cmd_doctrine(args):
    from . import doctrine
    if args.write is not None:
        doctrine.write(Path(args.write) if args.write else None)
    else:
        print(doctrine.motion(), end='')


def cmd_footage(args):
    from . import footage
    if args.footage_cmd == 'list':
        _print_json([{'id': s.id, 'path': s.path, 'copied': s.copied,
                      'files': len(s.files)} for s in footage.list_shoots()])
    elif args.footage_cmd == 'status':
        _print_json(footage.status(args.shoot))
    else:
        _guard_write()
        progress = lambda message: print(message, file=sys.stderr, flush=True)
        shoot = footage.import_shoot(args.path, copy=args.copy, progress=progress)
        # jobs uses daemon threads; the CLI must finish the worker before exiting.
        _print_json(footage.process_and_detect(shoot.id, progress))


def cmd_learning(args):
    from . import channels, learning
    if args.cmd == 'format' and args.action == 'list':
        return _print_json(channels.load(args.cid).formats)
    _guard_write()
    if args.cmd == 'rule':
        result = learning.add(args.pid, args.text, scope=args.scope)
    elif args.cmd == 'look':
        result = learning.add(args.pid, args.token, kind='rejected_looks', scope=args.scope)
    else:
        project = store.load(args.pid)
        result = learning.save_format(project.channel_id, args.pid, args.name)
    _print_json(result)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    command = sub.add_parser('render')
    command.add_argument('pid')
    mode = command.add_mutually_exclusive_group()
    mode.add_argument('--section', metavar='SID')
    mode.add_argument('--full', action='store_true')
    command.add_argument('--yes', action='store_true')
    command.add_argument('--force', action='store_true')
    command = sub.add_parser('publish')
    command.add_argument('pid')
    command.add_argument('--channel', help="Confirm the project's existing channel id")
    command.add_argument('--privacy', choices=('private', 'unlisted', 'public'), default='private')
    command.add_argument('--title')
    command.add_argument('--description')
    command.add_argument('--tag', action='append', default=[])
    command.add_argument('--category-id', default='22')
    command = sub.add_parser("new")
    command.add_argument("idea")
    command.add_argument("--test", action="store_true")
    for name in ('plan', 'research'):
        command = sub.add_parser(name)
        command.add_argument('pid')
        if name == 'plan':
            command.add_argument('--fresh', action='store_true')
    command = sub.add_parser('doctrine')
    command.add_argument('--write', nargs='?', const='', metavar='PATH')
    for name in ("timeline", "storyboard", "check"):
        command = sub.add_parser(name)
        command.add_argument("pid")
        command.add_argument("--json", action="store_true")
    command = sub.add_parser("snapshot")
    command.add_argument("pid")
    command.add_argument("--sheet", action="store_true")
    command = sub.add_parser("review")
    command.add_argument("pid")
    command.add_argument("--full", action="store_true")
    command.add_argument("--json", action="store_true")
    command = sub.add_parser("fix")
    command.add_argument("pid")
    command.add_argument("note_id")
    command.add_argument("--apply", action="store_true")
    command = sub.add_parser("apply")
    command.add_argument("pid")
    command.add_argument("patch")
    command = sub.add_parser("ask")
    command.add_argument("pid")
    command.add_argument("t", type=float)
    command.add_argument("intent")
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--copy", action="store_true")
    mode.add_argument("--apply", action="store_true")
    command = sub.add_parser("scene-check")
    command.add_argument("template")
    command.add_argument("--ctx")
    command = sub.add_parser("scene-preview")
    command.add_argument("template")
    command.add_argument("--ctx")
    command.add_argument("--project")
    command.add_argument("--t", type=float, default=1.5)
    command.add_argument("--out")
    command.add_argument("--mp4", action="store_true")
    command.add_argument("--seconds", type=float, default=3)
    command = sub.add_parser("catalog")
    catalog_sub = command.add_subparsers(dest="catalog_cmd", required=True)
    catalog_sub.add_parser("list")
    catalog_sub.add_parser("search").add_argument("query")
    catalog_sub.add_parser("fetch").add_argument("name")
    command = sub.add_parser('footage')
    footage_sub = command.add_subparsers(dest='footage_cmd', required=True)
    child = footage_sub.add_parser('import', help='Import or resume a shoot from the same path')
    child.add_argument('path')
    child.add_argument('--copy', action='store_true', help='Copy sources into app storage (default: link)')
    footage_sub.add_parser('list')
    footage_sub.add_parser('status').add_argument('shoot')
    for name, action, value in [('rule', 'add', 'text'), ('look', 'reject', 'token'), ('format', 'save', 'name')]:
        command = sub.add_parser(name)
        actions = command.add_subparsers(dest='action', required=True)
        child = actions.add_parser(action)
        child.add_argument(value)
        child.add_argument('--pid', required=True)
        if name != 'format':
            child.add_argument('--scope', choices=('project', 'channel'), default='project')
        else:
            actions.add_parser('list').add_argument('cid')
    args = ap.parse_args(argv)
    try:
        ensure_dirs()
        status = {"rule": cmd_learning, "look": cmd_learning, "format": cmd_learning, "render": cmd_render, "publish": cmd_publish, "new": cmd_new, "plan": cmd_plan, "research": cmd_plan,
         "doctrine": cmd_doctrine, "check": cmd_check, "list": cmd_list, "timeline": cmd_timeline,
         "storyboard": cmd_storyboard, "apply": cmd_apply, "snapshot": cmd_snapshot,
         "scene-check": cmd_scene_check, "scene-preview": cmd_scene_preview, "catalog": cmd_catalog, "footage": cmd_footage,
         "review": cmd_review, "fix": cmd_fix, "ask": cmd_ask}[args.cmd](args)
        sys.stdout.flush()
        return status or 0
    except BrokenPipeError:
        # A consumer such as head has finished; avoid another error at exit.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except (edits.EditError, OSError, ValueError, httpx.HTTPError, ffutil.FFError, llm.LLMError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
