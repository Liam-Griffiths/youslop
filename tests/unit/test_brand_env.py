"""Brand aliases preserve both name priority and configuration source priority."""
import os
import subprocess
from pathlib import Path

import pytest

from app import brand


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith((brand.ENV_PREFIX, *brand.LEGACY_ENV_PREFIXES)):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CORKBORED_DATA", str(tmp_path))


def test_env_names():
    assert brand.env_names("EFFORT") == [
        "CORKBORED_EFFORT", "YOUSLOP_EFFORT", "VB_EFFORT"]


@pytest.mark.parametrize("values, expected", [
    ({}, "fallback"),
    ({"VB_EFFORT": "low"}, "low"),
    ({"YOUSLOP_EFFORT": "high"}, "high"),
    ({"VB_EFFORT": "low", "YOUSLOP_EFFORT": "high"}, "high"),
    ({"YOUSLOP_EFFORT": "high", "CORKBORED_EFFORT": "max"}, "max"),
    ({"YOUSLOP_EFFORT": "high", "CORKBORED_EFFORT": ""}, ""),
])
def test_env(monkeypatch, values, expected):
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert brand.env("EFFORT", "fallback") == expected


@pytest.mark.parametrize("values, expected", [
    ({"VB_EFFORT": "low", "YOUSLOP_EFFORT": "high"}, "high"),
    ({"YOUSLOP_EFFORT": "high", "VB_EFFORT": "low"}, "high"),
    ({"VB_EFFORT": "low"}, "low"),
    ({"YOUSLOP_EFFORT": "high", "CORKBORED_EFFORT": ""}, ""),
])
def test_promote_legacy(values, expected):
    original = dict(values)
    brand.promote_legacy(values)
    assert values["CORKBORED_EFFORT"] == expected
    assert all(values[key] == value for key, value in original.items())
    once = dict(values)
    brand.promote_legacy(values)
    assert values == once


@pytest.mark.parametrize("shell, dot, expected", [
    ({"YOUSLOP_EFFORT": "high"}, "CORKBORED_EFFORT=medium", "high"),
    ({"VB_EFFORT": "high"}, "YOUSLOP_EFFORT=medium", "high"),
    ({"CORKBORED_EFFORT": ""}, "YOUSLOP_EFFORT=medium", ""),
    ({}, "YOUSLOP_EFFORT=high", "high"),
    ({}, "VB_EFFORT=medium\nYOUSLOP_EFFORT=high", "high"),
    ({}, "CORKBORED_EFFORT=max\nYOUSLOP_EFFORT=high", "max"),
    ({}, "", "low"),
])
def test_configuration_sources(monkeypatch, tmp_path, shell, dot, expected):
    from app import config, settings

    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    settings.save_file({"effort": "low"})
    (tmp_path / ".env").write_text(dot)
    for name, value in shell.items():
        monkeypatch.setenv(name, value)
    # Track the writes from _load_environment so they are restored by pytest.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    config._load_environment()
    assert brand.env("EFFORT") == expected
    assert settings.environment_overrides() == {"CORKBORED_EFFORT": "low"}
    assert settings.load_file() == {"effort": "low"}


@pytest.mark.parametrize("prefix", ["CORKBORED_", "YOUSLOP_", "VB_"])
def test_settings_legacy_lock(monkeypatch, prefix):
    from app import settings

    settings.save_file({"effort": "low"})
    monkeypatch.setenv(prefix + "EFFORT", "high")
    field = next(f for f in settings.status() if f["key"] == "effort")
    assert field["locked"] is True
    assert field["env"] == "CORKBORED_EFFORT"
    assert field["aliases"] == ["YOUSLOP_EFFORT", "VB_EFFORT"]
    third_party = settings.FIELDS_BY_KEY["anthropic_api_key"]
    assert third_party.env == "ANTHROPIC_API_KEY"
    assert third_party.aliases == ()


@pytest.mark.parametrize("prefix", ["CORKBORED_", "YOUSLOP_", "VB_"])
def test_data_root_before_config(monkeypatch, tmp_path, prefix):
    from app import paths

    monkeypatch.delenv("CORKBORED_DATA")
    monkeypatch.setenv(prefix + "DATA", str(tmp_path))
    assert paths.data_root() == tmp_path
    assert paths.describe()["overridden"] is True


@pytest.mark.parametrize("values, expected, query", [
    ({"VB_TOKEN": "old"}, "old", "?t=old"),
    ({"VB_TOKEN": "old", "YOUSLOP_TOKEN": "middle"}, "middle", "?t=middle"),
    ({"VB_TOKEN": "old", "CORKBORED_TOKEN": "new"}, "new", "?t=new"),
    ({"VB_TOKEN": "old", "CORKBORED_TOKEN": "off"}, "off", ""),
])
def test_run_sh_token_aliases(tmp_path, values, expected, query):
    # Exercise only the token block: no server, network, or token-file writes.
    source = (Path(__file__).resolve().parents[2] / "run.sh").read_text()
    block = source[source.index('QS=""'):source.index('echo "→')]
    result = subprocess.run(
        ["bash", "-eu", "-c", block + '\nprintf "%s\\n%s" "$CORKBORED_TOKEN" "$QS"'],
        env={**os.environ, "HOST": "0.0.0.0", **values}, cwd=tmp_path,
        capture_output=True, text=True, check=True)
    assert result.stdout == expected + "\n" + query
