"""PY-ROUTE-2 equivalence on edited *copies* of real fixtures (never the sources).

The only local 2D sediment plan (``sediment-2d-Weise.p01``) stores contradictory
unit metadata (``/Geometry/@SI Units=US Customary`` versus ``/@Units System=SI``),
so every HdfResultsSediment reader raises the same ``ValueError`` in all modes on
the original. To qualify the success path, a temporary copy drops only the
contradictory ``/Geometry/@SI Units`` attribute; all datasets keep their exact
real values. The same three-mode ``_check`` (exact equality, h5py value-read
gate, injected engine failures) then runs on the copy.

PY-ROUTE-3 adds the same treatment for ``HdfPump.get_pump_operation_timeseries``
(``orleans_pump_copy``): its success path has no real fixture (baseline bug,
PR #557), so it is qualified on an internally consistent copy of OrleansEx.p02.

Gate: ``RAS_ROUTE2_FIXTURES`` (manifest must list ``sediment-2d-Weise.p01`` and
``OrleansEx.p02``).
"""
import shutil

import h5py
import pytest

from ._cases import CASES
from .test_routed_equivalence import FIXTURES, MANIFEST, _check

pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE2_FIXTURES to the PY-ROUTE-2 real-fixture JSON manifest")

SEDIMENT = sorted(c for c in CASES if c.startswith("HdfResultsSediment."))


@pytest.fixture(scope="module")
def weise_units_copy(tmp_path_factory):
    source = {f["name"]: f["path"] for f in FIXTURES}.get("sediment-2d-Weise.p01")
    if source is None:
        pytest.skip("sediment-2d-Weise.p01 not in manifest")
    copy = tmp_path_factory.mktemp("weise") / "Weise.units-consistent.p01.hdf"
    shutil.copyfile(source, copy)
    with h5py.File(copy, "r+") as f:
        del f["Geometry"].attrs["SI Units"]
    return str(copy)


@pytest.mark.parametrize("case", SEDIMENT)
def test_sediment_units_consistent_copy(case, weise_units_copy, monkeypatch):
    _check(case, CASES[case], weise_units_copy, "sediment-2d-Weise.p01[units-consistent copy]", monkeypatch)


# ---------------------------------------------------------------- PY-ROUTE-3: pump operation success path
PUMP_OPERATION = "HdfPump.get_pump_operation_timeseries"
DSS_TS = "Results/Unsteady/Output/Output Blocks/DSS Profile Output/Unsteady Time Series"
BASE_TS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


@pytest.fixture(scope="module")
def orleans_pump_copy(tmp_path_factory):
    """OrleansEx.p02 copy whose DSS Profile pump block is internally consistent.

    On every real fixture ``get_pump_operation_timeseries`` raises the same
    ValueError in all modes: it labels the DSS Profile block rows (64 on Orleans)
    with the Base Output time stamps (127), the baseline bug PR #557 fixes. To
    exercise the success-path assembly, the copy replaces the DSS Profile block's
    time datasets and ``Pumping Stations`` group with h5py copies of the Base
    Output ones (real values, attributes and storage layout), so both axes have
    127 rows. Every value in the copy is a real stored value.
    """
    source = {f["name"]: f["path"] for f in FIXTURES}.get("OrleansEx.p02")
    if source is None:
        pytest.skip("OrleansEx.p02 not in manifest")
    copy = tmp_path_factory.mktemp("orleans") / "OrleansEx.pump-consistent.p02.hdf"
    shutil.copyfile(source, copy)
    with h5py.File(copy, "r+") as f:
        dss, base = f[DSS_TS], f[BASE_TS]
        for name in ("Pumping Stations", "Time", "Time Date Stamp", "Time Date Stamp (ms)", "Time Step"):
            del dss[name]
            f.copy(base[name], dss, name=name)
    return str(copy)


def test_pump_operation_consistent_copy(orleans_pump_copy, monkeypatch):
    _check(PUMP_OPERATION, CASES[PUMP_OPERATION], orleans_pump_copy,
           "OrleansEx.p02[pump-consistent copy]", monkeypatch)
    with h5py.File(orleans_pump_copy, "r") as f:
        rows = f[f"{DSS_TS}/Pumping Stations"]
        assert all(rows[s]["Structure Variables"].shape[0] == f[f"{BASE_TS}/Time"].shape[0] for s in rows)
