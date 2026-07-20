"""Static contract tests for the pinned Bald Eagle 7.0.1 fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


FIXTURES = Path(__file__).parent / "qualification" / "fixtures"
SPEC_PATH = FIXTURES / "bald_eagle_701.json"


def _spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_bald_eagle_spec_pins_source_plan_and_crs():
    spec = _spec()

    assert spec["id"] == "bald-eagle-plan06-g09-u03-hecras-701"
    assert spec["source"]["tree_sha256"] == (
        "3871280ea71ad266287f2aa2d3ee6271791caf751b0022f988df10fcb84b8658"
    )
    assert all(
        len(digest) == 64 for digest in spec["source"]["files"].values()
    )
    assert spec["projection"]["epsg"] == 2271
    assert spec["plan"] == {
        "number": "06",
        "title": "Gridded Precip - Infiltration",
        "source_program_version": "6.00",
        "qualification_program_version": "7.01",
        "geometry_number": "09",
        "unsteady_number": "03",
        "simulation_date": "09SEP2018,0000,14SEP2018,0000",
        "computation_interval": "20SEC",
        "compute_cores": 1,
        "required_flags": {
            "Run HTab": "-1",
            "Run UNet": "-1",
            "Run RASMapper": "0",
        },
    }


def test_bald_eagle_spec_pins_cumulative_mesh_sequence():
    sequence = _spec()["mesh_sequence"]

    assert [item["operation"] for item in sequence] == [
        "mesh.generate_initial",
        "mesh.regenerate",
        "mesh.refinement_region",
        "mesh.breakline",
    ]
    assert [
        (item["expected_cell_count"], item["expected_face_count"])
        for item in sequence
    ] == [(4362, 9500), (4362, 9500), (4426, 9661), (4431, 9656)]
    assert all(len(item["topology_fingerprint"]) == 64 for item in sequence)
    assert sequence[0]["topology_fingerprint"] == sequence[1][
        "topology_fingerprint"
    ]


def test_bald_eagle_result_series_sidecar_is_pinned_and_projected():
    outflow = _spec()["result_series"]["outflow"]
    path = SPEC_PATH.parents[3] / outflow["profile_lines_path"]
    content = json.loads(path.read_text(encoding="utf-8"))

    canonical_bytes = path.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(canonical_bytes).hexdigest() == outflow[
        "profile_lines_sha256"
    ]
    assert content["crs"]["properties"]["name"].endswith("EPSG::2271")
    assert content["features"][0]["properties"]["Name"] == outflow["line_name"]
    assert content["features"][0]["geometry"]["type"] == "LineString"


def test_bald_eagle_acceptance_is_content_based_and_one_core():
    spec = _spec()
    preparation = spec["acceptance"]["preparation"]
    compute = spec["acceptance"]["compute"]

    assert spec["plan"]["compute_cores"] == 1
    assert preparation["exact_cell_face_counts"] is True
    assert preparation["exact_topology"] is True
    assert preparation["exact_boundary_assignments"] is True
    assert preparation["property_table_coverage"] == 1.0
    assert preparation["invalid_cell_count"] == 0
    assert compute["volume_accounting"]["max_abs_error_percent"] > 0
    assert set(compute["series"]) == {"outflow", "wse_cells"}
    assert set(compute["rasters"]) == {"wse", "depth", "velocity"}
