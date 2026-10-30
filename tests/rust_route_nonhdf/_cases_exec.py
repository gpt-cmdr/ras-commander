"""ROUTE-NONHDF cases: execution-side modules (RasCmdr, RasPreprocess, RasProcess,
RasApptainer, _container_compute, ExecutionEvidence, remote.PortableExecution,
RasControl, RasFlowOptimization, RasCalibrate, _preprocess_validation).

Their public entry points run HEC-RAS (Windows, Linux, Apptainer, containers) or
RasProcess.exe, so the cases call the read helpers those entry points use, on the
real fixture HDFs, and name the public function in ``helper``. The fixture files are
opened read-only; a helper that takes an open handle receives one opened here.
"""
from contextlib import contextmanager
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import h5py

from ._case import Case

PLAN = {"plan"}
ANY_RAS = {"plan", "geom"}


@contextmanager
def _open(path):
    with h5py.File(path, "r") as hdf:
        yield hdf


def _with_handle(func, *args):
    def call(path):
        with _open(path) as hdf:
            return func(hdf, *args)
    return call


# ------------------------------------------------------------------ module accessors
def _cmdr():
    from ras_commander.RasCmdr import RasCmdr
    return RasCmdr


def _pv():
    return importlib.import_module("ras_commander._preprocess_validation")


def _pre():
    from ras_commander.RasPreprocess import RasPreprocess
    return RasPreprocess


def _app():
    return importlib.import_module("ras_commander.RasApptainer")


def _cc():
    return importlib.import_module("ras_commander._container_compute")


def _ee():
    return importlib.import_module("ras_commander.ExecutionEvidence")


def _pe():
    return importlib.import_module("ras_commander.remote.PortableExecution")


def _proc():
    from ras_commander.RasProcess import RasProcess
    return RasProcess


def _ctrl():
    from ras_commander.RasControl import RasControl
    return RasControl


def _flow():
    from ras_commander.RasFlowOptimization import RasFlowOptimization
    return RasFlowOptimization


def _cal():
    return importlib.import_module("ras_commander.RasCalibrate")


# ------------------------------------------------------------------ case helpers
def _event_conditions(path):
    with _open(path) as hdf:
        return (_pv()._event_condition_errors(hdf), _pv()._hdf_ras_major_version(hdf),
                _pv()._event_condition_errors(hdf, "gridded"))


def _layout(layout, arguments, version):
    profile = SimpleNamespace(layout=layout, arguments=arguments, ras_version=version)
    return lambda p: _app()._check_layout_matches_hdf(Path(p), profile)


def _validate_result(path):
    """``_validate_result`` after the solver-log gate (patched: no solver log exists)."""
    cc = _cc()
    from ras_commander.hdf.HdfUtils import HdfUtils
    with _open(path) as hdf:  # harness: derive the simulation window from the stamps
        base = hdf.get(cc.TIME_SERIES)
        stamps = None if base is None else base.get("Time Date Stamp")
        if stamps is None or not len(stamps):
            window = None
        else:
            text = [cc._text(v) for v in stamps[:]]
            window = (HdfUtils.parse_ras_datetime(text[0]), HdfUtils.parse_ras_datetime(text[-1]))
    meshes = cc._mesh(path, property_tables=False)
    if window is None:
        return ("no-window", meshes)
    with mock.patch.object(_cmdr(), "_validate_linux_solve", lambda *a, **k: (True, "ok")):
        return cc._validate_result(path, None, "01", meshes, window, property_tables=False)


def _prepared_tmp(path):
    """``_prepared_window`` on a HEC-RAS-written ``*.p##.tmp.hdf`` (classified ``sidecar``)."""
    if not Path(path).name.lower().endswith(".tmp.hdf"):
        import pytest
        pytest.skip("not a prepared *.tmp.hdf")
    return _cc()._prepared_window(path)


def _plan_info(func):
    def call(path):
        with _open(path) as hdf:
            info = hdf.get("Plan Data/Plan Information")
            return None if info is None else func(info)
    return call


def _flow_frames(path):
    """``_dataset_to_dataframe`` on fixed real datasets (2-D numeric, 1-D, compound)."""
    names = ("Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time",
             "Geometry/Cross Sections/Attributes", "Geometry/2D Flow Areas/Attributes",
             "Geometry/Cross Sections/Station Elevation Info")
    out = {}
    with _open(path) as hdf:
        for name in names:
            if name in hdf:
                out[name] = _flow()._dataset_to_dataframe(hdf[name])
    return out


