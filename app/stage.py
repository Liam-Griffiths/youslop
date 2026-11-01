"""The 3D stage's browser: everything that needs the GPU runs in a throwaway
headless Chromium, on the same scene code the app's own pages use.

    intake(ids)              measure, classify and photograph library models
    solve(items, models)     plan and check shots (static/stage/plan.js)
    render(items, models)    draw solved shots to mp4 clips

Each call starts a private HTTP server on 127.0.0.1 that serves the app's
static files, the model library and one `job.json`, then opens
static/stage/run.html in Chromium with a fresh profile. The page posts its
results back; for a render it posts every frame raw, in order, and the server
pipes them into ffmpeg. There is no Playwright and no remote debugging
protocol in push mode — the page drives itself, and a watchdog ends it if
it goes quiet. DOM scenes use CDP to seek and capture PNG frames instead.

The browser draws on the GPU (ANGLE over Vulkan on Linux; the spike measured
about 40 fps at 1080p on a Radeon 780M). See docs/3d-explainer.md, step 10.
"""
from __future__ import annotations

import base64
import http.server
import itertools
import json
import math
import os
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from . import brand, models3d, paths
from .config import FFMPEG, STATIC_DIR

Progress = Callable[[str], None]

PAGE = "/static/stage/run.html"


class StageError(RuntimeError):
    pass


# ------------------------------------------------------------------ browser
def browser() -> str | None:
    """A Chromium to draw with: $CHROMIUM, or the first one on the path."""
    names = [os.environ.get("CHROMIUM"), "chromium", "chromium-browser",
             "google-chrome", "google-chrome-stable", "chrome"]
    for name in names:
        if name and shutil.which(name):
            return shutil.which(name)
    for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(path).exists():
            return path
    return None


def available() -> tuple[bool, str]:
    if browser():
        return True, ""
    return False, ("3D shots are drawn by Chromium or Google Chrome, and neither "
                   "was found. Install one, or set CHROMIUM to its path.")


def _angle() -> str:
    # ANGLE's backend per platform: Vulkan reaches the GPU headless on Linux.
    return {"darwin": "metal", "win32": "d3d11"}.get(sys.platform, "vulkan")


# ------------------------------------------------------------------- server
class _Run:
    def __init__(self, job: dict, out_dir: Path | None):
        self.job, self.out_dir = job, out_dir
        self.token = secrets.token_hex(8)
        self.results: list[dict] = []
        self.errors: list[str] = []
        self.logs: list[str] = []
        self.thumbs: dict[str, bytes] = {}
        self.clips: dict[str, dict] = {}         # clip -> {proc, tmp, out, frames, got}
        self.done = threading.Event()
        self.last = time.time()
        self.lock = threading.Lock()
        self.on_result: Callable[[dict], None] = lambda r: None
        self.on_log: Callable[[str], None] = lambda m: None


