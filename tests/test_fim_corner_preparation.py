"""Corner-cache provenance refusal and opt-in native preparation checks."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def bound_cache(tmp_path):
    from ras_commander.fim._corner_preparation import _identity, _digest

    plan, terrain, rasmap = [tmp_path / name for name in ("plan.hdf", "terrain.tif", "project.rasmap")]
    for path in (plan, terrain, rasmap):
        path.write_bytes(path.name.encode())
    folder = tmp_path / "prepared"
    folder.mkdir()
    cache = folder / "PostProcessing.hdf"
    cache.write_bytes(b"immutable native cache payload")
    document = dict(schema="ras-commander-corner-preparation/1", status="complete",
                    hdf=_identity(plan), hdf_sha256=_digest(plan),
                    rasmap=_identity(rasmap), rasmap_sha256=_digest(rasmap),
                    cache_sha256=_digest(cache),
                    inputs={str(path): _identity(path) for path in (plan, terrain, rasmap)})
    receipt = folder / "corner_elevation_receipt.json"
    receipt.write_text(json.dumps(document))
    return plan, cache, receipt, terrain, rasmap


def test_receipt_accepts_only_bound_sources_and_tracks_dependencies(bound_cache):
    from ras_commander.fim._corner_preparation import validate_receipt

    plan, cache, receipt, terrain, rasmap = bound_cache
    _, watched = validate_receipt(plan, cache)
    assert set(watched.values()) == {receipt, terrain, rasmap}
    # A byte-identical rasmap restoration may have a newer filesystem timestamp.
    rasmap.write_bytes(rasmap.read_bytes())
    validate_receipt(plan, cache)


@pytest.mark.parametrize("changed", ["plan", "cache", "terrain", "rasmap", "receipt"])
def test_receipt_rejects_changed_inputs(bound_cache, changed):
    from ras_commander.fim._corner_preparation import validate_receipt

    plan, cache, receipt, terrain, rasmap = bound_cache
    path = dict(plan=plan, cache=cache, terrain=terrain, rasmap=rasmap, receipt=receipt)[changed]
    if changed == "receipt":
        document = json.loads(path.read_text())
        document["status"] = "aborted"
        path.write_text(json.dumps(document))
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        validate_receipt(plan, cache)


def test_unbound_cache_is_not_accepted(bound_cache):
    from ras_commander.fim._corner_preparation import validate_receipt

    plan, cache, receipt, *_ = bound_cache
    receipt.unlink()
    with pytest.raises(ValueError, match="prepare_corner_elevations"):
        validate_receipt(plan, cache)


def test_preparation_rejects_unqualified_native_version_before_loading(tmp_path):
    from ras_commander import RasFim

    with pytest.raises(ValueError, match="7.0.1"):
        RasFim.prepare_corner_elevations(
            tmp_path / "absent.hdf", tmp_path / "output", rasmap_path="absent.rasmap",
            terrain_name="Terrain", hecras_version="6.6")
    assert not (tmp_path / "output").exists()
