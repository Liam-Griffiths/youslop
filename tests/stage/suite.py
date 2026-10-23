"""The 3D stage's regression suite: the spike's six models, their reference
shots, and what the solver makes of them.

    ./.venv/bin/python tests/stage/suite.py              run, compare, report
    ./.venv/bin/python tests/stage/suite.py --only loft  just the models whose file name matches
    ./.venv/bin/python tests/stage/suite.py --accept     make the last run the baseline

It serves the repo and the model library (YOUSLOP_DATA's, like the app) to
headless Chromium, which runs tests/stage/suite/page.js: every case's search
with the GPU checks, then three preview frames of each pick. Results go to
<data>/stage-suite/latest/:

    results.json     each case's pick, check numbers and timing
    <model>.jpg      a contact sheet: a row per case, first / middle / last

and are compared with <data>/stage-suite/baseline/. A check that passed and
now fails, a case newly flagged, or a frame that no longer looks like the
baseline's (SSIM under 0.9) is a regression, and the exit code is 1. Numbers
that only move are listed, so a change that shifts them is seen before it
ships — the 3D counterpart of the 2D renderer's SSIM check.

The library is the creator's: the suite only reads it. It renders six large
models on the GPU, which takes a few minutes and is felt on a laptop.
"""
from __future__ import annotations

import argparse
import base64
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

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from app.config import DATA, MODELS_DIR  # noqa: E402

PAGE = "/tests/stage/suite/page.html"
SUITE_FILES = (                     # the spike's models; cases.js has their shots
    "airbus_a380.glb", "1903_wright_flyer.glb", "the_king_s_hall.glb",
    "westminster_abbey_london_uk.glb", "paris.glb", "loft_5_interior_for_free.glb",
)
TILE = (480, 270)
SSIM_MIN = 0.9
MOVED = 0.05                        # a number that moves more than 5% is listed


# ------------------------------------------------------------------ models
def library(only: list[str]) -> list[dict]:
    """The suite's models present in the library, newest copy of each file."""
    found: dict[str, dict] = {}
    for mf in sorted(MODELS_DIR.glob("*/manifest.json")):
        try:
            m = json.loads(mf.read_text())
        except (OSError, ValueError):
            continue
        name = m.get("filename")
        if name not in SUITE_FILES or (only and not any(o in name for o in only)):
            continue
        if name not in found or m.get("created_at", 0) > found[name]["created_at"]:
            found[name] = {"file": name, "id": m["id"], "created_at": m.get("created_at", 0)}
    return [{"file": f["file"], "id": f["id"]} for f in found.values()]


# ------------------------------------------------------------------ server
class Run:
    def __init__(self, models: list[dict], out: Path):
        self.models, self.out, self.trace = models, out, False
        self.results: list[dict] = []
        self.errors: list[str] = []
        self.done = threading.Event()
        self.last = time.time()