def _handler(run: _Run):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(STATIC_DIR.parent), **k)

        def log_message(self, *a):
            pass

        def translate_path(self, path):
            path = path.split("?")[0]
            if path.startswith("/catalog/"):
                from .catalog import CATALOG_DIR
                root = CATALOG_DIR.resolve()
                relative = unquote(path[len("/catalog/"):])
                target = (root / relative).resolve()
                if (not target.is_relative_to(root) or target == root
                        or any(part.startswith('_') for part in Path(relative).parts)
                        or not target.is_file()):
                    return "/nonexistent"
                return str(target)
            if path.startswith("/scene/"):
                parts = unquote(path).split("/", 3)
                root = run.job.get("scene_root")
                if len(parts) != 4 or parts[2] != run.token or not root:
                    return "/nonexistent"
                root = Path(root).resolve()
                relative = parts[3]
                if ".." in relative:
                    return "/nonexistent"
                kind, _, rel = relative.partition("/")
                if kind in ("project", "channel"):
                    asset_root = run.job.get(kind + "_root")
                    if not asset_root or not rel:
                        return "/nonexistent"
                    root, relative = Path(asset_root).resolve(), rel
                if kind == "assets" and run.job.get("assets_root"):
                    root = Path(run.job["assets_root"]).resolve()
                    relative = relative[len("assets/"):]
                target = (root / relative).resolve()
                if target == root or not target.is_relative_to(root):
                    return "/nonexistent"
                return str(target)
            if path.startswith("/fonts/"):
                root = (paths.resource_root() / "resources" / "fonts").resolve()
                target = (root / unquote(path[len("/fonts/"):])).resolve()
                return str(target) if target.is_relative_to(root) else "/nonexistent"
            if path.startswith("/models/"):
                p = Path(path)
                try:
                    return str(models3d.glb_path(p.stem))
                except models3d.ModelError:
                    return "/nonexistent"
            if path.startswith("/static/"):
                return str(STATIC_DIR / path[len("/static/"):])
            return "/nonexistent"

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path.startswith(f"/scene/{run.token}/"):
                path = Path(self.translate_path(self.path))
                if path.suffix == ".html" and path.is_file():
                    body = path.read_text(encoding="utf-8").replace("{token}", run.token).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            if self.path.split("?")[0] == "/job.json":
                body = json.dumps(run.job).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def _reply(self, code: int = 204, text: str = ""):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            run.last = time.time()
            parts = self.path.split("/")
            what = parts[1] if len(parts) > 1 else ""
            if what == "frame":
                # Straight from the socket into the encoder: a 1080p frame is
                # 8 MB and there are thirty a second.
                clip = run.clips.get(parts[2])
                body = self.rfile.read(n)
                if not clip or clip["proc"].poll() is not None:
                    return self._reply(500, "no encoder for that clip")
                try:
                    clip["proc"].stdin.write(body)
                except (BrokenPipeError, OSError):
                    return self._reply(500, "the encoder stopped")
                clip["got"] += 1
                return self._reply()
            body = self.rfile.read(n)
            try:
                if what == "result":
                    r = json.loads(body)
                    with run.lock:
                        run.results.append(r)
                    run.on_result(r)
                elif what == "thumb":
                    run.thumbs["/".join(parts[2:])] = body
                elif what == "log":
                    msg = body.decode(errors="replace")
                    run.logs.append(msg)
                    run.on_log(msg)
                elif what == "error":
                    run.errors.append(json.loads(body).get("error", "") or "unknown page error")
                elif what == "begin":
                    _begin(run, parts[2], json.loads(body))
                elif what == "end":
                    _end(run, parts[2])
                elif what == "done":
                    run.done.set()
            except StageError as exc:
                run.errors.append(str(exc))
                return self._reply(500, str(exc))
            self._reply()
    return H


def _begin(run: _Run, clip: str, spec: dict) -> None:
    out = run.out_dir / f"{clip}.mp4"
    tmp = out.with_suffix(".part.mp4")
    W, H, fps = int(spec["W"]), int(spec["H"]), int(spec["fps"])
    # Kept close to lossless: this clip is graded and encoded again with the
    # titles over it, and an intermediate encode's softness would show twice.
    proc = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
         "-vf", "vflip", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
         "-pix_fmt", "yuv420p", "-an", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    run.clips[clip] = {"proc": proc, "tmp": tmp, "out": out, "frames": int(spec["frames"]), "got": 0}


def _end(run: _Run, clip: str) -> None:
    c = run.clips.get(clip)
    if not c:
        raise StageError(f"no clip {clip} was started")
    c["proc"].stdin.close()
    err = c["proc"].stderr.read().decode(errors="replace")
    if c["proc"].wait() != 0 or c["got"] != c["frames"]:
        c["tmp"].unlink(missing_ok=True)
        raise StageError(f"clip {clip}: {c['got']} of {c['frames']} frames encoded. {err.strip()[-300:]}")
    os.replace(c["tmp"], c["out"])
    c["done"] = True


