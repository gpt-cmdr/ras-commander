"""Offline cache identity regressions using temporary ZIP central directories."""

import importlib
import os
import zipfile
from unittest.mock import Mock

import pandas as pd
import pytest

from ras_commander import RasExamples


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(RasExamples, "_user_data_dir", tmp_path)
    monkeypatch.setattr(RasExamples, "csv_file_path", tmp_path / "example_projects.csv")
    monkeypatch.setattr(RasExamples, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(RasExamples, "_zip_file_path", None)
    monkeypatch.setattr(RasExamples, "_folder_df", None)
    save = Mock(wraps=RasExamples._save_to_csv)
    monkeypatch.setattr(RasExamples, "_save_to_csv", save)

    def forbidden(*args, **kwargs):
        pytest.fail("Cache validation must not download or read ZIP payloads")

    module = importlib.import_module("ras_commander.RasExamples")
    monkeypatch.setattr(module.requests, "get", forbidden)
    return tmp_path, save, forbidden


def write_archive(root, version, records):
    archive = root / f"Example_Projects_{version.replace('.', '_')}.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for category, project in records:
            # Two members per project deliberately leave sparse DataFrame indices.
            for filename in ("model.prj", "model.g01"):
                zipped.writestr(f"{category}/{project}/{filename}", "unused payload")
    return archive


def cached_records():
    return pd.read_csv(
        RasExamples.csv_file_path, dtype=str, keep_default_na=False
    ).to_dict("records")


def test_newer_stale_cache_is_rebuilt_from_archive(catalog, monkeypatch):
    root, save, forbidden = catalog
    archive = write_archive(root, "6.6", [("Unsteady", "One"), ("Unsteady", "Two")])
    RasExamples.csv_file_path.write_text("Category,Project\nwrong,stale\n", encoding="utf-8")
    future = archive.stat().st_mtime_ns + 60_000_000_000
    os.utime(RasExamples.csv_file_path, ns=(future, future))
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)

    RasExamples.get_example_projects("6.6")

    expected = [dict(Category="Unsteady", Project=name) for name in ("One", "Two")]
    assert RasExamples._folder_df.to_dict("records") == expected
    assert cached_records() == expected
    assert save.call_count == 1


def test_switching_versions_replaces_shared_cache(catalog, monkeypatch):
    root, save, forbidden = catalog
    write_archive(root, "6.6", [("Unsteady", "Version66")])
    write_archive(root, "7.0", [("Unsteady", "Version70")])
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)

    for version, name in (("6.6", "Version66"), ("7.0", "Version70"), ("6.6", "Version66")):
        RasExamples.get_example_projects(version)
        expected = [dict(Category="Unsteady", Project=name)]
        assert RasExamples._folder_df.to_dict("records") == expected
        assert cached_records() == expected
    assert save.call_count == 3


@pytest.mark.parametrize("category,project", [
    ("Unsteady", "Normal"), ("Unsteady", "123"), ("Unsteady", "NA"),
    ("123", "Normal"), ("NA", "Normal"),
])
def test_matching_cache_preserves_literal_identifiers_without_writes(
    catalog, monkeypatch, category, project
):
    root, save, forbidden = catalog
    write_archive(root, "6.6", [(category, project), (category, "Other")])
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    RasExamples.get_example_projects("6.6")
    assert save.call_count == 1
    before = RasExamples.csv_file_path.read_bytes()
    stamp = RasExamples.csv_file_path.stat().st_mtime_ns
    save.reset_mock()

    for _ in range(2):
        RasExamples.get_example_projects("6.6")
        assert RasExamples._folder_df.to_dict("records") == [
            dict(Category=category, Project=project), dict(Category=category, Project="Other")
        ]
    save.assert_not_called()
    assert RasExamples.csv_file_path.read_bytes() == before
    assert RasExamples.csv_file_path.stat().st_mtime_ns == stamp
