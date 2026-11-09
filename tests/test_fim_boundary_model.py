"""Managed adaptation of canonical receipts, without native execution."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ras_commander.fim import _boundary_model as adapter, _coupled, _one_d
from ras_commander.fim.errors import FimUnsupportedError


@pytest.fixture
def environment(tmp_path, monkeypatch):
    hdf, terrain, engine = (tmp_path / name for name in ("source.hdf", "terrain.tif", "engine.exe"))
    for path in (hdf, terrain, engine):
        path.write_bytes(path.name.encode())
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "unrelated.txt").write_text("preserve")
    calls, prepared_objects = [], []

    def prepare(hdf_path, terrain_path, folder, **kwargs):
        calls.append((hdf_path, terrain_path, folder, deepcopy(kwargs)))
        folder.mkdir()
        files = {}
        for key in adapter._FILES:
            path = folder / (key + ".bin")
            path.write_bytes(b"payload")
            files[key] = str(path)
        levels = []
        for index in range(len(kwargs["profiles"])):
            path = folder / f"level-{index}.bin"
            path.write_bytes(b"12345678")
            levels.append(str(path))
        receipt = {"point_count": 3, "triangle_count": 1, "segment_count": 1,
            "cross_section_count": 2, "source_hdf": str(hdf_path), "terrain": str(terrain_path),
            "files": files, "levels": levels, "profiles": list(kwargs["profiles"].values()),
            "profile_ids": list(kwargs["profiles"]), "storage": None}
        if "threads" in kwargs:
            nested = folder / "two_d"
            nested.mkdir()
            for name in ("cells.wkb", "mesh.json", "values.bin"):
                (nested / name).write_bytes(b"payload")
            receipt["mesh"] = {"geometry_file": "two_d/cells.wkb", "mesh_files": ["two_d/mesh.json"],
                "profiles": [{"id": name, "values_files": ["two_d/values.bin"]} for name in kwargs["profiles"]]}
        else:
            pool = folder / "storage.wkb"
            pool.write_bytes(b"pool")
            receipt["storage"] = {"count": 1, "polygons": str(pool), "levels": levels}
        hashes = {str(p): _one_d.digest(p) for p in (hdf_path, terrain_path, *folder.rglob("*")) if p.is_file()}
        validates = []

        def validate():
            validates.append(True)
            for path, expected in hashes.items():
                if _one_d.digest(path) != expected:
                    raise FimUnsupportedError("bound source/payload changed")
            return deepcopy(receipt)

        prepared = SimpleNamespace(validate=validate, receipt=receipt, validates=validates)
        prepared_objects.append(prepared)
        return prepared

    monkeypatch.setattr(_one_d, "prepare_one_d_model", prepare)
    monkeypatch.setattr(_coupled, "prepare_coupled_model", prepare)
    return SimpleNamespace(hdf=hdf, terrain=terrain, engine=engine, root=root,
        calls=calls, objects=prepared_objects)


def run(env, **kwargs):
    options = dict(engine_path=env.engine, threads=3, max_working_mib=64)
    options.update(kwargs)
    return adapter.prepare_boundary_xs(env.hdf, env.terrain, env.root,
        {"max": "Max", "saved": 7}, **options)


@pytest.mark.parametrize("scope", ["one_d", "coupled"])
def test_exact_descriptor_profile_order_paths_and_canonical_optin(environment, scope):
    env = environment
    with run(env, scope=scope) as product:
        assert set(product) == {"xs", "receipt", "mesh", "storage"}
        descriptor = product["xs"]
        assert set(descriptor) == {*adapter._COUNTS, *(name + "_file" for name in adapter._FILES),
            "clipping_scope", "profiles"}
        assert descriptor["clipping_scope"] == "levees-and-xs-end-obstructions-only"
        assert [p["id"] for p in descriptor["profiles"]] == ["max", "saved"]
        assert all(Path(descriptor[name + "_file"]).is_absolute() for name in adapter._FILES)
        assert all(Path(p["levels_file"]).is_file() for p in descriptor["profiles"])
        assert env.calls[0][3]["allow_unqualified"] is True
        assert env.calls[0][3]["profiles"] == {"max": "Max", "saved": 7}
        if scope == "coupled":
            assert env.calls[0][3]["engine_path"] == env.engine
            assert env.calls[0][3]["threads"] == 3
            assert Path(product["mesh"]["geometry_file"]).is_absolute()
            assert Path(product["mesh"]["profiles"][0]["values_files"][0]).is_absolute()
            assert product["storage"] is None
        else:
            assert "engine_path" not in env.calls[0][3]
            assert product["mesh"] is None
            assert Path(product["storage"]["polygons"]).is_absolute()
        managed = Path(descriptor["points_file"]).parent
    assert not managed.exists()
    assert len(env.objects[0].validates) >= 3
    assert list(env.root.iterdir()) == [env.root / "unrelated.txt"]


@pytest.mark.parametrize("options", [
    {"scope": "invalid"}, {"threads": 0}, {"threads": 65}, {"threads": True},
    {"max_working_mib": 0}, {"max_working_mib": True},
])
def test_scope_and_resource_refusals_precede_preparation(environment, options):
    with pytest.raises(ValueError):
        with run(environment, **options):
            pytest.fail("invalid inputs yielded")
    assert environment.calls == []
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]


@pytest.mark.parametrize("change", ["source", "payload", "engine"])
def test_changed_bindings_fail_on_exit_and_clean_owned_folder(environment, change):
    env = environment
    with pytest.raises(FimUnsupportedError, match="changed"):
        with run(env) as product:
            path = env.hdf if change == "source" else env.engine if change == "engine" else Path(product["xs"]["points_file"])
            path.write_bytes(b"changed")
    assert list(env.root.iterdir()) == [env.root / "unrelated.txt"]


def test_failure_preserves_original_exception_and_cleans_folder(environment):
    with pytest.raises(KeyboardInterrupt, match="owned failure"):
        with run(environment):
            environment.hdf.write_bytes(b"changed")
            raise KeyboardInterrupt("owned failure")
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]


@pytest.mark.parametrize("mutation", ["source", "profiles", "counts", "payload"])
def test_bad_canonical_receipt_refuses_before_yield(environment, monkeypatch, mutation):
    original = _one_d.prepare_one_d_model

    def prepare(*args, **kwargs):
        prepared = original(*args, **kwargs)
        if mutation == "source":
            prepared.receipt["source_hdf"] = str(environment.terrain)
        elif mutation == "profiles":
            prepared.receipt["profile_ids"].reverse()
        elif mutation == "counts":
            prepared.receipt["point_count"] = True
        else:
            prepared.receipt["files"]["points"] = str(environment.hdf)
        return prepared

    monkeypatch.setattr(_one_d, "prepare_one_d_model", prepare)
    with pytest.raises(FimUnsupportedError):
        with run(environment):
            pytest.fail("invalid receipt yielded")
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]


def test_canonical_preparation_failure_cleans_only_managed_folder(environment, monkeypatch):
    def fail(hdf, terrain, folder, **kwargs):
        folder.mkdir()
        (folder / "partial.bin").write_bytes(b"partial")
        raise FimUnsupportedError("canonical refused unsupported geometry")
    monkeypatch.setattr(_one_d, "prepare_one_d_model", fail)
    with pytest.raises(FimUnsupportedError, match="unsupported geometry"):
        with run(environment):
            pytest.fail("failure yielded")
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]


def test_engine_change_during_preparation_refuses_before_yield(environment, monkeypatch):
    original = _one_d.prepare_one_d_model

    def prepare(*args, **kwargs):
        prepared = original(*args, **kwargs)
        environment.engine.write_bytes(b"changed during preparation")
        return prepared

    monkeypatch.setattr(_one_d, "prepare_one_d_model", prepare)
    with pytest.raises(FimUnsupportedError, match="engine identity changed"):
        with run(environment):
            pytest.fail("changed engine yielded")
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]


def test_canonical_receipt_drift_is_detected_after_use(environment):
    with pytest.raises(FimUnsupportedError, match="receipt changed"):
        with run(environment):
            environment.objects[0].receipt["point_count"] = 4
    assert list(environment.root.iterdir()) == [environment.root / "unrelated.txt"]