def _chromium_flags(prof, size):
    return ["--headless=new", f"--use-angle={_angle()}", "--ignore-gpu-blocklist",
            f"--user-data-dir={prof}", f"--window-size={size[0]},{size[1]}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding"]


def _run(job: dict, progress: Progress, *, out_dir: Path | None = None,
         silence: int = 180, size: tuple[int, int] = (480, 270),
         on_result: Callable[[dict], None] | None = None) -> _Run:
    exe = browser()
    if not exe:
        raise StageError(available()[1])
    run = _Run(job, out_dir)
    if on_result:
        run.on_result = on_result
    run.on_log = lambda m: progress("  " + m) if m.startswith("shot ") else None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(run))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}{PAGE}"
    # A throwaway profile per run: a crashed run's profile lock once blocked
    # the next one silently.
    with tempfile.TemporaryDirectory(prefix=f"{brand.SLUG}-stage-",
                                     ignore_cleanup_errors=True) as prof:
        cmd = [exe, *_chromium_flags(prof, size), url]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while not run.done.wait(timeout=1):
                if time.time() - run.last > silence:
                    run.errors.append(f"the 3D page was silent for {silence} s")
                    break
                if proc.poll() is not None:
                    run.errors.append("the browser exited")
                    break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            srv.shutdown()
            srv.server_close()
            for c in run.clips.values():
                if not c.get("done") and c["proc"].poll() is None:
                    c["proc"].kill()
                    c["tmp"].unlink(missing_ok=True)
    return run


def _models(ids) -> dict[str, dict]:
    out = {}
    for mid in ids:
        out[mid] = models3d.get(mid)
    return out


# ------------------------------------------------------------------- intake
def intake(ids: list[str], progress: Progress = lambda m: None) -> list[dict]:
    """Measure and classify models the way the confirm screen does on first
    open, and give each a thumbnail. Saves into each manifest; returns what
    was found."""
    if not ids:
        return []
    progress(f"Measuring {len(ids)} model(s) on the GPU")
    run = _run({"task": "intake", "models": _models(ids), "items": [{"model": m} for m in ids]},
               progress, silence=300, size=(640, 360))
    for r in run.results:
        changes = {"analysis": r["analysis"], "measured": r["measured"]}
        models3d.update(r["model"], changes)
        thumb = run.thumbs.get(r["model"])
        if thumb:
            models3d.set_thumb(r["model"], thumb)
        progress(f"  {r['model']}: {r['analysis'].get('kind_auto')} ({r.get('ms')} ms)")
    if run.errors:
        raise StageError("; ".join(run.errors))
    return run.results


# -------------------------------------------------------------------- solve
def solve(items: list[dict], models: dict[str, dict], progress: Progress = lambda m: None,
          thumbs_dir: Path | None = None) -> dict[str, dict]:
    """Solve each item's shot. An item:

        {"id": slide id, "entries": [{"sid", "model"}], "intent": {...},
         "secs": seconds, "prev_id": an earlier item's id | None,
         "prev": {"shot", "k", "scene"} | None, "thumbs": bool}

    Returns {id: the page's result}. Thumbnails, when asked for, are written
    to `thumbs_dir` as <id>_<0|1|2>.jpg (first, middle, last frame)."""
    if not items:
        return {}
    for it in items:
        it.setdefault("thumbs", thumbs_dir is not None)
    out: dict[str, dict] = {}

    def got(r: dict) -> None:
        out[r["id"]] = r
        if r.get("error"):
            progress(f"  shot {len(out)}/{len(items)}: {r['error']}")
        else:
            state = "ok" if not r.get("flagged") else "flagged: " + ", ".join(r.get("failed") or [])
            progress(f"  shot {len(out)}/{len(items)} ({r.get('subject')}): {state}, "
                     f"{r.get('tried')} of {r.get('of')} tried in {r.get('ms')} ms")

    run = _run({"task": "solve", "models": models, "items": items}, progress, on_result=got)
    if thumbs_dir is not None:
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        for key, data in run.thumbs.items():
            sid, _, j = key.partition("/")
            (thumbs_dir / f"{sid}_{j}.jpg").write_bytes(data)
    if run.errors and not out:
        raise StageError("; ".join(run.errors))
    for e in run.errors:
        progress("3D page: " + e)
    return out


