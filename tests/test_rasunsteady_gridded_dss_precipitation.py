"""Tests for gridded DSS precipitation .u## configuration."""

from pathlib import Path

import pytest

h5py = pytest.importorskip("h5py")


BALD_EAGLE_DSS_PATHNAME = (
    "/SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/"
)


def _write_unsteady_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_hdf_failure_does_not_advertise_new_dss_configuration(tmp_path, monkeypatch):
    from ras_commander import RasUnsteady

    path = _write_unsteady_file(tmp_path / "Model.u01", "Flow Title=Rain\nProgram Version=6.60\n")
    before = path.read_bytes()

    def locked_hdf(**kwargs):
        raise PermissionError("HDF locked by another application")

    monkeypatch.setattr(RasUnsteady, "_update_gridded_dss_precipitation_hdf", locked_hdf)
    with pytest.raises(PermissionError, match="HDF locked"):
        RasUnsteady.configure_gridded_dss_precipitation(path, "rain.dss", "/A/B/PRECIP///F/", ratio=1.0)
    assert path.read_bytes() == before


def test_configures_official_baldeagle_gridded_dss_structure_and_round_trips(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "BaldEagleDamBrk.u03",
        """Flow Title=Gridded Precipitation
Program Version=6.60
Use Restart= 0
Precipitation Mode=Disable
Met BC=Precipitation|Mode=Constant
Met BC=Precipitation|Gridded Source=GDAL Raster File(s)
Met BC=Precipitation|Gridded Interpolation=Bilinear
Met BC=Precipitation|Gridded GDAL Filename=.\\Precipitation\\old.nc
Met BC=Precipitation|Gridded GDAL Group=old_group
Met BC=Precipitation|Gridded GDAL Datasetname=legacy_group
Met BC=Precipitation|Gridded GDAL Folder=.\\Precipitation
Met BC=Precipitation|Gridded GDAL Filter=*.nc
Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,                                ,
""",
    )

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file=unsteady_file,
        dss_filename=".\\Precipitation\\precip.2018.09.dss",
        dss_pathname=BALD_EAGLE_DSS_PATHNAME,
    )

    lines = unsteady_file.read_text(encoding="utf-8").splitlines()
    expected_block = [
        "Precipitation Mode=Enable",
        "Met BC=Precipitation|Mode=Gridded",
        "Met BC=Precipitation|Gridded Source=DSS",
        "Met BC=Precipitation|Gridded DSS Filename=.\\Precipitation\\precip.2018.09.dss",
        f"Met BC=Precipitation|Gridded DSS Pathname={BALD_EAGLE_DSS_PATHNAME}",
    ]
    start_idx = lines.index("Precipitation Mode=Enable")
    assert lines[start_idx:start_idx + len(expected_block)] == expected_block
    assert not any("Gridded GDAL" in line for line in lines)
    assert not any("Gridded Interpolation=" in line for line in lines)

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["precipitation_mode"] == "Enable"
    assert config["mode"] == "Gridded"
    assert config["source"] == "DSS"
    assert config["dss_filename"] == ".\\Precipitation\\precip.2018.09.dss"
    assert config["dss_pathname"] == BALD_EAGLE_DSS_PATHNAME

    hdf_attrs = config["hdf_attributes"]
    assert hdf_attrs["Mode"] == "Gridded"
    assert hdf_attrs["Source"] == "DSS"
    assert hdf_attrs["DSS Filename"] == ".\\Precipitation\\precip.2018.09.dss"
    assert hdf_attrs["DSS Pathname"] == BALD_EAGLE_DSS_PATHNAME
    assert "Interpolation Method" not in hdf_attrs


def test_configure_gridded_dss_creates_met_bc_section_for_minimal_file(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "minimal.u01",
        """Flow Title=Minimal
Program Version=6.60
""",
    )

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file=unsteady_file,
        dss_filename="Precipitation/precip.dss",
        dss_pathname="/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/VORTEX/",
        interpolation="Nearest",
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["mode"] == "Gridded"
    assert config["source"] == "DSS"
    assert config["interpolation"] == "Nearest"
    assert config["dss_filename"] == ".\\Precipitation\\precip.dss"
    assert config["hdf_attributes"]["Interpolation Method"] == "Nearest"


