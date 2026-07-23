"""Tests for the self-contained raster performance decision report."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "benchmarks"
    / "generate_raster_performance_report.py"
)


def load_report_module():
    spec = importlib.util.spec_from_file_location("raster_html_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def synthetic_payload(seconds: float, batch_bytes: int) -> dict:
    return {
        "schema": "ras-commander.native-tiff-synthetic-benchmark/2",
        "runs": [
            {
                "id": f"patched_serial_{batch_bytes}_w8_q2",
                "settings": {
                    "RASCOMMANDER_TIFF_BATCH_BYTES": str(batch_bytes),
                    "RASCOMMANDER_TIFF_PIPELINE_WORKERS": "8",
                },
                "execution": {
                    "wall_seconds": seconds,
                    "peak_rss_bytes": 80 * 1024 * 1024,
                    "effective_logical_cpus": 4.5,
                    "process_io": {
                        "write_operations": 20,
                        "mean_write_bytes": 1024 * 1024,
                    },
                },
                "equivalence": {"equivalent": True},
            }
        ],
    }


def store_map_payload(batch_bytes: int, original: float, patched: float) -> dict:
    base = {
        "execution": {
            "peak_private_bytes": 1024 * 1024 * 1024,
            "process_io": {"write_iops": 12},
        }
    }
    return {
        "schema": "ras-commander.native-tiff-store-map-benchmark/2",
        "runs": [
            {
                **base,
                "id": "original",
                "execution": {**base["execution"], "wall_seconds": original},
            },
            {
                **base,
                "id": f"patched_serial_{batch_bytes}_w8",
                "settings": {
                    "RASCOMMANDER_TIFF_BATCH_BYTES": str(batch_bytes),
                    "RASCOMMANDER_TIFF_PIPELINE_WORKERS": "8",
                },
                "execution": {**base["execution"], "wall_seconds": patched},
                "tiff_io": {"underlying_write_calls": 6},
                "equivalence": {"equivalent": True},
                "result_hdf_preserved": True,
            },
        ],
    }


def writer_scaling_payload(original: float, eight_workers: float) -> dict:
    return {
        "schema": "ras-commander.native-tiff-synthetic-benchmark/2",
        "runs": [
            {
                "id": "original",
                "execution": {
                    "wall_seconds": original,
                    "effective_logical_cpus": 1.4,
                    "peak_rss_bytes": 42 * 1024 * 1024,
                },
            },
            {
                "id": "patched_serial_262144_w8_q2",
                "settings": {"RASCOMMANDER_TIFF_PIPELINE_WORKERS": "8"},
                "execution": {
                    "wall_seconds": eight_workers,
                    "effective_logical_cpus": 5.2,
                    "peak_rss_bytes": 75 * 1024 * 1024,
                },
                "equivalence": {"equivalent": True},
            },
        ],
    }


def profile_matrix_payload() -> dict:
    def run(run_id: str, seconds: float, private_mib: float, helpers: int) -> dict:
        return {
            "run_id": run_id,
            "status": "complete",
            "elapsed_seconds": seconds,
            "cpu_seconds": seconds * helpers,
            "peak_tree_private_bytes": private_mib * 1024 * 1024,
            "minimum_available_memory_bytes": 12 * 1024**3,
            "maximum_helpers": helpers,
        }

    return {
        "schema": "ras-commander.raster-profile-matrix-summary/1",
        "runs": [
            run("store_all3_serial_local", 10, 1000, 1),
            run("store_all3_auto_local", 6, 1800, 3),
            run("store_all3_workers2_local", 8, 1400, 2),
            run("store_all3_serial_network", 12, 1000, 1),
            run("store_all3_auto_network", 7, 1800, 3),
            run("store_all3_workers2_network", 9, 1400, 2),
            run("spring_all3_auto_local", 300, 10000, 1),
            run("spring_all3_auto_network", 360, 10000, 1),
        ],
    }


def spring_payload() -> dict:
    return {
        "schema": "ras-commander.native-tiff-store-map-benchmark/2",
        "all_semantically_equivalent": True,
        "runs": [
            {
                "id": "original",
                "execution": {
                    "wall_seconds": 110,
                    "peak_private_bytes": 11 * 1024**3,
                    "effective_logical_cpus": 2.8,
                },
                "phase_profile": {},
                "resource_samples": [],
            },
            {
                "id": "patched_serial_262144_w8",
                "settings": {"RASCOMMANDER_TIFF_PIPELINE_WORKERS": "8"},
                "execution": {
                    "wall_seconds": 108,
                    "peak_private_bytes": 11 * 1024**3,
                    "effective_logical_cpus": 2.9,
                },
            },
        ],
    }


def test_report_aggregates_repeats_and_writes_accessible_html(tmp_path):
    report = load_report_module()
    synthetic = (
        write_json(tmp_path / "synthetic-1.json", synthetic_payload(0.8, 2 * 1024**2)),
        write_json(tmp_path / "synthetic-2.json", synthetic_payload(0.7, 2 * 1024**2)),
        write_json(tmp_path / "synthetic-3.json", synthetic_payload(0.9, 2 * 1024**2)),
    )
    store_map = (
        write_json(
            tmp_path / "store-map.json",
            store_map_payload(2 * 1024**2, original=10, patched=9),
        ),
    )
    storage = write_json(
        tmp_path / "storage.json",
        {
            "schema": "ras-commander.storage-io-benchmark/1",
            "label": "test disk",
            "results": [
                {"block_bytes": 65536, "write_mib_per_second": 500},
                {"block_bytes": 1048576, "write_mib_per_second": 900},
            ],
        },
    )
    matrix = write_json(tmp_path / "matrix.json", profile_matrix_payload())
    writer_scaling = write_json(
        tmp_path / "writer-scaling.json",
        writer_scaling_payload(original=2.4, eight_workers=0.8),
    )
    spring = write_json(tmp_path / "spring.json", spring_payload())
    output = tmp_path / "report" / "index.html"

    html_path, data_path = report.write_report(
        report.ReportInputs(
            synthetic=synthetic,
            store_map_batch=store_map,
            spring=spring,
            storage=(storage,),
            profile_matrices=(matrix,),
            writer_scaling=(writer_scaling,),
        ),
        output,
    )

    normalized = json.loads(data_path.read_text(encoding="utf-8"))
    document = html_path.read_text(encoding="utf-8")
    row = normalized["synthetic_batch"][0]
    assert row["samples"] == 3
    assert row["wall_median_seconds"] == 0.8
    assert "Actionable decision" in document
    assert "Paired real StoreMap speedup" in document
    assert "Storage request size throughput" in document
    assert "Can additional parallelism produce meaningful speedup?" in document
    assert "Three map products" in document
    assert "Isolated TIFF writer" in document
    assert "Spring three-product planning scenarios" in document
    assert "This gain is not SMB-specific" in document
    assert normalized["parallelism"]["comparisons"][0]["speedup_percent"] == 40
    assert round(normalized["writer_scaling"][-1]["speedup_factor"], 2) == 3
    assert "fastest larger setting was" in document
    assert 'role="img"' in document
    assert "Semantic checks passed" in document
    assert "NaN" not in document


def test_horizontal_bar_chart_supports_negative_speedup():
    report = load_report_module()

    svg = report._svg_horizontal_bars(
        "paired speedup",
        (("slower", -3.5), ("faster", 2.0)),
        x_label="percent",
    )

    assert 'width="-' not in svg
    assert "-3.50" in svg
    assert "2.00" in svg


def test_report_rejects_wrong_input_schema(tmp_path):
    report = load_report_module()
    invalid = write_json(tmp_path / "invalid.json", {"schema": "wrong"})

    try:
        report.normalize(
            report.ReportInputs(
                synthetic=(invalid,),
                store_map_batch=(),
                spring=None,
                storage=(),
            )
        )
    except ValueError as error:
        assert "Not a synthetic TIFF benchmark" in str(error)
    else:
        raise AssertionError("wrong schema should fail")
