"""The FIM code composes transforms with ``Affine @ Affine`` (affine 3.0 and later)."""

from pathlib import Path
import runpy


REPO_ROOT = Path(__file__).resolve().parents[1]


def _setup_metadata(monkeypatch):
    captured = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr("setuptools.setup", fake_setup)
    runpy.run_path(str(REPO_ROOT / "setup.py"), run_name="__main__")
    return captured


def test_extras_with_the_fim_stack_require_affine_3(monkeypatch):
    extras = _setup_metadata(monkeypatch)["extras_require"]

    for extra in ("fim", "full", "all"):
        assert "affine>=3" in extras[extra], extra


def test_fim_code_still_needs_affine_matmul():
    # Keep the pin honest: drop it only once the FIM code no longer uses '@'.
    sources = [REPO_ROOT / "ras_commander" / "fim" / name for name in ("_aoi.py", "_prepare.py")]
    assert any("@ Affine." in path.read_text(encoding="utf-8") for path in sources)
