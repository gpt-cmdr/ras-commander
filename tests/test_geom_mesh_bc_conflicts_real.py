"""``GeomMesh.detect_bc_conflicts`` on real HEC-RAS HDFs.

HEC-RAS keeps 2D boundary condition lines in ``Geometry/Boundary Condition
Lines`` and marks a perimeter face by its ghost cell (``Faces Cell Indexes`` at
or above the area's ``Cell Count``). Every expectation here is computed
independently from plain h5py and Shapely; the method must agree in h5py and
native mode.

The committed excerpt (``tests/fixtures/bc_conflicts``) always runs. More
files come from ``RAS_ROUTE2_FIXTURES`` (``{"fixtures": [{"name", "path"}]}``)
when it is set: every listed HDF with ``Geometry/Boundary Condition Lines`` and
2D face tables is checked; the parametrisation is empty otherwise.
"""
import json
import os
from dataclasses import asdict
from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString

from ras_commander import fast_hdf
from ras_commander.geom.GeomMesh import GeomMesh

FIXTURE = Path(__file__).parent / "fixtures" / "bc_conflicts" / "BaldEagleDamBrk.p18.bclines.hdf"
BC = "Geometry/Boundary Condition Lines"
ND = "Event Conditions/Unsteady/Boundary Conditions/Normal Depths"
MAX_MB = 400


def _text(value):
    return bytes(value).decode("utf-8").rstrip("\x00").strip()


def _has_layout(path):
    with h5py.File(path, "r") as hdf:
        if BC not in hdf or "Geometry/2D Flow Areas/Attributes" not in hdf:
            return False
        attrs = hdf["Geometry/2D Flow Areas/Attributes"]
        if "Cell Count" not in (attrs.dtype.names or ()):
            return False
        return any(
            f"Geometry/2D Flow Areas/{_text(n)}/Faces Cell Indexes" in hdf
            for n in attrs["Name"]
        )


def _manifest_files():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    files = []
    for entry in json.loads(Path(manifest).read_text()).get("fixtures", []):
        path = Path(entry["path"])
        if path.suffix.lower() != ".hdf" or not path.exists():
            continue
        if path.stat().st_size > MAX_MB * 1024 * 1024:
            continue
        try:
            if _has_layout(path):
                files.append(path)
        except OSError:
            continue
    return files


FILES = [FIXTURE] + _manifest_files()


def _independent(path, cell_size):
    """Expected conflicts from the stored tables, read with plain h5py."""
    buf = 0.01 * cell_size
    with h5py.File(path, "r") as hdf:
        group = hdf[BC]
        attrs = group["Attributes"][()]
        info = group["Polyline Info"][()]
        points = group["Polyline Points"][()]
        lines = []
        for row, (start, count, _part_start, part_count) in zip(attrs, info):
            if part_count != 1:
                pytest.skip("multipart BC line: not covered by the independent reader")
            if count < 2:
                continue
            lines.append((_text(row["Name"]), _text(row["SA-2D"]), _text(row["Type"]),
                          LineString(points[start:start + count])))
        normal_depth = set()
        if ND in hdf:
            for key in hdf[ND]:
                entry = hdf[ND][key]
                normal_depth.add((_text(entry.attrs["2D Flow Area"]), _text(entry.attrs["BC Line"])))

        expected = []
        for row in hdf["Geometry/2D Flow Areas/Attributes"][()]:
            area = _text(row["Name"])
            area_lines = [line for line in lines if line[1] == area]
            base = f"Geometry/2D Flow Areas/{area}"
            if len(area_lines) < 2 or f"{base}/Faces Cell Indexes" not in hdf:
                continue
            cells = hdf[f"{base}/Faces Cell Indexes"][()]
            face_points = hdf[f"{base}/Faces FacePoint Indexes"][()]
            coords = hdf[f"{base}/FacePoints Coordinate"][()]
            pinfo = hdf[f"{base}/Faces Perimeter Info"][()]
            pvalues = hdf[f"{base}/Faces Perimeter Values"][()]
            for face in range(len(cells)):
                if not (cells[face] >= int(row["Cell Count"])).any():
                    continue
                start, count = pinfo[face]
                vertices = [coords[face_points[face][0]]]
                vertices += list(pvalues[start:start + count]) if count > 0 else []
                vertices.append(coords[face_points[face][1]])
                face_line = LineString(vertices)
                hit = [line for line in area_lines if face_line.distance(line[3]) < buf]
                if len(hit) >= 2:
                    expected.append({
                        "face_id": face,
                        "bc_names": [line[0] for line in hit],
                        "flow_area_name": area,
                        "bc_types": [line[2] for line in hit],
                        "normal_depth_bc": next(
                            (line[0] for line in hit if (area, line[0]) in normal_depth), None),
                    })
    return expected


def _detect(backend, path, cell_size):
    with fast_hdf.backend_scope(backend):
        return [asdict(c) for c in GeomMesh.detect_bc_conflicts(str(path), cell_size)]


def _backends():
    try:
        import ras_commander_fast_hdf  # noqa: F401
    except ImportError:
        return ["h5py"]
    return ["h5py", "native"]


def test_excerpt_perimeter_faces_are_hec_ras_external_faces():
    """The ghost-cell rule covers every face HEC-RAS assigned to a BC line."""
    with h5py.File(FIXTURE, "r") as hdf:
        attrs = hdf[BC]["Attributes"][()]
        external = hdf[BC]["External Faces"][()]
        for i, row in enumerate(hdf["Geometry/2D Flow Areas/Attributes"][()]):
            area = _text(row["Name"])
            cells = hdf[f"Geometry/2D Flow Areas/{area}/Faces Cell Indexes"][()]
            ghost = (cells >= int(row["Cell Count"])).any(axis=1)
            assert int(ghost.sum()) == int((cells >= int(row["Cell Count"])).sum())
            assigned = [int(r["Face Index"]) for r in external
                        if _text(attrs["SA-2D"][r["BC Line ID"]]) == area]
            assert assigned and ghost[np.array(assigned)].all()


def test_excerpt_known_conflicts():
    """BaldEagleCr's two Normal Depth lines meet three perimeter faces within 1,000 ft."""
    for backend in _backends():
        conflicts = _detect(backend, FIXTURE, 100000.0)
        assert [c["face_id"] for c in conflicts] == [61, 670, 745]
        for conflict in conflicts:
            assert conflict["flow_area_name"] == "BaldEagleCr"
            assert conflict["bc_names"] == ["DSNormalDepth", "DS2NormalD"]
            assert conflict["bc_types"] == ["External", "External"]
            assert conflict["normal_depth_bc"] == "DSNormalDepth"
        assert _detect(backend, FIXTURE, 500.0) == []


@pytest.mark.parametrize("cell_size", [10.0, 500.0, 2000.0, 100000.0])
@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_matches_independent_read(path, cell_size):
    expected = _independent(path, cell_size)
    for backend in _backends():
        assert _detect(backend, path, cell_size) == expected, backend


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_native_reads_are_made(path):
    pytest.importorskip("ras_commander_fast_hdf")
    with fast_hdf.trace_reads() as records:
        _detect("native", path, 10.0)
    assert any(r["backend"].startswith("native") for r in records)
