"""ROUTE-NONHDF cases: ras_commander/check (RasCheck validators and their read helpers).

The public ``Check*.check_*`` entry points take HDF paths, so they are exercised
end to end: a plan fixture serves as both plan and geometry HDF (6.x plan HDFs
carry the geometry), a geometry fixture as both. Profile arguments come from the
fixture's steady ``Profile Names`` (harness read). Private helpers are also run
individually so each routed site has its own outcome row. Results are normalized
(dataclasses to dicts, enums to values); DataFrames compare exactly.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path

import h5py

from ._case import Case

STEADY_NAMES = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names"


def _norm(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _norm(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def _profiles(path):
    with h5py.File(path, "r") as f:
        if STEADY_NAMES not in f:
            return []
        return [n.decode("utf-8", "replace").strip() for n in f[STEADY_NAMES][()]]


def _base_fw(path):
    names = _profiles(path) or ["PF 1"]
    return names[0], names[-1]


def _thr():
    from ras_commander.check.thresholds import get_default_thresholds
    return get_default_thresholds()


def _bridge_indices(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/Structures/Attributes"
        if key not in f:
            return []
        rows = f[key][()]
    return [i for i, r in enumerate(rows) if r["Type"].decode().strip() == "Bridge"]


def _utils():
    from ras_commander.check import _utils
    return _utils


def _xs():
    from ras_commander.check.check_xs import CheckXs
    return CheckXs


def _nt():
    from ras_commander.check.check_nt import CheckNt
    return CheckNt


def _st():
    from ras_commander.check.check_structures import CheckStructures
    return CheckStructures


def _fw():
    from ras_commander.check.check_floodways import CheckFloodways
    return CheckFloodways


def _bridge_mannings(path):
    idx = _bridge_indices(path)
    if not idx:
        return _nt()._get_bridge_section_mannings_n(Path(path), 0)
    return [_nt()._get_bridge_section_mannings_n(Path(path), i) for i in idx]


_XS_GDF = {}


def _xs_gdf(path):
    """Cross sections as the public check builds them, read with h5py only.

    The argument must not depend on the mode under test (or on the injected engine
    failure), so it is built once with ``RAS_COMMANDER_FAST_HDF=0`` (during the
    first, h5py-only run of the test) and a copy is reused by the later runs, where
    the h5py gate is active; only the routed helper is compared. ``None`` when the
    fixture has no cross sections.
    """
    if path not in _XS_GDF:
        _XS_GDF[path] = _xs_gdf_h5py(path)
    value = _XS_GDF[path]
    return None if value is None else value.copy()


def _xs_gdf_h5py(path):
    import os
    from ras_commander.hdf import HdfXsec
    old = os.environ.get("RAS_COMMANDER_FAST_HDF")
    os.environ["RAS_COMMANDER_FAST_HDF"] = "0"
    try:
        return HdfXsec.get_cross_sections(Path(path))
    except Exception:  # the public checks guard the same call
        return None
    finally:
        if old is None:
            os.environ.pop("RAS_COMMANDER_FAST_HDF", None)
        else:
            os.environ["RAS_COMMANDER_FAST_HDF"] = old


def _contraction(path):
    import pytest
    xs = _xs_gdf(path)
    if xs is None:
        pytest.skip("fixture has no cross sections")
    return _norm(_xs()._check_contraction_coefficients_and_widths(xs, Path(path), _thr()))


def _transitions(path):
    import pytest
    xs = _xs_gdf(path)
    if xs is None:
        pytest.skip("fixture has no cross sections")
    return _norm(_nt()._check_structure_transition_coefficients(Path(path), xs, _thr()))


def _pr():
    from ras_commander.check.check_profiles import CheckProfiles
    return CheckProfiles


def _un():
    from ras_commander.check.check_unsteady import CheckUnsteady
    return CheckUnsteady


def _p(path):
    return Path(path)


CASES = {
    # _utils (coordinator pilot)
    "_utils.get_available_profiles": Case(lambda p: _utils().get_available_profiles(_p(p)), kinds={"plan"}),
    "_utils.get_structure_locations": Case(lambda p: _utils().get_structure_locations(_p(p))),
    "_utils.verify_steady_plan": Case(lambda p: _utils().verify_steady_plan(_p(p)), kinds={"plan"}),
    "_utils.detect_flow_type": Case(lambda p: _utils().detect_flow_type(_p(p)), kinds={"plan"}),
    "_utils.has_2d_mesh": Case(lambda p: _utils().has_2d_mesh(_p(p)), kinds={"plan"}),
    # public validators, end to end (fixture is both plan and geometry HDF)
    "CheckXs.check_xs": Case(lambda p: _norm(_xs().check_xs(_p(p), _p(p), _profiles(p)))),
    "CheckNt.check_nt": Case(lambda p: _norm(_nt().check_nt(_p(p)))),
    "CheckStructures.check_structures": Case(lambda p: _norm(_st().check_structures(_p(p), _p(p), _profiles(p)))),
    "CheckFloodways.check_floodways": Case(lambda p: _norm(_fw().check_floodways(_p(p), _p(p), *_base_fw(p)))),
    # Hdf*-consuming validators (no direct h5py reads; their broad handlers now
    # surface FastHdfError in required mode via reraise_required)
    "CheckProfiles.check_profiles": Case(lambda p: _norm(_pr().check_profiles(_p(p), _profiles(p))), kinds={"plan"}),
    "CheckUnsteady.check_mass_balance": Case(lambda p: _norm(_un().check_mass_balance(_p(p))), kinds={"plan"}),
    "CheckUnsteady.check_computation": Case(lambda p: _norm(_un().check_computation(_p(p))), kinds={"plan"}),
    "CheckUnsteady.check_peaks": Case(lambda p: _norm(_un().check_peaks(_p(p), _p(p))), kinds={"plan"}),
    "CheckUnsteady.check_stability": Case(lambda p: _norm(_un().check_stability(_p(p))), kinds={"plan"}),
    # CheckUnsteady.check_mesh_quality is not a case: it consumes HdfMesh.get_mesh_cell_polygons,
    # whose native (auto/required) polygons differ from h5py in ring start/orientation on
    # 1101001306.p01 and the BaldEagleDamBrk refpts p03 plans (cell areas differ in the last
    # bit). That divergence is in ras_commander/hdf (outside this group); see inventory/check.md.
    # private read helpers, individually
    "CheckXs._check_contraction_coefficients_and_widths": Case(_contraction, helper="CheckXs.check_xs"),
    "CheckNt._check_structure_transition_coefficients": Case(_transitions, helper="CheckNt.check_nt"),
    "CheckNt._check_bridge_section_mannings_n": Case(
        lambda p: _norm(_nt()._check_bridge_section_mannings_n(_p(p), _thr())), helper="CheckNt.check_nt"),
    "CheckNt._get_bridge_section_mannings_n": Case(_bridge_mannings, helper="CheckNt.check_nt"),
    "CheckStructures._check_culverts": Case(
        lambda p: _norm(_st()._check_culverts(_p(p), _p(p), _profiles(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_inline_weirs": Case(
        lambda p: _norm(_st()._check_inline_weirs(_p(p), _p(p), _profiles(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_bridge_flow_types": Case(
        lambda p: _norm(_st()._check_bridge_flow_types(_p(p), _p(p), _profiles(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_structure_distances": Case(
        lambda p: _norm(_st()._check_structure_distances(_p(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_structure_ineffective_section3": Case(
        lambda p: _norm(_st()._check_structure_ineffective_section3(_p(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_structure_permanent_ineffective": Case(
        lambda p: _norm(_st()._check_structure_permanent_ineffective(_p(p), is_floodway=True)),
        helper="CheckFloodways.check_floodways"),
    "CheckStructures._check_structure_geometry_alignment": Case(
        lambda p: _norm(_st()._check_structure_geometry_alignment(_p(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckStructures._check_structure_ground": Case(
        lambda p: _norm(_st()._check_structure_ground(_p(p), _thr())), helper="CheckStructures.check_structures"),
    "CheckFloodways._get_encroachment_stations": Case(
        lambda p: _fw()._get_encroachment_stations(_p(p), _base_fw(p)[1]), kinds={"plan"},
        helper="CheckFloodways.check_floodways"),
    "CheckFloodways._get_encroachment_parameters": Case(
        lambda p: _fw()._get_encroachment_parameters(_p(p), _base_fw(p)[1]), kinds={"plan"},
        helper="CheckFloodways.check_floodways"),
    "CheckFloodways._check_floodway_boundary_conditions": Case(
        lambda p: _norm(_fw()._check_floodway_boundary_conditions(_p(p), *_base_fw(p), _thr())), kinds={"plan"},
        helper="CheckFloodways.check_floodways"),
    "CheckFloodways._check_floodway_lateral_weirs": Case(
        lambda p: _norm(_fw()._check_floodway_lateral_weirs(_p(p), _p(p), _base_fw(p)[1], _thr())), kinds={"plan"},
        helper="CheckFloodways.check_floodways"),
    "CheckFloodways._check_structure_floodway": Case(
        lambda p: _norm(_fw()._check_structure_floodway(_p(p), _p(p), *_base_fw(p), _thr())), kinds={"plan"},
        helper="CheckFloodways.check_floodways"),
}
