"""Make source imports and a temporary data root safe before test collection."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
_DATA = tempfile.TemporaryDirectory(prefix="corkbored-tests-")
os.environ["CORKBORED_DATA"] = _DATA.name
