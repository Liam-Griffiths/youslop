"""Fresh filenames for audio; callers serialize allocation with the project lock."""
from pathlib import Path


def _next_path(folder: Path, sid: str, ext: str, reserved=()) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}{ext}"
    n = 2
    while path.exists() or path in reserved:
        path = folder / f"{sid}.{n}{ext}"
        n += 1
    return path


def _reserved(root):
    # A missing file may be put back later. Its old references, including undo
    # checkpoints, must keep pointing at that recording rather than a new one.
    from .undo import referenced_files
    return {root / path for path in referenced_files(root)} if (root / 'project.json').is_file() else set()


def next_take_path(root: Path, track: str, sid: str, ext: str = ".wav") -> Path:
    """Return takes/<track>/<sid>.wav, or the first free numbered variant."""
    return _next_path(root / "takes" / track, sid, ext, _reserved(root))


def next_raw_path(root: Path, sid: str, ext: str = ".webm") -> Path:
    """Return a free filename under raw/."""
    return _next_path(root / "raw", sid, ext, _reserved(root))
