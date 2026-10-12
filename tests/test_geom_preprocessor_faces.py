"""Public completion regression for actual native polylines, in source units."""

import runpy
from pathlib import Path

import h5py
import numpy as np
import pytest


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("case", ["exterior_vertex", "exterior_chord", "bent_boundary"])
def test_public_native_face_containment(tmp_path, monkeypatch, strict, case):
    contract = runpy.run_path(
        str(Path(__file__).with_name("test_geom_preprocessor_contract.py"))
    )
    lifecycle = runpy.run_path(
        str(Path(__file__).with_name("test_geom_preprocessor_persistence.py"))
    )
    ring = np.array([(0, 0), (1, 0), (0.8, 0.5), (1, 1), (0, 1), (0, 0)], dtype=float)
    template = tmp_path / "template"
    template.mkdir()
    text, _, _ = contract["fixture"](template)
    original = text.read_text()
    start = original.index("Storage Area Surface Line=")
    end = original.index("Storage Area Is2D=")
    authored = (
        original[:start]
        + f"Storage Area Surface Line= {len(ring)}\n"
        + "\n".join(f"{x:16.6f}{y:16.6f}" for x, y in ring)
        + "\n"
        + original[end:]
    )
    folder = tmp_path / "model"
    folder.mkdir()

    def geometry(path):
        _, hdf_path, _ = contract["fixture"](path.parent)
        with h5py.File(hdf_path, "r+") as hdf:
            del hdf[contract["AREA"] + "/Polygon Points"]
            hdf.create_dataset(contract["AREA"] + "/Polygon Points", data=ring)
            hdf[contract["AREA"] + "/Polygon Info"][...] = [[0, len(ring), 0, 1]]
        return hdf_path

    monkeypatch.setitem(lifecycle["project_run"].__globals__, "geometry", geometry)
    original_setattr = monkeypatch.setattr

    def intercept(target, name, value):
        if name == "_resolve_geometry_number":
            value = lambda *a: "01"
        if name == "Popen":
            launch = value

            def regenerate(*args, **kwargs):
                result = launch(*args, **kwargs)
                path = folder / "Synthetic.g01.hdf"
                with h5py.File(path, "r+") as hdf:
                    del hdf[contract["AREA"] + "/Synthetic"]
                contract["products"](path)
                if case != "exterior_chord":
                    with h5py.File(path, "r+") as hdf:
                        area = hdf[contract["AREA"] + "/Synthetic"]
                        del area["Faces Perimeter Values"]
                        area.create_dataset(
                            "Faces Perimeter Values",
                            data=[[0.8, 0.5]]
                            if case == "bent_boundary"
                            else [[1_000_000.0, 1_000_000.0]],
                        )
                        area["Faces Perimeter Info"][...] = [[0, 0], [0, 1]]
                return result

            value = regenerate
        return original_setattr(target, name, value)

    monkeypatch.setattr = intercept
    result, killed = lifecycle["project_run"](
        folder,
        monkeypatch,
        geometry_text=authored,
        write_products=False,
        require_complete_products=strict,
    )
    assert not killed
    assert result.success is (case == "bent_boundary")
    assert result.completion_contract["inputs_preserved"] is True
    assert result.completion_contract["products_complete"] is (case == "bent_boundary")
    if not result.success:
        assert "GEOMETRY_PRODUCTS_INCOMPLETE" in result.error
