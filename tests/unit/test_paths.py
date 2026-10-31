"""Data-folder fallback never moves data or creates folders on lookup."""
import pytest

from app import brand, paths


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    for name in brand.env_names("DATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "LEGACY_DIR_IN_USE", False)


@pytest.mark.parametrize("existing, expected, legacy", [
    (["youslop"], "youslop", True),
    (["youslop", "corkbored"], "corkbored", False),
    ([], "corkbored", False),
])
def test_platform_fallback(tmp_path, existing, expected, legacy):
    for name in existing:
        (tmp_path / name).mkdir()
    assert paths._platform_data_root() == tmp_path / expected
    assert paths.data_root() == tmp_path / expected
    assert paths.describe()["legacy"] is legacy
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(existing)


def test_legacy_flag_tracks_current_selection(monkeypatch, tmp_path):
    (tmp_path / "youslop").mkdir()
    assert paths.describe()["legacy"] is True
    (tmp_path / "corkbored").mkdir()
    assert paths.describe()["legacy"] is False
    monkeypatch.setenv("CORKBORED_DATA", str(tmp_path / "override"))
    assert paths.describe()["legacy"] is False
    assert paths.data_root() == tmp_path / "override"


def test_checkout_keeps_projects(monkeypatch, tmp_path):
    (tmp_path / "projects").mkdir()
    (tmp_path / "youslop").mkdir()
    paths._platform_data_root()
    monkeypatch.setattr(paths, "FROZEN", False)
    monkeypatch.setattr(paths, "SOURCE_ROOT", tmp_path)
    assert paths.data_root() == tmp_path
    assert paths.describe()["legacy"] is False


@pytest.mark.parametrize("prefix", ["CORKBORED_", "YOUSLOP_", "VB_"])
def test_data_override(monkeypatch, tmp_path, prefix):
    override = tmp_path / "override"
    monkeypatch.setenv(prefix + "DATA", str(override))
    assert paths.data_root() == override
    assert paths.describe()["overridden"] is True
    monkeypatch.setenv("CORKBORED_DATA", str(tmp_path / "preferred"))
    assert paths.data_root() == tmp_path / "preferred"
