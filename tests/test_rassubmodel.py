"""Focused real-format contracts for the one-reach RasSubmodel MVP."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import RasPrj, RasSubmodel


def _xs_block(station: int, downstream_length: int, y: int) -> str:
    return f"""Type RM Length L Ch R = 1 ,{station},{downstream_length},{downstream_length},{downstream_length}
BEGIN DESCRIPTION:
XS {station}
END DESCRIPTION:
XS GIS Cut Line= 2
               0{y:16d}             100{y:16d}
#Sta/Elev= 5
       0     110      25     105      50     100      75     105     100     110
#Mann= 3 , 0 , 0
       0    .06       0      25    .035       0      75    .055       0
Bank Sta=25,75
Levee= 1 , 20 , 108 , 1 , 80 , 108
#XS Ineff= 2 , 0
       0     106      15     106      85     106     100     106
Permanent Ineff=
       F       F
XS HTab Starting El and Incr=100,0.5,40
XS HTab Horizontal Distribution= 0

"""


def _structure_block(type_code: int, station: int, label: str) -> str:
    marker = "IW Pilot Flow=0" if type_code == 4 else "Bridge Culvert-0,0,1,-1, 0"
    return f"""Type RM Length L Ch R = {type_code} ,{station},,,
BEGIN DESCRIPTION:
{label}
END DESCRIPTION:
{marker}
#Inline Weir SE= 2
       0     106     100     106
