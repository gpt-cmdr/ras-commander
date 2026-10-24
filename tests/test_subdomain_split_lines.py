"""Unit tests of the split-line and footprint algorithm on synthetic grid meshes."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("shapely")

from ras_commander.subdomain import _split_lines as sl  # noqa: E402
from ras_commander.subdomain.RasSubdomain import SplitLineCriteria  # noqa: E402

GROW = dict(max_angle_deg=60.0, wet_depth=0.1, edge_fraction=0.01, max_half_length=1e9)


def grid_mesh(nx: int, ny: int, cell: float = 100.0) -> sl.Mesh:
    """Regular grid; flow positive along each stored normal from cell_0 to cell_1.

    Cells are numbered row-major from the bottom-left; ghost cells (ids >= nx*ny)
    sit on the perimeter faces.
    """
    def pid(i, j):
        return j * (nx + 1) + i

    points = np.array([(i * cell, j * cell) for j in range(ny + 1) for i in range(nx + 1)], float)
    cells, normals, fpts = [], [], []
    ghost = nx * ny

    def cid(i, j):
        return j * nx + i if 0 <= i < nx and 0 <= j < ny else None

    # vertical faces (normal +x), between (i-1, j) and (i, j)
    for j in range(ny):
        for i in range(nx + 1):
            a, b = cid(i - 1, j), cid(i, j)
            cells.append([a if a is not None else ghost, b if b is not None else ghost])
            normals.append([1.0, 0.0])
            fpts.append([pid(i, j), pid(i, j + 1)])
            if a is None or b is None:
                ghost += 1
    # horizontal faces (normal +y), between (i, j-1) and (i, j)
    for j in range(ny + 1):
        for i in range(nx):
            a, b = cid(i, j - 1), cid(i, j)
            cells.append([a if a is not None else ghost, b if b is not None else ghost])
            normals.append([0.0, 1.0])
            fpts.append([pid(i, j), pid(i + 1, j)])
            if a is None or b is None:
                ghost += 1
    cells = np.array(cells)
    # Perimeter faces: put the ghost on cell_1 so cell_0 is always the real cell.
    swap = cells[:, 0] >= nx * ny
    cells[swap] = cells[swap][:, ::-1]
    normals = np.array(normals)
    normals[swap] *= -1
    return sl.mesh_from_topology(nx * ny, cells, normals, np.full(len(cells), cell), np.array(fpts), points)


def south_flowing_volume(mesh: sl.Mesh, nx: int, channel: int, width: int) -> np.ndarray:
    """Event volume: flow south (-y) in a channel band of ``width`` columns, lateral inflow toward it."""
    vol = np.zeros(len(mesh.cell_0))
    for f in range(len(vol)):
        n = mesh.normal[f]
        x, _ = mesh.midpoint[f] / 100.0
        if n[1] != 0:  # horizontal face: south flow inside the band
            if abs(x - (channel + 0.5)) <= width / 2:
                vol[f] = -1000.0 * n[1]
        else:  # vertical face: lateral flow toward the channel
            vol[f] = (50.0 if x < channel + 0.5 - width / 2 else -50.0 if x > channel + 0.5 + width / 2 else 0.0) * n[0]
    return vol


def test_trapezoid_weights_integrate_exactly():
    w = sl.trapezoid_weights([0, 10, 30])
    assert np.allclose(w, [5, 15, 10])
    assert w @ np.array([2.0, 2.0, 2.0]) == pytest.approx(60.0)
    with pytest.raises(ValueError):
        sl.trapezoid_weights([0, 0, 1])


def test_grow_line_spans_wet_band_and_closes():
    nx, ny = 11, 6
    mesh = grid_mesh(nx, ny)
    vol = south_flowing_volume(mesh, nx, channel=5, width=5)
    depth = np.zeros(nx * ny)
    for j in range(ny):
        for i in range(3, 8):  # wet columns 3..7
            depth[j * nx + i] = 1.0
    down = np.array([0.0, -1.0])
    # seed: horizontal face below cell (5, 3)
    seed = next(f for f in range(len(vol)) if mesh.normal[f][1] != 0
                and np.allclose(mesh.midpoint[f], [550.0, 300.0]))
    faces, signs, closed = sl.grow_line(mesh, seed, down, depth, vol, **GROW)
    xs = sorted(mesh.midpoint[faces][:, 0] / 100.0)
    assert closed
    assert xs == [3.5, 4.5, 5.5, 6.5, 7.5]  # exactly the wet band
    assert np.all(signs == -1.0)  # stored normals point north; downstream is south


def test_conveyance_and_normal_depth_recover_slope():
    table = np.array([[0.0, 0.0, 0.0, 0.04], [1.0, 10.0, 12.0, 0.04], [5.0, 60.0, 20.0, 0.04]])
    tables = {0: table}
    lengths = np.array([10.0])
    k_fn = lambda z: sl.conveyance(tables, [0], z, lengths)  # noqa: E731
    slope = 0.002
    grid = np.arange(0.0, 40.0, 0.02)
    k = k_fn(grid)
    stage_true = np.linspace(0.5, 4.0, 40)
    q = np.interp(stage_true, grid, k) * math.sqrt(slope)
    q = np.r_[q, q[::-1]]
    stage = np.r_[stage_true, stage_true[::-1]]
    score = sl.score_line(q[:, None], np.array([1.0]), np.ones(len(q)), stage, 0.0, k_fn, slope,
                          fit_fraction=0.1, stage_step=0.02, stage_span=40.0)
    assert score["best_slope"] == pytest.approx(slope, rel=0.13)  # 81-point log grid
    assert score["rmse_ft"] < 0.1
    assert score["reverse_fraction"] == 0.0
    assert score["loop_ft"] < 1e-6  # no hysteresis in a single-valued rating
    gates = sl.failed_gates(score, True, 1.0, slope, max_reverse_fraction=0.05, max_fit_error_ft=0.5,
                            slope_ratio_bounds=(1 / 3, 3), share_bounds=(0.8, 1.2))
    assert gates == []
    bad = sl.failed_gates(score, False, 0.5, slope * 10, max_reverse_fraction=0.05, max_fit_error_ft=0.5,
                          slope_ratio_bounds=(1 / 3, 3), share_bounds=(0.8, 1.2))
    assert set(bad) == {"LINE_OPEN", "SLOPE_RATIO", "OUTFLOW_SHARE"}


def test_no_flow_is_reported_not_scored():
    score = sl.score_line(np.zeros((5, 1)), np.array([1.0]), np.ones(5), np.zeros(5), 0.0,
                          lambda z: np.ones_like(z), 0.01, fit_fraction=0.1, stage_step=0.02, stage_span=40.0)
    assert score["best_slope"] is None
    assert sl.failed_gates(score, True, None, 0.01, max_reverse_fraction=0.05, max_fit_error_ft=0.5,
                           slope_ratio_bounds=(1 / 3, 3), share_bounds=(0.8, 1.2)) == ["NO_FLOW"]


def test_stable_step_needs_a_passing_neighbour():
    assert sl.stable_step({0: True, 1: False, 2: True, 3: True}, {0: 0.01, 2: 0.3, 3: 0.2}) == 3
    assert sl.stable_step({0: True, 2: True}, {0: 0.1, 2: 0.1}) is None


def test_footprints_nest_and_drain_upstream():
    nx, ny = 11, 12
    mesh = grid_mesh(nx, ny)
    vol = south_flowing_volume(mesh, nx, channel=5, width=1)
    receiver = sl.receivers(mesh, vol)
    down = np.array([0.0, -1.0])

    def line_at(row):
        return [f for f in range(len(vol)) if mesh.normal[f][1] != 0 and mesh.midpoint[f][1] == row * 100.0
                and mesh.cell_0[f] < nx * ny and mesh.cell_1[f] < nx * ny]

    low = sl.drained_cells(mesh, receiver, line_at(3), down)
    high = sl.drained_cells(mesh, receiver, line_at(8), down)
    assert high < low  # nested: the upstream footprint is inside the downstream one
    assert all(c // nx >= 8 for c in high) and all(c // nx >= 3 for c in low)
    nested = sl.nest({"up": high, "down": low}, nested_fraction=0.95)
    assert nested["up"]["tier"] == 1 and nested["down"]["tier"] == 2
    assert nested["down"]["upstream"] == ["up"]
    assert nested["up"]["cells"] | nested["down"]["cells"] == low
    assert not nested["up"]["cells"] & nested["down"]["cells"]
    ex = sl.edge_exchange(mesh, nested["down"]["cells"], vol, line_at(3), line_at(8))
    assert ex["outlet_out"] > 0 and ex["inlet_in"] > 0


def test_domain_outflow_counts_only_outward_edges():
    nx, ny = 5, 5
    mesh = grid_mesh(nx, ny)
    vol = south_flowing_volume(mesh, nx, channel=2, width=1)
    member = np.zeros(nx * ny, bool)
    member[nx * 2:] = True  # rows 2..4
    out = sl.domain_outflow(mesh, member, vol)
    assert out == pytest.approx(1000.0)  # one channel face leaves southward


def test_criteria_validate():
    SplitLineCriteria()
    with pytest.raises(ValueError):
        SplitLineCriteria(step_spacing_ft=-1)
    with pytest.raises(ValueError):
        SplitLineCriteria(outflow_share_bounds=(1.2, 0.8))


def test_subdomain_import_is_lazy():
    import subprocess
    import sys

    script = "\n".join([
        "import sys",
        "import ras_commander.subdomain as s",
        "assert 'geopandas' not in sys.modules",
        "assert 'ras_commander.subdomain.RasSubdomain' not in sys.modules",
        "assert s.RasSubdomain.__name__ == 'RasSubdomain'",
    ])
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
