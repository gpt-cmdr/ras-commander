"""HEC-RAS 4.x acceptance of 1D boundary DSS6 files written by the native engine (D67).

The model and its HEC-written DSS6 boundary file come from HEC's public example archive
that ships inside the HEC-RAS 4.0 and 4.1 installers
(``<install>/Example Projects/Example Projects.7z``, ``Unsteady Examples``). Every DSS
boundary of the ``BaldEagleDamBrk`` unsteady plans is rewritten through
``RasDss.write_timeseries`` on the ``native`` backend into a new DSS6 file. HEC-RAS runs
only through ``RasControl.run_plan`` on disposable copies.

1. ``test_native_dss6_rewrite_reproduces_hec_records``: the rewrite has the same blocks
   and record type (RTD) as the HEC file, and the same times, values, units and type.
   No HEC-RAS run.
2. ``test_ras4_reads_native_dss6_boundaries_like_hec_dss``: each selected plan runs once
   with the HEC file and once with the native file. The boundary data HEC-RAS writes to
   its ``.b##`` file, the computed results at every cross section and output time
   (``RasControl.get_unsteady_results``) and the computation messages must be identical.
3. ``test_native_dss6_merge_matches_hec_merge``: each DSS6 merge/extend case is made twice
   on copies of the HEC-written file, once by the native engine and once by HEC Monolith
   (the oracle). The native reader and Monolith must each read the two files identically.
   No HEC-RAS run.
4. ``test_ras4_reads_native_dss6_merge_like_hec_merge``: HEC-RAS runs a PMF plan on the
   natively merged file and on the HEC-merged file. The ``.b##`` boundary input, the
   messages and the results must be identical, and the ``.b##`` input must differ from the
   run on the unmerged file (the control: HEC-RAS read the merged values). Where HEC-RAS
   refuses to compute (missing values inside the simulation window), it must refuse both
   files in the same way.

The merge cases follow the engine's DSS6 regular merge/extend qualification (P66). The
boundary records are uncompressed doubles, so a merge keeps every stored value outside the
written window on both writers; the engine's documented exception for delta-compressed
blocks (D70) does not arise in this file.

Tests skip cleanly without the selected HEC-RAS 4.x install, its example archive, the
archive's ``7za.exe``, an accepted TCU, or ras-commander-fast-dss with writers. The merge
tests also need the Java backend (pyjnius, a JVM and HEC Monolith) for the oracle. The TCU is
never accepted here; acceptance changes the registry and is left to the qualification
operator (``RasTcu.accept``).

``RAS4_DSS_ACCEPTANCE_VERSIONS`` selects versions (default ``4.1,4.0``).
``RAS4_DSS_ACCEPTANCE_PLANS`` selects plans (default ``04``; ``04,05,06,08`` covers every
plan whose unsteady file reads DSS). ``RAS4_DSS_ACCEPTANCE_MERGE_CASES`` selects the merge
cases that run in HEC-RAS (default ``partial_block_overlap``; ``all`` runs every case,
about 35 to 42 minutes per version; ``none`` runs no merge case in HEC-RAS).
``RAS4_DSS_ACCEPTANCE_MERGE_PLANS`` selects their PMF plans (default ``04``).
``RAS4_DSS_ACCEPTANCE_EVIDENCE`` names a folder for a JSON record of each comparison.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss, RasPrj, RasTcu, get_ras_exe, init_ras_project
from ras_commander.dss import _backend

PROJECT = "BaldEagleDamBrk"
DSS_NAME = "Bald_Eagle_Creek.dss"
ARCHIVE_MEMBER_DIR = "Unsteady Examples"
#: Plans whose unsteady files read DSS: p04 (u02, g01), p05 (u03), p06 (u02, g02 breach),
#: p08 (u04, g03 storage area and breach).
DSS_PLANS = ("04", "05", "06", "08")
#: Lines of HEC-RAS messages that report elapsed time and so differ between runs.
TIMING_LINE = re.compile(
    r"(\d+\s*(sec|min|hour|hours)\b)|^(Task\s+Time)|Complete Process|Computation Speed|seconds",
    re.IGNORECASE,
)

real_ras = [
    pytest.mark.integration,
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
    pytest.mark.slow,
]


def _versions() -> List[str]:
    return [v.strip() for v in os.environ.get("RAS4_DSS_ACCEPTANCE_VERSIONS", "4.1,4.0").split(",") if v.strip()]


def _plans() -> List[str]:
    raw = os.environ.get("RAS4_DSS_ACCEPTANCE_PLANS", "04")
    plans = [p.strip().zfill(2) for p in raw.split(",") if p.strip()]
    unknown = sorted(set(plans) - set(DSS_PLANS))
    if unknown:
        raise ValueError(f"plans {unknown} do not read DSS; choose from {DSS_PLANS}")
    return plans


def _install_dir(version: str) -> Optional[Path]:
    try:
        exe = Path(str(get_ras_exe(version)))
    except Exception:
        return None
    return exe.parent if exe.is_file() else None


def _extract_example(version: str, dest: Path) -> Path:
    """Extract the model files and the HEC DSS6 file from the installer's example archive.

    Uses the ``7za.exe`` HEC ships beside ``Ras.exe``; never runs ``Ras.exe``.
    """
    install = _install_dir(version)
    if install is None:
        pytest.skip(f"HEC-RAS {version} is not installed")
    archive = install / "Example Projects" / "Example Projects.7z"
    seven_zip = install / "7za.exe"
    if not archive.is_file() or not seven_zip.is_file():
        pytest.skip(f"HEC-RAS {version} example archive or 7za.exe is missing")
    raw = dest / "_archive"
    raw.mkdir(parents=True, exist_ok=True)
    members = [f"{ARCHIVE_MEMBER_DIR}\\{PROJECT}.*", f"{ARCHIVE_MEMBER_DIR}\\{DSS_NAME}"]
    proc = subprocess.run(
        [str(seven_zip), "x", "-y", f"-o{raw}", str(archive), *members],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    source = raw / ARCHIVE_MEMBER_DIR
    assert (source / f"{PROJECT}.prj").is_file() and (source / DSS_NAME).is_file()
    return source


def _stage(source: Path, dss: Path, folder: Path) -> Path:
    """Copy the model into ``folder`` with ``dss`` as its boundary file."""
    folder.mkdir(parents=True, exist_ok=False)
    for path in source.glob(f"{PROJECT}.*"):
        shutil.copyfile(path, folder / path.name)
    shutil.copyfile(dss, folder / DSS_NAME)
    return folder


@contextmanager
def _backend_selected(name: str):
    """``name`` backend whatever RAS_COMMANDER_DSS_BACKEND says, restored afterwards."""
    previous_env = os.environ.pop(_backend.ENV_VAR, None)
    previous_attr = RasDss.backend
    RasDss.backend = name
    try:
        yield
    finally:
        RasDss.backend = previous_attr
        if previous_env is not None:
            os.environ[_backend.ENV_VAR] = previous_env


def _native_backend():
    return _backend_selected("native")


def _dss_boundary_paths(project: Path, version: str) -> List[str]:
    """Boundary pathnames (D part blank) of every unsteady file that reads DSS."""
    ras = RasPrj()
    init_ras_project(project, version, ras_object=ras, load_results_summary=False, hide_intro=True)
    bdf = ras.boundaries_df
    used = bdf[(bdf["Use DSS"].astype(str) == "True") & bdf["DSS Path"].notna()]
    assert set(used["DSS File"]) == {DSS_NAME}, set(used["DSS File"])
    paths = []
    for pathname in used["DSS Path"]:
        parts = str(pathname).strip().split("/")
        parts[4] = ""
        condensed = "/".join(parts)
        if condensed not in paths:
            paths.append(condensed)
    return paths


def _rewrite_native_dss6(hec_dss: Path, paths: List[str], target: Path) -> Dict[str, pd.DataFrame]:
    """Write every boundary record of ``hec_dss`` into a new DSS6 file on the native backend."""
    with _native_backend():
        records = {p: RasDss.read_timeseries(hec_dss, p) for p in paths}
        for pathname, df in records.items():
            RasDss.write_timeseries(
                target, pathname, df.index.values, df["value"].to_numpy(),
                units=df.attrs["units"], data_type=df.attrs["type"], dss_version=6,
            )
    return records


def _blocks(dss: Path, paths: List[str]) -> List[tuple]:
    import ras_commander_fast_dss as fast_dss

    def key(pathname: str) -> tuple:
        parts = pathname.split("/")
        return tuple(parts[i] for i in (1, 2, 3, 5, 6))

    wanted = {key(p) for p in paths}
    catalog = fast_dss.get_catalog(str(dss))
    return sorted(
        (str(p), int(t)) for p, t in zip(catalog["pathname"], catalog["record_type"]) if key(str(p)) in wanted
    )


def _require_native_writes() -> None:
    if not _backend.native_writes_available():
        pytest.skip("ras-commander-fast-dss with writers is not installed")


def _record(name: str, payload: Dict) -> None:
    folder = os.environ.get("RAS4_DSS_ACCEPTANCE_EVIDENCE")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / f"{name}.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")


@pytest.fixture(scope="module", params=_versions())
def bench(request, tmp_path_factory):
    """The extracted example, its HEC DSS6 file and the native DSS6 rewrite."""
    version = request.param
    _require_native_writes()
    root = tmp_path_factory.mktemp(f"ras4_{version.replace('.', '')}")
    source = _extract_example(version, root)
    hec_dss = source / DSS_NAME
    with _native_backend():
        assert RasDss.get_file_version(hec_dss) == 6
    paths = _dss_boundary_paths(_stage(source, hec_dss, root / "inspect"), version)
    native_dss = root / "native6.dss"
    records = _rewrite_native_dss6(hec_dss, paths, native_dss)
    return {"version": version, "root": root, "source": source, "hec_dss": hec_dss,
            "native_dss": native_dss, "paths": paths, "records": records,
            "runs": {}, "merged": {}}


def test_native_dss6_rewrite_reproduces_hec_records(bench):
    hec_dss, native_dss, paths = bench["hec_dss"], bench["native_dss"], bench["paths"]
    with _native_backend():
        assert RasDss.get_file_version(native_dss) == 6
        for pathname, original in bench["records"].items():
            rewritten = RasDss.read_timeseries(native_dss, pathname)
            assert rewritten.index.equals(original.index), pathname
            np.testing.assert_array_equal(rewritten["value"].to_numpy(), original["value"].to_numpy())
            assert rewritten.attrs["units"] == original.attrs["units"]
            assert rewritten.attrs["type"] == original.attrs["type"]
    hec_blocks, native_blocks = _blocks(hec_dss, paths), _blocks(native_dss, paths)
    assert native_blocks == hec_blocks
    assert {t for _, t in native_blocks} == {105}  # RTD, as HEC stored them
    _record(f"rewrite_{bench['version']}", {"paths": paths, "blocks": native_blocks})


def _normalized(text: str, folder: Path, drop_timing: bool) -> List[str]:
    lines = [line.replace(str(folder), "<RUN>").rstrip() for line in text.splitlines()]
    return [line for line in lines if not (drop_timing and TIMING_LINE.search(line))]


def _run(folder: Path, version: str, plan: str,
         simulation_start: Optional[datetime] = None) -> Dict:
    """Run ``plan`` in ``folder`` through ``RasControl`` and collect what is compared.

    ``simulation_start`` moves the plan's start and keeps its end. A run that HEC-RAS ends
    without writing its output returns ``{"refused": <reason>}``.
    """
    from ras_commander import RasControl, RasPlan

    ras = RasPrj()
    init_ras_project(folder, version, ras_object=ras, load_results_summary=False, hide_intro=True)
    status = RasTcu.status(ras_object=ras)
    if status.accepted is not True:
        pytest.skip(
            f"HEC-RAS {version} TCU is not accepted ({status.reason}). Acceptance changes the "
            "registry, so this test leaves it to the qualification operator."
        )
    if simulation_start is not None:
        row = ras.plan_df[ras.plan_df["plan_number"] == plan].iloc[0]
        end_date, end_time = str(row["Simulation Date"]).split(",")[2:4]
        end = pd.to_datetime(end_date, format="%d%b%Y") + pd.Timedelta(hours=int(end_time[:2]), minutes=int(end_time[2:]))
        RasPlan.update_simulation_date(plan, simulation_start, end.to_pydatetime(), ras_object=ras)
    try:
        result = RasControl.run_plan(plan, ras_object=ras, force_recompute=True, strict_close=True,
                                     max_runtime=3600)
    except RuntimeError as error:
        if "result artifact was not created" not in str(error):
            raise
        return {
            "refused": str(error).replace(str(folder), "<RUN>"),
            "bfile_written": (folder / f"{PROJECT}.b{plan}").is_file(),
        }
    assert result.success, list(result.messages)[-20:]
    messages = RasControl.get_comp_msgs(plan, ras_object=ras) or ""
    return {
        "bfile": _normalized((folder / f"{PROJECT}.b{plan}").read_text(errors="replace"), folder, False),
        "messages": _normalized(messages, folder, True),
        "results": RasControl.get_unsteady_results(plan, ras_object=ras),
    }


def _assert_runs_identical(reference: Dict, candidate: Dict) -> Dict:
    """``candidate`` gave HEC-RAS the same boundary input, messages and results."""
    assert "refused" not in reference, reference["refused"]
    assert "refused" not in candidate, candidate["refused"]
    # Boundary hydrographs as HEC-RAS read them from DSS and passed to its solver.
    assert candidate["bfile"] == reference["bfile"]
    assert any("Hydrograph" in line for line in reference["bfile"])
    # Computation messages, timing lines removed.
    assert candidate["messages"] == reference["messages"]
    # Results at every cross section and output time, including the Max WS rows.
    left, right = reference["results"], candidate["results"]
    keys = ["river", "reach", "node_id", "time_string"]
    assert len(left) > 0 and left[keys].equals(right[keys])
    numeric = [c for c in left.columns if pd.api.types.is_float_dtype(left[c])]
    for column in numeric:
        np.testing.assert_array_equal(right[column].to_numpy(), left[column].to_numpy(), err_msg=column)
    return {
        "bfile_lines": len(reference["bfile"]), "message_lines": len(reference["messages"]),
        "result_rows": len(left), "cross_sections": int(left["node_id"].nunique()),
        "times": int(left["time_string"].nunique()),
    }


def _unmerged_run(bench: Dict, plan: str) -> Dict:
    """The run on the unmerged HEC file, shared by the tests of one version."""
    key = ("hec", plan)
    if key not in bench["runs"]:
        folder = _stage(bench["source"], bench["hec_dss"], bench["root"] / f"hec_p{plan}")
        bench["runs"][key] = _run(folder, bench["version"], plan)
    return bench["runs"][key]


@pytest.mark.parametrize("plan", _plans())
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_ras4_reads_native_dss6_boundaries_like_hec_dss(bench, plan):
    version, root = bench["version"], bench["root"]
    hec = _unmerged_run(bench, plan)
    native = _run(_stage(bench["source"], bench["native_dss"], root / f"native_p{plan}"), version, plan)
    summary = _assert_runs_identical(hec, native)
    _record(f"run_{version}_p{plan}", {"version": version, "plan": plan, **summary})


# ---------------------------------------------------------------------------------------
# DSS6 merge/extend cases (engine packet P66): the native merge against the HEC merge.
# ---------------------------------------------------------------------------------------

#: PMF plans: their boundary records span 01JAN1999 00:00 to 08JAN1999 00:00 in the
#: 01DEC1998 and 01JAN1999 blocks of the HEC file.
PMF_PLANS = ("04", "06", "08")
#: Factor applied to the stored values a merge replaces, so HEC-RAS sees a changed boundary.
MERGE_FACTOR = 1.05
#: A day inside the 01JAN1999 block and inside every PMF plan's simulation window.
MERGE_WINDOW = ("1999-01-02 00:00", "1999-01-03 00:00")

#: Each case merges one window into every PMF boundary record of a copy of the base file.
#: ``window``: first and last written time. ``constant``: write the record's first stored
#: value (times the factor) instead of the stored values, for times the record lacks.
#: ``missing_from``: from this time on the written values alternate NaN and -901.
#: ``value_type``: ``float`` writes single precision. ``base``: ``hec_float`` merges into a
#: file HEC Monolith wrote as floats (RTS) instead of the HEC example file (RTD).
#: ``simulation_start``: start the plan here so HEC-RAS reads the extended part.
#: ``refused``: HEC-RAS 4.x ends the run without output; both files must be refused alike.
MERGE_CASES: Dict[str, Dict] = {
    "partial_block_overlap": {
        "what": "replace one day inside an existing month block",
        "window": MERGE_WINDOW,
    },
    "extend_across_block_boundary": {
        "what": "extend the series one day earlier, across the 01DEC1998/01JAN1999 block boundary",
        "window": ("1998-12-31 00:00", "1999-01-01 06:00"),
        "constant": True,
        "simulation_start": datetime(1998, 12, 31, 12, 0),
    },
    "missing_values": {
        "what": "merge NaN and -901 over stored values after the simulation window",
        "window": ("1999-01-04 00:00", "1999-01-06 00:00"),
        "missing_from": "1999-01-05 06:00",
    },
    "missing_values_in_simulation": {
        "what": "merge NaN and -901 over stored values inside the simulation window",
        "window": MERGE_WINDOW,
        "missing_from": "1999-01-02 12:00",
        "refused": True,
    },
    "float_into_double": {
        "what": "merge float values into an existing RTD (double) record",
        "window": MERGE_WINDOW,
        "value_type": "float",
    },
    "double_into_float": {
        "what": "merge double values into an existing RTS (float) record",
        "window": MERGE_WINDOW,
        "base": "hec_float",
    },
}


def _merge_cases() -> List[str]:
    """Merge cases that run in HEC-RAS (``RAS4_DSS_ACCEPTANCE_MERGE_CASES``)."""
    raw = os.environ.get("RAS4_DSS_ACCEPTANCE_MERGE_CASES", "partial_block_overlap").strip()
    if raw.lower() == "all":
        return sorted(MERGE_CASES)
    if raw.lower() in ("", "none"):
        return []
    cases = [c.strip() for c in raw.split(",") if c.strip()]
    unknown = sorted(set(cases) - set(MERGE_CASES))
    if unknown:
        raise ValueError(f"unknown merge cases {unknown}; choose from {sorted(MERGE_CASES)}")
    return cases


def _merge_plans() -> List[str]:
    raw = os.environ.get("RAS4_DSS_ACCEPTANCE_MERGE_PLANS", "04")
    plans = [p.strip().zfill(2) for p in raw.split(",") if p.strip()]
    unknown = sorted(set(plans) - set(PMF_PLANS))
    if unknown:
        raise ValueError(f"plans {unknown} are not PMF plans; choose from {PMF_PLANS}")
    return plans


def _require_java_backend() -> None:
    """HEC Monolith makes the oracle merges; skip without pyjnius, a JVM or Monolith."""
    try:
        RasDss._configure_jvm()
    except Exception as error:  # the oracle is unavailable, not a failure of the native writer
        pytest.skip(f"Java DSS backend (HEC Monolith) is not available: {error}")


def _monolith_put_floats(dss: Path, pathname: str, times: pd.DatetimeIndex, values: np.ndarray,
                         units: str, data_type: str, new_dss6_file: bool = False) -> None:
    """Store single-precision values through HEC Monolith.

    ``RasDss.write_timeseries`` on the Java backend always stores doubles, so the float
    oracle sets the container's store-as-doubles flag itself.
    """
    from jnius import autoclass, cast

    HecDss = autoclass("hec.heclib.dss.HecDss")
    TimeSeriesContainer = autoclass("hec.io.TimeSeriesContainer")
    HecTimeArray = autoclass("hec.heclib.util.HecTimeArray")
    hec_times = RasDss._datetimes_to_hec_times(times)
    tsc = TimeSeriesContainer()
    tsc.fullName, tsc.units, tsc.type = pathname, units, data_type
    tsc.interval = int(np.median(np.diff(hec_times)))
    tsc.setStoreAsDoubles(False)
    assert tsc.setTimes(HecTimeArray(hec_times.tolist())) == 0
    assert tsc.setValues([float(v) for v in values]) == 0
    tsc.numberValues = len(values)
    RasDss._drain_hec_messages()
    handle = HecDss.open(str(dss), 6) if new_dss6_file else HecDss.open(str(dss))
    try:
        handle.put(cast("hec.io.DataContainer", tsc))
        RasDss._raise_hec_write_failures(RasDss._drain_hec_messages())
    finally:
        handle.done()
        RasDss._release_dss_file(str(dss))


def _merge_writes(case: str, records: Dict[str, pd.DataFrame]) -> List[Dict]:
    """The writes of ``case``: one window for every PMF boundary record."""
    spec = MERGE_CASES[case]
    times = pd.date_range(*spec["window"], freq="15min")
    writes = []
    for pathname, stored in records.items():
        if stored.index[0].year != 1999:
            continue  # the 1972 records belong to plan 05
        if spec.get("constant"):
            values = np.full(len(times), stored["value"].iloc[0] * MERGE_FACTOR)
        else:
            values = stored["value"].reindex(times).to_numpy() * MERGE_FACTOR
            assert not np.isnan(values).any(), pathname
        if spec.get("missing_from"):
            missing = np.flatnonzero(times >= pd.Timestamp(spec["missing_from"]))
            values[missing[0::2]] = np.nan
            values[missing[1::2]] = -901.0
        writes.append({"pathname": pathname, "times": times, "values": values,
                       "units": stored.attrs["units"], "type": stored.attrs["type"]})
    assert writes
    return writes


def _apply_merge(writer: str, dss: Path, writes: List[Dict], value_type: str) -> None:
    """Merge ``writes`` into the existing DSS6 file ``dss`` with the native engine or HEC."""
    import ras_commander_fast_dss as fast_dss

    for w in writes:
        if value_type == "double":
            # Both writers through the public API; an existing file keeps its DSS version.
            with _backend_selected("native" if writer == "native" else "java"):
                RasDss.write_timeseries(dss, w["pathname"], w["times"], w["values"],
                                        units=w["units"], data_type=w["type"], dss_version=6)
        elif writer == "native":
            fast_dss.write_timeseries(str(dss), w["pathname"], w["values"], times=w["times"].values,
                                      units=w["units"], data_type=w["type"], version=6,
                                      value_type="float")
        else:
            _monolith_put_floats(dss, w["pathname"], w["times"], w["values"], w["units"], w["type"])


def _merged_files(bench: Dict, case: str) -> Dict:
    """Copies of the base file merged by the native engine and by HEC, made once per version."""
    if case in bench["merged"]:
        return bench["merged"][case]
    _require_java_backend()
    spec, root, records = MERGE_CASES[case], bench["root"], bench["records"]
    base = bench["hec_dss"]
    if spec.get("base") == "hec_float":
        base = root / "hec_float_base.dss"
        if not base.exists():
            for pathname, stored in records.items():
                _monolith_put_floats(base, pathname, stored.index, stored["value"].to_numpy(),
                                     stored.attrs["units"], stored.attrs["type"],
                                     new_dss6_file=not base.exists())
    writes = _merge_writes(case, records)
    files = {"base": base, "writes": writes}
    for writer in ("native", "hec"):
        files[writer] = root / f"merge_{case}_{writer}.dss"
        shutil.copyfile(base, files[writer])
        _apply_merge(writer, files[writer], writes, spec.get("value_type", "double"))
    bench["merged"][case] = files
    return files


def _read_all(backend: str, dss: Path, pathnames: List[str]) -> Dict[str, pd.DataFrame]:
    with _backend_selected(backend):
        return {p: RasDss.read_timeseries(dss, p) for p in pathnames}


@pytest.mark.parametrize("case", sorted(MERGE_CASES))
def test_native_dss6_merge_matches_hec_merge(bench, case):
    files = _merged_files(bench, case)
    spec, writes = MERGE_CASES[case], files["writes"]
    pathnames = [w["pathname"] for w in writes]
    with _native_backend():
        assert RasDss.get_file_version(files["native"]) == 6
        assert RasDss.get_file_version(files["hec"]) == 6

    # Both readers read the natively merged file as they read the HEC-merged file.
    reads = {}
    for reader in ("native", "java"):
        reads[reader] = native, hec = (_read_all(reader, files["native"], pathnames),
                                       _read_all(reader, files["hec"], pathnames))
        for pathname in pathnames:
            assert native[pathname].index.equals(hec[pathname].index), (reader, pathname)
            np.testing.assert_array_equal(native[pathname]["value"].to_numpy(),
                                          hec[pathname]["value"].to_numpy(), err_msg=f"{reader} {pathname}")
            assert native[pathname].attrs["units"] == hec[pathname].attrs["units"]
            assert native[pathname].attrs["type"] == hec[pathname].attrs["type"]
    # Same blocks and record types (RTD 105, RTS 100) in both files.
    blocks = _blocks(files["native"], pathnames)
    assert blocks == _blocks(files["hec"], pathnames)

    # The merge did what the case says: written values at the written times, every other
    # stored value unchanged, and the series covers the stored and the written times.
    base = _read_all("native", files["base"], pathnames)
    merged, merged_java = reads["native"][0], reads["java"][0]
    missing_total = 0
    mixed_precision = len({record_type for _, record_type in blocks}) > 1
    for w in writes:
        pathname, times = w["pathname"], w["times"]
        series, stored = merged[pathname]["value"], base[pathname]["value"]
        assert series.index.equals(stored.index.union(times)), pathname
        expected = np.where(w["values"] == -901.0, np.nan, w["values"])
        if spec.get("value_type") == "float":
            expected = expected.astype(np.float32).astype(np.float64)
        np.testing.assert_array_equal(series.reindex(times).to_numpy(), expected, err_msg=pathname)
        kept = stored.index.difference(times)
        np.testing.assert_array_equal(series.reindex(kept).to_numpy(), stored.reindex(kept).to_numpy())
        # Monolith agrees with the native reader wherever a value is stored. It returns a
        # series whose blocks mix floats and doubles in single precision.
        present = ~series.isna().to_numpy()
        java_values, native_values = merged_java[pathname]["value"].to_numpy()[present], series.to_numpy()[present]
        if mixed_precision:
            java_values, native_values = java_values.astype(np.float32), native_values.astype(np.float32)
        np.testing.assert_array_equal(java_values, native_values, err_msg=pathname)
        missing_total += int((~present).sum())
    assert (missing_total > 0) == bool(spec.get("missing_from"))
    _record(f"merge_{bench['version']}_{case}", {
        "case": case, "what": spec["what"], "records": len(writes), "values_per_write": len(writes[0]["times"]),
        "missing_values": missing_total, "blocks": blocks,
    })


@pytest.mark.parametrize("plan", _merge_plans())
@pytest.mark.parametrize("case", _merge_cases())
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_ras4_reads_native_dss6_merge_like_hec_merge(bench, case, plan):
    version, root, spec = bench["version"], bench["root"], MERGE_CASES[case]
    files = _merged_files(bench, case)
    start = spec.get("simulation_start")
    hec = _run(_stage(bench["source"], files["hec"], root / f"{case}_hec_p{plan}"), version, plan, start)
    native = _run(_stage(bench["source"], files["native"], root / f"{case}_native_p{plan}"), version, plan, start)

    if spec.get("refused"):
        # HEC-RAS 4.x does not compute with missing boundary values in the simulation
        # window. It must treat the native merge exactly as it treats the HEC merge.
        assert "refused" in hec and "refused" in native
        assert native == hec
        _record(f"merge_run_{version}_{case}_p{plan}", {"version": version, "case": case, "plan": plan, **hec})
        return
    summary = _assert_runs_identical(hec, native)
    # Control: HEC-RAS read the merged values, so its boundary input differs from the
    # run on the unmerged file.
    unmerged = _unmerged_run(bench, plan)["bfile"]
    changed = sum(a != b for a, b in zip(native["bfile"], unmerged)) + abs(len(native["bfile"]) - len(unmerged))
    assert changed > 0
    _record(f"merge_run_{version}_{case}_p{plan}", {
        "version": version, "case": case, "plan": plan, **summary,
        "bfile_lines_changed_from_unmerged": changed,
    })