# ------------------------------------------------------------------- render
def render(items: list[dict], models: dict[str, dict], out_dir: Path,
           progress: Progress = lambda m: None) -> dict[str, Path]:
    """Draw clips. An item:

        {"clip": file stem, "entries": [...], "shot": {...}, "intent": {...},
         "look": "set", "haze": {...} | None, "W", "H", "fps", "frames",
         "overlay": {"template": "...html", "ctx": {...}, "project_root": "..."}}

    Writes <out_dir>/<clip>.mp4 for each and returns them by clip."""
    if not items:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = sum(int(i["frames"]) for i in items)
    W, H = items[0]["W"], items[0]["H"]
    progress(f"Drawing {len(items)} 3D shot(s), {frames} frames at {W}×{H}")
    t0 = time.time()
    # Overlay context belongs to the Python builder, not the WebGL page.
    push_items = [{k: v for k, v in i.items() if k != "overlay"} for i in items]
    run = _run({"task": "render", "models": models, "items": push_items}, progress, out_dir=out_dir)
    made = {c: v["out"] for c, v in run.clips.items() if v.get("done")}
    if run.errors or len(made) < len(items):
        missing = [i["clip"] for i in items if i["clip"] not in made]
        raise StageError("The 3D shots did not all render"
                         + (f" ({len(missing)} missing)" if missing else "")
                         + (": " + "; ".join(run.errors) if run.errors else ""))
    for item in items:
        if item.get("overlay"):
            _overlay_shot(item, made[item["clip"]])
    secs = max(0.01, time.time() - t0)
    progress(f"3D shots drawn: {frames} frames in {secs:.0f} s ({frames / secs:.0f} fps)")
    return made


def _overlay_shot(item, push_path):
    """Composite a builder alpha MOV; publish only a complete result."""
    from . import ffutil, scene_builder, scenes

    overlay = item["overlay"]
    size = (item["W"], item["H"])
    # Templates expect the standard scene context (frame, palette, fonts); the
    # caller's ctx overrides it, and its vars merge over the defaults.
    base = scenes.context_base(overlay.get("project"))
    given = dict(overlay["ctx"])
    ctx = {**base, **given, "vars": {**base.get("vars", {}), **given.get("vars", {})},
           "builder_alpha": True}
    # Lay out at the templates' design size (1920 on the long side); the builder
    # draws plates at the shot's size, as it does for quarter-size previews.
    if "width" not in given:
        long_side = 1920
        ctx["width"], ctx["height"] = ((long_side, round(long_side * size[1] / size[0]))
                                       if size[0] >= size[1] else
                                       (round(long_side * size[0] / size[1]), long_side))
    # Local scratch/cache by default; callers can share their project cache.
    with tempfile.TemporaryDirectory(dir=push_path.parent, prefix="stage-overlay-") as work:
        directory = Path(work)
        plate = scene_builder.render(overlay.get("project_root", directory),
            overlay["template"], ctx, directory / "overlay.mov",
            seconds=item["frames"] / item["fps"], size=size, fps=item["fps"], crf=12)
        graph = directory / "overlay.ffgraph"
        graph.write_text("[0:v]setpts=PTS-STARTPTS[base];"
                         "[1:v]setpts=PTS-STARTPTS[title];"
                         "[base][title]overlay=0:0:eof_action=pass:repeatlast=0:"
                         "format=auto,format=yuv420p[out]", encoding="utf-8")
        out = directory / "composited.mp4"
        args = ["-i", str(push_path), "-i", str(plate.path),
                "-filter_complex_threads", str(ffutil._default_threads()),
                "-filter_complex_script", str(graph), "-map", "[out]",
                "-frames:v", str(item["frames"]), "-r", str(item["fps"]),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                "-pix_fmt", "yuv420p", "-an", str(out)]
        try:
            try:
                ffutil.run(args)
            except ffutil.FFError as exc:
                # Match the builder's support for ffmpeg's newer file syntax.
                if "Unrecognized option 'filter_complex_script'" not in str(exc):
                    raise
                args[args.index('-filter_complex_script')] = '-/filter_complex'
                ffutil.run(args)
        except ffutil.FFError as exc:
            raise StageError(f"3D overlay failed: {exc}") from exc
        out.replace(push_path)


