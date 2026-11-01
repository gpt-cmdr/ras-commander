"""Filesystem discovery tests; fixture libraries are never loaded or executed.

Cross-platform directory layouts exercise candidate selection without starting
Java, importing pyjnius, or downloading the monolith bridge.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ras_commander.dss.RasDss import RasDss


def _make_jvm(root: Path, name: str, library: str = "libjvm.so") -> Path:
    """Exercise discovery against isolated filesystem fixtures."""
    home = root / name
    (home / "lib" / "server").mkdir(parents=True, exist_ok=True)
    (home / "lib" / "server" / library).write_bytes(b"")
    (home / "bin").mkdir(parents=True, exist_ok=True)
    (home / "bin" / "java").write_bytes(b"")
    return home


@pytest.fixture
def no_java_on_path(monkeypatch):
    """Exercise discovery against isolated filesystem fixtures."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)


@pytest.fixture
def empty_roots(monkeypatch, tmp_path):
    """Exercise discovery against isolated filesystem fixtures."""
    missing = tmp_path / "nothing-here"
    monkeypatch.setattr(RasDss, "_WINDOWS_JAVA_ROOTS", (missing,))
    monkeypatch.setattr(RasDss, "_WINDOWS_HEC_ROOT", missing)
    monkeypatch.setattr(RasDss, "_POSIX_JAVA_ROOTS", (missing,))
    monkeypatch.setattr(RasDss, "_MACOS_JAVA_ROOTS", (missing,))


# -- Linux ------------------------------------------------------------------

