"""Contract tests for the standalone proposal, before native binding integration.

The standalone graph kernel is ``tests/fluvial_graph.rs`` of
https://github.com/gpt-cmdr/ras-commander-fast-hdf: set RAS_FAST_HDF_SOURCE to
a checkout of it. Set FLUVIAL_RUSTC when rustc is outside PATH. RAS_FLUVIAL_HDF
accepts a local computed BaldEagle plan HDF; unset fixtures skip explicitly.
Never runs HEC-RAS.
"""
from pathlib import Path
import itertools
import os
import random
import shutil
import subprocess

import pytest


@pytest.fixture(scope="module")
def kernel(tmp_path_factory):
    rustc = os.environ.get("FLUVIAL_RUSTC") or shutil.which("rustc")
    if not rustc:
        pytest.skip("Rust toolchain unavailable; standalone kernel not tested")
    source = os.environ.get("RAS_FAST_HDF_SOURCE")
    if not source:
        pytest.skip("set RAS_FAST_HDF_SOURCE to a ras-commander-fast-hdf checkout to test the kernel")
    kernel_rs = Path(source) / "tests/fluvial_graph.rs"
    assert kernel_rs.is_file(), f"{kernel_rs} not found"
    binary = tmp_path_factory.mktemp("fluvial") / "graph.exe"
    subprocess.run([rustc, "--edition", "2021", "-O", "-A", "dead_code",
                    str(kernel_rs), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    return binary


def invoke(kernel, rows, times, delta, tolerance, keys=None, masks=None):
    n = len(rows)
    keys = keys if keys is not None else [(0, i) for i in range(n)]
    masks = masks if masks is not None else [(1, 1, 1)] * n
    offsets = [0]
    neighbors = []
    for row in rows:
        neighbors.extend(row)
        offsets.append(len(neighbors))
    fields = [n, len(neighbors), delta, tolerance]
    for key, time, mask in zip(keys, times, masks):
        fields.extend([*key, time, *mask])
    fields.extend(offsets)
    fields.extend(neighbors)
    result = subprocess.run([str(kernel)], input=" ".join(map(str, fields)),
                            text=True, capture_output=True, check=True)
    return list(map(int, result.stdout.split()))


def oracle(rows, times, delta, tolerance, masks=None):
    """Independent set-based, synchronous reference with exact integer times."""
    masks = masks if masks is not None else [(1, 1, 1)] * len(rows)
    labels = [4 if not valid else 5 if not wet else 6 if not present else 0
              for valid, wet, present in masks]
    votes = [set() for _ in rows]
    for a, neighbors in enumerate(rows):
        for b in neighbors:
            if b <= a or labels[a] or labels[b] or abs(times[a] - times[b]) < delta:
                continue
            if times[a] == times[b]:
                votes[a].update((1, 2)); votes[b].update((1, 2))
            else:
                late, early = (a, b) if times[a] > times[b] else (b, a)
                votes[late].add(1); votes[early].add(2)
    for i, vote in enumerate(votes):
        if vote:
            labels[i] = next(iter(vote)) if len(vote) == 1 else 3
    fronts = {label: {i for i, value in enumerate(labels) if value == label} for label in (1, 2)}
    while any(fronts.values()):
        arrivals = {label: {b for a in fronts[label] for b in rows[a]
                            if labels[b] == 0 and abs(times[a] - times[b]) <= tolerance}
                    for label in (1, 2)}
        conflicts = arrivals[1] & arrivals[2]
        for i in conflicts:
            labels[i] = 3
        fronts = {label: arrivals[label] - conflicts for label in (1, 2)}
        for label, cells in fronts.items():
            for i in cells:
                labels[i] = label
    return labels


@pytest.mark.parametrize("delta,tolerance", [(0, 0), (1, 1), (10, 5), (2**64 - 1, 2**64 - 1)])
def test_seeded_random_graphs_match_independent_oracle(kernel, delta, tolerance):
    rng = random.Random(81437)
    for _ in range(32):
        n = rng.randrange(0, 25)
        rows = [[] for _ in range(n)]
        for a, b in itertools.combinations(range(n), 2):
            if rng.random() < .13:
                rows[a].append(b); rows[b].append(a)
        times = [rng.choice([-(2**63), -10, 0, 5, 10, 32503680000000, 2**63 - 1]) for _ in rows]
        masks = [rng.choice([(1, 1, 1)] * 8 + [(0, 1, 1), (1, 0, 1), (1, 1, 0)]) for _ in rows]
        expected = oracle(rows, times, delta, tolerance, masks)
        assert invoke(kernel, rows, times, delta, tolerance, masks=masks) == expected
        for row in rows:
            rng.shuffle(row)
        assert invoke(kernel, rows, times, delta, tolerance, masks=masks) == expected


def test_multi_mesh_colliding_cell_ids_are_not_collapsed(kernel):
    rows = [[1], [0], [3], [2]]
    assert invoke(kernel, rows, [10, 0, 0, 10], 10, 0,
                  keys=[(0, 0), (0, 1), (1, 0), (1, 1)]) == [1, 2, 2, 1]


def test_vertex_permutations_preserve_identity_labels(kernel):
    rows = [[1, 4], [0, 2], [1, 3], [2, 5], [0, 5], [4, 3]]
    times = [0, 100, 60, 50, 40, 50]
    expected = invoke(kernel, rows, times, 100, 50)
    for order in [(5, 4, 3, 2, 1, 0), (2, 0, 5, 1, 4, 3)]:
        inverse = {old: new for new, old in enumerate(order)}
        result = invoke(kernel, [[inverse[b] for b in rows[a]] for a in order],
                        [times[a] for a in order], 100, 50,
                        keys=[(0, a) for a in order])
        assert {a: result[i] for i, a in enumerate(order)} == dict(enumerate(expected))


@pytest.fixture(scope="module")
def real_selection():
    path = os.environ.get("RAS_FLUVIAL_HDF")
    if not path:
        pytest.skip("set RAS_FLUVIAL_HDF to a computed BaldEagle plan HDF")
    from ras_commander import HdfMesh, HdfResultsMesh, HdfBase, HdfFluvialPluvial
    cells = HdfMesh.get_mesh_cell_polygons(Path(path))
    peaks = HdfResultsMesh.get_mesh_max_ws(Path(path), round_to="1ms")
    assert not cells.empty and not peaks.empty, "empty API output is a fixture failure"
    assert not cells.duplicated(["mesh_name", "cell_id"]).any()
    assert not peaks.duplicated(["mesh_name", "cell_id"]).any()
    mesh = cells.mesh_name.iloc[0]
    cells = cells[cells.mesh_name == mesh].sort_values("cell_id").iloc[:256].copy()
    cells = cells.merge(peaks[["mesh_name", "cell_id", "maximum_water_surface_time"]],
                        on=["mesh_name", "cell_id"], validate="one_to_one", how="left")
    adjacency, _ = HdfFluvialPluvial._process_cell_adjacencies(cells)
    index = {int(cell): i for i, cell in enumerate(cells.cell_id)}
    # Adjacency keys are (mesh_name, cell_id) identities (#564/#572).
    rows = [[index[int(other[1])] for other in adjacency.get((mesh, int(cell)), [])] for cell in cells.cell_id]
    # Masks here qualify peak-valid cells only: wetness is an explicit all-true
    # input, not an inference that peak-time presence establishes inundation.
    masks = [(int(g.is_valid and not g.is_empty), 1, int(t == t))
             for g, t in zip(cells.geometry, cells.maximum_water_surface_time)]
    times = [int(t.value // 1_000_000) if present else 0
             for t, (_, _, present) in zip(cells.maximum_water_surface_time, masks)]
    version = HdfBase.get_attrs(Path(path), "/")["File Version"]
    assert "HEC-RAS" in version
    assert any(rows), "selected fixture has no adjacency"
    assert any(mask[2] for mask in masks), "selected fixture has no valid peak times"
    return cells, rows, times, masks, version


def test_real_adjacency_against_independent_geometry(real_selection):
    cells, rows, _, _, _ = real_selection
    expected = set()
    for a, b in itertools.combinations(range(len(cells)), 2):
        # Independent geometric intersection, rather than the Python edge hash.
        if cells.geometry.iloc[a].boundary.intersection(cells.geometry.iloc[b].boundary).length > 1e-7:
            expected.add((a, b))
    actual = {(a, b) for a, row in enumerate(rows) for b in row if a < b}
    assert actual == expected


@pytest.mark.parametrize("delta,tolerance", [(0, 0), (3_600_000, 600_000), (43_200_000, 3_600_000)])
def test_real_labels_and_python_seed_pairs(kernel, real_selection, delta, tolerance):
    from ras_commander import HdfFluvialPluvial
    cells, rows, times, masks, _ = real_selection
    assert invoke(kernel, rows, times, delta, tolerance, masks=masks) == oracle(rows, times, delta, tolerance, masks)
    adjacency = {int(cells.cell_id.iloc[a]): [int(cells.cell_id.iloc[b]) for b in row]
                 for a, row in enumerate(rows)}
    cell_times = dict(zip(map(int, cells.cell_id), cells.maximum_water_surface_time))
    pairs = HdfFluvialPluvial._get_boundary_cell_pairs(adjacency, cell_times, delta / 3_600_000)
    expected = {tuple(sorted((int(cells.cell_id.iloc[a]), int(cells.cell_id.iloc[b]))))
                for a, row in enumerate(rows) for b in row if a < b
                and masks[a][2] and masks[b][2] and abs(times[a] - times[b]) >= delta}
    assert set(pairs) == expected


def test_foot_based_area_conversion_has_independent_expected_value(real_selection):
    # Correctness expectation for a future polygon/filter adapter. The existing
    # Python area/4046.8564224 assumption must never be a compatibility oracle.
    cells, _, _, _, _ = real_selection
    assert cells.crs.is_projected
    factor = cells.crs.axis_info[0].unit_conversion_factor
    assert factor == pytest.approx(1200 / 3937)
    correct_acres = 43560 * factor**2 / 4046.8564224
    assert correct_acres == pytest.approx(1.000004000012)
    assert 43560 / 4046.8564224 > 10