BC HTab HWMax=120
"""


def _write_project(root: Path) -> RasPrj:
    root.mkdir()
    base = "Source"
    (root / f"{base}.prj").write_text(
        "Proj Title=Source\n"
        "Current Plan=p01\n"
        "Plan File=p01\n"
        "Geom File=g01\n"
        "Flow File=f01\n"
        "Default Exp/Contr=0.3,0.1\n",
        encoding="utf-8",
    )
    (root / f"{base}.p01").write_text(
        "Plan Title=Base Plan\n"
        "Program Version=6.60\n"
        "Short Identifier=Base\n"
        "Geom File=g01\n"
        "Flow File=f01\n"
        "Run HTab= 1\n",
        encoding="utf-8",
    )
    geom = (
        "Geom Title=Source Geometry\n"
        "Program Version=6.60\n"
        "Viewing Rectangle= 0 , 100 , 100 , 0\n"
        "Use User Specified Reach Order=0\n"
        "River Reach=Other River,Other Reach\n"
        "Reach XY= 2\n"
        "               0               0             100               0\n"
        + _xs_block(50, 0, -10)
        + "River Reach=Main River,Main Reach\n"
        "Reach XY= 2\n"
        "               0              50             100              50\n"
        + _xs_block(500, 100, 90)
        + _xs_block(400, 100, 80)
        + _structure_block(4, 350, "Inline structure")
        + _xs_block(300, 100, 70)
        + _structure_block(2, 250, "Culvert")
        + _xs_block(200, 100, 60)
        + _xs_block(100, 0, 50)
        + "Junct Name=Removed Junction\n"
        "Junct X Y & Text X Y=0,0,0,0\n"
    )
    (root / f"{base}.g01").write_text(geom, encoding="utf-8")
    (root / f"{base}.f01").write_text(
        "Flow Title=Source Flow\n"
        "Program Version=6.60\n"
        "Number of Profiles= 2\n"
        "Profile Names=Low,High\n"
        "River Rch & RM=Main River,Main Reach,500\n"
        "     100     200\n"
        "River Rch & RM=Main River,Main Reach,300\n"
        "     120     220\n"
        "River Rch & RM=Main River,Main Reach,100\n"
        "     140     240\n"
        "Boundary for River Rch & Prof#=Main River,Main Reach, 1\n"
        "Up Type= 0\n"
        "Dn Type= 3\n"
        "Dn Slope=   0.001\n"
        "Boundary for River Rch & Prof#=Main River,Main Reach, 2\n"
        "Up Type= 0\n"
        "Dn Type= 3\n"
        "Dn Slope=   0.002\n",
        encoding="utf-8",
    )
    ras = RasPrj()
    ras.initialize(
        root,
        "Ras.exe",
        suppress_logging=True,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    return ras


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_steady_hdf(
    path: Path,
    stations: list[int],
    *,
    wse_offset: float = 0.0,
) -> None:
    attributes_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S32"),
            ("Len Channel", "f4"),
        ]
    )
    base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    attributes = np.array(
        [
            (
                b"Main River",
                b"Main Reach",
                str(station).encode(),
                0.0 if index == len(stations) - 1 else 100.0,
            )
            for index, station in enumerate(stations)
        ],
        dtype=attributes_dtype,
    )
    low_wse = np.array([100.0 + index + wse_offset for index in range(len(stations))])
    high_wse = low_wse + 2.0
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/Cross Sections/Attributes", data=attributes)
        hdf.create_dataset(f"{base}/Profile Names", data=np.array([b"Low", b"High"]))
        hdf.create_dataset(
            f"{base}/Cross Sections/Water Surface",
            data=np.vstack([low_wse, high_wse]),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Flow",
            data=np.vstack(
                [np.full(len(stations), 100.0), np.full(len(stations), 200.0)]
            ),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Additional Variables/Maximum Depth Total",
            data=np.vstack([np.full(len(stations), 5.0), np.full(len(stations), 7.0)]),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Additional Variables/Hydraulic Depth Channel",
            data=np.vstack([np.full(len(stations), 3.0), np.full(len(stations), 4.0)]),
        )


def test_extract_reach_preserves_blocks_relationships_and_flow_changes(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    source_geom = Path(source.geom_df.iloc[0]["full_path"])
    before = _digest(source_geom)

    result = RasSubmodel.extract_reach(
        source,
        tmp_path / "submodel",
        "Main River",
        "Main Reach",
        upstream_station=425,
        downstream_station=175,
        boundary_mode="preserve",
    )

    assert result.selection.stations == ("400", "300", "200")
    assert result.validation.is_valid
    assert _digest(source_geom) == before
    assert result.destination_ras.plan_df.iloc[0]["flow_type"] == "Steady"
    assert (
        Path(result.destination_ras.plan_df.iloc[0]["Geom Path"])
        == result.geometry_file
    )
    assert Path(result.destination_ras.plan_df.iloc[0]["Flow Path"]) == result.flow_file

    geometry_text = result.geometry_file.read_text(encoding="utf-8")
    assert "River Reach=Other River,Other Reach" not in geometry_text
    assert "Junct Name=" not in geometry_text
    assert "Type RM Length L Ch R = 1 ,500" not in geometry_text
    assert "Type RM Length L Ch R = 1 ,100" not in geometry_text
    assert "Inline structure" in geometry_text
    assert "Culvert" in geometry_text
    assert "#Mann= 3" in geometry_text
    assert "Levee= 1" in geometry_text
    assert "#XS Ineff= 2" in geometry_text
    assert "XS HTab Starting El and Incr=" in geometry_text
    assert "Type RM Length L Ch R = 1 ,200,0,0,0" in geometry_text

    from ras_commander import RasSteady

    flow = RasSteady.read_flow_file(result.flow_file)
    assert [(item["station"], item["flows"]) for item in flow["flow_changes"]] == [
        ("400", [100.0, 200.0]),
        ("300", [120.0, 220.0]),
    ]
    comparison = RasSubmodel.compare_geometry(
        source_geom, result.geometry_file, result.selection
    )
    assert comparison["content_equal"].all()
    assert comparison.attrs["structure_blocks_equal"] is True
    assert comparison.attrs["source_structure_count"] == 2


def test_supplied_xs_selector_requires_a_continuous_source_slice(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])

    selection = RasSubmodel.select_by_cross_sections(
        geom, "Main River", "Main Reach", [400, 300, 200]
    )
    assert selection.stations == ("400", "300", "200")
    assert selection.selector == "cross_sections"

    with pytest.raises(ValueError, match="contiguous"):
        RasSubmodel.select_by_cross_sections(
            geom, "Main River", "Main Reach", [400, 200]
        )


def test_polygon_selector_resolves_one_reach_and_fills_intervening_xs(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    polygon = shapely.box(-1, 55, 101, 85)

    selection = RasSubmodel.select_by_polygon(
        geom, polygon, river="Main River", reach="Main Reach"
    )

    assert selection.selector == "polygon"
    assert selection.stations == ("400", "300", "200")

    network_selection = RasSubmodel.select_by_network_segment(
        geom,
        shapely.LineString([(50, 55), (50, 85)]),
        river="Main River",
        reach="Main Reach",
    )
    assert network_selection.selector == "network_segment"
    assert network_selection.stations == selection.stations


def test_run_is_explicit_and_delegates_to_rascmdr(tmp_path: Path, monkeypatch):
    source = _write_project(tmp_path / "source")
    result = RasSubmodel.extract_reach(
        source,
        tmp_path / "submodel",
        "Main River",
        "Main Reach",
        400,
        200,
        boundary_mode="preserve",
    )
    observed = {}

    def fake_compute(plan_number, **kwargs):
        observed["plan_number"] = plan_number
        observed.update(kwargs)
        return "computed"

    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    monkeypatch.setattr(
        rascmdr_module.RasCmdr, "compute_plan", staticmethod(fake_compute)
    )

    assert RasSubmodel.run(result, verify=False, num_cores=2) == "computed"
    assert observed["plan_number"] == "01"
    assert observed["ras_object"] is result.destination_ras
    assert observed["verify"] is False
    assert observed["clear_geompre"] is True
    assert observed["num_cores"] == 2


def test_internal_cut_uses_source_result_wse_and_compares_retained_results(
    tmp_path: Path,
):
    source = _write_project(tmp_path / "source")
    source_hdf = tmp_path / "source" / "Source.p01.hdf"
    _write_steady_hdf(source_hdf, [500, 400, 300, 200, 100])

    result = RasSubmodel.extract_reach(
        source,
        tmp_path / "submodel",
        "Main River",
        "Main Reach",
        400,
        200,
        boundary_mode="source_results",
        source_plan_hdf=source_hdf,
    )

    from ras_commander import RasSteady

    flow = RasSteady.read_flow_file(result.flow_file)
    assert result.boundary_provenance == "source_results"
    assert [item["downstream"]["known_ws"] for item in flow["boundaries"]] == [
        pytest.approx(103.0),
        pytest.approx(105.0),
    ]

    destination_hdf = tmp_path / "submodel" / "submodel.p01.hdf"
    _write_steady_hdf(destination_hdf, [400, 300, 200], wse_offset=0.25)
    comparison = RasSubmodel.compare_results(
        source_hdf, destination_hdf, result.selection
    )
    assert set(comparison["_merge"].astype(str)) == {"both"}
    assert len(comparison) == 6
    assert "wsel_delta" in comparison.columns


def test_selected_lateral_structure_fails_closed(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    text = geom.read_text(encoding="utf-8").replace(
        "Junct Name=Removed Junction",
        "Lat Struct=Side Weir\n"
        "Lat Struct RS=350,250\n"
        "#Lat Struct Sta/Elev= 2\n"
        "       0     105     100     105\n"
        "Junct Name=Removed Junction",
    )
    geom.write_text(text, encoding="utf-8")

    with pytest.raises(NotImplementedError, match="Lateral structures"):
        RasSubmodel.extract_reach(
            source,
            tmp_path / "submodel",
            "Main River",
            "Main Reach",
            400,
            200,
            boundary_mode="preserve",
        )
