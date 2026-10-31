"""Fresh filenames for audio; callers serialize allocation with the project lock."""
from pathlib import Path


def _next_path(folder: Path, sid: str, ext: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}{ext}"
    n = 2
    while path.exists():
        path = folder / f"{sid}.{n}{ext}"
        n += 1
    return path


def next_take_path(root: Path, track: str, sid: str, ext: str = ".wav") -> Path:
    """Return takes/<track>/<sid>.wav, or the first free numbered variant."""
    return _next_path(root / "takes" / track, sid, ext)


def next_raw_path(root: Path, sid: str, ext: str = ".webm") -> Path:
    """Return a free filename under raw/."""
    return _next_path(root / "raw", sid, ext)