CASES = {
    "RasCmdr._tmp_hdf_ras_release": Case(
        lambda p: _cmdr()._tmp_hdf_ras_release(p), kinds=ANY_RAS,
        helper="RasCmdr.compute_plan_linux / RasCmdr._select_linux_solver_arguments"),
    "_preprocess_validation.event_conditions": Case(
        _event_conditions, kinds=ANY_RAS,
        helper="RasPreprocess.preprocess_plan / RasApptainer.check_solver_ready"),
    "RasPreprocess._read_event_condition_errors": Case(
        lambda p: _pre()._read_event_condition_errors(Path(p), None), kinds=ANY_RAS,
        helper="RasPreprocess.preprocess_plan"),
    "RasPreprocess._validate_materialized_gridded_precipitation": Case(
        lambda p: _pre()._validate_materialized_gridded_precipitation(Path(p)), kinds=ANY_RAS,
        helper="RasPreprocess.preprocess_plan (gridded precipitation)"),
    "RasApptainer.check_solver_ready": Case(
        lambda p: _app().check_solver_ready(p), kinds=ANY_RAS),
    "RasApptainer.check_solver_ready[geom_preprocess]": Case(
        lambda p: _app().check_solver_ready(p, geom_preprocess=True), kinds=PLAN),
    "RasApptainer._check_layout_matches_hdf[canonical]": Case(
        _layout("canonical", "tmphdf", "6.6"), kinds=ANY_RAS, helper="RasApptainer.render_job"),
    "RasApptainer._check_layout_matches_hdf[bin_ras]": Case(
        _layout("bin_ras", "cfile", "5.0.7"), kinds=PLAN, helper="RasApptainer.render_job"),
    "RasApptainer._gridded_dss_dependency": Case(
        lambda p: _app()._gridded_dss_dependency(Path(p)), kinds=ANY_RAS, helper="RasApptainer.render_job"),
    "RasApptainer._expected_simulation_end": Case(
        lambda p: _app()._expected_simulation_end(Path(p)), kinds=ANY_RAS, helper="RasApptainer.render_job"),
    "_container_compute._mesh": Case(
        lambda p: _cc()._mesh(p), kinds=ANY_RAS, helper="_container_compute.run_compute / prepare"),
    "_container_compute._mesh[cfile]": Case(
        lambda p: _cc()._mesh(p, property_tables=False), kinds=PLAN, helper="_container_compute.run_compute"),
    "_container_compute._prepared_window": Case(
        lambda p: _cc()._prepared_window(p), kinds=ANY_RAS, helper="_container_compute.run_compute",
        note="plan/geom fixtures carry /Results or lack Plan Information: error paths only"),
    "_container_compute._prepared_window[tmp]": Case(
        _prepared_tmp, kinds={"sidecar"}, helper="_container_compute.run_compute",
        note="prepared *.p##.tmp.hdf: reads Simulation Start/End Time"),
    "_container_compute._validate_result": Case(
        _validate_result, kinds=PLAN, helper="_container_compute.run_compute"),
    "ExecutionEvidence._observed_hdf_version": Case(
        _with_handle(lambda h: _ee()._observed_hdf_version(h)), kinds=ANY_RAS,
        helper="ExecutionEvidence.inspect_execution_evidence"),
    "ExecutionEvidence._structured_runtime_seconds": Case(
        _with_handle(lambda h: _ee()._structured_runtime_seconds(h)), kinds=ANY_RAS,
        helper="ExecutionEvidence.inspect_execution_evidence"),
    "ExecutionEvidence._hdf_window": Case(
        _plan_info(lambda info: _ee()._hdf_window(info)), kinds=ANY_RAS,
        helper="ExecutionEvidence.inspect_execution_evidence"),
    "PortableExecution._hdf_content_digest": Case(
        lambda p: _pe()._hdf_content_digest(Path(p)), kinds={"plan", "geom", "sidecar", "unsteady"},
        max_mb=150, note="whole-file digest; bounded for suite time",
        helper="PortableExecution.run_portable_plan (result fingerprint)"),
    "PortableExecution.validate_unsteady_results": Case(
        lambda p: _pe().validate_unsteady_results(p, Path(p).with_suffix(".absent-u"), Path(p).with_suffix(".absent-p")),
        kinds=PLAN),
    "RasProcess._hdf_has_wet_maximum_depth": Case(
        lambda p: _proc()._hdf_has_wet_maximum_depth(p), kinds=PLAN,
        helper="RasProcess.store_maps (all-NoData depth audit)"),
    "RasProcess._get_plan_short_id": Case(
        lambda p: _proc()._get_plan_short_id(p), kinds=ANY_RAS, helper="RasProcess.store_maps"),
    "RasControl._read_hdf_comp_msgs": Case(
        lambda p: _ctrl()._read_hdf_comp_msgs(Path(p)), kinds=PLAN, helper="RasControl.get_comp_msgs"),
    "RasFlowOptimization._extract_trial_results_from_hdf": Case(
        lambda p: _flow()._extract_trial_results_from_hdf(Path(p)), kinds=PLAN,
        helper="RasFlowOptimization.run_flow_optimization"),
    "RasFlowOptimization._read_compute_messages": Case(
        lambda p: _flow()._read_compute_messages(None, Path(p)), kinds=PLAN,
        helper="RasFlowOptimization.run_flow_optimization"),
    "RasFlowOptimization._dataset_to_dataframe": Case(
        _flow_frames, kinds=ANY_RAS, helper="RasFlowOptimization.run_flow_optimization"),
    "RasCalibrate._get_reference_dataset[lines]": Case(
        lambda p: _cal()._get_reference_dataset(Path(p), "lines"), kinds=PLAN,
        helper="RasCalibrate.calibrate (reference line targets)"),
    "RasCalibrate._get_reference_dataset[points]": Case(
        lambda p: _cal()._get_reference_dataset(Path(p), "points"), kinds=PLAN,
        helper="RasCalibrate.calibrate (reference point targets)"),
}
