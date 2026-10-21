"""PY-ROUTE-2 equivalence on edited *copies* of real fixtures (never the sources).

The only local 2D sediment plan (``sediment-2d-Weise.p01``) stores contradictory
unit metadata (``/Geometry/@SI Units=US Customary`` versus ``/@Units System=SI``),
so every HdfResultsSediment reader raises the same ``ValueError`` in all modes on
the original. To qualify the success path, a temporary copy drops only the
contradictory ``/Geometry/@SI Units`` attribute; all datasets keep their exact
real values. The same three-mode ``_check`` (exact equality, h5py value-read
gate, injected engine failures) then runs on the copy.

Gate: ``RAS_ROUTE2_FIXTURES`` (manifest must list ``sediment-2d-Weise.p01``).
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
