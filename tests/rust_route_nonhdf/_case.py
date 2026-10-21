"""Case declaration and fixture selection for the ROUTE-NONHDF equivalence suite.

Each case module ``_cases_<group>.py`` defines ``CASES = {name: Case(...)}``. A case is
a callable taking one fixture (its path, or the project dict for ``kinds={"project"}``)
and returning a comparable value. Arguments are derived from the fixture inside the
case module (harness reads, exempt from the h5py gate). ``kinds`` selects fixtures:

- ``plan``: ``*.p##.hdf`` plan HDFs; ``geom``: ``*.g##.hdf`` geometry HDFs;
- ``unsteady``: ``*.u##.hdf``; ``sidecar``: other HDFs (land cover, soils, infiltration,
  terrain, sediment materials); ``project``: route-2 project dicts (geom + sidecars).

``max_mb`` bounds the fixture size for slow functions (the reason is recorded in the
skip). ``helper`` names the public function whose read helper the case exercises when
the public function itself needs HEC-RAS/.NET execution (reported in the inventory).
"""
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from typing import Callable, FrozenSet, Optional

KINDS = {"plan", "geom", "unsteady", "sidecar", "project"}


@dataclass(frozen=True)
class Case:
    call: Callable
    kinds: FrozenSet[str] = frozenset({"plan", "geom"})
    max_mb: Optional[float] = None
    helper: Optional[str] = None
    note: str = ""

    def __post_init__(self):
        kinds = frozenset(self.kinds)
        assert kinds <= KINDS, kinds
        object.__setattr__(self, "kinds", kinds)


def fixture_kind(path):
    name = Path(path).name.lower()
    if re.search(r"\.p\d\d\.hdf$", name):
        return "plan"
    if re.search(r"\.g\d\d\.hdf$", name):
        return "geom"
    if re.search(r"\.u\d\d\.hdf$", name):
        return "unsteady"
    return "sidecar"


def load_fixtures():
    """Union of the route-1 and route-2 manifests (by name), plus route-2 projects."""
    fixtures, projects, seen = [], [], set()
    for var in ("RAS_ROUTE1_FIXTURES", "RAS_ROUTE2_FIXTURES"):
        manifest = os.environ.get(var)
        if not manifest:
            continue
        data = json.loads(Path(manifest).read_text())
        for f in data.get("fixtures", []):
            if f["name"] not in seen and Path(f["path"]).is_file():
                seen.add(f["name"])
                fixtures.append(dict(f, kind=fixture_kind(f["path"])))
        for p in data.get("projects", []):
            if p["name"] not in {q["name"] for q in projects}:
                projects.append(p)
    return fixtures, projects


def all_cases():
    """Every ``_cases_<group>.py`` module's CASES, keyed ``<group>:<name>``."""
    import importlib
    out = {}
    here = Path(__file__).parent
    for module in sorted(here.glob("_cases_*.py")):
        group = module.stem[len("_cases_"):]
        cases = importlib.import_module(f"{__package__}.{module.stem}").CASES
        for name, case in cases.items():
            out[f"{group}:{name}"] = case
    return out
