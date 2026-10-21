"""ROUTE-NONHDF cases: ras_commander/check (RasCheck read helpers)."""
from pathlib import Path

from ._case import Case


def _utils():
    from ras_commander.check import _utils
    return _utils


CASES = {
    "_utils.get_available_profiles": Case(lambda p: _utils().get_available_profiles(Path(p)), kinds={"plan"}),
    "_utils.get_structure_locations": Case(lambda p: _utils().get_structure_locations(Path(p))),
    "_utils.verify_steady_plan": Case(lambda p: _utils().verify_steady_plan(Path(p)), kinds={"plan"}),
    "_utils.detect_flow_type": Case(lambda p: _utils().detect_flow_type(Path(p)), kinds={"plan"}),
    "_utils.has_2d_mesh": Case(lambda p: _utils().has_2d_mesh(Path(p)), kinds={"plan"}),
}
