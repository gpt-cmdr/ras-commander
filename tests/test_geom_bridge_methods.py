"""
Regression tests for bridge hydraulic method selection APIs.

These tests cover exact BR Coef text changes, unsupported method combinations,
and parsing against a real HEC-RAS bridge example.
"""

import re
import sys
from pathlib import Path

import pytest


# Ensure we're using local source, not installed package
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


from ras_commander import RasExamples
from ras_commander.geom import GeomBridge


BRIDGE_FIXTURE_TEXT = """Geom Title=Bridge Methods Fixture
River Reach=Beaver Creek,Kentwood
Type RM Length L Ch R = 3 ,5.4     ,,,
Bridge Culvert--1,0,0,-1, 0 
Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee
30,40,2.6,0, 0, 0, , , 0.95, 0, 0,0,,
BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,
WSPro=,,,, 1 ,,,, 0 ,,,, 0 ,,,,-1 ,-1 ,-1 , 0 , 0 , 0 , 0 , 0 
BC Design=,, 0 ,, 0 ,,,,,,
Type RM Length L Ch R = 1 ,5.39    ,,,
"""


def _write_bridge_fixture(tmp_path: Path) -> Path:
    geom_file = tmp_path / "bridge_methods.g01"
    geom_file.write_text(BRIDGE_FIXTURE_TEXT, encoding="utf-8")
    return geom_file


def _get_geom_file(project_path: Path) -> Path:
    geom_files = sorted(
        path for path in project_path.iterdir()
        if path.is_file() and re.search(r"\.g\d\d$", path.name.lower())
    )
    assert geom_files, f"No geometry files found in {project_path}"
    return geom_files[0]


def test_get_hydraulic_methods_parses_bridge_records(tmp_path):
    geom_file = _write_bridge_fixture(tmp_path)

    methods = GeomBridge.get_hydraulic_methods(
        geom_file,
        "Beaver Creek",
        "Kentwood",
        "5.4",
    )

    assert methods["low_flow_method"] == "momentum"
    assert methods["low_flow_method_code"] == 1
    assert methods["high_flow_method"] == "pressure_weir"
    assert methods["enabled_low_flow_methods"] == {
        "energy": True,
        "momentum": False,
        "yarnell": False,
        "wspro": False,
    }
    assert methods["coefficients"]["submerged_inlet_cd"] == pytest.approx(0.34)
    assert methods["coefficients"]["submerged_inlet_outlet_cd"] == pytest.approx(0.7)
    assert methods["wspro"]["abutment_type"] == pytest.approx(1.0)
    assert methods["wspro"]["piers_continuous"] is True
    assert methods["raw"]["br_coef_line"] == "BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,"


def test_set_hydraulic_methods_exact_before_after_file_change(tmp_path):
    geom_file = _write_bridge_fixture(tmp_path)
    before_text = geom_file.read_text(encoding="utf-8")
    expected_after = before_text.replace(
        "BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,",
        "BR Coef=-1 , 0 , -1 ,1.05, 0 ,,0.36,0.72,-1,1.33,2,",
    )

    result = GeomBridge.set_hydraulic_methods(
        geom_file,
        "Beaver Creek",
        "Kentwood",
        "5.4",
        low_flow_method="yarnell",
        high_flow_method="energy",
        yarnell_k=1.05,
        momentum_cd=1.33,
        pressure_flow_submerged_inlet_cd=0.36,
        pressure_flow_submerged_inlet_outlet_cd=0.72,
    )

    assert geom_file.read_text(encoding="utf-8") == expected_after
    assert result["br_coef_before"] == "BR Coef=-1 , 0 , 0 ,, 0 ,,0.34,0.7,0,,1,"
    assert result["br_coef_after"] == "BR Coef=-1 , 0 , -1 ,1.05, 0 ,,0.36,0.72,-1,1.33,2,"
    assert result["low_flow_method"] == "yarnell"
    assert result["high_flow_method"] == "energy"

    backup_path = Path(result["backup_path"])
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == before_text


def test_set_hydraulic_methods_rejects_unsupported_combinations(tmp_path):
    geom_file = _write_bridge_fixture(tmp_path)

    with pytest.raises(ValueError, match="low_flow_method must be one of"):
        GeomBridge.set_hydraulic_methods(
            geom_file,
            "Beaver Creek",
            "Kentwood",
            "5.4",
            low_flow_method="culvert",
        )

    with pytest.raises(ValueError, match="selected low_flow_method 'yarnell' cannot be disabled"):
        GeomBridge.set_hydraulic_methods(
            geom_file,
            "Beaver Creek",
            "Kentwood",
            "5.4",
            low_flow_method="yarnell",
            use_yarnell=False,
        )


def test_get_hydraulic_methods_reads_real_bridge_example():
    project_path = RasExamples.extract_project(
        "Bridge Hydraulics",
        suffix="test_geom_bridge_methods_parse",
    )
    geom_file = _get_geom_file(project_path)
    bridges = GeomBridge.get_bridges(geom_file)

    assert not bridges.empty, "Expected at least one bridge in the example project"

    row = bridges.iloc[0]
    methods = GeomBridge.get_hydraulic_methods(
        geom_file,
        row["River"],
        row["Reach"],
        str(row["RS"]),
    )

    assert methods["raw"]["bridge_culvert_line"].startswith("Bridge Culvert-")
    assert methods["raw"]["br_coef_line"].startswith("BR Coef=")
    assert methods["low_flow_method"] in {"energy", "momentum", "yarnell", "wspro"}
    assert methods["high_flow_method"] in {"energy", "pressure_weir"}
    assert methods["coefficients"]["submerged_inlet_cd"] == pytest.approx(0.34)
    assert methods["coefficients"]["submerged_inlet_outlet_cd"] == pytest.approx(0.7)
