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


CLB673_FIXTURE_NAMES = [
    "precip_00_disabled_official_davis.u01",
    "precip_01_enabled_none_gui_davis.u01",
    "precip_02_constant_gui_davis.u01",
    "precip_03_point_thiessen_gui_davis.u01",
    "precip_04_gridded_dss_gui_davis.u01",
    "precip_05_gridded_gdal_gui_davis.u01",
    "precip_06_gridded_dss_official_baldeagle.u03",
]


MET_PRECIP_MODE_CASES = [
    pytest.param(
        {
            "kwargs": {"mode": "None"},
            "expected": {
                "enabled": True,
                "precipitation_mode": "Enable",
                "mode": None,
            },
            "present": [
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=None",
            ],
            "absent": [
                "Met BC=Precipitation|Constant Value=",
                "Met BC=Precipitation|Constant Units=",
                "Met BC=Precipitation|Point Interpolation=",
                "Met BC=Precipitation|Gridded Source=",
                "Met BC=Precipitation|Gridded Interpolation=",
                "Met BC=Precipitation|Gridded DSS Filename=",
                "Met BC=Precipitation|Gridded DSS Pathname=",
                "Met BC=Precipitation|Gridded GDAL Filename=",
                "Met BC=Precipitation|Gridded GDAL Group=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
                "Met BC=Precipitation|Gridded GDAL Folder=",
                "Met BC=Precipitation|Gridded GDAL Filter=",
            ],
        },
        id="none",
    ),
    pytest.param(
        {
            "kwargs": {
                "mode": "Constant",
                "constant_value": 0.25,
                "constant_units": "mm/hr",
            },
            "expected": {
                "enabled": True,
                "precipitation_mode": "Enable",
                "mode": "Constant",
                "constant_value": 0.25,
                "constant_units": "mm/hr",
            },
            "present": [
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=Constant",
                "Met BC=Precipitation|Constant Value=0.25",
                "Met BC=Precipitation|Constant Units=mm/hr",
            ],
            "absent": [
                "Met BC=Precipitation|Point Interpolation=",
                "Met BC=Precipitation|Gridded Source=",
                "Met BC=Precipitation|Gridded Interpolation=",
                "Met BC=Precipitation|Gridded DSS Filename=",
                "Met BC=Precipitation|Gridded DSS Pathname=",
                "Met BC=Precipitation|Gridded GDAL Filename=",
                "Met BC=Precipitation|Gridded GDAL Group=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
                "Met BC=Precipitation|Gridded GDAL Folder=",
                "Met BC=Precipitation|Gridded GDAL Filter=",
            ],
        },
        id="constant",
    ),
    pytest.param(
        {
            "kwargs": {
                "mode": "Point",
                "point_interpolation": "Thiessen Polygon",
            },
            "expected": {
                "enabled": True,
                "precipitation_mode": "Enable",
                "mode": "Point",
                "point_interpolation": "Thiessen Polygon",
            },
            "present": [
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=Point",
                "Met BC=Precipitation|Point Interpolation=Thiessen Polygon",
            ],
            "absent": [
                "Met BC=Precipitation|Constant Value=",
                "Met BC=Precipitation|Constant Units=",
                "Met BC=Precipitation|Gridded Source=",
                "Met BC=Precipitation|Gridded Interpolation=",
                "Met BC=Precipitation|Gridded DSS Filename=",
                "Met BC=Precipitation|Gridded DSS Pathname=",
                "Met BC=Precipitation|Gridded GDAL Filename=",
                "Met BC=Precipitation|Gridded GDAL Group=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
                "Met BC=Precipitation|Gridded GDAL Folder=",
                "Met BC=Precipitation|Gridded GDAL Filter=",
            ],
        },
        id="point",
    ),
    pytest.param(
        {
            "kwargs": {
                "mode": "Gridded",
                "source": "DSS",
                "interpolation": "Nearest",
                "dss_filename": r".\Precipitation\precip.2018.09.dss",
                "dss_pathname": (
                    "/SHG/MARFC/PRECIP/01SEP2018:0200/"
                    "01SEP2018:0300/NEXRAD/"
                ),
            },
            "expected": {
                "enabled": True,
                "precipitation_mode": "Enable",
                "mode": "Gridded",
                "source": "DSS",
                "interpolation": "Nearest",
                "dss_filename": r".\Precipitation\precip.2018.09.dss",
                "dss_pathname": (
                    "/SHG/MARFC/PRECIP/01SEP2018:0200/"
                    "01SEP2018:0300/NEXRAD/"
                ),
            },
            "present": [
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=Gridded",
                "Met BC=Precipitation|Gridded Source=DSS",
                "Met BC=Precipitation|Gridded Interpolation=Nearest",
                r"Met BC=Precipitation|Gridded DSS Filename=.\Precipitation\precip.2018.09.dss",
                (
                    "Met BC=Precipitation|Gridded DSS Pathname="
                    "/SHG/MARFC/PRECIP/01SEP2018:0200/"
                    "01SEP2018:0300/NEXRAD/"
                ),
            ],
            "absent": [
                "Met BC=Precipitation|Constant Value=",
                "Met BC=Precipitation|Constant Units=",
                "Met BC=Precipitation|Point Interpolation=",
                "Met BC=Precipitation|Gridded GDAL Filename=",
                "Met BC=Precipitation|Gridded GDAL Group=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
                "Met BC=Precipitation|Gridded GDAL Folder=",
                "Met BC=Precipitation|Gridded GDAL Filter=",
            ],
        },
        id="gridded-dss",
    ),
    pytest.param(
        {
            "kwargs": {
                "mode": "Gridded",
                "source": "GDAL Raster File(s)",
                "interpolation": "Bilinear",
                "gdal_filename": Path("Precipitation") / "aorc.nc",
                "gdal_group": "APCP_surface",
                "gdal_folder": Path("Precipitation"),
                "gdal_filter": "*.nc",
            },
            "expected": {
                "enabled": True,
                "precipitation_mode": "Enable",
                "mode": "Gridded",
                "source": "GDAL Raster File(s)",
                "interpolation": "Bilinear",
                "gdal_filename": r".\Precipitation\aorc.nc",
                "gdal_group": "APCP_surface",
                "gdal_folder": r".\Precipitation",
                "gdal_filter": "*.nc",
            },
            "present": [
                "Precipitation Mode=Enable",
                "Met BC=Precipitation|Mode=Gridded",
                "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)",
                "Met BC=Precipitation|Gridded Interpolation=Bilinear",
                r"Met BC=Precipitation|Gridded GDAL Filename=.\Precipitation\aorc.nc",
                "Met BC=Precipitation|Gridded GDAL Group=APCP_surface",
                r"Met BC=Precipitation|Gridded GDAL Folder=.\Precipitation",
                "Met BC=Precipitation|Gridded GDAL Filter=*.nc",
            ],
            "absent": [
                "Met BC=Precipitation|Constant Value=",
                "Met BC=Precipitation|Constant Units=",
                "Met BC=Precipitation|Point Interpolation=",
                "Met BC=Precipitation|Gridded DSS Filename=",
                "Met BC=Precipitation|Gridded DSS Pathname=",
                "Met BC=Precipitation|Gridded GDAL Datasetname=",
            ],
        },
        id="gridded-gdal",
    ),
]


