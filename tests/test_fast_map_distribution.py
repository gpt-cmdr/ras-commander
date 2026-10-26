"""External-wheel discovery without requiring an activated shell environment."""
from importlib import metadata
import os
from types import SimpleNamespace

import pytest

from ras_commander.fim import _engine
from ras_commander.fim.errors import FimEngineNotFoundError


def test_installed_wheel_resolves_without_path(tmp_path, monkeypatch):
    name = _engine.ENGINE_NAME + (".exe" if os.name == "nt" else "")
    binary = tmp_path / "scripts" / name
    binary.parent.mkdir()
    binary.write_bytes(b"installed engine")
    binary.chmod(0o755)
    files = [metadata.PackagePath(f"../../../scripts/{name}")]
    distribution = SimpleNamespace(files=files, locate_file=lambda _: binary)
    monkeypatch.setattr(_engine.metadata, "distribution", lambda name: distribution if name == "ras-commander-fast-map" else None)
    monkeypatch.delenv(_engine.ENGINE_ENV_VAR, raising=False)
    monkeypatch.setattr(_engine.shutil, "which", lambda _: None)
    assert _engine.find_engine() == binary.resolve()


def test_explicit_missing_engine_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setattr(_engine, "_installed_engine", lambda: pytest.fail("explicit override must fail directly"))
    with pytest.raises(FimEngineNotFoundError, match="engine_path"):
        _engine.find_engine(tmp_path / "missing")


def test_path_precedes_installed_distribution(tmp_path, monkeypatch):
    binary = tmp_path / "custom-engine"
    binary.write_bytes(b"explicit PATH engine")
    monkeypatch.delenv(_engine.ENGINE_ENV_VAR, raising=False)
    monkeypatch.setattr(_engine.shutil, "which", lambda _: str(binary))
    monkeypatch.setattr(_engine, "_installed_engine", lambda: pytest.fail("PATH has precedence"))
    assert _engine.find_engine() == binary.resolve()


def test_missing_package_or_script_is_not_silently_accepted(tmp_path, monkeypatch):
    def absent(_):
        raise metadata.PackageNotFoundError
    monkeypatch.setattr(_engine.metadata, "distribution", absent)
    assert _engine._installed_engine() is None
    monkeypatch.setattr(_engine.metadata, "distribution", lambda _: SimpleNamespace(files=[metadata.PackagePath("ras2fim-batch")], locate_file=lambda _: tmp_path / "missing"))
    assert _engine._installed_engine() is None
