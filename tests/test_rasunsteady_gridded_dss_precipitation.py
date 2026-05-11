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
