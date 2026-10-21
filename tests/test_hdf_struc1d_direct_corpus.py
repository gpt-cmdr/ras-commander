"""Opt-in read-only comparison with retained Wave 2 public result identities.

Set RAS_STRUCTURE_CORPUS_ROOT to a relocated ras-native-successor fixture root
containing the relative paths in data/structure_direct_wave2_manifest.json.
An unset root skips corpus reads; an explicit incomplete/wrong corpus fails.
The manifest preserves historical file/array hashes, geometry rows and labels.
It does NOT contain the author's 54 maxima: those are independently calculated
from raw stored columns when the exact HDF files become available. This suite
never invokes the native engine or HEC-RAS. Tiny format controls live separately
in test_hdf_struc1d_direct_families.py and always run.
"""

import hashlib
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfStruc1D


MANIFEST = json.loads((Path(__file__).parent / "data/structure_direct_wave2_manifest.json").read_text())


def _sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value):
    return value.decode("utf-8").strip().strip("\0").strip() if isinstance(value, bytes) else value.strip()


def test_retained_manifest_has_five_files_eighteen_identities_and_all_families():
    cases = MANIFEST["cases"]
    assert len(cases) == 5
    assert [len(case["records"]) for case in cases] == [11, 1, 2, 1, 3]
    assert {r["type"] for c in cases for r in c["records"]} == {"Inline", "Bridge", "Culvert", "Pump"}
    for case in cases:
        assert len(case["sha256"]) == 64
        identities = [tuple(record["identity"]) for record in case["records"]]
        assert len(identities) == len(set(identities))


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["name"])
def test_frozen_public_corpus_matches_geometry_labels_bytes_and_raw_maxima(case):
    root = os.environ.get("RAS_STRUCTURE_CORPUS_ROOT")
    if not root:
        pytest.skip("Set RAS_STRUCTURE_CORPUS_ROOT to the retained precomputed public corpus")
    path = Path(root) / case["path"]
    assert path.is_file(), f"Missing explicitly requested corpus file: {path}"
    assert _sha_file(path) == case["sha256"]
    inventory = HdfStruc1D.list_1d_structures(path)
    assert inventory.columns.tolist() == ["River", "Reach", "RS", "Name", "Type"]
    assert set(inventory[["River", "Reach", "RS"]].itertuples(index=False, name=None)) == {
        tuple(record["identity"]) for record in case["records"]
    }
    with h5py.File(path, "r") as hdf:
        for record in case["records"]:
            row = hdf[record["geometry_table"]][record["geometry_row"]]
            identity = ("", "", _text(row["Name"])) if record["type"] == "Pump" else tuple(
                _text(row[key]) for key in ("River", "Reach", "RS")
            )
            assert list(identity) == record["identity"]
            if record["type"] != "Pump":
                assert _text(row["Type"]) == record["type"]
            dataset = hdf[record["dataset"]]
            assert list(dataset.shape) == record["shape"]
            assert dataset.dtype.str == record["dtype"]
            raw = dataset[()]
            little_endian = np.ascontiguousarray(raw.astype(raw.dtype.newbyteorder("<"), copy=False))
            assert hashlib.sha256(little_endian.tobytes()).hexdigest() == record["sha256"]
            labels = [[_text(v) for v in pair] for pair in dataset.attrs["Variable_Unit"]]
            assert labels == record["labels"]
            result = HdfStruc1D.get_structure_max_values(path, *identity)
            assert result["found"]
            flow = "Total Flow" if record["type"] == "Inline" else "Flow"
            for label, key in [("Stage HW", "hw"), ("Stage TW", "tw"), (flow, "flow")]:
                column = [pair[0] for pair in labels].index(label)
                values = raw[:, column]
                expected = None if np.isnan(values).all() else float(np.nanmax(values))
                assert result[f"max_{key}"] == expected
                expected_source = None if expected is None else f"/{record['dataset']} [{label}]"
                assert result[f"{key}_source"] == expected_source
    assert _sha_file(path) == case["sha256"], "Read-only validation changed the source"