def test_a_debian_openjdk_is_found_without_java_home(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """Exercise discovery against isolated filesystem fixtures."""
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    home = _make_jvm(jvm_root, "java-17-openjdk-amd64")
    monkeypatch.setattr(RasDss, "_POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") == home


def test_a_name_list_implementation_would_miss_this(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """Exercise discovery against isolated filesystem fixtures."""
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    home = _make_jvm(jvm_root, "java-17-openjdk-amd64")
    monkeypatch.setattr(RasDss, "_POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") == home
    # Neither hardcoded name the sibling implementation looks for exists here.
    assert not (jvm_root / "java-17-openjdk").exists()
    assert not (jvm_root / "java-11-openjdk").exists()


def test_a_directory_without_a_jvm_library_is_not_a_java_home(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """Exercise discovery against isolated filesystem fixtures."""
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    (jvm_root / "java-17-openjdk-amd64-headless-docs").mkdir(parents=True)
    monkeypatch.setattr(RasDss, "_POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") is None


def test_the_java_on_path_resolves_to_its_java_home(monkeypatch, tmp_path, empty_roots):
    """Exercise discovery against isolated filesystem fixtures."""
    import shutil

    home = _make_jvm(tmp_path / "opt", "jdk-21")
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: str(home / "bin" / "java"))
    assert RasDss._discover_java_home("linux") == home


def test_no_jvm_anywhere_still_yields_nothing(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    assert RasDss._discover_java_home("linux") is None
    assert RasDss._discover_java_home("darwin") is None
    assert RasDss._discover_java_home("win32") is None


# -- macOS ------------------------------------------------------------------

def test_a_macos_bundle_resolves_to_contents_home(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    root = tmp_path / "Library" / "Java" / "JavaVirtualMachines"
    home = root / "temurin-17.jdk" / "Contents" / "Home"
    (home / "lib" / "server").mkdir(parents=True)
    (home / "lib" / "server" / "libjvm.dylib").write_bytes(b"")
    monkeypatch.setattr(RasDss, "_MACOS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("darwin") == home


# -- Windows keeps working --------------------------------------------------

def test_a_windows_jdk_is_still_found(monkeypatch, tmp_path, empty_roots, no_java_on_path):
    root = tmp_path / "Program Files" / "Java"
    home = _make_jvm(root, "jdk-21", library="jvm.dll")
    monkeypatch.setattr(RasDss, "_WINDOWS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("win32") == home


def test_a_windows_search_does_not_accept_a_posix_library(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    root = tmp_path / "Program Files" / "Java"
    _make_jvm(root, "jdk-21", library="libjvm.so")
    monkeypatch.setattr(RasDss, "_WINDOWS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("win32") is None


# -- the error still names what was searched --------------------------------

def test_java_library_names_are_platform_specific():
    assert RasDss._jvm_library_names("win32") == ("jvm.dll",)
    assert RasDss._jvm_library_names("linux") == ("libjvm.so",)
    assert "libjvm.dylib" in RasDss._jvm_library_names("darwin")


# -- the two orderings, pinned together -------------------------------------

def test_path_wins_on_posix_and_loses_on_windows_from_one_fixture(
        monkeypatch, tmp_path):
    """Exercise discovery against isolated filesystem fixtures."""
    import shutil

    on_path = _make_jvm(tmp_path / "path", "jdk-on-path", library="libjvm.so")
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: str(on_path / "bin" / "java"))

    posix_root = tmp_path / "usr-lib-jvm"
    installed_posix = _make_jvm(posix_root, "java-17-openjdk-amd64")
    windows_root = tmp_path / "program-files-java"
    installed_windows = _make_jvm(windows_root, "jdk-21", library="jvm.dll")
    monkeypatch.setattr(RasDss, "_POSIX_JAVA_ROOTS", (posix_root,))
    monkeypatch.setattr(RasDss, "_WINDOWS_JAVA_ROOTS", (windows_root,))
    monkeypatch.setattr(RasDss, "_WINDOWS_HEC_ROOT", tmp_path / "nothing-here")
    monkeypatch.setattr(RasDss, "_MACOS_JAVA_ROOTS", (tmp_path / "nothing-here",))

    # Same fixture, opposite answers -- the platform is the only difference.
    assert RasDss._discover_java_home("linux") == on_path
    assert RasDss._discover_java_home("win32") == installed_windows

    # And the orderings themselves, so a reordering is caught even if both
    # candidates happen to resolve.
    posix_order = RasDss._java_home_candidates("linux")
    assert posix_order[0] == on_path
    assert installed_posix in posix_order

    windows_order = RasDss._java_home_candidates("win32")
    assert windows_order[0] == installed_windows
    assert windows_order[-1] == on_path, "PATH is the Windows fallback, never first"


@pytest.fixture
def configuration_without_java(monkeypatch):
    import sys
    import types
    monolith = types.SimpleNamespace(get_classpath=lambda: ["bridge.jar"], get_library_path=lambda: "native")
    config = types.SimpleNamespace(vm_running=False, add_classpath=lambda *args: None)
    monkeypatch.setattr(RasDss, "_ensure_monolith", lambda: monolith)
    monkeypatch.setattr(RasDss, "_jvm_configured", False)
    monkeypatch.setitem(sys.modules, "jnius_config", config)
    monkeypatch.setattr(RasDss, "_silence_hec_messages", staticmethod(lambda: None))
    monkeypatch.delenv("JAVA_HOME", raising=False)
    # Ensure configuration changes remain local to this test.
    monkeypatch.setenv("LD_LIBRARY_PATH", "original-native-path")
    monkeypatch.setenv("PATH", "original-path")
    return config


def test_configure_finds_linux_java_on_path_without_starting_a_jvm(monkeypatch, tmp_path, configuration_without_java):
    import os
    import shutil
    import sys
    home = _make_jvm(tmp_path, "jdk-on-path")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda *args: str(home / "bin" / "java"))
    original_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: False if p.as_posix().lower().startswith("c:/program files") else original_exists(p))
    RasDss._configure_jvm()
    assert os.environ["JAVA_HOME"] == str(home)
    assert RasDss._jvm_configured is True


@pytest.mark.parametrize("explicit", ["", "caller-selected-runtime"])
def test_explicit_java_home_is_preserved(monkeypatch, configuration_without_java, explicit):
    import os
    monkeypatch.setenv("JAVA_HOME", explicit)
    monkeypatch.setattr(RasDss, "_discover_java_home", lambda *args: pytest.fail("explicit JAVA_HOME must win"))
    RasDss._configure_jvm()
    assert os.environ["JAVA_HOME"] == explicit


def test_no_runtime_error_names_search_sources(monkeypatch, configuration_without_java):
    monkeypatch.setattr(RasDss, "_discover_java_home", lambda *args: None)
    with pytest.raises(RuntimeError, match="Searched: java on PATH"):
        RasDss._configure_jvm()
    assert RasDss._jvm_configured is False


def test_directory_named_like_a_library_is_not_accepted(tmp_path):
    home = tmp_path / "jdk"
    (home / "lib/server/libjvm.so").mkdir(parents=True)
    assert not RasDss._has_jvm_lib(home, "linux")
