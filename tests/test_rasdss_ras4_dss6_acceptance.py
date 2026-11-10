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
3. ``test_dss6_merge_extend_acceptance_pending_p66``: the merge/extend cases wait for
   the engine's DSS6 regular time-series merge/extend (P66) and are skipped until then.

Tests skip cleanly without the selected HEC-RAS 4.x install, its example archive, the
archive's ``7za.exe``, an accepted TCU, or ras-commander-fast-dss with writers. The TCU is
never accepted here; acceptance changes the registry and is left to the qualification
operator (``RasTcu.accept``).

``RAS4_DSS_ACCEPTANCE_VERSIONS`` selects versions (default ``4.1,4.0``).
``RAS4_DSS_ACCEPTANCE_PLANS`` selects plans (default ``04``; ``04,05,06,08`` covers every
plan whose unsteady file reads DSS). ``RAS4_DSS_ACCEPTANCE_EVIDENCE`` names a folder for a
JSON record of each comparison.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
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
def _native_backend():
    """Native backend whatever RAS_COMMANDER_DSS_BACKEND says, restored afterwards."""
    previous_env = os.environ.pop(_backend.ENV_VAR, None)
    previous_attr = RasDss.backend
    RasDss.backend = "native"
    try:
        yield
    finally:
        RasDss.backend = previous_attr
        if previous_env is not None:
            os.environ[_backend.ENV_VAR] = previous_env


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
            "native_dss": native_dss, "paths": paths, "records": records}


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


def _run(folder: Path, version: str, plan: str) -> Dict:
    from ras_commander import RasControl

    ras = RasPrj()
    init_ras_project(folder, version, ras_object=ras, load_results_summary=False, hide_intro=True)
    status = RasTcu.status(ras_object=ras)
    if status.accepted is not True:
        pytest.skip(
            f"HEC-RAS {version} TCU is not accepted ({status.reason}). Acceptance changes the "
            "registry, so this test leaves it to the qualification operator."
        )
    result = RasControl.run_plan(plan, ras_object=ras, force_recompute=True, strict_close=True,
                                 max_runtime=3600)
    assert result.success, list(result.messages)[-20:]
    messages = RasControl.get_comp_msgs(plan, ras_object=ras) or ""
    return {
        "bfile": _normalized((folder / f"{PROJECT}.b{plan}").read_text(errors="replace"), folder, False),
        "messages": _normalized(messages, folder, True),
        "results": RasControl.get_unsteady_results(plan, ras_object=ras),
    }


@pytest.mark.parametrize("plan", _plans())
@pytest.mark.integration
@pytest.mark.real_ras
@pytest.mark.destructive_copy
@pytest.mark.slow
def test_ras4_reads_native_dss6_boundaries_like_hec_dss(bench, plan):
    version, root = bench["version"], bench["root"]
    hec = _run(_stage(bench["source"], bench["hec_dss"], root / f"hec_p{plan}"), version, plan)
    native = _run(_stage(bench["source"], bench["native_dss"], root / f"native_p{plan}"), version, plan)

    # Boundary hydrographs as HEC-RAS read them from DSS and passed to its solver.
    assert native["bfile"] == hec["bfile"]
    assert any("Hydrograph" in line for line in hec["bfile"])
    # Computation messages, timing lines removed.
    assert native["messages"] == hec["messages"]
    # Results at every cross section and output time, including the Max WS rows.
    left, right = hec["results"], native["results"]
    keys = ["river", "reach", "node_id", "time_string"]
    assert len(left) > 0 and left[keys].equals(right[keys])
    numeric = [c for c in left.columns if pd.api.types.is_float_dtype(left[c])]
    for column in numeric:
        np.testing.assert_array_equal(right[column].to_numpy(), left[column].to_numpy(), err_msg=column)
    _record(f"run_{version}_p{plan}", {
        "version": version, "plan": plan, "bfile_lines": len(hec["bfile"]),
        "message_lines": len(hec["messages"]), "result_rows": len(left),
        "cross_sections": int(left["node_id"].nunique()), "times": int(left["time_string"].nunique()),
    })


#: DSS6 merge/extend acceptance cases that wait for P66 (DSS6 regular time-series
#: merge/extend into existing blocks with heclib store semantics).
PENDING_P66 = {
    "partial_block_overlap": "replace part of an existing month block in a copy of the HEC file",
    "extend_across_block_boundary": "extend an existing series past its month block into the next block",
    "missing_values": "merge a window containing -901/NaN over stored values",
    "float_into_double": "merge float values into an existing RTD (double) record",
    "double_into_float": "merge double values into an existing RTS (float) record",
}


@pytest.mark.parametrize("case", sorted(PENDING_P66))
def test_dss6_merge_extend_acceptance_pending_p66(case):
    pytest.skip(f"pending P66 (DSS6 merge/extend): {PENDING_P66[case]}")
