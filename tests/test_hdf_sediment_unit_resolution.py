"""
Unit resolution for 2D sediment results on real HEC-RAS output.

Weise_2D (SI) result HDFs written by HEC-RAS 6.6 and 7.0 carry root
``/@Units System = SI Units`` with ``/Geometry/@SI Units = False``: RasMapper
writes that geometry flag from a ``False`` default and never updates it from
the project units. Every dataset ``Units`` label in the file says SI.
Chippewa_2D (US Customary) is the consistent success path.

The tests read real result HDFs, never synthetic ones:

- ``RAS_COMMANDER_SEDIMENT_UNIT_FIXTURES`` names a folder containing the
  ``RasCmdr.compute_plan`` destination folders ``Weise_2D_<tag>`` and
  ``Chippewa_2D_<tag>`` (``tag`` = ``66`` or ``70``), each with its ``.prj``.
- Otherwise, with ``RAS_COMMANDER_RUN_HECRAS_INTEGRATION=1`` on Windows, the
  plans are computed on demand through ``RasCmdr.compute_plan`` for each
  installed HEC-RAS version (``prepare_and_compute`` below).
- Otherwise the tests skip.

Weise p01 is computed with the active-layer D10/D50/D90 output and stored
``Cell Velocity`` components; Chippewa p02 is shortened to two days.
Contradiction cases use real-derived excerpts of the Weise result.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("geopandas")

from ras_commander import HdfBase
from ras_commander.hdf import HdfResultsSediment

pytestmark = pytest.mark.integration

_FIXTURE_ENV = "RAS_COMMANDER_SEDIMENT_UNIT_FIXTURES"
_VERSIONS = {"66": "6.6", "70": "7.0"}
_PLANS = {"Weise_2D": ("Weise", "01"), "Chippewa_2D": ("Chippewa_2D", "02")}
_ACTIVE_LAYER = ["2D Cell d50 Active", "2D Cell d10 Active", "2D Cell d90 Active"]
_BED = ("Results/Unsteady/Output/Output Blocks/Sediment Bed/"
        "Unsteady Time Series/2D Flow Areas")
_BASE = ("Results/Unsteady/Output/Output Blocks/Base Output/"
         "Unsteady Time Series/2D Flow Areas")


def prepare_and_compute(project: str, version: str, dest_root: Path) -> Path:
    """Extract, prepare and compute one example plan; return its dest folder."""
    from ras_commander import RasCmdr, RasExamples, RasPlan, init_ras_project

    tag = version.replace(".", "")
    source = RasExamples.extract_project(
        project, output_path=dest_root / "source", suffix=f"v{tag}")
    ras = init_ras_project(source, version)
    plan = _PLANS[project][1]
    output_variables = None
    if project == "Weise_2D":
        RasPlan.set_sediment_output_variables(
            plan, _ACTIVE_LAYER, output_level=6, ras_object=ras)
        output_variables = ["Cell Velocity"]
    else:
        start = RasPlan.get_plan_value(plan, "Simulation Date", ras_object=ras)
        day, clock = start.split(",")[:2]
        begin = datetime.strptime(f"{day} {clock}", "%d%b%Y %H%M")
        RasPlan.update_simulation_date(
            plan, begin, begin + timedelta(days=2), ras_object=ras)
    dest = dest_root / f"{project}_{tag}"
    result = RasCmdr.compute_plan(
        plan, dest_folder=dest, ras_object=ras, overwrite_dest=True,
        hdf_output_variables=output_variables)
    if not result:
        raise RuntimeError(f"{project} plan {plan} failed on HEC-RAS {version}: {result}")
    return dest


def _installed(version: str) -> bool:
    return Path(r"C:\Program Files (x86)\HEC\HEC-RAS", version, "Ras.exe").exists()


@pytest.fixture(scope="session")
def result_folder(tmp_path_factory):
    cache = {}

    def get(project: str, tag: str) -> Path:
        key = (project, tag)
        if key in cache:
            return cache[key]
        root = os.environ.get(_FIXTURE_ENV)
        if root:
            folder = Path(root) / f"{project}_{tag}"
            if not folder.is_dir():
                pytest.skip(f"{folder} not in {_FIXTURE_ENV}")
        elif (platform.system() == "Windows"
              and os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") == "1"
              and _installed(_VERSIONS[tag])):
            folder = prepare_and_compute(
                project, _VERSIONS[tag], tmp_path_factory.mktemp(f"sed_units_{tag}"))
        else:
            pytest.skip(f"Set {_FIXTURE_ENV} or RAS_COMMANDER_RUN_HECRAS_INTEGRATION=1 "
                        f"with HEC-RAS {_VERSIONS[tag]} installed")
        cache[key] = folder
        return folder

    return get


def _plan_hdf(folder: Path, project: str) -> Path:
    stem, plan = _PLANS[project]
    return folder / f"{stem}.p{plan}.hdf"


def _median_at_t0(hdf: Path, percentile: str, **kwargs):
    gdf = HdfResultsSediment.get_active_layer_grain_class(
        hdf, percentile, time_index=0, **kwargs)
    return float(np.median(gdf[f"{percentile.lower()}_mm"])), gdf


def _excerpt(source: Path, dest: Path, objects) -> Path:
    """Copy root/geometry unit attributes and selected objects of a real HDF."""
    with h5py.File(source, "r") as src, h5py.File(dest, "w") as out:
        for key, value in src.attrs.items():
            out.attrs[key] = value
        geometry = out.require_group("Geometry")
        for key, value in src["Geometry"].attrs.items():
            geometry.attrs[key] = value
        out.require_group("Results")
        for path in objects:
            parent = out.require_group(str(Path(path).parent.as_posix()))
            src.copy(src[path], parent, name=Path(path).name)
    return dest


@pytest.fixture
def weise_hdf(result_folder):
    return _plan_hdf(result_folder("Weise_2D", "66"), "Weise_2D")


def _weise_area(hdf: Path) -> str:
    with h5py.File(hdf, "r") as f:
        return next(iter(f[_BED].keys()))


@pytest.mark.parametrize("tag", sorted(_VERSIONS))
def test_sediment_units_chippewa_consistent(result_folder, tag):
    hdf = _plan_hdf(result_folder("Chippewa_2D", tag), "Chippewa_2D")

    metadata = HdfBase.get_result_unit_metadata(hdf)
    assert metadata["status"] == "resolved"
    assert metadata["length_units"] == "ft"
    assert metadata["warnings"] == []

    d50, gdf = _median_at_t0(hdf, "D50")
    assert d50 == pytest.approx(4.0, abs=1e-4)
    assert gdf.attrs == {"units": "mm", "length_unit": "ft"}
    assert _median_at_t0(hdf, "D10")[0] == pytest.approx(0.5, abs=1e-4)
    assert _median_at_t0(hdf, "D90")[0] == pytest.approx(32.0, abs=1e-3)


@pytest.mark.parametrize("tag", sorted(_VERSIONS))
def test_sediment_units_weise_known_hec_pattern(result_folder, tag):
    hdf = _plan_hdf(result_folder("Weise_2D", tag), "Weise_2D")

    metadata = HdfBase.get_result_unit_metadata(hdf)
    assert metadata["status"] == "resolved"
    assert metadata["source"] == "plan_hdf"
    assert metadata["unit_system"] == "SI"
    assert metadata["length_units"] == "m"
    assert len(metadata["warnings"]) == 1
    assert "/Geometry/@SI Units" in metadata["warnings"][0]
    assert {item["attribute"]: item["unit_system"] for item in metadata["evidence"]} == {
        "/Geometry/@SI Units": "US Customary",
        "/@Units System": "SI",
    }

    # Log2-interpolated .s01 bed gradation of the Weise flume.
    d50, gdf = _median_at_t0(hdf, "D50")
    assert d50 == pytest.approx(5.2780, abs=1e-3)
    assert gdf.attrs == {"units": "mm", "length_unit": "m"}
    assert _median_at_t0(hdf, "D10")[0] == pytest.approx(2.7407, abs=1e-3)
    assert _median_at_t0(hdf, "D90")[0] == pytest.approx(7.8431, abs=1e-3)

    assert HdfResultsSediment.get_cell_bed_change(hdf).attrs["length_unit"] == "m"


def test_weise_pattern_requires_corroboration(weise_hdf, tmp_path):
    area = _weise_area(weise_hdf)
    excerpt = _excerpt(weise_hdf, tmp_path / "Weise.p01.hdf", [
        f"{_BASE}/{area}/Water Surface",
        f"{_BED}/{area}/Cell Bed Change",
    ])
    with h5py.File(excerpt, "r+") as f:
        f[f"{_BASE}/{area}/Water Surface"].attrs["Units"] = np.bytes_("ft")

    with pytest.raises(ValueError, match="do not corroborate SI.*unit_system="):
        HdfBase.get_result_unit_metadata(excerpt)
    metadata = HdfBase.get_result_unit_metadata(excerpt, strict=False)
    assert metadata["status"] == "contradictory"


def test_weise_pattern_without_labelled_datasets_raises(weise_hdf, tmp_path):
    excerpt = _excerpt(weise_hdf, tmp_path / "Weise.p01.hdf", [])

    with pytest.raises(ValueError, match="unit_system='SI'"):
        HdfBase.get_result_unit_metadata(excerpt)

    metadata = HdfBase.get_result_unit_metadata(excerpt, unit_system="SI")
    assert metadata["status"] == "resolved"
    assert metadata["source"] == "override"
    assert metadata["length_units"] == "m"
    assert len(metadata["evidence"]) == 2
    assert "/Geometry/@SI Units=US Customary" in metadata["warnings"][0]


def test_active_layer_requires_mm_label(weise_hdf, tmp_path):
    area = _weise_area(weise_hdf)
    d50 = f"{_BED}/{area}/Cell Active Layer Percentile Diameters - D50"
    excerpt = _excerpt(weise_hdf, tmp_path / "Weise.p01.hdf", [
        d50,
        f"Geometry/2D Flow Areas/{area}/Cells Surface Area",
        f"Geometry/2D Flow Areas/{area}/Cells Center Coordinate",
    ])
    assert _median_at_t0(excerpt, "D50")[0] == pytest.approx(5.2780, abs=1e-3)

    with h5py.File(excerpt, "r+") as f:
        f[d50].attrs["Units"] = np.bytes_("m")
    with pytest.raises(ValueError, match="must be labelled 'mm'"):
        HdfResultsSediment.get_active_layer_grain_class(excerpt, "D50")


def test_prj_marker_overrides_hdf(result_folder, tmp_path):
    from ras_commander import RasPrj, init_ras_project

    folder = result_folder("Weise_2D", "66")
    hdf = _plan_hdf(folder, "Weise_2D")
    prj = folder / "Weise.prj"

    metadata = HdfBase.get_result_unit_metadata(hdf, project_file=prj)
    assert metadata["source"] == "project_file"
    assert metadata["length_units"] == "m"
    assert "project file marker" in metadata["warnings"][0]

    ras = init_ras_project(folder, "6.6", ras_object=RasPrj(),
                           load_results_summary=False)
    gdf = HdfResultsSediment.get_cell_bed_change("01", ras_object=ras)
    assert gdf.attrs["length_unit"] == "m"

    wrong = tmp_path / "Weise.prj"
    wrong.write_text(prj.read_text(encoding="utf-8", errors="replace")
                     .replace("SI Units", "English Units"), encoding="utf-8")
    with pytest.raises(ValueError, match="disagrees with /@Units System=SI"):
        HdfBase.get_result_unit_metadata(hdf, project_file=wrong)


def test_weise_velocity_query_accepts_si_units(weise_hdf):
    pytest.importorskip("scipy")
    from ras_commander.hdf import HdfResultsQuery

    query_module = importlib.import_module("ras_commander.hdf.HdfResultsQuery")
    area = _weise_area(weise_hdf)
    stored = f"{_BASE}/{area}/Cell Velocity - Velocity X"
    with h5py.File(weise_hdf, "r") as f:
        if stored not in f:
            pytest.skip("Weise fixture lacks stored Cell Velocity components")
        assert HdfBase._decode_unit_attribute(f[stored].attrs["Units"]) == "m/s"
        x, y = f[f"Geometry/2D Flow Areas/{area}/Cells Center Coordinate"][100]

    # Stored components pass _qualify_velocity_dataset unit checks.
    result = HdfResultsQuery.query_point(
        weise_hdf, float(x), float(y), variable="velocity", time_index=-1)
    assert np.isfinite(result["value"]) and result["value"] >= 0
    assert query_module._read_unit_metadata(weise_hdf)["velocity_units"] == "m/s"
