from types import SimpleNamespace

import pandas as pd

import scripts.ebfe_geometry_preprocessor_batch as preprocessor_batch
from scripts.ebfe_geometry_preprocessor_batch import (
    backup_result_hdf,
    run_project,
    restore_result_hdf,
)


def test_backup_and_restore_result_hdf(tmp_path):
    result_hdf = tmp_path / "Model.p01.hdf"
    result_hdf.write_bytes(b"delivered result")

    backup_path = backup_result_hdf(result_hdf, tmp_path / "reports", "Model", "01")
    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.read_bytes() == b"delivered result"

    result_hdf.unlink()
    assert restore_result_hdf(result_hdf, backup_path)

    assert result_hdf.read_bytes() == b"delivered result"
    assert not backup_path.exists()


def test_restore_result_hdf_noops_without_backup(tmp_path):
    result_hdf = tmp_path / "Model.p01.hdf"

    assert not restore_result_hdf(result_hdf, None)
    assert not result_hdf.exists()


def test_run_project_records_exception_and_restores_result_hdf(tmp_path, monkeypatch):
    result_hdf = tmp_path / "Model.p01.hdf"
    result_hdf.write_bytes(b"delivered result")

    class FakeRasPrj:
        def __init__(self):
            self.project_folder = tmp_path
            self.project_name = "Model"
            self.plan_df = pd.DataFrame(
                [
                    {
                        "plan_number": "01",
                        "geometry_number": "01",
                        "HDF_Results_Path": str(result_hdf),
                    }
                ]
            )

    monkeypatch.setattr(preprocessor_batch, "RasPrj", FakeRasPrj)
    monkeypatch.setattr(preprocessor_batch, "init_ras_project", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        preprocessor_batch.GeomPreprocessor,
        "run_geometry_preprocessor",
        staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    args = SimpleNamespace(
        ras_version=None,
        plan_strategy="one-per-geometry",
        plan="01",
        dry_run=False,
        output_dir=tmp_path / "reports",
        preserve_result_hdf=True,
        max_wait=1,
        no_force=False,
        clear_geompre=False,
        run_until_flow_start=False,
        stop_on_failure=False,
    )

    record = run_project(
        "spring-river",
        {"folder": tmp_path, "project_name": "Model"},
        args,
    )

    assert record["status"] == "failed"
    assert record["plans"][0]["error"] == "boom"
    assert record["plans"][0]["restored_result_hdf"] is True
    assert result_hdf.read_bytes() == b"delivered result"