# -------------------------------------------------------------- DOM scenes
class _Cdp:
    """NUL-framed CDP pipe, with independent reply queues and bounded events."""
    def __init__(self, w_in, r_out):
        self.w, self.r = w_in, r_out
        self.ids = itertools.count(1)
        self.waiting = {}
        self.events = []
        self.condition = threading.Condition()
        self.write_lock = threading.Lock()
        self.closed = False
        self.on_event = None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        buf = b""
        try:
            while chunk := os.read(self.r, 1 << 20):
                buf += chunk
                while b"\0" in buf:
                    raw, buf = buf.split(b"\0", 1)
                    msg = json.loads(raw)
                    with self.condition:
                        if "id" in msg:
                            q = self.waiting.pop(msg["id"], None)
                            if q is not None:
                                q.put(msg)
                        else:
                            if self.on_event is not None:
                                self.on_event(msg)
                            self.events.append(msg)
                            self.events[:] = self.events[-200:]
                        self.condition.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            with self.condition:
                self.closed = True
                for q in self.waiting.values():
                    q.put(None)
                self.waiting.clear()
                self.condition.notify_all()

    def send(self, method, params=None, session=None, timeout=30):
        q = queue.Queue(1)
        with self.condition:
            if self.closed:
                raise StageError("the CDP pipe closed")
            ident = next(self.ids)
            self.waiting[ident] = q
        msg = {"id": ident, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        try:
            with self.write_lock:
                data = memoryview(json.dumps(msg).encode() + b"\0")
                while data:
                    data = data[os.write(self.w, data):]
            reply = q.get(timeout=timeout)
            if reply is None:
                raise StageError("the CDP pipe closed")
            if "error" in reply:
                raise StageError(f"{method}: {reply['error']}")
            return reply.get("result", {})
        except (OSError, queue.Empty) as exc:
            raise StageError(f"{method}: CDP pipe failed or timed out") from exc
        finally:
            with self.condition:
                self.waiting.pop(ident, None)

    def clear_events(self):
        with self.condition:
            self.events.clear()

    def wait_event(self, method, timeout=30):
        end = time.monotonic() + timeout
        with self.condition:
            while True:
                for event in self.events:
                    if event.get("method") == method:
                        self.events.remove(event)
                        return event
                if self.closed:
                    raise StageError("the CDP pipe closed")
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise StageError(f"waiting for {method} timed out")
                self.condition.wait(remaining)

    def close(self):
        os.close(self.w)
        self.reader.join(timeout=2)
        os.close(self.r)


def _begin_png(run, clip, W, H, fps, frames, *, alpha=False):
    out = run.out_dir / (clip + (".mov" if alpha else ".mp4"))
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    encoding = (["-c:v", "png", "-pix_fmt", "rgba"] if alpha else
                ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                 "-pix_fmt", "yuv420p"])
    proc = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "image2pipe", "-c:v", "png", "-framerate", str(fps), "-i", "-",
         *encoding, "-an", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    run.clips[clip] = {"proc": proc, "tmp": tmp, "out": out, "frames": frames, "got": 0}


def _evaluate(cdp, session, expression):
    result = cdp.send("Runtime.evaluate", {"expression": expression,
                      "awaitPromise": True, "returnByValue": True}, session)
    if details := result.get("exceptionDetails"):
        raise StageError(details.get("exception", {}).get("description")
                         or details.get("text", "scene JavaScript failed"))
    return result


