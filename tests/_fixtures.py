"""Copy the synthetic project into the already isolated application data root."""
import shutil
from pathlib import Path

from app import store

ROOT = Path(__file__).resolve().parents[1]


def load_project():
    """Return a fresh model; all generated assets stay in temporary storage."""
    source = ROOT / "tests/fixtures/project_min"
    destination = store.project_dir("ptest0001")
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return store.load("ptest0001")
