"""Opt-in, heavy measurement: two full-size single-segment renders, never a cut.

Usage: CORKBORED_DATA=/path/to/project-copy .venv/bin/python \
    scripts/measure_segment_rss.py <pid>

Each format runs in a fresh process so RUSAGE_CHILDREN maxima are independent.
Inputs are read from the explicit data root; generated files live in temporary
directories. The project and its recordings are never saved or overwritten.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile


def measure(pid: str, fmt: str, source: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="corkbored-rss-") as tmp:
        data = Path(tmp)
        original = source / "projects" / pid
        project = data / "projects" / pid
        project.mkdir(parents=True)
        shutil.copyfile(original / "project.json", project / "project.json")
        for name in ("media", "takes"):
            if (original / name).exists():
                (project / name).symlink_to(original / name, target_is_directory=True)
        for name in ("assets", "channels"):
            if (source / name).exists():
                (data / name).symlink_to(source / name, target_is_directory=True)
        # config.DATA is fixed at import time; only import after isolation.
        os.environ["CORKBORED_DATA"] = str(data)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import channels, render, store

        p = store.load(pid)
        p.style.format = fmt  # In memory only; never store.save.
        layout = render._layout(p)
        groups = layout["groups"]
        if not groups:
            raise ValueError("Project has no picture groups")
        index = max(range(len(groups)), key=lambda i: len(groups[i]))
        group = groups[index]
        _, _, seg_len = render._segment_timing(p, groups, index)
        chapter = (render.chapter_card(p, groups[index + 1][0][0])
                   if index + 1 < len(groups) else None)
        print(f"{fmt}: group {index}, {len(group)} paragraphs, "
              f"{seg_len:.3f}s, 1920x1080 at 30 fps", flush=True)
        render._render_segment(
            p, group, seg_len, index, data / "segment.mp4",
            channel=channels.load_or_none(p.channel_id), chapter=chapter,
            dip_out=render._dips_into(groups, index + 1))
        rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        mb = rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
        print(f"{fmt}: peak child RSS {mb:.2f} MB", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid")
    parser.add_argument("--child", choices=("essay", "kenburns"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = os.environ.get("CORKBORED_DATA") or os.environ.get("YOUSLOP_DATA")
    if not root:
        parser.error("Set CORKBORED_DATA (or YOUSLOP_DATA) to a project copy first")
    if Path(args.pid).name != args.pid or args.pid in (".", ".."):
        parser.error("pid must be a project id, not a path")
    if args.child:
        measure(args.pid, args.child, Path(root).expanduser().resolve())
        return
    print("WARNING: opt-in heavy work: rendering one full-size segment each "
          "for essay and kenburns, sequentially, in temporary directories.", flush=True)
    for fmt in ("essay", "kenburns"):
        subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        args.pid, "--child", fmt], check=True)


if __name__ == "__main__":
    main()