def _run_cdp(job, progress, *, out_dir=None, size=(480, 270), fps=30,
             frames=1, seek_js="window.__seek({t})", deterministic=True,
             session_action=None, scene_probe=None):
    """Run scene capture, or a custom action with the same managed CDP session.

    session_action(cdp, session, run) owns navigation and capture when supplied.
    Event callbacks run on the reader thread and must not send CDP commands.
    """
    if sys.platform == "win32":
        raise StageError("scene rendering needs Linux or macOS for now")
    import fcntl

    exe = browser()
    if not exe:
        raise StageError(available()[1])
    run = _Run(job, out_dir)
    srv = None
    if session_action is None:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(run))
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    proc = cdp = prof = None
    pipes = []
    try:
        prof = tempfile.TemporaryDirectory(prefix=f"{brand.SLUG}-scene-",
                                           ignore_cleanup_errors=True)
        r_in, w_in = os.pipe()
        r_out, w_out = os.pipe()
        pipes = [r_in, w_in, r_out, w_out]

        def wire():
            a = fcntl.fcntl(r_in, fcntl.F_DUPFD, 5)
            b = fcntl.fcntl(w_out, fcntl.F_DUPFD, 5)
            os.dup2(a, 3)
            os.dup2(b, 4)
            os.close(a)
            os.close(b)

        cmd = [exe, *_chromium_flags(prof.name, size), "--remote-debugging-pipe",
               "--mute-audio", "--hide-scrollbars", "--force-color-profile=srgb",
               "--disable-gpu-vsync", "--run-all-compositor-stages-before-draw"]
        proc = subprocess.Popen(cmd, pass_fds=(3, 4), preexec_fn=wire,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r_in)
        os.close(w_out)
        pipes = [w_in, r_out]
        cdp = _Cdp(w_in, r_out)
        pipes = []
        targets = cdp.send("Target.getTargets")["targetInfos"]
        target = next((t for t in targets if t["type"] == "page"), None)
        if target is None:
            target = cdp.send("Target.createTarget", {"url": "about:blank"})
        session = cdp.send("Target.attachToTarget", {
            "targetId": target["targetId"], "flatten": True})["sessionId"]
        cdp.send("Page.enable", session=session)
        cdp.send("Runtime.enable", session=session)
        if session_action is not None:
            session_action(cdp, session, run)
            return run
        for item in job["items"]:
            W, H = int(item["W"]), int(item["H"])
            output_size = item.get("size", size)
            if output_size[0] / W != output_size[1] / H:
                raise StageError("scene output size must match the composition aspect ratio")
            cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": W, "height": H, "deviceScaleFactor": output_size[0] / W,
                "mobile": False}, session)
            path = item["url_path"].replace("{token}", run.token)
            if not path.startswith(("/static/", f"/scene/{run.token}/")):
                raise StageError("scene URL must be a local /static/ or /scene/{token}/ path")
            cdp.clear_events()
            nav = cdp.send("Page.navigate", {
                "url": f"http://127.0.0.1:{srv.server_address[1]}{path}"}, session)
            if nav.get("errorText"):
                raise StageError(nav["errorText"])
            cdp.wait_event("Page.loadEventFired")
            cdp.send("Emulation.setDefaultBackgroundColorOverride",
                     {"color": {"r": 0, "g": 0, "b": 0, "a": 0}} if item.get("alpha") else {}, session)
            _evaluate(cdp, session, "window.__ready")
            if deterministic:
                _evaluate(cdp, session, """(() => {
                    const style = document.createElement('style');
                    style.textContent = '*{transition:none!important;animation-play-state:paused!important;caret-color:transparent!important}';
                    document.head.appendChild(style);
                })()""")
            clip = item.get("clip", "snapshot")
            count, rate = int(item.get("frames", frames)), item.get("fps", fps)
            if out_dir is not None:
                _begin_png(run, clip, *output_size, rate, count, alpha=item.get("alpha", False))
            for i in range(count):
                t = item.get("t", i / rate)
                _evaluate(cdp, session, seek_js.format(t=t))
                if scene_probe is not None:
                    scene_probe(cdp, session, item, t)
                if item.get("measure_only"):
                    continue
                png = base64.b64decode(cdp.send("Page.captureScreenshot", {
                    "format": "png", "fromSurface": True}, session)["data"])
                if out_dir is None:
                    run.thumbs[clip] = png
                else:
                    c = run.clips[clip]
                    try:
                        c["proc"].stdin.write(png)
                    except OSError as exc:
                        raise StageError(f"scene encoder stopped: {clip}") from exc
                    c["got"] += 1
                if (i + 1) % 30 == 0:
                    progress(f"Scene {clip}: {i + 1}/{count} frames")
            if out_dir is not None:
                _end(run, clip)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if cdp is not None:
            cdp.close()
        if prof is not None:
            prof.cleanup()
        for fd in pipes:
            os.close(fd)
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        for c in run.clips.values():
            if not c.get("done"):
                if c["proc"].poll() is None:
                    c["proc"].kill()
                c["proc"].wait()
                try:
                    c["proc"].stdin.close()
                except OSError:
                    pass
                c["proc"].stderr.close()
                c["tmp"].unlink(missing_ok=True)
    return run


