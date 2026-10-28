"""Opt-in split-line search on a real parent plan HDF with native Face Flow.

Set RAS_SUBDOMAIN_NATIVE_CASE to a local JSON case with ``plan_hdf_paths`` (list),
``streams`` and ``catchments`` (GeoParquet from ``RasTauDem.delineate``), optional
``mesh_name`` and ``link_ids``, and ``expect_min_split_lines``. Inputs are read
only. Private model bytes and case paths are never stored in this repo.
"""

import json
import os

import pytest


@pytest.mark.integration
def test_split_lines_and_partition_on_real_parent():
    case_path = os.environ.get("RAS_SUBDOMAIN_NATIVE_CASE")
    if not case_path:
        pytest.skip("Set RAS_SUBDOMAIN_NATIVE_CASE to a local real-parent case")
    gpd = pytest.importorskip("geopandas")
    from ras_commander.subdomain import RasSubdomain

    case = json.loads(open(case_path, encoding="utf-8").read())
    search = RasSubdomain.find_split_lines(
        case["plan_hdf_paths"], gpd.read_parquet(case["streams"]), gpd.read_parquet(case["catchments"]),
        mesh_name=case.get("mesh_name"), link_ids=case.get("link_ids"))
    assert len(search.split_lines) >= int(case.get("expect_min_split_lines", 1))
    assert search.candidates["passes"].any()
    partition = RasSubdomain.build_subdomains(search)
    owner = partition.cell_owner
    assert owner["cell_id"].is_unique  # every physical cell owned once
    assert set(owner["subdomain_id"]) == set(partition.subdomains["subdomain_id"])
    tiers = partition.subdomains.set_index("subdomain_id")["tier"]
    for row in partition.subdomains.itertuples():
        for up in row.upstream_subdomain_ids:
            assert tiers[up] < row.tier
