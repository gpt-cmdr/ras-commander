import importlib
import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ras_commander.RasPermutation import RasPermutation


def test_define_parameters_count_is_debug_not_info(caplog) -> None:
    params = {"channel_n": [0.03, 0.04]}

    with caplog.at_level(logging.INFO, logger="ras_commander.RasPermutation"):
        result = RasPermutation.define_parameters(params)

    assert len(result) == 2
    assert not any(
        "Defined 2 total permutation(s)" in record.getMessage()
        for record in caplog.records
    )

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasPermutation"):
        RasPermutation.define_parameters(params)

    assert any(
        record.levelno == logging.DEBUG
        and "Defined 2 total permutation(s)" in record.getMessage()
        for record in caplog.records
    )


def test_execute_and_summarize_uses_quiet_batch_init_and_summary(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    rasprj_module = importlib.import_module("ras_commander.RasPrj")
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    batch_folder = tmp_path / "Project_perms_001"
    batch_folder.mkdir()
    master_log_path = tmp_path / "Project_perms_master_log.csv"
    hdf_path = batch_folder / "Project.p02.hdf"
    hdf_path.touch()

    pd.DataFrame(
        {
            "absolute_perm_id": [1],
            "batch_folder": [batch_folder.name],
            "batch_index": [1],
            "plan_number": ["02"],
            "short_id": ["P00001"],
            "plan_title": ["Permutation 1"],
        }
    ).to_csv(master_log_path, index=False)

    pd.DataFrame(
        {
            "absolute_perm_id": [1],
            "plan_number": ["02"],
            "plan_title": ["Permutation 1"],
        }
    ).to_csv(batch_folder / "permutations_log.csv", index=False)

    init_calls = []

    def fake_init_ras_project(
        project_folder,
        ras_exe_path,
        ras_object=None,
        **kwargs,
    ):
        init_calls.append(
            {
                "project_folder": Path(project_folder),
                "ras_exe_path": ras_exe_path,
                **kwargs,
            }
        )
        return ras_object

    class FakeComputeResult:
        execution_results = {"02": True}
        results_df = pd.DataFrame(
            {
                "plan_number": ["02"],
                "completed": [True],
                "has_errors": [False],
                "hdf_exists": [True],
                "runtime_complete_process_hours": [0.25],
                "hdf_path": [str(hdf_path)],
            }
        )

    def fake_compute_parallel(**kwargs):
        return FakeComputeResult()

    monkeypatch.setattr(
        rasprj_module,
        "init_ras_project",
        fake_init_ras_project,
    )
    monkeypatch.setattr(
        rascmdr_module.RasCmdr,
        "compute_parallel",
        staticmethod(fake_compute_parallel),
    )
    monkeypatch.setattr(
        RasPermutation,
        "_extract_max_wse",
        staticmethod(lambda hdf, ras_object=None: 123.4),
    )

    plan_matrix = {
        "master_log": master_log_path,
        "batch_folders": [batch_folder],
    }
    source_ras = SimpleNamespace(ras_exe_path="Ras.exe")

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasPermutation"):
        result = RasPermutation.execute_and_summarize(
            plan_matrix,
            max_workers=2,
            num_cores=1,
            ras_object=source_ras,
        )

    assert init_calls == [
        {
            "project_folder": batch_folder,
            "ras_exe_path": "Ras.exe",
            "load_results_summary": False,
            "hide_intro": True,
        }
    ]
    assert result.loc[0, "status"] == "completed"
    assert result.loc[0, "max_wse"] == 123.4

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == [
        "Executed and summarized 1 permutation(s): completed=1"
    ]
    assert any(str(master_log_path) in message for message in debug_messages)