def render_scene(items: list[dict], out_dir: Path,
                 progress: Progress = lambda m: None, *, models=None) -> dict[str, Path]:
    """Capture local HTML scenes sequentially using one browser.

    Items supply clip, url_path, W, H, fps, frames, size. For project files,
    also supply a shared scene_root and use /scene/{token}/relative.html.
    With models supplied, items are 3D shots (including optional overlay),
    delegated to the push renderer. CDP never captures 3D video.
    """
    if models is not None:
        return render(items, models, out_dir, progress)
    if not items:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    roots = {str(Path(i["scene_root"]).resolve()) for i in items if i.get("scene_root")}
    if len(roots) > 1:
        raise StageError("one scene_root is allowed per render call")
    assets = {str(Path(i["assets_root"]).resolve()) for i in items if i.get("assets_root")}
    if len(assets) > 1:
        raise StageError("one assets_root is allowed per render call")
    asset_roots = {}
    for kind in ("project", "channel"):
        values = {str(Path(i[kind + '_root']).resolve()) for i in items if i.get(kind + '_root')}
        if len(values) > 1:
            raise StageError(f"one {kind}_root is allowed per render call")
        asset_roots[kind + '_root'] = next(iter(values), None)
    run = _run_cdp({"items": items, "scene_root": next(iter(roots), None),
                    "assets_root": next(iter(assets), None), **asset_roots},
                   progress, out_dir=out_dir)
    return {key: c["out"] for key, c in run.clips.items() if c.get("done")}


def capture_stills(items, scene_root=None, *, project_root=None, channel_root=None,
                   scene_probe=None, assets_root=None, models=None):
    """Capture local scenes, or 3D shot items at their requested t with models."""
    job = dict(items=items, scene_root=str(scene_root) if scene_root is not None else None,
               assets_root=assets_root, project_root=project_root, channel_root=channel_root)
    if models is not None:
        job.update(task="still", models=models,
                   stage_items=[{k: v for k, v in i.items() if k != "overlay"} for i in items])
        job["items"] = [dict(clip=i.get("clip", "snapshot"), W=i["W"], H=i["H"],
            size=i.get("size", (i["W"], i["H"])), t=i.get("t", 0), frames=1,
            url_path=f"{PAGE}?item={n}") for n, i in enumerate(items)]
    run = _run_cdp(job, lambda m: None,
                   scene_probe=scene_probe)
    return run.thumbs