@pytest.mark.parametrize("fixture_name", CLB673_FIXTURE_NAMES)
@pytest.mark.parametrize("case", MET_PRECIP_MODE_CASES)
def test_set_met_precipitation_mode_round_trips_each_mode_from_clb673_fixtures(
    tmp_path,
    fixture_name,
    case,
):
    unsteady_file = tmp_path / fixture_name
    unsteady_file.write_bytes((FIXTURE_DIR / fixture_name).read_bytes())

    RasUnsteady.set_met_precipitation_mode(unsteady_file, **case["kwargs"])
    first_write = unsteady_file.read_bytes()
    RasUnsteady.set_met_precipitation_mode(unsteady_file, **case["kwargs"])
    second_write = unsteady_file.read_bytes()

    assert second_write == first_write

    lines = unsteady_file.read_text(encoding="utf-8").splitlines()
    assert lines.count("Precipitation Mode=Enable") == 1
    mode_line = next(
        line for line in case["present"]
        if line.startswith("Met BC=Precipitation|Mode=")
    )
    assert lines.count(mode_line) == 1
    for expected_line in case["present"]:
        assert expected_line in lines
    for stale_prefix in case["absent"]:
        assert not any(line.startswith(stale_prefix) for line in lines)

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    for key, expected_value in case["expected"].items():
        assert config[key] == expected_value


def test_set_met_precipitation_mode_creates_precipitation_block_from_scratch(tmp_path):
    unsteady_file = tmp_path / "minimal.u01"
    unsteady_file.write_text(
        "\n".join(
            [
                "Flow Title=Minimal",
                "Program Version=6.60",
                "Boundary Location=River,Reach,1000",
            ]
        ),
        encoding="utf-8",
    )

    RasUnsteady.set_met_precipitation_mode(
        unsteady_file,
        "Gridded",
        source="GDAL",
        interpolation="Nearest",
        gdal_filename="Precipitation/aorc.nc",
        gdal_group="APCP_surface",
        gdal_folder="Precipitation",
        gdal_filter="*.nc",
    )

    lines = unsteady_file.read_text(encoding="utf-8").splitlines()
    assert lines.index("Precipitation Mode=Enable") < lines.index(
        "Boundary Location=River,Reach,1000"
    )
    assert "Met BC=Precipitation|Mode=Gridded" in lines
    assert "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)" in lines
    assert r"Met BC=Precipitation|Gridded GDAL Filename=.\Precipitation\aorc.nc" in lines

    config = RasUnsteady.get_met_precipitation_config(unsteady_file)
    assert config["mode"] == "Gridded"
    assert config["source"] == "GDAL Raster File(s)"
    assert config["gdal_group"] == "APCP_surface"


def test_set_met_precipitation_mode_validates_mode_specific_inputs(tmp_path):
    unsteady_file = tmp_path / "minimal.u01"
    unsteady_file.write_text(
        "Flow Title=Minimal\nProgram Version=6.60\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mode must be"):
        RasUnsteady.set_met_precipitation_mode(unsteady_file, "Hyetograph")

    with pytest.raises(ValueError, match="source is required"):
        RasUnsteady.set_met_precipitation_mode(unsteady_file, "Gridded")

    with pytest.raises(ValueError, match="interpolation"):
        RasUnsteady.set_met_precipitation_mode(
            unsteady_file,
            "Gridded",
            source="DSS",
            interpolation="Kriging",
        )

    with pytest.raises(ValueError, match="constant_value must be >= 0"):
        RasUnsteady.set_met_precipitation_mode(
            unsteady_file,
            "Constant",
            constant_value=-0.01,
        )
