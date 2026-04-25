"""Tests for HDF output option helpers in RasPlan."""

from pathlib import Path

from ras_commander.RasPlan import RasPlan


class _DummyRas:
    def check_initialized(self):
        return None


def _write_plan(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Plan Title=HDF Test",
                "Program Version=6.60",
                "Geom File=g01",
                "Flow File=u01",
                "HDF Write Warmup=0",
                "HDF Compression= 9 ",
                "HDF Chunk Size= 4 ",
                "HDF Spatial Parts= 1",
                "HDF Use Max Rows=-1",
                "HDF Fixed Rows= 1 ",
                "Calibration Method= 0 ",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_set_and_get_hdf_output_options(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    assert RasPlan.set_hdf_output_options(
        plan_path,
        write_warmup=True,
        write_time_slices=False,
        hdf_flush=False,
        compression=4,
        chunk_size_mb=2,
        spatial_parts=1,
        use_max_rows=True,
        fixed_rows=1,
        ras_object=_DummyRas(),
    )

    options = RasPlan.get_hdf_output_options(plan_path, ras_object=_DummyRas())

    assert options["write_warmup"] is True
    assert options["write_time_slices"] is False
    assert options["hdf_flush"] is False
    assert options["compression"] == 4
    assert options["chunk_size_mb"] == 2
    assert options["use_max_rows"] is True


def test_enable_disable_hdf_output_variable(tmp_path):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    ras_obj = _DummyRas()

    assert RasPlan.enable_hdf_output_variable(
        plan_path,
        "Face Flow",
        ras_object=ras_obj,
    )
    assert RasPlan.get_hdf_output_variables(plan_path, ras_object=ras_obj) == [
        "Face Flow"
    ]

    assert RasPlan.disable_hdf_output_variable(
        plan_path,
        "Face Flow",
        ras_object=ras_obj,
    )
    assert RasPlan.get_hdf_output_variables(plan_path, ras_object=ras_obj) == []


def test_apply_hdf_output_profile_adds_missing_options_before_calibration(tmp_path):
    plan_path = tmp_path / "Project.p01"
    plan_path.write_text(
        "Plan Title=HDF Test\n"
        "Program Version=6.60\n"
        "HDF Additional Output Variable=Face Flow\n"
        "Calibration Method= 0 \n",
        encoding="utf-8",
    )

    assert RasPlan.apply_hdf_output_profile(
        plan_path,
        profile="balanced",
        additional_variables=["Face Shear Stress"],
        ras_object=_DummyRas(),
    )

    content = plan_path.read_text(encoding="utf-8")
    assert "HDF Compression= 4 " in content
    assert "HDF Chunk Size= 4 " in content
    assert "HDF Additional Output Variable=Face Flow\n" in content
    assert "HDF Additional Output Variable=Face Shear Stress\n" in content
    assert content.index("HDF Compression= 4 ") < content.index("Calibration Method=")