def capture_one(url_path, W, H, t, size, *, assets_root=None,
                project_root=None, channel_root=None, scene_probe=None,
                stage_item=None, models=None) -> bytes:
    """Return a local scene PNG, or a 3D stage_item frame when models is supplied.

    For 3D, pass PAGE as url_path and the original push item's fps/frames/shot.
    t is in shot seconds and size is the screenshot size.
    """
    if stage_item is not None:
        if models is None:
            raise ValueError("3D stills require models")
        item = dict(stage_item, clip="snapshot", W=W, H=H, t=t, size=size)
        return capture_stills([item], models=models, scene_probe=scene_probe)["snapshot"]
    root = None
    if Path(url_path).is_file():
        from urllib.parse import quote
        path = Path(url_path).resolve()
        root, url_path = str(path.parent), "/scene/{token}/" + quote(path.name)
    run = _run_cdp({"scene_root": root,
                    "project_root": str(project_root) if project_root is not None else None,
                    "channel_root": str(channel_root) if channel_root is not None else None,
                    "assets_root": str(assets_root) if assets_root is not None else None, "items": [dict(
        url_path=url_path, W=W, H=H, t=t, size=size)]}, lambda m: None, scene_probe=scene_probe)
    return run.thumbs["snapshot"]


# Seek each element independently: later beats may be hidden at the first beat.
_TEXT_MEASURE = """(async () => {
    const rows = [];
    for (const e of document.querySelectorAll('[data-text]')) {
        let start = 0, arrive = 0;
        for (let c = e; c; c = c.parentElement) {
            if (c === e || c.matches('.clip')) start += Number(c.dataset.start || 0);
            if (c.dataset.revealStart) start += Number(c.dataset.revealStart);
            const css = getComputedStyle(c);
            if (c.dataset.anim || c.dataset.arrival) arrive = Math.max(arrive,
                Number(c.dataset.arrival || c.dataset.animDur || css.getPropertyValue('--arrive-s') || 0));
        }
        const t = Math.max(MEASURE_TIME, start + arrive);
        await window.__seek(t);
        const r = e.getBoundingClientRect(), css = getComputedStyle(e);
        const painted = e.matches('svg') ? [...e.querySelectorAll('text')].map(c => c.getBoundingClientRect()) : [r];
        let overflow = e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1;
        // SVG text has no CSS scroll box. Compare painted bounds to clipping
        // ancestors and the composition instead (also catches off-frame HTML).
        for (let c = e.parentElement; c; c = c.parentElement) {
            const style = getComputedStyle(c), b = c.getBoundingClientRect();
            if (c === document.documentElement || /hidden|clip|auto|scroll/.test(style.overflow)) {
                overflow ||= painted.some(r => r.left < b.left - 1 || r.right > b.right + 1 ||
                            r.top < b.top - 1 || r.bottom > b.bottom + 1);
            }
        }
        rows.push({id:e.dataset.text, ...r.toJSON(), px:parseFloat(css.fontSize), overflow, start, t});
    }
    return rows;
})()"""


def measure_many(items, scene_root, *, assets_root=None, project_root=None, channel_root=None):
    """Measure local pages in one managed browser, without screenshots."""
    measured = {}

    def probe(cdp, session, item, t):
        result = _evaluate(cdp, session, _TEXT_MEASURE.replace('MEASURE_TIME', repr(t)))
        measured[item['clip']] = result['result']['value']

    if items:
        _run_cdp(dict(items=[dict(i, measure_only=True) for i in items],
                      scene_root=str(scene_root) if scene_root is not None else None,
                      assets_root=str(assets_root) if assets_root is not None else None,
                      project_root=project_root, channel_root=channel_root),
                 lambda m: None, scene_probe=probe)
    return measured


def measure(url_path, W, H, t, **roots) -> list[dict]:
    """Report text geometry in composition pixels at each element's landing."""
    if not math.isfinite(t) or t < 0:
        raise ValueError('measurement time must be finite and nonnegative')
    root = None
    if Path(url_path).is_file():
        from urllib.parse import quote
        path = Path(url_path).resolve()
        root, url_path = path.parent, '/scene/{token}/' + quote(path.name)
    return measure_many([dict(clip='measure', url_path=str(url_path), W=W, H=H,
                              size=(W / 4, H / 4), t=t)], root, **roots)['measure']
