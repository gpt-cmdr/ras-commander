import logging
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfHydraulicTables import HdfHydraulicTables


LOGGER_NAME = "ras_commander.hdf.HdfHydraulicTables"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_hydraulic_tables_hdf(
    hdf_path: Path,
    *,
    include_property_tables: bool = True,
    xs_count: int = 2,
) -> Path:
    attrs_dtype = np.dtype([
        ("River", "S32"),
        ("Reach", "S32"),
        ("RS", "S32"),
    ])
    attrs = np.array(
        [
            (b"River", b"Reach", f"{100 + i}".encode("ascii"))
            for i in range(xs_count)
        ],
        dtype=attrs_dtype,
    )

    with h5py.File(hdf_path, "w") as hdf:
        xs_group = hdf.create_group("Geometry").create_group("Cross Sections")
        xs_group.create_dataset("Attributes", data=attrs)

        if include_property_tables:
            prop_group = xs_group.create_group("Property Tables")
            rows_per_xs = 2
            xsec_info = np.array(
                [[i * rows_per_xs, rows_per_xs, 0] for i in range(xs_count)],
                dtype=np.int32,
            )
            prop_group.create_dataset("XSEC Info", data=xsec_info)

            values = np.zeros((xs_count * rows_per_xs, 23), dtype=np.float64)
            for i in range(xs_count):
                start = i * rows_per_xs
                values[start:start + rows_per_xs, 0] = [100.0 + i, 101.0 + i]
                values[start:start + rows_per_xs, 1:4] = 1.0
                values[start:start + rows_per_xs, 7:10] = 2.0
                values[start:start + rows_per_xs, 10:13] = 3.0

            value_ds = prop_group.create_dataset("XSEC Value", data=values)
            variable_names = [
                "Elevation",
                "Area LOB",
                "Area Chan",
                "Area ROB",
                "Area Ineff LOB",
                "Area Ineff Chan",
                "Area Ineff ROB",
                "Conv LOB",
                "Conv Chan",
                "Conv ROB",
                "WP LOB",
                "WP Chan",
                "WP ROB",
                "Mann N LOB",
                "Mann N Chan",
                "Mann N ROB",
                "Top Width",
                "Top Width LOB",
                "Top Width Chan",
                "Top Width ROB",
                "Alpha",
                "Storage Area",
                "Beta",
            ]
            value_ds.attrs["Variables"] = np.array(
                [(name.encode("ascii"), b"") for name in variable_names],
                dtype=[("name", "S32"), ("unit", "S16")],
            )

    return hdf_path


def test_successful_htab_reads_keep_one_concise_batch_info(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_hydraulic_tables_hdf(tmp_path / "synthetic.g01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        htab = HdfHydraulicTables.get_xs_htab(hdf_path, "River", "Reach", "100")
        all_htabs = HdfHydraulicTables.get_all_xs_htabs(hdf_path)

    assert not htab.empty
    assert len(all_htabs) == 2

    records = _records(caplog)
    messages = [record.getMessage() for record in records]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert messages == ["Extracted 2 HTAB property table(s) from synthetic.g01.hdf"]
    assert str(tmp_path) not in messages[0]


def test_missing_htab_tables_single_read_logs_preprocessor_guidance(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_hydraulic_tables_hdf(
        tmp_path / "missing_tables.g01.hdf",
        include_property_tables=False,
        xs_count=1,
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(IOError) as exc_info:
            HdfHydraulicTables.get_xs_htab(hdf_path, "River", "Reach", "100")

    records = _records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.ERROR
    assert "missing_tables.g01.hdf" in message
    assert "River/Reach/RS 100" in message
    assert "created by the HEC-RAS geometry preprocessor" in message
    assert "run the geometry preprocessor first" in message
    assert "/Geometry/Cross Sections/Property Tables" in message
    assert str(tmp_path) not in message
    assert "run the geometry preprocessor first" in str(exc_info.value)


def test_missing_htab_tables_batch_read_logs_one_preprocessor_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_hydraulic_tables_hdf(
        tmp_path / "missing_batch.g01.hdf",
        include_property_tables=False,
        xs_count=2,
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        all_htabs = HdfHydraulicTables.get_all_xs_htabs(hdf_path)

    assert all_htabs == {}
    records = _records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.ERROR
    assert "missing_batch.g01.hdf" in message
    assert "all cross sections" in message
    assert "created by the HEC-RAS geometry preprocessor" in message
    assert "/Geometry/Cross Sections/Property Tables" in message
    assert str(tmp_path) not in message


def test_partial_htab_batch_failure_keeps_details_at_debug(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_hydraulic_tables_hdf(tmp_path / "partial.g01.hdf", xs_count=2)

    with h5py.File(hdf_path, "a") as hdf:
        del hdf["/Geometry/Cross Sections/Property Tables/XSEC Info"]
        hdf["/Geometry/Cross Sections/Property Tables"].create_dataset(
            "XSEC Info",
            data=np.array([[0, 2, 0]], dtype=np.int32),
        )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        all_htabs = HdfHydraulicTables.get_all_xs_htabs(hdf_path)

    assert len(all_htabs) == 1
    warning_records = _records(caplog)
    warning_messages = [record.getMessage() for record in warning_records]
    assert len(warning_records) == 1
    assert warning_records[0].levelno == logging.WARNING
    assert "Skipped 1/2 HTAB property table(s) from partial.g01.hdf" in warning_messages[0]
    assert "River/Reach/RS 101" in warning_messages[0]
    assert str(tmp_path) not in warning_messages[0]

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfHydraulicTables.get_all_xs_htabs(hdf_path)

    debug_messages = [record.getMessage() for record in _records(caplog)]
    assert any("Skipped HTAB cross sections from" in message for message in debug_messages)
    assert any(str(hdf_path) in message for message in debug_messages)
