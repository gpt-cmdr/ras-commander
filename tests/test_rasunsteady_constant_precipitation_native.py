"""Native acceptance of RasUnsteady.set_constant_precipitation().

Regression for HEC-RAS 7.0 rejecting constant precipitation written to an
unsteady file without meteorology records (BaldEagleCrkMulti2D u13): the plan
stopped with "Error processing event conditions" and wrote no results.

The test runs a one-hour window of plan 03 on a disposable example copy. It
is skipped when Windows or an installed HEC-RAS 7.0.x is unavailable.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
]


def _installed_ras_exe(version: str) -> Path:
    if os.name != "nt":
        pytest.skip("HEC-RAS execution requires Windows")
    from ras_commander.RasPrj import get_ras_exe

    executable = Path(str(get_ras_exe(version)))
    if not executable.is_absolute() or not executable.is_file():
        pytest.skip(f"HEC-RAS {version} is not installed")
    return executable


def test_constant_precipitation_runs_on_file_without_meteorology(tmp_path):
    executable = _installed_ras_exe("7.0")

    from ras_commander import RasCmdr, RasExamples, RasPlan, RasPrj, RasUnsteady
    from ras_commander import init_ras_project
    from ras_commander.hdf import HdfResultsPlan

    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path)
    ras = init_ras_project(project, str(executable), ras_object=RasPrj())
    plan = "03"
    row = ras.plan_df[ras.plan_df["plan_number"] == plan].iloc[0]
    unsteady = project / f"{ras.project_name}.u{row['unsteady_number']}"
    assert "Met BC=" not in unsteady.read_text(encoding="utf-8", errors="replace")

    start = datetime(1999, 1, 1, 12)
    RasPlan.update_simulation_date(plan, start, start + timedelta(hours=1), ras_object=ras)
    RasUnsteady.set_constant_precipitation(unsteady, value=1.0, units="in/hr", ras_object=ras)

    dest = tmp_path / "run"
    result = RasCmdr.compute_plan(
        plan,
        dest_folder=dest,
        force_rerun=True,
        overwrite_dest=True,
        num_cores=2,
        ras_object=ras,
    )

    hdf = dest / f"{ras.project_name}.p{plan}.hdf"
    assert hdf.is_file(), "HEC-RAS wrote no plan results"
    messages = HdfResultsPlan.get_compute_messages(hdf) or ""
    assert "Error processing event conditions" not in messages
    assert bool(result), messages[-2000:]

    # One hour at 1 in/hr: native cumulative precipitation reaches 1 in.
    import h5py

    series = (
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
        "2D Flow Areas/BaldEagleCr/Cell Cumulative Precipitation Depth"
    )
    with h5py.File(hdf, "r") as results:
        precip = results["Event Conditions/Meteorology/Precipitation"].attrs
        assert precip["Mode"].decode() == "Constant"
        assert float(results[series][-1].max()) == pytest.approx(1.0, abs=1e-3)
