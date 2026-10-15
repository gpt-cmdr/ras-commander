"""Keep a comparison solve from invalidating freshly prepared geometry."""

import pytest

from ras_commander import RasCmdr
from scripts.qualification.native_gdal_windows_versions import (
    _compute_preprocessed_plan,
)


@pytest.mark.parametrize("complete_geometry", [False, True])
def test_compute_retains_preprocessed_geometry_unless_rebuild_requested(
    monkeypatch, complete_geometry
):
    calls = []
    project = object()
    expected = object()

    def compute(plan, **kwargs):
        calls.append((plan, kwargs))
        return expected

    monkeypatch.setattr(RasCmdr, "compute_plan", compute)
    result = _compute_preprocessed_plan(
        project,
        cores=1,
        timeout=300,
        complete_geometry=complete_geometry,
        disable_omp_affinity=True,
    )

    assert result is expected
    assert calls == [
        (
            "06",
            {
                "ras_object": project,
                "num_cores": 1,
                "clear_geompre": complete_geometry,
                "force_geompre": complete_geometry,
                "force_rerun": True,
                "verify": True,
                "max_runtime": 300,
                "disable_omp_affinity": True,
            },
        )
    ]
