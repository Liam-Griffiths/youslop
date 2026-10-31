"""Project and style bundles remain readable across the rename."""
import json
import zipfile

import pytest

from app import brand, slide_styles, store, transfer
from app.schema import Project


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    # conftest sets CORKBORED_DATA before collection; isolate each test too.
    projects = tmp_path / "projects"
    monkeypatch.setattr(store, "PROJECTS_DIR", projects)
    monkeypatch.setattr(transfer, "PROJECTS_DIR", projects)
    monkeypatch.setattr(transfer, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(transfer, "MUSIC_DIR", tmp_path / "music")


def test_export_keeps_old_builds_readable(tmp_path):
    project = store.save(Project(id="pexport", idea="Test", title="Tiny Video"))
    dest = tmp_path / (transfer.filename_for(project) + transfer.EXTENSION)
    transfer.export(project.id, dest)
    assert dest.name == "tiny-video.corkbored"
    assert transfer.EXTENSION == brand.FILE_EXT
    assert ".youslop" in transfer.LEGACY_EXTENSIONS
    with zipfile.ZipFile(dest) as zf:
        assert zf.read("corkbored.json") == zf.read("youslop.json")
        manifest = json.loads(zf.read("youslop.json"))
        assert manifest["corkbored_project"] == manifest["youslop_project"] == 1
        assert "project/project.json" in zf.namelist()
    imported = transfer.import_(dest, on_conflict="copy")
    assert store.load(imported["id"]).idea == project.idea


@pytest.mark.parametrize("manifest_name,key,extension", [
    ("youslop.json", "youslop_project", ".youslop"),
    ("corkbored.json", "corkbored_project", ".corkbored"),
])
def test_import_single_manifest(tmp_path, manifest_name, key, extension):
    project = Project(id="pimport", idea="Old idea", title="Portable video")
    src = tmp_path / ("portable" + extension)
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr(manifest_name, json.dumps({key: 1, "project_id": project.id}))
        zf.writestr("project/project.json", json.dumps(project.to_dict()))
    result = transfer.import_(src)
    loaded = store.load(result["id"])
    assert loaded.id == project.id
    assert loaded.title == project.title
    assert loaded.idea == project.idea


def test_new_manifest_takes_precedence(tmp_path):
    src = tmp_path / "future.corkbored"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("corkbored.json", json.dumps({"corkbored_project": 2}))
        zf.writestr("youslop.json", json.dumps({"youslop_project": 1}))
    with pytest.raises(transfer.TransferError, match="newer"):
        transfer.read_manifest(src)


def test_style_export_has_both_keys(monkeypatch):
    style = slide_styles.SlideStyle(id="ssfixture", name="Portable", spec={"elements": []})
    monkeypatch.setattr(slide_styles, "get", lambda sid: style)
    bundle = slide_styles.export_bundle(style.id)
    assert bundle["corkbored_slide_style"] == bundle["youslop_slide_style"] == 1


@pytest.mark.parametrize("key", ["corkbored_slide_style", "youslop_slide_style"])
def test_style_import_accepts_either_key(monkeypatch, key):
    # Avoid drawing a thumbnail: only the bundle wrapper is under test.
    monkeypatch.setattr(slide_styles, "save", lambda name, spec, hand: (name, spec))
    assert slide_styles.import_bundle({
        key: 1, "name": "Portable", "spec": {"elements": []},
    }) == ("Portable", {"elements": []})