def test_absolute_dss_path_inside_unsteady_folder_is_written_relative(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "absolute_inside.u01",
        "Flow Title=Absolute Inside\nProgram Version=6.60\n",
    )
    absolute_dss = tmp_path / "Precipitation" / "precip.dss"

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file=unsteady_file,
        dss_filename=str(absolute_dss),
        dss_pathname=BALD_EAGLE_DSS_PATHNAME,
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["dss_filename"] == ".\\Precipitation\\precip.dss"
    assert config["hdf_attributes"]["DSS Filename"] == ".\\Precipitation\\precip.dss"


def test_absolute_dss_path_outside_unsteady_folder_is_preserved(tmp_path):
    from ras_commander import RasUnsteady

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    unsteady_file = _write_unsteady_file(
        project_dir / "absolute_outside.u01",
        "Flow Title=Absolute Outside\nProgram Version=6.60\n",
    )
    absolute_dss = tmp_path / "external_precip.dss"

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file=unsteady_file,
        dss_filename=str(absolute_dss),
        dss_pathname=BALD_EAGLE_DSS_PATHNAME,
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["dss_filename"] == str(absolute_dss)
    assert config["hdf_attributes"]["DSS Filename"] == str(absolute_dss)


def test_configure_gridded_dss_accepts_string_and_safe_resolves_project_path(
    tmp_path, monkeypatch
):
    from ras_commander import RasUnsteady, RasUtils

    unsteady_file = _write_unsteady_file(
        tmp_path / "mapped_drive.u01",
        "Flow Title=Mapped Drive\nProgram Version=6.60\n",
    )
    resolved = []

    def tracked_safe_resolve(path):
        resolved.append(Path(path))
        return Path(path)

    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(tracked_safe_resolve))

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file=str(unsteady_file),
        dss_filename="Precipitation/precip.dss",
        dss_pathname=BALD_EAGLE_DSS_PATHNAME,
    )

    assert resolved == [unsteady_file]
    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["dss_filename"] == ".\\Precipitation\\precip.dss"


def test_invalid_gridded_dss_interpolation_raises(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "invalid_interpolation.u01",
        "Flow Title=Invalid\nProgram Version=6.60\n",
    )

    with pytest.raises(ValueError, match="interpolation"):
        RasUnsteady.configure_gridded_dss_precipitation(
            unsteady_file=unsteady_file,
            dss_filename="Precipitation/precip.dss",
            dss_pathname=BALD_EAGLE_DSS_PATHNAME,
            interpolation="Kriging",
        )


def test_hec_ras_61_rejects_retained_dss_ratio_before_mutation(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "ratio.u01",
        "Flow Title=Ratio\n"
        "Program Version=6.10\n"
        "Met BC=Precipitation|Ratio=1.25\n",
    )
    before = unsteady_file.read_bytes()

    with pytest.raises(ValueError, match="does not apply that ratio"):
        RasUnsteady.configure_gridded_dss_precipitation(
            unsteady_file,
            "rain.dss",
            BALD_EAGLE_DSS_PATHNAME,
        )

    assert unsteady_file.read_bytes() == before
    assert not Path(str(unsteady_file) + ".hdf").exists()


def test_hec_ras_61_explicit_unit_dss_ratio_clears_retained_value(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_file = _write_unsteady_file(
        tmp_path / "ratio.u01",
        "Flow Title=Ratio\n"
        "Program Version=6.10\n"
        "Met BC=Precipitation|Ratio=1.25\n",
    )

    RasUnsteady.configure_gridded_dss_precipitation(
        unsteady_file,
        "rain.dss",
        BALD_EAGLE_DSS_PATHNAME,
        ratio=1.0,
    )

    text = unsteady_file.read_text(encoding="utf-8")
    assert text.count("Met BC=Precipitation|Ratio=") == 1
    assert "Met BC=Precipitation|Ratio=1\n" in text
    with h5py.File(Path(str(unsteady_file) + ".hdf"), "r") as hdf:
        ratio = hdf["Event Conditions/Meteorology/Precipitation"].attrs["Ratio"]
        assert ratio == pytest.approx(1.0)
