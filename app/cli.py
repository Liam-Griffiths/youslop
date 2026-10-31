"""Small in-process command line interface; writes require a closed app."""
import httpx

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import check, edits, render, store, storyboard
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
    result = check.run(store.load(args.pid))
    if args.json:
        _print_json(result)
    else:
        for level in ("P0", "P1", "P2"):
            print(f"{level} ({result['counts'][level]})")
            for finding in result["findings"]:
                if finding["level"] == level:
                    print(f"  {finding['t']:.3f}s  {finding['msg']}")
    return 1 if result["counts"]["P0"] else 0


def cmd_apply(args):
    _guard_write()
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    with store.lock_for(args.pid):
        project = store.load(args.pid)
        changed = storyboard.apply(project, patch)
        store.save(project)
    _print_json(changed)


def cmd_scene_preview(args):
    from . import scenes

    project = store.load(args.project) if args.project else None
    ctx = scenes.context_base(project)
    if args.ctx:
        ctx.update(json.loads(Path(args.ctx).read_text(encoding="utf-8")))
    out = Path(args.out or ("scene.mp4" if args.mp4 else "frame.png"))
    # Keep temporary inputs alive until Chromium has finished reading them.
    with tempfile.TemporaryDirectory(prefix="corkbored-scene-") as temporary:
        root = project if project else Path(temporary)
        if args.mp4:
            clip = scenes.ensure_clip(root, args.template, ctx,
                                      seconds=args.seconds, size=(480, 270), fps=30)
            out.write_bytes(clip.read_bytes())
        else:
            out.write_bytes(scenes.capture(root, args.template, ctx,
                                          t=args.t, size=(480, 270)))
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("timeline", "storyboard", "check"):
        command = sub.add_parser(name)
        command.add_argument("pid")
        command.add_argument("--json", action="store_true")
    command = sub.add_parser("apply")
    command.add_argument("pid")
    command.add_argument("patch")
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
    args = ap.parse_args(argv)
    try:
        ensure_dirs()
        status = {"check": cmd_check, "list": cmd_list, "timeline": cmd_timeline,
         "storyboard": cmd_storyboard, "apply": cmd_apply,
         "scene-preview": cmd_scene_preview, "catalog": cmd_catalog}[args.cmd](args)
        sys.stdout.flush()
        return status or 0
    except BrokenPipeError:
        # A consumer such as head has finished; avoid another error at exit.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except (edits.EditError, OSError, ValueError, httpx.HTTPError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
