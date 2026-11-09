"""Synthetic raw boundaries: byte identity is separate from valid topology."""
import json
from pathlib import Path
import random
import struct

import pytest

pytest.importorskip("pyproj")
from pyproj import CRS

from ras_commander.fim import FimEngineError, FimGeometryError, FimUnsupportedError
from ras_commander.fim import _boundary_raw as raw

BUDGET = 32 << 20
CRS_NAME = "EPSG:2227"
SQUARE = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
BOWTIE = [[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0], [0.0, 0.0]]


def geojson(path, rings, *, crs=CRS_NAME):
    path.write_text(json.dumps(dict(type="FeatureCollection",
        crs=dict(type="name", properties=dict(name=crs)),
        features=[dict(type="Feature", properties={}, geometry=dict(
            type="MultiPolygon", coordinates=[[ring] for ring in rings]))])), encoding="utf-8")
    return path


def shapefile(path, rings, *, crs=CRS_NAME):
    points = [xy for ring in rings for xy in ring]
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    offsets, count = [], 0
    for ring in rings:
        offsets.append(count)
        count += len(ring)
    body = (struct.pack("<i4d2i", 5, *bounds, len(rings), len(points))
            + struct.pack("<" + "i" * len(offsets), *offsets)
            + b"".join(struct.pack("<dd", *xy) for xy in points))

    def header(size):
        return (struct.pack(">7i", 9994, 0, 0, 0, 0, 0, size // 2)
                + struct.pack("<2i8d", 1000, 5, *bounds, 0.0, 0.0, 0.0, 0.0))

    path.write_bytes(header(108 + len(body)) + struct.pack(">2i", 1, len(body) // 2) + body)
    path.with_suffix(".shx").write_bytes(header(108) + struct.pack(">2i", 50, len(body) // 2))
    dbf = bytearray(32)
    dbf[0] = 3
    struct.pack_into("<IHH", dbf, 4, 1, 33, 1)
    path.with_suffix(".dbf").write_bytes(dbf + b"\r \x1a")
    path.with_suffix(".prj").write_text(CRS.from_user_input(crs).to_wkt(), encoding="utf-8")
    return path


def rotated(ring):
    core = ring[:-1]
    core = list(reversed(core[2:] + core[:2]))
    return core + [core[0]]


def test_typed_refusal_is_engine_error_and_value_error():
    error = FimGeometryError("invalid", diagnostic_manifest=Path("receipt.json"),
                             artifacts=[Path("raw.shp")], validity_reason="self-intersection")
    assert isinstance(error, (FimEngineError, ValueError))
    assert isinstance(error, FimEngineError) and isinstance(error, ValueError)
    assert error.diagnostic_manifest == Path("receipt.json")
    assert error.artifacts == (Path("raw.shp"),)
    assert error.validity_reason == "self-intersection"


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_opt_in_boolean_is_strict(value):
    with pytest.raises(TypeError, match="boolean"):
        raw.validate_options(value, method="native_serial", allow_unqualified=True)


def test_default_does_not_change_normal_route():
    assert raw.validate_options(method="deterministic", allow_unqualified=False, bbox=(0, 0, 1, 1)) is False
    assert raw.validate_options(True, method="native_serial", allow_unqualified=True) is True


@pytest.mark.parametrize("options", [dict(method="deterministic", allow_unqualified=True),
    dict(method="native_serial", allow_unqualified=False),
    dict(method="native_serial", allow_unqualified=1),
    *[dict(method="native_serial", allow_unqualified=True, **{k: v}) for k, v in
      [("bbox", (0, 0, 1, 1)), ("polygon", object()), ("polygon_layer", ""), ("aoi_crs", CRS_NAME)]]])
def test_wrong_method_gate_and_aoi_refuse(options):
    with pytest.raises(FimUnsupportedError):
        raw.validate_options(True, **options)


@pytest.mark.parametrize("writer,suffix", [(geojson, ".geojson"), (shapefile, ".shp")])
def test_finite_self_intersection_is_retained_intact(tmp_path, writer, suffix):
    source = writer(tmp_path / ("invalid" + suffix), [BOWTIE])
    before = {p.name: p.read_bytes() for p in raw._headers(source, BUDGET)["files"]}
    receipt = raw.retain_raw_geometry(source, tmp_path / "diagnostics", CRS_NAME, BUDGET,
        validity_reason="Ring self-intersection", topology_valid=False)
    assert receipt["status"] == "aborted" and receipt["diagnostic_only"]
    assert receipt["topology_validity"] is False
    assert receipt["qualified"] is receipt["native_vector_parity"] is False
    assert receipt["raw_counts"]["vertices"] == len(BOWTIE)
    for item in receipt["artifacts"]:
        assert Path(item["path"]).read_bytes() == before[Path(item["source"]).name]
        assert Path(item["source"]).read_bytes() == before[Path(item["source"]).name]
    assert json.loads(Path(receipt["diagnostic_manifest"]).read_text())["status"] == "aborted"


def test_manifest_like_source_name_does_not_clobber_artifact(tmp_path):
    source = geojson(tmp_path / "diagnostic_manifest.json", [BOWTIE])
    original = source.read_bytes()
    receipt = raw.retain_raw_geometry(source, tmp_path / "raw", CRS_NAME, BUDGET,
                                     validity_reason="invalid")
    assert Path(receipt["artifacts"][0]["path"]).read_bytes() == original
    assert Path(receipt["artifacts"][0]["path"]) != Path(receipt["diagnostic_manifest"])


def test_optional_cpg_is_retained_and_identities_are_labeled(tmp_path):
    source = shapefile(tmp_path / "a.shp", [BOWTIE])
    source.with_suffix(".cpg").write_bytes(b"UTF-8")
    receipt = raw.retain_raw_geometry(source, tmp_path / "raw", CRS_NAME, BUDGET,
                                     validity_reason="invalid")
    assert len(receipt["artifacts"]) == 5
    for item in receipt["artifacts"]:
        assert item["source_identity"]["sha256"] == item["retained_identity"]["sha256"]
        assert item["source_identity"]["size"] == item["retained_identity"]["size"]


def test_ordered_shp_buffers_and_point_bits_are_separate(tmp_path):
    collinear = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.0], [2.0, 0.0],
                 [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    other = [[p[0] + 5, p[1]] for p in SQUARE]
    a = shapefile(tmp_path / "a.shp", [collinear, other])
    b = shapefile(tmp_path / "b.shp", [other, rotated(collinear)])
    same = raw.compare_raw_geometry(a, a, CRS_NAME, BUDGET)
    assert same["raw_ordered_part_comparison_eligible"]
    assert same["raw_part_buffers_equal"] and same["raw_point_bits_equal"]
    result = raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET)
    assert result["raw_ring_bits_equal"]
    assert not result["raw_part_buffers_equal"] and not result["raw_point_bits_equal"]


def test_cross_format_start_orientation_and_part_order_only(tmp_path):
    other = [[p[0] + 5, p[1]] for p in SQUARE]
    a = shapefile(tmp_path / "a.shp", [BOWTIE, other])
    b = geojson(tmp_path / "b.geojson", [rotated(other), rotated(BOWTIE)])
    result = raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET)
    assert result["raw_ring_bits_equal"]
    assert not result["raw_ordered_part_comparison_eligible"]
    assert not result["raw_part_buffers_equal"] and not result["raw_point_bits_equal"]


def test_signed_zero_bits_and_repeated_collinear_vertices_are_not_discarded(tmp_path):
    negative = [[0.0, 0.0], [2.0, -0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    a = shapefile(tmp_path / "a.shp", [negative])
    b = geojson(tmp_path / "b.geojson", [negative])
    b.write_text(b.read_text().replace("-0.0", "-0"))
    assert raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET)["raw_point_bits_equal"]
    c = geojson(tmp_path / "c.geojson", [SQUARE])
    assert not raw.compare_raw_geometry(a, c, CRS_NAME, BUDGET)["raw_ring_bits_equal"]
    repeated = SQUARE[:1] + [SQUARE[0]] + SQUARE[1:]
    d = geojson(tmp_path / "d.geojson", [repeated])
    assert not raw.compare_raw_geometry(c, d, CRS_NAME, BUDGET)["raw_ring_bits_equal"]


def test_canonical_bits_preserve_repeats_for_all_starts_and_reversals():
    generator = random.Random(710)
    for _ in range(25):
        core = [[generator.choice([-0.0, 0.0, 1.0, 2.0]),
                 generator.choice([-0.0, 0.0, 1.0, 2.0])] for _ in range(9)]
        def bits(points):
            return b"".join(struct.pack("<dd", *xy) for xy in points + points[:1])
        expected = raw._canonical_bits(bits(core))
        for shift in range(len(core)):
            rotated_core = core[shift:] + core[:shift]
            assert raw._canonical_bits(bits(rotated_core)) == expected
            assert raw._canonical_bits(bits(list(reversed(rotated_core)))) == expected


def test_numerically_closed_bit_distinct_endpoints_are_preserved(tmp_path):
    ring = [[-0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    a = shapefile(tmp_path / "a.shp", [ring])
    b = geojson(tmp_path / "b.geojson", [ring])
    result = raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET)
    assert result["raw_point_bits_equal"] and result["raw_ring_bits_equal"]
    c = geojson(tmp_path / "c.geojson", [SQUARE])
    assert not raw.compare_raw_geometry(a, c, CRS_NAME, BUDGET)["raw_ring_bits_equal"]


@pytest.mark.parametrize("suffix", [".geojson", ".shp"])
def test_unclosed_parts_refuse_before_artifact_creation(tmp_path, suffix):
    source = (geojson if suffix == ".geojson" else shapefile)(tmp_path / ("bad" + suffix), [SQUARE[:-1] + [[0.0, 1.0]]])
    with pytest.raises(ValueError, match="closed"):
        raw.retain_raw_geometry(source, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    assert not (tmp_path / "raw").exists()


def test_nonfinite_geojson_and_shp_refuse(tmp_path):
    a = geojson(tmp_path / "bad.geojson", [SQUARE])
    a.write_text(a.read_text().replace("2.0", "NaN", 1))
    with pytest.raises(ValueError, match="finite"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    b = shapefile(tmp_path / "bad.shp", [SQUARE])
    data = bytearray(b.read_bytes())
    struct.pack_into("<d", data, 156 + 16, float("nan"))
    b.write_bytes(data)
    with pytest.raises(ValueError, match="finite"):
        raw.compare_raw_geometry(b, b, CRS_NAME, BUDGET)


@pytest.mark.parametrize("component", ["shp", "shx", "dbf"])
def test_malformed_headers_and_partial_bundles_refuse(tmp_path, component):
    source = shapefile(tmp_path / "bad.shp", [SQUARE])
    target = source.with_suffix("." + component)
    data = bytearray(target.read_bytes())
    if component == "shp":
        struct.pack_into("<i", data, 108 + 40, 500)
    elif component == "shx":
        struct.pack_into(">i", data, 100, 51)
    else:
        data = data[:33]
    target.write_bytes(data)
    with pytest.raises(ValueError):
        raw.retain_raw_geometry(source, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    assert not (tmp_path / "raw").exists()


def test_pair_budget_is_checked_before_json_load(tmp_path, monkeypatch):
    a = geojson(tmp_path / "a.geojson", [SQUARE])
    b = geojson(tmp_path / "b.geojson", [SQUARE])
    info = raw._headers(a, BUDGET)
    one = raw._admit([info], BUDGET)
    monkeypatch.setattr(raw, "_prepare", lambda *args: pytest.fail("pair loaded before admission"))
    with pytest.raises(ValueError, match="pair/parsing budget"):
        raw.compare_raw_geometry(a, b, CRS_NAME, one)


def test_noncoordinate_json_metadata_parse_tree_is_admitted(tmp_path, monkeypatch):
    a = geojson(tmp_path / "a.geojson", [SQUARE])
    data = json.loads(a.read_text())
    data["features"][0]["properties"]["metadata"] = [[] for _ in range(5000)]
    a.write_text(json.dumps(data))
    info = raw._headers(a, BUDGET)
    assert info["json_nodes"]["arrays"] >= 5000
    estimate = raw._admit([info], BUDGET)
    monkeypatch.setattr(raw, "_read_json", lambda *a: pytest.fail("JSON loaded before metadata admission"))
    with pytest.raises(ValueError, match="budget"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, estimate - 1, validity_reason="invalid")


def test_crs_mismatch_and_symlinks_refuse(tmp_path):
    a = geojson(tmp_path / "a.geojson", [BOWTIE], crs="EPSG:2271")
    with pytest.raises(ValueError, match="CRS"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    linked = tmp_path / "linked.geojson"
    try:
        linked.symlink_to(a)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="Symlink"):
        raw.compare_raw_geometry(linked, a, CRS_NAME, BUDGET)


def test_source_change_cleans_only_owned_output(tmp_path):
    a = geojson(tmp_path / "a.geojson", [BOWTIE])
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 2:
            a.write_bytes(a.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET,
                                validity_reason="invalid", check_sources=check)
    assert len(calls) == 2 and not (tmp_path / "raw").exists()


def test_comparison_checks_both_source_identities_after_scan(tmp_path):
    a = geojson(tmp_path / "a.geojson", [SQUARE])
    b = shapefile(tmp_path / "b.shp", [SQUARE])
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 2:
            b.with_suffix(".prj").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET, check_sources=check)
    assert len(calls) == 2


def test_json_growth_is_bounded_before_parse(tmp_path, monkeypatch):
    a = geojson(tmp_path / "a.geojson", [SQUARE])
    info = raw._headers(a, BUDGET)
    a.write_bytes(a.read_bytes() + b" " * 100)
    with pytest.raises(ValueError, match="grew beyond"):
        raw._prepare(info, CRS_NAME)


def test_crs_growth_and_oversized_reason_refuse_before_publication(tmp_path):
    a = shapefile(tmp_path / "a.shp", [SQUARE])
    info = raw._headers(a, BUDGET)
    prj = a.with_suffix(".prj")
    prj.write_bytes(prj.read_bytes() + b" ")
    with pytest.raises(ValueError, match="CRS grew"):
        raw._prepare(info, CRS_NAME)
    with pytest.raises(ValueError, match="bounded string"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET,
                                validity_reason="x" * 65537)
    assert not (tmp_path / "raw").exists()


def test_interrupt_cleans_partial_output_and_existing_folder_is_preserved(tmp_path, monkeypatch):
    a = geojson(tmp_path / "a.geojson", [BOWTIE])
    def interrupt(source, destination, length):
        destination.write(b"partial")
        raise KeyboardInterrupt()
    monkeypatch.setattr(raw, "_copy_bounded", interrupt)
    with pytest.raises(KeyboardInterrupt):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    assert not (tmp_path / "raw").exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "mine").write_bytes(b"owned by caller")
    with pytest.raises(FileExistsError):
        raw.retain_raw_geometry(a, existing, CRS_NAME, BUDGET, validity_reason="invalid")
    assert (existing / "mine").read_bytes() == b"owned by caller"


def test_source_growth_during_copy_is_bounded_and_cleaned(tmp_path, monkeypatch):
    a = geojson(tmp_path / "a.geojson", [BOWTIE])
    original = raw._copy_bounded
    def growing(source, destination, size):
        with a.open("ab") as writer:
            writer.write(b" " * 100)
        original(source, destination, size)
    monkeypatch.setattr(raw, "_copy_bounded", growing)
    with pytest.raises(ValueError, match="grew during bounded"):
        raw.retain_raw_geometry(a, tmp_path / "raw", CRS_NAME, BUDGET, validity_reason="invalid")
    assert not (tmp_path / "raw").exists()


def test_raw_invalid_diagnostics_never_call_geos_overlays(tmp_path, monkeypatch):
    shapely = pytest.importorskip("shapely")
    for name in ("intersection", "union", "difference", "symmetric_difference", "area",
                 "hausdorff_distance", "buffer", "make_valid"):
        monkeypatch.setattr(shapely, name, lambda *a, **k: pytest.fail("GEOS operation in raw diagnostics"))
    a = shapefile(tmp_path / "a.shp", [BOWTIE])
    b = geojson(tmp_path / "b.geojson", [BOWTIE])
    result = raw.compare_raw_geometry(a, b, CRS_NAME, BUDGET)
    assert result["status"] == "diagnostic_only" and result["raw_ring_bits_equal"]
    assert not result["qualified"] and not result["native_vector_parity"]
    assert not {"geometry_equal", "area", "intersection_over_union", "hausdorff_distance"} & result.keys()
