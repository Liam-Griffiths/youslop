"""Isolate application data before any test module imports app."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DATA = tempfile.TemporaryDirectory(prefix="corkbored-tests-")
os.environ["YOUSLOP_DATA"] = os.environ["CORKBORED_DATA"] = _DATA.name


def pytest_addoption(parser):
    # update deliberately, say why in the commit
    parser.addoption("--update-goldens", action="store_true", default=False,
                     help="Deliberately replace graph and visual references")


@pytest.fixture(scope="session")
def project_min():
    from tests._fixtures import load_project
    return load_project()


@pytest.fixture
def project(project_min):
    from app.schema import Project
    return Project.from_dict(project_min.to_dict())