def handler(run: Run):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(REPO), **k)

        def log_message(self, *a):
            pass

        def translate_path(self, path):
            path = path.split("?")[0]
            if path.startswith("/models/"):
                p = Path(path)
                return str(MODELS_DIR / p.stem / ("model.glb" if p.suffix == ".glb" else "manifest.json"))
            return super().translate_path(path)

        def do_GET(self):
            if self.path == "/suite/models.json":
                body = json.dumps({"models": run.models, "trace": run.trace}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            run.last = time.time()
            if self.path.startswith("/frame/"):
                _, _, model, case, j = self.path.split("/")
                d = run.out / "frames" / Path(model).stem
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{case}_{j}.jpg").write_bytes(base64.b64decode(body.split(b",", 1)[1]))
            elif self.path == "/result":
                r = json.loads(body)
                run.results.append(r)
                status = "ok" if not r.get("failed") else "FLAGGED " + ",".join(r["failed"])
                print(f"  {Path(r['model']).stem} / {r['case']}: {status}"
                      f"  ({r.get('tried')} of {r.get('of')} tried, {r.get('ms')} ms)", flush=True)
            elif self.path == "/trace":
                t = json.loads(body)
                (run.out / f"trace-{Path(t['model']).stem}-{t['case']}.json").write_text(json.dumps(t, indent=1))
            elif self.path == "/log":
                print("  " + body.decode(), flush=True)
            elif self.path == "/error":
                run.errors.append(json.loads(body).get("error", ""))
                print("PAGE ERROR: " + run.errors[-1], flush=True)
            if self.path == "/done":
                run.done.set()
            self.send_response(204)
            self.end_headers()
    return H


def browser() -> str:
    for name in (os.environ.get("CHROMIUM"), "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if name and shutil.which(name):
            return shutil.which(name)
    sys.exit("No Chromium found; set CHROMIUM to its path.")


def run_page(run: Run, silence: int) -> None:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler(run))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}{PAGE}"
    # A throwaway profile per run: a crashed run's profile lock once blocked
    # the next one silently.
    with tempfile.TemporaryDirectory(prefix="stage-suite-") as prof:
        cmd = [browser(), "--headless=new", "--use-angle=vulkan",
               f"--user-data-dir={prof}", "--window-size=480,270", "--no-first-run", url]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while not run.done.wait(timeout=2):
                if time.time() - run.last > silence:
                    run.errors.append(f"the page was silent for {silence} s")
                    print("WATCHDOG: " + run.errors[-1], flush=True)
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


# ------------------------------------------------------------------ sheets
def headline(r: dict) -> str:
    c = r.get("checks") or {}
    bits = []
    for name, keys in (("visible", ["visible"]), ("voids", ["holes_pct", "sky_pct"]), ("edge", ["pct"]),
                       ("detail", ["px_per_texel"]), ("look_down", ["min_deg"]), ("haze", ["subject_haze"]),
                       ("clearance", ["metres"]), ("motion", ["peak_turn_deg_s"]), ("level", ["tilt_deg"])):
        if name in c:
            bits.append(name + " " + "/".join(str(c[name].get(k)) for k in keys))
    status = "ok" if not r.get("failed") else "FLAGGED: " + ", ".join(r["failed"])
    return f"{r['case']}  {status}   " + "  ".join(bits)


def sheet(out: Path, model: str, rows: list[dict]) -> Path:
    w, h, band = TILE[0], TILE[1], 22
    img = Image.new("RGB", (w * 3, (h + band) * len(rows)), (24, 24, 24))
    d = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        y = i * (h + band)
        d.text((6, y + 5), headline(r), fill=(255, 120, 120) if r.get("failed") else (230, 230, 230))
        for j in range(3):
            f = out / "frames" / Path(model).stem / f"{r['case']}_{j}.jpg"
            if f.exists():
                img.paste(Image.open(f).convert("RGB").resize(TILE), (j * w, y + band))
    path = out / f"{Path(model).stem}.jpg"
    img.save(path, quality=88)
    return path


# ------------------------------------------------------------------ compare
def ssim(a: Path, b: Path) -> float:
    """Mean SSIM over 8×8 windows on luma — enough to tell a changed frame
    from GPU noise."""
    x = np.asarray(Image.open(a).convert("L").resize(TILE), dtype=np.float64)
    y = np.asarray(Image.open(b).convert("L").resize(TILE), dtype=np.float64)

    def box(z, k=8):
        c = np.pad(z, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    mx, my = box(x), box(y)
    vx, vy, cxy = box(x * x) - mx * mx, box(y * y) - my * my, box(x * y) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s.mean())


