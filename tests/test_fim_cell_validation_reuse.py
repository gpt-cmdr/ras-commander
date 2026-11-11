"""Cell-polygon validation: unchanged accept/refuse results and content-keyed reuse."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
import shapely
import shapely.affinity
from affine import Affine
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from ras_commander.fim import FimUnsupportedError, _cell_validation, _horizontal

CRS = "EPSG:2278"


@pytest.fixture
def terrain(tmp_path):
    path = tmp_path / "terrain.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=64, width=64, count=1, dtype="float32",
        crs=CRS, transform=from_origin(0, 64, 1, 1), nodata=-9999,
    ) as dst:
        dst.write(np.full((64, 64), 100, dtype="float32"), 1)
    return path


@pytest.fixture
def store(tmp_path, monkeypatch):
    folder = tmp_path / "validation-store"
    monkeypatch.setenv(_cell_validation.ENVIRONMENT, str(folder))
    monkeypatch.setattr(_cell_validation, "_passed", type(_cell_validation._passed)())
    return folder


@pytest.fixture
def counted(monkeypatch):
    calls = []
    original = _horizontal.prepare_grid

    def prepare(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(_horizontal, "prepare_grid", prepare)
    return calls


def frame(geometries):
    return gpd.GeoDataFrame(geometry=list(geometries), crs=CRS)


def grid(size=8, step=8.0):
    return [
        box(i * step, j * step, (i + 1) * step, (j + 1) * step)
        for j in range(size) for i in range(size)
    ]


def plan_for(cells, terrain):
    return _horizontal.plan_grid(cells, terrain, None, 1024, native=True)


def all_cells_plan(cells, transform=Affine(1, 0, 0, 0, -1, 64), shape=(64, 64)):
    """A non-empty plan over every cell, for scenes plan_grid itself would not admit."""
    return SimpleNamespace(shape=shape, transform=transform, cell_positions=np.arange(len(cells)))


def reference_outcome(geometries, plan):
    """Upstream PR 803's validation: one index query per cell, then its tolerance.

    Returns the refusal message (or ``None``) and the residues it accepted.
    """
    tolerated = 0
    if (
        not np.isin(shapely.get_type_id(geometries), [3]).all()
        or shapely.is_empty(geometries).any()
        or not shapely.is_valid(geometries).all()
    ):
        return "horizontal mapping requires valid, non-empty cell Polygons", 0
    index = shapely.STRtree(geometries)
    for i, geometry in enumerate(geometries):
        others = index.query(geometry)
        others = others[others > i]
        if not len(others):
            continue
        first, second = geometries[np.full(len(others), i)], geometries[others]
        interiors = shapely.relate_pattern(first, second, "T********")
        if interiors.any():
            intersections = shapely.intersection(first[interiors], second[interiors])
            for intersection in intersections[shapely.area(intersections) > 0]:
                if not _horizontal._numerical_overlap_without_sample(intersection, plan):
                    return "horizontal cells have overlapping interiors", tolerated
                tolerated += 1
    return None, tolerated


def outcome(cells, terrain, threads, plan):
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            grid = _horizontal.prepare_grid(cells, terrain, plan, False, threads=threads)
        except FimUnsupportedError as exc:
            return str(exc), None
    residues = [w for w in caught if "Numerical cell-overlap residue" in str(w.message)]
    assert all(w.category is RuntimeWarning for w in residues)
    assert len(residues) == grid.tolerated_overlaps
    return None, grid.tolerated_overlaps


# Upstream PR 803's own scene: 6-unit pixels at 1e7, cells meeting at x = 10,000,007.
FAR = 10_000_000.0
EPS = float(np.spacing(FAR))
FAR_TRANSFORM = Affine(6, 0, FAR, 0, -6, FAR + 12)


def far_plan(cells, shape=(2, 3), transform=FAR_TRANSFORM):
    return all_cells_plan(cells, transform, shape)


def far_pair(right_edge):
    return [shapely.box(FAR, FAR, FAR + 7, FAR + 12), shapely.box(right_edge, FAR, FAR + 14, FAR + 12)]


def far_strip(count=40):
    """A row of cells: every second seam carries one-ULP roundoff residue."""
    edges = FAR + 7.0 * np.arange(count + 1)
    return [
        shapely.box(edges[i] - (float(np.spacing(edges[i])) if i % 2 else 0.0), FAR, edges[i + 1], FAR + 12)
        for i in range(count)
    ]


ROUNDOFF = {
    # name: (cells, plan shape, transform, accepted, residues)
    "unsampled_residue": (far_pair(FAR + 7 - EPS), (2, 3), FAR_TRANSFORM, True, 1),
    "residue_on_pixel_centre": (
        [shapely.box(FAR, FAR, FAR + 3 + EPS, FAR + 12), shapely.box(FAR + 3 - EPS, FAR, FAR + 14, FAR + 12)],
        (2, 3), FAR_TRANSFORM, False, None),
    "substantial_unsampled_overlap": (far_pair(FAR + 6.9), (2, 3), FAR_TRANSFORM, False, None),
    # The same residue under another plan: 2-unit pixels put a centre at x + 7.
    "same_residue_sampled_by_another_plan": (
        [shapely.box(FAR, FAR, FAR + 7 + EPS, FAR + 12), shapely.box(FAR + 7 - EPS, FAR, FAR + 14, FAR + 12)],
        (6, 7), Affine(2, 0, FAR, 0, -2, FAR + 12), False, None),
    "same_cells_unsampled_by_coarse_plan": (
        [shapely.box(FAR, FAR, FAR + 7 + EPS, FAR + 12), shapely.box(FAR + 7 - EPS, FAR, FAR + 14, FAR + 12)],
        (2, 3), FAR_TRANSFORM, True, 1),
    "many_residues_across_batches": (far_strip(), (2, 47), FAR_TRANSFORM, True, 20),
    "residues_then_real_overlap": (
        far_strip() + [shapely.box(FAR + 280 - 0.5, FAR, FAR + 290, FAR + 12)], (2, 49), FAR_TRANSFORM, False, None),
}


@pytest.mark.parametrize("threads", [1, 4])
@pytest.mark.parametrize("name", sorted(ROUNDOFF))
def test_roundoff_tolerance_matches_reference(name, threads, monkeypatch):
    geometries, shape, transform, accepted, residues = ROUNDOFF[name]
    monkeypatch.setattr(_horizontal, "_PAIR_BATCH", 7)
    monkeypatch.setattr(_horizontal, "_PAIR_QUERY_BUDGET", 5 * len(geometries))
    cells = frame(geometries)
    plan = far_plan(cells, shape, transform)
    expected = reference_outcome(cells.geometry.to_numpy(), plan)
    actual = outcome(cells, None, threads, plan)
    assert actual[0] == expected[0]
    if accepted:
        assert actual == expected == (None, residues)
    else:
        assert actual[0] == "horizontal cells have overlapping interiors"


def test_envelope_pruning_keeps_every_pair_the_tolerance_must_judge():
    """A pair with any positive-area intersection has strictly overlapping envelopes."""
    for name, (geometries, shape, transform, _, _) in ROUNDOFF.items():
        values = np.array(geometries, dtype=object)
        kept = set()
        for left, right in _horizontal._candidate_batches(values, shapely.STRtree(values)):
            kept.update(zip(left.tolist(), right.tolist()))
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                if shapely.area(shapely.intersection(values[i], values[j])) > 0:
                    assert (i, j) in kept, name


def test_tolerance_dependent_pass_is_never_recorded_or_reused(store, counted):
    cells = frame(ROUNDOFF["same_cells_unsampled_by_coarse_plan"][0])
    coarse = far_plan(cells)
    fine = far_plan(cells, (6, 7), Affine(2, 0, FAR, 0, -2, FAR + 12))
    assert _cell_validation.identity(cells.geometry.to_numpy()) is not None
    for attempt in (1, 2):
        with pytest.warns(RuntimeWarning, match="Numerical cell-overlap residue"):
            assert _cell_validation.validate(cells, None, coarse, threads=attempt) is False
        assert len(counted) == attempt
    assert not _cell_validation._passed
    assert not store.exists() or not list(store.iterdir())
    # The same cells under a plan whose pixel centre lies in the residue are refused.
    with pytest.raises(FimUnsupportedError, match="overlapping interiors"):
        _cell_validation.validate(cells, None, fine)
    assert len(counted) == 3 and not _cell_validation._passed
    assert not store.exists() or not list(store.iterdir())


def test_unknown_validation_answer_is_not_recorded(store, monkeypatch):
    cells = frame(grid())
    monkeypatch.setattr(_horizontal, "prepare_grid", lambda *a, **k: object())
    assert _cell_validation.validate(cells, None, all_cells_plan(cells)) is False
    assert not _cell_validation._passed


def test_prepared_context_does_not_retain_a_tolerance_dependent_pass():
    from collections import OrderedDict

    from ras_commander.fim._sloping_context import FimPreparedSlopingModel

    cells = frame(ROUNDOFF["same_cells_unsampled_by_coarse_plan"][0])
    model = object.__new__(FimPreparedSlopingModel)
    model._cells, model._terrain = cells, None
    model._validated_positions, model._validation_bytes = OrderedDict(), 0
    model._validation_limit = 4096
    with pytest.warns(RuntimeWarning, match="Numerical cell-overlap residue"):
        assert model._validate_grid(far_plan(cells)) is False
    assert not model._validated_positions
    # Identical cell positions, another window: judged again and refused.
    with pytest.raises(FimUnsupportedError, match="overlapping interiors"):
        model._validate_grid(far_plan(cells, (6, 7), Affine(2, 0, FAR, 0, -2, FAR + 12)))
    clean = frame(grid())
    model._cells = clean
    assert model._validate_grid(all_cells_plan(clean)) is False
    assert model._validate_grid(all_cells_plan(clean)) is True


def skewed(seed, overlap):
    """A sheared, jittered quad mesh; envelopes of neighbours overlap."""
    rng = np.random.default_rng(seed)
    n = 9
    x, y = np.meshgrid(np.arange(n) * 6.0 + 4, np.arange(n) * 6.0 + 4)
    x = x + 0.35 * y / 6.0 + rng.uniform(-0.8, 0.8, x.shape)
    y = y + rng.uniform(-0.8, 0.8, y.shape)
    quads = [
        Polygon([(x[j, i], y[j, i]), (x[j, i + 1], y[j, i + 1]),
                 (x[j + 1, i + 1], y[j + 1, i + 1]), (x[j + 1, i], y[j + 1, i])])
        for j in range(n - 1) for i in range(n - 1)
    ]
    if overlap:
        k = int(rng.integers(len(quads)))
        quads.append(shapely.affinity.translate(quads[k], 0.9, 0.7))
    return quads


RING = Polygon(box(8, 8, 40, 40).exterior.coords, [box(16, 16, 32, 32).exterior.coords])
ACCEPTED = {
    "square_grid": grid(),
    "ring_with_cell_in_hole": [RING, box(16, 16, 32, 32)],
    "corner_touch": [box(8, 8, 16, 16), box(16, 16, 24, 24)],
    "edge_touch": [box(8, 8, 16, 16), box(16, 8, 24, 16)],
    "envelopes_overlap_interiors_apart": [
        Polygon([(8, 8), (20, 8), (8, 20)]), Polygon([(21, 9), (21, 21), (9, 21)])],
    **{f"skewed_{seed}": skewed(seed, False) for seed in range(4)},
}
REFUSED = {
    "cell_wider_than_hole": [RING, box(15, 16, 32, 32)],
    "sliver_overlap": [box(8, 8, 16, 16), box(16 - 1e-9, 8, 24, 16)],
    "nested": [box(8, 8, 40, 40), box(16, 16, 24, 24)],
    "coincident": [box(8, 8, 16, 16)] * 3,
    "crossing_bands": [Polygon([(8, 8), (40, 38), (40, 40), (8, 10)]),
                       Polygon([(8, 40), (40, 8), (40, 10), (8, 42)])],
    "bowtie": [box(8, 8, 16, 16), Polygon([(20, 20), (30, 30), (30, 20), (20, 30)])],
    "multipolygon": [box(8, 8, 16, 16), shapely.MultiPolygon([box(20, 20, 24, 24)])],
    "empty": [box(8, 8, 16, 16), Polygon()],
    **{f"skewed_overlap_{seed}": skewed(seed, True) for seed in range(4)},
}
CASES = {**ACCEPTED, **REFUSED}


@pytest.mark.parametrize("threads", [1, 4])
@pytest.mark.parametrize("name", sorted(CASES))
def test_validation_outcome_matches_released_reference(name, threads, terrain, monkeypatch):
    # Small batches exercise batch boundaries and the worker pool on tiny scenes.
    monkeypatch.setattr(_horizontal, "_PAIR_BATCH", 7)
    monkeypatch.setattr(_horizontal, "_PAIR_QUERY_BUDGET", 5 * len(CASES[name]))
    cells = frame(CASES[name])
    plan = all_cells_plan(cells)
    expected = reference_outcome(cells.geometry.to_numpy(), plan)
    actual = outcome(cells, terrain, threads, plan)
    assert actual[0] == expected[0]
    assert (expected[0] is None) == (name in ACCEPTED)
    if name in ACCEPTED:
        assert actual == expected == (None, 0)


def test_passed_validation_is_reused_in_process_and_across_processes(terrain, store, counted):
    cells = frame(grid())
    plan = plan_for(cells, terrain)
    assert _cell_validation.validate(cells, terrain, plan, threads=2) is False
    assert counted == [{"threads": 2}]
    assert _cell_validation.validate(cells, terrain, plan) is True
    assert len(counted) == 1
    records = list(store.glob("*.json"))
    assert len(records) == 1
    digest = _cell_validation.identity(cells.geometry.to_numpy())
    assert records[0].stem == digest and len(digest) == 64
    assert json.loads(records[0].read_text())["cells"] == len(cells)
    # A new process has no in-memory record and trusts only a matching file.
    _cell_validation._passed.clear()
    equal_copy = frame(grid())
    assert _cell_validation.validate(equal_copy, terrain, plan_for(equal_copy, terrain)) is True
    assert len(counted) == 1


def test_changed_geometry_order_or_subset_never_reuses(terrain, store, counted):
    base = grid()
    cells = frame(base)
    assert _cell_validation.validate(cells, terrain, plan_for(cells, terrain)) is False
    moved = list(base)
    moved[-1] = Polygon([(56, 56), (64, 56), (64, 64 - 1e-9), (56, 64)])
    reordered = base[1:] + base[:1]
    fewer = base[:-1]
    holed = list(base)
    holed[0] = Polygon(base[0].exterior.coords, [box(2, 2, 4, 4).exterior.coords])
    digests = {_cell_validation.identity(cells.geometry.to_numpy())}
    for expected_calls, variant in enumerate((moved, reordered, fewer, holed), start=2):
        changed = frame(variant)
        digests.add(_cell_validation.identity(changed.geometry.to_numpy()))
        assert _cell_validation.validate(changed, terrain, plan_for(changed, terrain)) is False
        assert len(counted) == expected_calls
    assert len(digests) == 5
    # A bounding-box AOI selects another cell subset of the unchanged geometry.
    from ras_commander.fim import _aoi

    aoi = _aoi.resolve_aoi(bbox=[0, 0, 20, 20], polygon=None, polygon_layer=None,
                           aoi_crs=None, default_crs=cells.crs)
    window = _horizontal.plan_grid(cells, terrain, aoi, 1024, native=True)
    assert 0 < len(window.cell_positions) < len(cells)
    assert _cell_validation.validate(cells, terrain, window) is False
    assert _cell_validation.validate(cells, terrain, window) is True
    assert len(counted) == 6


def test_ring_division_is_part_of_the_identity():
    outer = [(0, 0), (9, 0), (9, 9), (0, 9), (0, 0)]
    inner = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]
    # The same flat coordinate list divided into rings and cells three ways.
    one = np.array([Polygon(outer, [inner])], dtype=object)
    two = np.array([Polygon(outer), Polygon(inner)], dtype=object)
    three = np.array([Polygon(outer, [inner]), Polygon(inner)], dtype=object)
    four = np.array([Polygon(outer), Polygon(inner, [inner])], dtype=object)
    assert len({_cell_validation.identity(v) for v in (one, two, three, four)}) == 4
    assert _cell_validation.identity(three) == _cell_validation.identity(three.copy())


@pytest.mark.parametrize("geometries", [
    [box(0, 0, 8, 8), shapely.MultiPolygon([box(8, 8, 16, 16)])],
    [box(0, 0, 8, 8), Polygon()],
    [],
])
def test_identity_refuses_inputs_the_validator_does_not_accept(geometries):
    assert _cell_validation.identity(np.array(geometries, dtype=object)) is None


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_refusal_is_never_recorded(name, terrain, store, counted):
    cells = frame(REFUSED[name])
    for attempt in (1, 2):
        with pytest.raises(FimUnsupportedError):
            _cell_validation.validate(cells, terrain, all_cells_plan(cells))
        assert len(counted) == attempt
    assert not _cell_validation._passed
    assert not store.exists() or not list(store.iterdir())


def test_copied_pass_for_other_content_does_not_admit_overlap(terrain, store, counted):
    good = frame(grid())
    assert _cell_validation.validate(good, terrain, plan_for(good, terrain)) is False
    record = next(store.glob("*.json"))
    bad = frame(REFUSED["sliver_overlap"])
    digest = _cell_validation.identity(bad.geometry.to_numpy())
    # A copied record keeps the digest of the content that really passed.
    (store / f"{digest}.json").write_text(record.read_text())
    with pytest.raises(FimUnsupportedError, match="overlapping"):
        _cell_validation.validate(bad, terrain, all_cells_plan(bad))


@pytest.mark.parametrize("damage", [
    lambda text: "",
    lambda text: text[: len(text) // 2],
    lambda text: "[]",
    lambda text: "\x00" * 64,
    lambda text: text.replace(_cell_validation.SCHEMA, "fim-cell-validation/1"),
    lambda text: text.replace('"passed"', '"failed"'),
    lambda text: json.dumps({**json.loads(text), "cells": json.loads(text)["cells"] + 1}),
    lambda text: json.dumps({**json.loads(text), "geos": "0.0.0"}),
    lambda text: json.dumps({**json.loads(text), "digest": "0" * 64}),
    lambda text: json.dumps({**json.loads(text), "extra": 1}),
    lambda text: text + " " * 8192,
])
def test_damaged_or_mismatching_record_falls_back_to_full_validation(damage, terrain, store, counted):
    cells = frame(grid())
    plan = plan_for(cells, terrain)
    assert _cell_validation.validate(cells, terrain, plan) is False
    record = next(store.glob("*.json"))
    record.write_text(damage(record.read_text()))
    _cell_validation._passed.clear()
    assert _cell_validation.validate(cells, terrain, plan) is False
    assert len(counted) == 2
    # The completed validation replaces the unusable record.
    _cell_validation._passed.clear()
    assert _cell_validation.validate(cells, terrain, plan) is True
    assert len(counted) == 2


def test_persistence_can_be_disabled_and_storage_failure_is_harmless(terrain, store, counted, monkeypatch):
    cells = frame(grid())
    plan = plan_for(cells, terrain)
    monkeypatch.setenv(_cell_validation.ENVIRONMENT, "off")
    assert _cell_validation.store_directory() is None
    assert _cell_validation.validate(cells, terrain, plan) is False
    assert _cell_validation.validate(cells, terrain, plan) is True
    assert not store.exists()
    _cell_validation._passed.clear()
    assert _cell_validation.validate(cells, terrain, plan) is False
    # A path that cannot be a directory leaves validation working, without reuse on disk.
    blocker = store.parent / "blocker"
    blocker.write_text("file")
    monkeypatch.setenv(_cell_validation.ENVIRONMENT, str(blocker / "child"))
    _cell_validation._passed.clear()
    assert _cell_validation.validate(cells, terrain, plan) is False
    _cell_validation._passed.clear()
    assert _cell_validation.validate(cells, terrain, plan) is False
    assert len(counted) == 4


def test_store_is_bounded(terrain, store, monkeypatch):
    monkeypatch.setattr(_cell_validation, "_STORE_RECORDS", 3)
    for size in range(2, 8):
        cells = frame(grid(size))
        assert _cell_validation.validate(cells, terrain, plan_for(cells, terrain)) is False
    assert len(list(store.glob("*.json"))) == 3
    assert not list(store.glob(".pending-*"))


def test_empty_window_is_not_recorded(terrain, store, counted):
    cells = frame(grid())
    plan = SimpleNamespace(shape=(0, 0), cell_positions=np.array([], dtype=np.int64))
    assert _cell_validation.validate(cells, terrain, plan) is False
    assert _cell_validation.validate(cells, terrain, plan) is False
    assert len(counted) == 2 and not _cell_validation._passed
