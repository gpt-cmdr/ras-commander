"""``RasDss`` must find an installed JVM on Linux and macOS, not only on Windows.

The bug, with its measurement (fleet survey, 2026-09-19). ``RasDss.get_catalog``
enters ``_configure_jvm``, which sets ``JAVA_HOME`` when the environment does not.
Its candidate list held Windows paths only -- ``C:/Program Files/Java``,
``C:/Program Files (x86)/Java``, ``C:/Program Files/HEC`` -- so on Linux the list
was empty and it raised ``RuntimeError: Java not found`` on hosts with a working
OpenJDK. On CLB04 the call reproduced that string byte-for-byte with ``JAVA_HOME``
unset, and with ``JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`` the same call read
a delivered DSS and returned 756 records.

The cost: the eBFE audit's DSS record check enters here, so 39 studies and 2,104
boundaries were recorded as unverified. All 42 failing audit records came from
five hosts that each had OpenJDK 17 installed and each read DSS catalogs
successfully at other times, in one sweep launched without ``JAVA_HOME``. The one
runner genuinely without Java produced none of them.

Why the fix is a resolution and not a longer list of names. A sibling
implementation (``hms_commander/dss/core.py``) does try Linux candidates, but
hardcodes ``/usr/lib/jvm/java-17-openjdk`` and ``/usr/lib/jvm/java-11-openjdk``.
Every container in this fleet has ``/usr/lib/jvm/java-17-openjdk-amd64``, so the
architecture suffix defeats it. ``test_a_name_list_implementation_would_miss_this``
pins that case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ras_commander.dss.RasDss import RasDss


def _make_jvm(root: Path, name: str, library: str = "libjvm.so") -> Path:
    """A directory shaped like a real JAVA_HOME: ``<home>/lib/server/<library>``."""
    home = root / name
    (home / "lib" / "server").mkdir(parents=True, exist_ok=True)
    (home / "lib" / "server" / library).write_bytes(b"")
    (home / "bin").mkdir(parents=True, exist_ok=True)
    (home / "bin" / "java").write_bytes(b"")
    return home


@pytest.fixture
def no_java_on_path(monkeypatch):
    """The ``java``-on-PATH branch is the other discovery route; silence it."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)


@pytest.fixture
def empty_roots(monkeypatch, tmp_path):
    """Point every platform's roots at empty directories."""
    missing = tmp_path / "nothing-here"
    monkeypatch.setattr(RasDss, "WINDOWS_JAVA_ROOTS", (missing,))
    monkeypatch.setattr(RasDss, "WINDOWS_HEC_ROOT", missing)
    monkeypatch.setattr(RasDss, "POSIX_JAVA_ROOTS", (missing,))
    monkeypatch.setattr(RasDss, "MACOS_JAVA_ROOTS", (missing,))


# -- Linux ------------------------------------------------------------------

def test_a_debian_openjdk_is_found_without_java_home(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """Today's silent failure: a JVM is installed and JAVA_HOME is unset."""
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    home = _make_jvm(jvm_root, "java-17-openjdk-amd64")
    monkeypatch.setattr(RasDss, "POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") == home


def test_a_name_list_implementation_would_miss_this(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """The exact layout every container in this fleet has.

    ``hms_commander`` looks for ``java-17-openjdk`` and ``java-11-openjdk``; the
    directory here is ``java-17-openjdk-amd64`` and neither name matches it. The
    glob-and-validate approach must find it anyway.
    """
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    home = _make_jvm(jvm_root, "java-17-openjdk-amd64")
    monkeypatch.setattr(RasDss, "POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") == home
    # Neither hardcoded name the sibling implementation looks for exists here.
    assert not (jvm_root / "java-17-openjdk").exists()
    assert not (jvm_root / "java-11-openjdk").exists()


def test_a_directory_without_a_jvm_library_is_not_a_java_home(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    """``/usr/lib/jvm`` collects stubs and headless packages; only a real JVM counts."""
    jvm_root = tmp_path / "usr" / "lib" / "jvm"
    (jvm_root / "java-17-openjdk-amd64-headless-docs").mkdir(parents=True)
    monkeypatch.setattr(RasDss, "POSIX_JAVA_ROOTS", (jvm_root,))
    assert RasDss._discover_java_home("linux") is None


def test_the_java_on_path_resolves_to_its_java_home(monkeypatch, tmp_path, empty_roots):
    """``readlink -f $(command -v java)`` up to the home, the branch a container needs."""
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
    monkeypatch.setattr(RasDss, "MACOS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("darwin") == home


# -- Windows keeps working --------------------------------------------------

def test_a_windows_jdk_is_still_found(monkeypatch, tmp_path, empty_roots, no_java_on_path):
    root = tmp_path / "Program Files" / "Java"
    home = _make_jvm(root, "jdk-21", library="jvm.dll")
    monkeypatch.setattr(RasDss, "WINDOWS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("win32") == home


def test_a_windows_search_does_not_accept_a_posix_library(
        monkeypatch, tmp_path, empty_roots, no_java_on_path):
    root = tmp_path / "Program Files" / "Java"
    _make_jvm(root, "jdk-21", library="libjvm.so")
    monkeypatch.setattr(RasDss, "WINDOWS_JAVA_ROOTS", (root,))
    assert RasDss._discover_java_home("win32") is None


# -- the error still names what was searched --------------------------------

def test_java_library_names_are_platform_specific():
    assert RasDss._jvm_library_names("win32") == ("jvm.dll",)
    assert RasDss._jvm_library_names("linux") == ("libjvm.so",)
    assert "libjvm.dylib" in RasDss._jvm_library_names("darwin")


# -- the two orderings, pinned together -------------------------------------

def test_path_wins_on_posix_and_loses_on_windows_from_one_fixture(
        monkeypatch, tmp_path):
    """The ordering intent, with both platforms' candidates present at once.

    The separate per-platform tests each fix one half, so neither would notice
    if the two halves drifted into agreement. Here a `java` on PATH and an
    installed-root JVM are both discoverable in the same fixture, and only the
    platform decides which is chosen:

    * POSIX takes PATH first -- the distribution's own answer, and the branch a
      container needs (the fleet's hosts all have `/usr/lib/jvm/...-amd64`);
    * Windows takes its installed roots first and PATH only as a fallback,
      because the historical order has been the selection for every existing
      install and a stray or 32-bit `java.exe` on PATH must not silently change
      which JVM HEC Monolith loads.
    """
    import shutil

    on_path = _make_jvm(tmp_path / "path", "jdk-on-path", library="libjvm.so")
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: str(on_path / "bin" / "java"))

    posix_root = tmp_path / "usr-lib-jvm"
    installed_posix = _make_jvm(posix_root, "java-17-openjdk-amd64")
    windows_root = tmp_path / "program-files-java"
    installed_windows = _make_jvm(windows_root, "jdk-21", library="jvm.dll")
    monkeypatch.setattr(RasDss, "POSIX_JAVA_ROOTS", (posix_root,))
    monkeypatch.setattr(RasDss, "WINDOWS_JAVA_ROOTS", (windows_root,))
    monkeypatch.setattr(RasDss, "WINDOWS_HEC_ROOT", tmp_path / "nothing-here")
    monkeypatch.setattr(RasDss, "MACOS_JAVA_ROOTS", (tmp_path / "nothing-here",))

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
