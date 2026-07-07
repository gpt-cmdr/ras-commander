"""Pure-Python unit tests for RasMonteCarlo statistics/sampling hardening.

These tests cover the adversarial-QA fixes that do NOT require HEC-RAS:

- H5: seeding reproducibility + global np.random state untouched.
- H3: Manning's-n physical-bounds warning.
- C3: convergence stabilization flag on a synthetic stabilizing series.
- C2: min_valid_fraction guard + completed_with_errors excluded by default.
- M1: run_ensemble-style status histogram keys (via status_histogram()).
- M3: prediction-interval labeling + n_samples_used.

No HEC-RAS is invoked. Ensemble dicts / DataFrames are synthetic and mirror
the shapes the code already uses. WSE extraction is monkeypatched so the
statistics paths run entirely in memory.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander.RasMonteCarlo import (
    RasMonteCarlo,
    _DEFAULT_MIN_VALID_FRACTION,
)


# ---------------------------------------------------------------------------
# H5 — seeding reproducibility / no global RNG mutation
# ---------------------------------------------------------------------------

PARAM_SPECS = {
    "channel_n": {"min": 0.025, "max": 0.05, "mean": 0.035, "std": 0.005},
    "overbank_n": {"min": 0.05, "max": 0.12, "mean": 0.08, "std": 0.01},
}


@pytest.mark.parametrize("method", ["uniform", "truncated_normal", "latin_hypercube"])
def test_h5_same_seed_identical_samples(method):
    a = RasMonteCarlo.generate_samples(PARAM_SPECS, n_samples=50, method=method, seed=123)
    b = RasMonteCarlo.generate_samples(PARAM_SPECS, n_samples=50, method=method, seed=123)
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.parametrize("method", ["uniform", "truncated_normal", "latin_hypercube"])
def test_h5_different_seed_differs(method):
    a = RasMonteCarlo.generate_samples(PARAM_SPECS, n_samples=50, method=method, seed=1)
    b = RasMonteCarlo.generate_samples(PARAM_SPECS, n_samples=50, method=method, seed=2)
    assert not a.drop(columns="sample_id").equals(b.drop(columns="sample_id"))


@pytest.mark.parametrize("method", ["uniform", "truncated_normal", "latin_hypercube"])
def test_h5_global_np_random_untouched(method):
    # Capture global RNG state, generate samples, confirm state unchanged.
    np.random.seed(999)
    before = np.random.get_state()
    RasMonteCarlo.generate_samples(PARAM_SPECS, n_samples=40, method=method, seed=7)
    after = np.random.get_state()
    # state tuple: (str, ndarray keys, pos, has_gauss, cached_gauss)
    assert before[0] == after[0]
    assert np.array_equal(before[1], after[1])
    assert before[2] == after[2]


# ---------------------------------------------------------------------------
# H3 — Manning's-n physical-bounds warning
# ---------------------------------------------------------------------------

def test_h3_mannings_out_of_range_warns(caplog):
    with caplog.at_level(logging.WARNING):
        RasMonteCarlo.generate_samples(
            {"n": {"min": 0.001, "max": 0.5, "kind": "mannings_n"}},
            n_samples=5,
            method="uniform",
            seed=0,
        )
    assert any("physically plausible range" in r.message for r in caplog.records)


def test_h3_negative_roughness_always_warns(caplog):
    with caplog.at_level(logging.WARNING):
        RasMonteCarlo.generate_samples(
            {"n": {"min": -0.02, "max": 0.05, "kind": "mannings_n"}},
            n_samples=5,
            method="uniform",
            seed=0,
        )
    assert any("physically impossible" in r.message for r in caplog.records)


def test_h3_in_range_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        RasMonteCarlo.generate_samples(
            {"n": {"min": 0.03, "max": 0.08, "kind": "mannings_n"}},
            n_samples=5,
            method="uniform",
            seed=0,
        )
    assert not any(
        "physically" in r.message for r in caplog.records
    )


def test_h3_no_kind_no_bounds_warning(caplog):
    # Without a kind hint, out-of-roughness-range bounds are not flagged.
    with caplog.at_level(logging.WARNING):
        RasMonteCarlo.generate_samples(
            {"flow_mult": {"min": 0.5, "max": 2.0}},
            n_samples=5,
            method="uniform",
            seed=0,
        )
    assert not any("Manning" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# C3 — convergence stabilization flag
# ---------------------------------------------------------------------------

def test_c3_stabilizing_series_flagged_converged():
    # Single column whose running mean stabilizes: values approach a constant.
    n = 60
    rng = np.random.default_rng(0)
    # decreasing noise so the running mean settles
    noise = rng.normal(0.0, 1.0, size=n) / (np.arange(1, n + 1))
    values = 100.0 + noise
    matrix = values.reshape(-1, 1)
    result = RasMonteCarlo._convergence_from_matrix(
        matrix,
        statistic_key="mean",
        window=5,
        tolerance=0.02,
        aggregate_key="mean",
        n_samples_used=n,
    )
    assert result["stabilized"] is True
    assert result["final_relative_change"] < 0.02
    assert len(result["running_statistic"]) == n
    assert result["sample_counts"][0] == 1


def test_c3_nonstabilizing_series_not_converged():
    # Running mean keeps drifting upward -> not stabilized within tolerance.
    n = 40
    values = np.arange(1, n + 1, dtype=float) * 10.0  # strong trend
    matrix = values.reshape(-1, 1)
    result = RasMonteCarlo._convergence_from_matrix(
        matrix,
        statistic_key="p90",
        window=5,
        tolerance=0.001,
        aggregate_key="mean",
        n_samples_used=n,
    )
    assert result["stabilized"] is False


# ---------------------------------------------------------------------------
# Synthetic ensemble helpers (no HEC-RAS) for C2 / M1 / M3
# ---------------------------------------------------------------------------

def _make_ensemble(statuses, hdf_exists=True, tmp_path=None):
    """Build a synthetic ensemble_result dict mirroring run_ensemble output."""
    rows = []
    for i, status in enumerate(statuses, start=1):
        if hdf_exists and tmp_path is not None:
            hdf = tmp_path / f"sample.p{i:02d}.hdf"
            hdf.write_text("stub")
            hdf_path = str(hdf)
        else:
            hdf_path = str((tmp_path or "") and f"missing_{i}.hdf") or f"missing_{i}.hdf"
        rows.append({"sample_id": i, "status": status, "hdf_path": hdf_path})
    return {"results_df": pd.DataFrame(rows), "total_samples": len(statuses)}


@pytest.fixture()
def patch_full_domain(monkeypatch):
    """Patch full-domain WSE extraction to return synthetic aligned vectors."""
    meta = pd.DataFrame({"mesh_name": ["m"] * 4, "cell_id": [0, 1, 2, 3]})

    def fake_extract(hdf_path, variable, ras_object=None):
        # Deterministic per-file values based on the plan number in the name.
        import re

        match = re.search(r"\.p(\d+)\.hdf", str(hdf_path))
        seed = int(match.group(1)) if match else 1
        vals = np.array([100.0, 101.0, 102.0, 103.0], dtype=float) + seed
        return meta.copy(), vals

    monkeypatch.setattr(
        RasMonteCarlo, "_extract_full_domain_values", staticmethod(fake_extract)
    )
    return meta


# ---------------------------------------------------------------------------
# M1 — status histogram keys
# ---------------------------------------------------------------------------

def test_m1_status_histogram_keys(tmp_path):
    ens = _make_ensemble(
        ["completed", "completed", "failed", "completed_with_errors", "incomplete"],
        tmp_path=tmp_path,
    )
    hist = RasMonteCarlo.status_histogram(ens)
    assert hist["total"] == 5
    assert hist["completed"] == 2
    assert hist["failed"] == 1
    assert hist["completed_with_errors"] == 1
    assert hist["incomplete"] == 1


# ---------------------------------------------------------------------------
# C2 — min_valid_fraction guard + completed_with_errors excluded by default
# ---------------------------------------------------------------------------

def test_c2_error_runs_excluded_by_default(tmp_path, patch_full_domain):
    # 4 completed + 1 completed_with_errors. Default excludes the error run.
    ens = _make_ensemble(
        ["completed", "completed", "completed", "completed", "completed_with_errors"],
        tmp_path=tmp_path,
    )
    out = RasMonteCarlo.exceedance_probabilities(
        ens, variable="wse", min_valid_fraction=0.0
    )
    assert out["n_samples_used"] == 4
    assert out["status_accounting"]["include_error_runs"] is False


def test_c2_error_runs_included_when_opted_in(tmp_path, patch_full_domain):
    ens = _make_ensemble(
        ["completed", "completed", "completed", "completed", "completed_with_errors"],
        tmp_path=tmp_path,
    )
    out = RasMonteCarlo.exceedance_probabilities(
        ens, variable="wse", include_error_runs=True, min_valid_fraction=0.0
    )
    assert out["n_samples_used"] == 5


def test_c2_min_valid_fraction_guard_raises(tmp_path, patch_full_domain):
    # 10 total samples but 6 failed -> only 4 usable (fraction 0.4 < 0.95).
    statuses = ["completed"] * 4 + ["failed"] * 6
    ens = _make_ensemble(statuses, tmp_path=tmp_path)
    with pytest.raises(ValueError, match="Refusing to compute statistics"):
        RasMonteCarlo.exceedance_probabilities(ens, variable="wse")


def test_c2_override_allows_low_valid_fraction(tmp_path, patch_full_domain):
    statuses = ["completed"] * 4 + ["failed"] * 6
    ens = _make_ensemble(statuses, tmp_path=tmp_path)
    out = RasMonteCarlo.exceedance_probabilities(
        ens, variable="wse", allow_low_valid_fraction=True
    )
    assert out["n_samples_used"] == 4
    assert out["status_accounting"]["valid_fraction"] == pytest.approx(0.4)


def test_c2_missing_hdf_warning_is_summarized(
    tmp_path,
    patch_full_domain,
    caplog,
):
    ens = _make_ensemble(["completed", "completed"], tmp_path=tmp_path)
    missing_path = Path(ens["results_df"].loc[1, "hdf_path"])
    missing_path.unlink()

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasMonteCarlo"):
        out = RasMonteCarlo.exceedance_probabilities(
            ens,
            variable="wse",
            min_valid_fraction=0.0,
        )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert out["n_samples_used"] == 1
    assert warning_messages == [
        "Dropping 1 sample(s) with missing HDF files during wse statistics: "
        "sample_ids=2. Enable DEBUG logging for paths."
    ]
    assert any(
        "sample 2" in message and str(missing_path) in message
        for message in debug_messages
    )


def test_c2_extraction_error_warning_is_summarized(
    tmp_path,
    monkeypatch,
    caplog,
):
    ens = _make_ensemble(["completed", "completed"], tmp_path=tmp_path)
    failed_path = Path(ens["results_df"].loc[1, "hdf_path"])
    meta = pd.DataFrame({"mesh_name": ["m"] * 4, "cell_id": [0, 1, 2, 3]})

    def fake_extract(hdf_path, variable, ras_object=None):
        if Path(hdf_path) == failed_path:
            raise RuntimeError("bad sample HDF")
        return meta.copy(), np.array([100.0, 101.0, 102.0, 103.0])

    monkeypatch.setattr(
        RasMonteCarlo,
        "_extract_full_domain_values",
        staticmethod(fake_extract),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasMonteCarlo"):
        out = RasMonteCarlo.exceedance_probabilities(
            ens,
            variable="wse",
            min_valid_fraction=0.0,
        )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert out["n_samples_used"] == 1
    assert warning_messages == [
        "Dropping 1 sample(s) during wse extraction: sample_ids=2; "
        "first error: bad sample HDF. Enable DEBUG logging for per-sample "
        "details."
    ]
    assert any(
        "sample 2" in message
        and str(failed_path) in message
        and "bad sample HDF" in message
        for message in debug_messages
    )


def test_c2_default_min_valid_fraction_value():
    assert _DEFAULT_MIN_VALID_FRACTION == 0.95


# ---------------------------------------------------------------------------
# M3 — prediction-interval labeling + n_samples_used + low-N warning
# ---------------------------------------------------------------------------

def test_m3_prediction_interval_labeling(tmp_path, patch_full_domain, caplog):
    ens = _make_ensemble(["completed"] * 6, tmp_path=tmp_path)
    with caplog.at_level(logging.WARNING):
        out = RasMonteCarlo.confidence_intervals(
            ens, variable="wse", confidence_level=0.90, min_valid_fraction=0.0
        )
    assert out["interval_type"] == "prediction"
    assert out["n_samples_used"] == 6
    # 6 samples < default min_samples_warn=30 -> warning emitted
    assert any("Prediction interval computed from only" in r.message for r in caplog.records)


def test_m3_prediction_intervals_alias(tmp_path, patch_full_domain):
    ens = _make_ensemble(["completed"] * 6, tmp_path=tmp_path)
    out = RasMonteCarlo.prediction_intervals(
        ens, variable="wse", min_valid_fraction=0.0
    )
    assert out["interval_type"] == "prediction"
    assert out["n_samples_used"] == 6


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
