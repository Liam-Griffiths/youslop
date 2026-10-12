#!/usr/bin/env python3
"""Fetch the ffmpeg and ffprobe this platform will ship with.

A build step, not a runtime one, and deliberately not committed: the binaries
are ~90MB a platform and git is the wrong place for them. `resources/bin/` is
gitignored; a release build runs this first, and a checkout that has not run it
falls back to whatever ffmpeg is on PATH (see `config._binary`).

Youslop is GPLv3, so these are **GPL** builds — the ones with libx264 in them,
which every render needs. An LGPL build without x264 would fail on the first
segment. See THIRD-PARTY.md for what that obliges us to carry.

    python scripts/fetch_ffmpeg.py              this platform
    python scripts/fetch_ffmpeg.py --all        every platform (for CI)
    python scripts/fetch_ffmpeg.py --verify     re-check what is already there

Each fetch records the URL and the SHA-256 it actually got in
`resources/bin/MANIFEST.json`. Run it once, commit the manifest, and every
later run verifies against it and refuses a binary that has changed underneath
you — the upstream "latest" URLs are moving targets.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "resources" / "bin"
MANIFEST = DEST / "MANIFEST.json"

# (platform, machine) -> how to get each binary.
#   gz      a gzipped bare executable
#   tar.xz  an archive, with the member path to pull out
#   zip     likewise
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
STATIC = ("https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1")

SOURCES: dict[str, dict] = {
    "darwin-arm64": {
        "ffmpeg": {"url": f"{STATIC}/ffmpeg-darwin-arm64.gz", "kind": "gz"},
        "ffprobe": {"url": f"{STATIC}/ffprobe-darwin-arm64.gz", "kind": "gz"},
    },
    "darwin-x86_64": {
        "ffmpeg": {"url": f"{STATIC}/ffmpeg-darwin-x64.gz", "kind": "gz"},
        "ffprobe": {"url": f"{STATIC}/ffprobe-darwin-x64.gz", "kind": "gz"},
    },
    "linux-x86_64": {
        "_archive": {"url": f"{BTBN}/ffmpeg-master-latest-linux64-gpl.tar.xz",
                     "kind": "tar.xz", "prefix": "ffmpeg-master-latest-linux64-gpl/bin"},
    },
    "linux-arm64": {
        "_archive": {"url": f"{BTBN}/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
                     "kind": "tar.xz", "prefix": "ffmpeg-master-latest-linuxarm64-gpl/bin"},
    },
    "windows-x86_64": {
        "_archive": {"url": f"{BTBN}/ffmpeg-master-latest-win64-gpl.zip",
                     "kind": "zip", "prefix": "ffmpeg-master-latest-win64-gpl/bin",
                     "suffix": ".exe"},
    },
}


def target() -> str:
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(
        platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    machine = {"aarch64": "arm64", "amd64": "x86_64", "x64": "x86_64"}.get(machine, machine)
    return f"{system}-{machine}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, into: Path) -> Path:
    print(f"    {url}")
    with urllib.request.urlopen(url) as r, into.open("wb") as fh:
        shutil.copyfileobj(r, fh)
    return into


def fetch(key: str, out_dir: Path) -> list[Path]:
    """Put ffmpeg and ffprobe for `key` into `out_dir`. Returns what it wrote."""
    spec = SOURCES.get(key)
    if spec is None:
        raise SystemExit(f"No ffmpeg source known for {key}. "
                         f"Known: {', '.join(sorted(SOURCES))}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if "_archive" in spec:
            a = spec["_archive"]
            blob = download(a["url"], tmp / "ffmpeg-archive")
            suffix = a.get("suffix", "")
            if a["kind"] == "zip":
                with zipfile.ZipFile(blob) as z:
                    for name in ("ffmpeg", "ffprobe"):
                        member = f"{a['prefix']}/{name}{suffix}"
                        out = out_dir / f"{name}{suffix}"
                        out.write_bytes(z.read(member))
                        written.append(out)
            else:
                with tarfile.open(blob) as t:
                    for name in ("ffmpeg", "ffprobe"):
                        member = t.extractfile(f"{a['prefix']}/{name}")
                        out = out_dir / name
                        out.write_bytes(member.read())
                        written.append(out)
        else:
            for name, a in spec.items():
                blob = download(a["url"], tmp / f"{name}.gz")
                out = out_dir / name
                with gzip.open(blob) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                written.append(out)
    for p in written:
        p.chmod(0o755)
    return written


def record(key: str, paths: list[Path]) -> None:
    data = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    spec = SOURCES[key]
    url = spec.get("_archive", {}).get("url") or next(iter(spec.values()))["url"]
    data[key] = {"source": url,
                 "files": {p.name: sha256(p) for p in sorted(paths)}}
    MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def verify(key: str, paths: list[Path]) -> bool:
    """Against the committed manifest, if there is one. First run writes it."""
    if not MANIFEST.exists():
        return True
    known = json.loads(MANIFEST.read_text()).get(key, {}).get("files", {})
    ok = True
    for p in paths:
        want = known.get(p.name)
        if want and want != sha256(p):
            print(f"  !! {p.name} does not match the manifest — refusing it")
            ok = False
    return ok


def smoke(out_dir: Path) -> bool:
    """Does it run, and was it built with the encoder every render needs?"""
    exe = out_dir / ("ffmpeg.exe" if (out_dir / "ffmpeg.exe").exists() else "ffmpeg")
    try:
        r = subprocess.run([str(exe), "-version"], capture_output=True, text=True,
                           timeout=30)
    except OSError as exc:
        print(f"  !! cannot run {exe}: {exc}")
        return False
    first = (r.stdout or "").splitlines()[:1]
    print(f"  {first[0] if first else '(no version line)'}")
    if "libx264" not in r.stdout:
        print("  !! built without libx264 — every render would fail")
        return False
    print("  libx264: present")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="every known platform")
    ap.add_argument("--verify", action="store_true",
                    help="only check what is already in resources/bin")
    args = ap.parse_args()

    if args.verify:
        ok = smoke(DEST)
        sys.exit(0 if ok else 1)

    keys = sorted(SOURCES) if args.all else [target()]
    for key in keys:
        out_dir = DEST if key == target() else DEST / key
        print(f"{key} -> {out_dir.relative_to(ROOT)}")
        paths = fetch(key, out_dir)
        if not verify(key, paths):
            sys.exit(1)
        record(key, paths)
        if key == target():
            if not smoke(out_dir):
                sys.exit(1)
        else:
            print("  fetched (not runnable here)")
    print(f"\nManifest: {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
