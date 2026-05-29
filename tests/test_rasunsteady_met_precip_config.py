from pathlib import Path

import pytest

from ras_commander import RasUnsteady


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "research" / "fixtures" / "met_data"

BASE_CONFIG = {
    "enabled": False,
    "precipitation_mode": "",
    "mode": None,
    "source": None,
    "dss_filename": None,
    "dss_pathname": None,
    "interpolation": None,
    "constant_value": None,
    "constant_units": None,
    "gdal_filename": None,
    "gdal_group": None,
    "gdal_folder": None,
    "gdal_filter": None,
    "point_interpolation": None,
    "raw": {},
    "hdf_attributes": {},
}


DAVIS_RAW_DISABLED = {
    "Mode": "Constant",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "",
    "Gridded Source": "DSS",
    "Gridded Interpolation": "",
}

DAVIS_RAW_NONE = {
    "Mode": "None",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "Thiessen Polygon",
    "Gridded Source": "GDAL Raster File(s)",
    "Gridded Interpolation": "",
}

DAVIS_RAW_CONSTANT = {
    "Mode": "Constant",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "Thiessen Polygon",
    "Gridded Source": "GDAL Raster File(s)",
    "Gridded Interpolation": "",
}

DAVIS_RAW_POINT = {
    "Mode": "Point",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "Thiessen Polygon",
    "Gridded Source": "GDAL Raster File(s)",
    "Gridded Interpolation": "",
}

DAVIS_RAW_GRIDDED_DSS = {
    "Mode": "Gridded",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "Thiessen Polygon",
    "Gridded Source": "DSS",
    "Gridded Interpolation": "",
}

DAVIS_RAW_GRIDDED_GDAL = {
    "Mode": "Gridded",
    "Expanded View": "-1",
    "Constant Value": "1",
    "Constant Units": "in/hr",
    "Point Interpolation": "Thiessen Polygon",
    "Gridded Source": "GDAL Raster File(s)",
    "Gridded Interpolation": "",
}

BALDEAGLE_RAW = {
    "Mode": "Gridded",
    "Expanded View": "-1",
    "Constant Units": "mm/hr",
    "Point Interpolation": "",
    "Gridded Source": "DSS",
    "Gridded DSS Filename": r".\Precipitation\precip.2018.09.dss",
    "Gridded DSS Pathname": "/SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/",
}


def expected_config(**overrides):
    config = dict(BASE_CONFIG)
    config.update(overrides)
    return config


@pytest.mark.parametrize(
    "fixture_name,expected",
    [
        (
            "precip_00_disabled_official_davis.u01",
            expected_config(
                precipitation_mode="Disable",
                raw=DAVIS_RAW_DISABLED,
            ),
        ),
        (
            "precip_01_enabled_none_gui_davis.u01",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                raw=DAVIS_RAW_NONE,
            ),
        ),
        (
            "precip_02_constant_gui_davis.u01",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                mode="Constant",
                constant_value=1.0,
                constant_units="in/hr",
                raw=DAVIS_RAW_CONSTANT,
            ),
        ),
        (
            "precip_03_point_thiessen_gui_davis.u01",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                mode="Point",
                point_interpolation="Thiessen Polygon",
                raw=DAVIS_RAW_POINT,
            ),
        ),
        (
            "precip_04_gridded_dss_gui_davis.u01",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                mode="Gridded",
                source="DSS",
                interpolation="",
                raw=DAVIS_RAW_GRIDDED_DSS,
            ),
        ),
        (
            "precip_05_gridded_gdal_gui_davis.u01",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                mode="Gridded",
                source="GDAL Raster File(s)",
                interpolation="",
                raw=DAVIS_RAW_GRIDDED_GDAL,
            ),
        ),
        (
            "precip_06_gridded_dss_official_baldeagle.u03",
            expected_config(
                enabled=True,
                precipitation_mode="Enable",
                mode="Gridded",
                source="DSS",
                dss_filename=r".\Precipitation\precip.2018.09.dss",
                dss_pathname="/SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/",
                raw=BALDEAGLE_RAW,
            ),
        ),
    ],
)
def test_get_met_precipitation_config_clb673_fixtures(fixture_name, expected):
    config = RasUnsteady.get_met_precipitation_config(FIXTURE_DIR / fixture_name)

    assert config == expected


def test_get_met_precipitation_config_no_met_section(tmp_path):
    unsteady_file = tmp_path / "no_met.u01"
    unsteady_file.write_text(
        "\n".join(
            [
                "Flow Title=No Met",
                "Program Version=6.60",
                "Boundary Location=River,Reach,1000",
                "Flow Hydrograph= 3",
                "     100     200     300",
            ]
        ),
        encoding="utf-8",
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)

    assert config == expected_config()


def test_get_met_precipitation_config_partial_enabled_file(tmp_path):
    unsteady_file = tmp_path / "partial.u01"
    unsteady_file.write_text(
        "\n".join(
            [
                "Flow Title=Partial Met",
                "Program Version=6.60",
                "Precipitation Mode=Enable",
            ]
        ),
        encoding="utf-8",
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)

    assert config == expected_config(
        enabled=True,
        precipitation_mode="Enable",
    )


def test_get_met_precipitation_config_gridded_gdal_source_fields(tmp_path):
    unsteady_file = tmp_path / "gdal.u01"
    unsteady_file.write_text(
        "\n".join(
            [
                "Flow Title=GDAL Met",
                "Program Version=6.60",
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=Gridded",
                "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)",
                "Met BC=Precipitation|Gridded Interpolation=Nearest",
                r"Met BC=Precipitation|Gridded GDAL Filename=.\Precipitation\aorc.nc",
                "Met BC=Precipitation|Gridded GDAL Group=precip",
                r"Met BC=Precipitation|Gridded GDAL Folder=.\Precipitation",
                "Met BC=Precipitation|Gridded GDAL Filter=*.nc",
            ]
        ),
        encoding="utf-8",
    )

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)

    assert config == expected_config(
        enabled=True,
        precipitation_mode="Enable",
        mode="Gridded",
        source="GDAL Raster File(s)",
        interpolation="Nearest",
        gdal_filename=r".\Precipitation\aorc.nc",
        gdal_group="precip",
        gdal_folder=r".\Precipitation",
        gdal_filter="*.nc",
        raw={
            "Mode": "Gridded",
            "Gridded Source": "GDAL Raster File(s)",
            "Gridded Interpolation": "Nearest",
            "Gridded GDAL Filename": r".\Precipitation\aorc.nc",
            "Gridded GDAL Group": "precip",
            "Gridded GDAL Folder": r".\Precipitation",
            "Gridded GDAL Filter": "*.nc",
        },
    )
