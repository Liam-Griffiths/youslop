"""Small in-process command line interface; writes require a closed app."""
import argparse
import json
import os
import sys
from pathlib import Path

from . import edits, render, store, storyboard
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


def cmd_apply(args):
    _guard_write()
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    with store.lock_for(args.pid):
        project = store.load(args.pid)
        changed = storyboard.apply(project, patch)
        store.save(project)
    _print_json(changed)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("timeline", "storyboard"):
        command = sub.add_parser(name)
        command.add_argument("pid")
        command.add_argument("--json", action="store_true")
    command = sub.add_parser("apply")
    command.add_argument("pid")
    command.add_argument("patch")
    args = ap.parse_args(argv)
    try:
        ensure_dirs()
        {"list": cmd_list, "timeline": cmd_timeline,
         "storyboard": cmd_storyboard, "apply": cmd_apply}[args.cmd](args)
        sys.stdout.flush()
    except BrokenPipeError:
        # A consumer such as head has finished; avoid another error at exit.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except (edits.EditError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
