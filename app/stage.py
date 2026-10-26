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
protocol — the page drives itself, and a watchdog ends it if it goes quiet.

The browser draws on the GPU (ANGLE over Vulkan on Linux; the spike measured
about 40 fps at 1080p on a Radeon 780M). See docs/3d-explainer.md, step 10.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from . import models3d
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
    with tempfile.TemporaryDirectory(prefix="youslop-stage-") as prof:
        cmd = [exe, "--headless=new", f"--use-angle={_angle()}", "--ignore-gpu-blocklist",
               f"--user-data-dir={prof}", f"--window-size={size[0]},{size[1]}",
               "--no-first-run", "--no-default-browser-check", "--disable-extensions",
               "--disable-background-timer-throttling", "--disable-renderer-backgrounding", url]
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
         "look": "set", "haze": {...} | None, "W", "H", "fps", "frames"}

    Writes <out_dir>/<clip>.mp4 for each and returns them by clip."""
    if not items:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = sum(int(i["frames"]) for i in items)
    W, H = items[0]["W"], items[0]["H"]
    progress(f"Drawing {len(items)} 3D shot(s), {frames} frames at {W}×{H}")
    t0 = time.time()
    run = _run({"task": "render", "models": models, "items": items}, progress, out_dir=out_dir)
    made = {c: v["out"] for c, v in run.clips.items() if v.get("done")}
    if run.errors or len(made) < len(items):
        missing = [i["clip"] for i in items if i["clip"] not in made]
        raise StageError("The 3D shots did not all render"
                         + (f" ({len(missing)} missing)" if missing else "")
                         + (": " + "; ".join(run.errors) if run.errors else ""))
    secs = max(0.01, time.time() - t0)
    progress(f"3D shots drawn: {frames} frames in {secs:.0f} s ({frames / secs:.0f} fps)")
    return made