def flat(d, prefix=""):
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            yield from flat(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def compare(latest: Path, base: Path, now: list[dict], ran: set[str]) -> tuple[list[str], list[str]]:
    """(regressions, notes) against the baseline run, for the models that ran."""
    bad, notes = [], []
    try:
        then = {(r["model"], r["case"]): r for r in json.loads((base / "results.json").read_text())}
    except (OSError, ValueError):
        return bad, ["no baseline yet: run with --accept to make this run the baseline"]
    for r in now:
        key, name = (r["model"], r["case"]), f"{Path(r['model']).stem} / {r['case']}"
        old = then.pop(key, None)
        if old is None:
            notes.append(f"{name}: new case")
            continue
        if r.get("flagged") and not old.get("flagged"):
            bad.append(f"{name}: newly flagged ({', '.join(r.get('failed', []))})")
        if old.get("pick") != r.get("pick"):
            notes.append(f"{name}: the pick changed {old.get('pick')} -> {r.get('pick')}")
        a, b = dict(flat(old.get("checks"))), dict(flat(r.get("checks")))
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k), b.get(k)
            if isinstance(va, bool) or isinstance(vb, bool):
                if va is True and vb is False:
                    bad.append(f"{name}: {k.split('.')[0]} passed, now fails")
                elif va != vb:
                    notes.append(f"{name}: {k} {va} -> {vb}")
            elif isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                if abs(vb - va) > 0.01 and abs(vb - va) > MOVED * max(abs(va), abs(vb)):
                    notes.append(f"{name}: {k} {va} -> {vb}")
            elif va != vb:
                notes.append(f"{name}: {k} {va} -> {vb}")
        for j in range(3):
            rel = Path("frames") / Path(r["model"]).stem / f"{r['case']}_{j}.jpg"
            if (latest / rel).exists() and (base / rel).exists():
                s = ssim(latest / rel, base / rel)
                if s < SSIM_MIN:
                    bad.append(f"{name}: frame {j} looks different (SSIM {s:.3f})")
    for (model, case) in then:
        if model in ran:
            notes.append(f"{Path(model).stem} / {case}: in the baseline, not run")
    return bad, notes


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="", help="comma-separated parts of model file names")
    ap.add_argument("--accept", action="store_true", help="make the last run the baseline, then exit")
    ap.add_argument("--out", type=Path, default=DATA / "stage-suite")
    ap.add_argument("--trace", action="store_true", help="save every candidate's checks (latest/trace-*.json)")
    ap.add_argument("--silence", type=int, default=120, help="seconds of page silence before giving up")
    args = ap.parse_args()
    latest, base = args.out / "latest", args.out / "baseline"

    if args.accept:
        if not (latest / "results.json").exists():
            sys.exit("Nothing to accept: run the suite first.")
        shutil.rmtree(base, ignore_errors=True)
        shutil.copytree(latest, base)
        print(f"Baseline is now the last run ({base}).")
        return 0

    only = [o.strip() for o in args.only.split(",") if o.strip()]
    models = library(only)
    missing = [f for f in SUITE_FILES if f not in {m["file"] for m in models} and (not only or any(o in f for o in only))]
    if not models:
        sys.exit(f"None of the suite's models are in {MODELS_DIR}.")
    shutil.rmtree(latest, ignore_errors=True)
    latest.mkdir(parents=True)
    print(f"Stage suite: {len(models)} models from {MODELS_DIR}")
    for f in missing:
        print(f"  not in the library, skipped: {f}")

    run = Run(models, latest)
    run.trace = args.trace
    t0 = time.time()
    run_page(run, args.silence)
    results = sorted(run.results, key=lambda r: (SUITE_FILES.index(r["model"]), r["case"]))
    (latest / "results.json").write_text(json.dumps(results, indent=1))
    for m in models:
        rows = [r for r in results if r["model"] == m["file"] and not r.get("error")]
        if rows:
            print(f"  sheet: {sheet(latest, m['file'], rows)}")

    bad, notes = compare(latest, base, results, {m["file"] for m in models})
    bad = [f"page: {e}" for e in run.errors] + bad
    flagged = [r for r in results if r.get("flagged")]
    print(f"\n{len(results)} shots in {time.time() - t0:.0f} s; {len(flagged)} flagged by the solver.")
    for n in notes:
        print("  moved   " + n)
    for b in bad:
        print("  WORSE   " + b)
    if not bad:
        print("No regressions against the baseline." if (base / "results.json").exists() else "")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
