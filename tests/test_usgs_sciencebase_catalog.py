from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import RasDss
from ras_commander.RasExamples import RasExamples
from ras_commander.sources.federal.sciencebase_validation import (
    ScienceBaseValidation,
)
from ras_commander.sources.federal.usgs_sciencebase import (
    ScienceBaseInteractiveDownloadRequired,
    UsgsScienceBase,
)


def test_sciencebase_source_is_available_from_public_source_namespaces():
    from ras_commander.sources import UsgsScienceBase as SourcesScienceBase
    from ras_commander.sources.federal import UsgsScienceBase as FederalScienceBase

    assert SourcesScienceBase is UsgsScienceBase
    assert FederalScienceBase is UsgsScienceBase


def test_registry_contains_only_hecras_archives():
    expected = {
        "fox-chain-of-lakes": {
            "sciencebase_id": "661e9565d34e7eb9eb7e3ce4",
            "software": ["HEC-RAS 6.5"],
            "size_bytes": 11_959_830_006,
            "validation_status": "solver_ready",
            "runnable": True,
        },
        "silver-creek-safb": {
            "sciencebase_id": "644c1526d34e45f6ddcd4a3a",
            "software": ["HEC-HMS 4.9", "HEC-RAS 6.5"],
            "size_bytes": 68_546_574_746,
            "validation_status": "validated",
            "runnable": True,
        },
    }

    candidates = UsgsScienceBase.list_models(validated_only=False)
    assert "wabash-srh2d" not in candidates
    assert "upper-illinois-cequalw2" not in candidates
    assert "umrs-inundation" not in candidates

    for slug, assertions in expected.items():
        info = UsgsScienceBase.get_model_info(slug)
        assert info["sciencebase_id"] == assertions["sciencebase_id"]
        assert info["software"] == assertions["software"]
        assert info["ras_compatible"] is True
        assert info["validation"]["status"] == assertions["validation_status"]
        assert info["runnable"] is assertions["runnable"]
        required_file = next(
            file_info
            for file_info in info["files"].values()
            if file_info["required"]
        )
        assert required_file["size_bytes"] == assertions["size_bytes"]


def test_public_catalog_uses_explicit_runnable_promotion_flag():
    public_ids = {
        model.source_id
        for model in UsgsScienceBase.list_catalog_models()
    }
    candidate_models = {
        model.source_id: model
        for model in UsgsScienceBase.list_catalog_models(validated_only=False)
    }

    assert "fox-chain-of-lakes" in public_ids
    assert "silver-creek-safb" in public_ids
    assert "st-joseph" in public_ids
    assert "fox-chain-of-lakes" in candidate_models
    assert candidate_models["fox-chain-of-lakes"].extra["runnable"] is True
    assert (
        candidate_models["fox-chain-of-lakes"].extra["validation"]["status"]
        == "solver_ready"
    )
    assert candidate_models["silver-creek-safb"].extra["runnable"] is True


def test_silver_creek_is_validated_after_registered_dependency_repair():
    info = UsgsScienceBase.get_model_info("silver-creek")
    validation = info["validation"]
    evidence = validation["evidence"]
    compute = evidence["validation_run"]

    assert info["runnable"] is True
    assert info["ras_version"] == "6.6"
    assert info["project_file"] == (
        "model_run_files/HEC-RAS_model/SAFB_RAS2D.prj"
    )
    assert info["archive_prefixes"] == ["model_run_files/HEC-RAS_model"]
    assert validation["status"] == "validated"
    assert validation["paths_validated"] is True
    assert validation["compute_verified"] is True
    assert validation["validated_plan"] == "10"
    assert validation["component_counts"] == {
        "plan": 35,
        "geometry": 8,
        "steady_flow": 0,
        "unsteady_flow": 38,
    }
    assert evidence["path_issue_count"] == 0
    assert evidence["repaired_reference_count"] == 2
    assert evidence["pruned_unsteady_count"] == 3
    assert evidence["dss_preflight"]["series_read"] == 29
    assert evidence["dss_preflight"]["series_failed"] == 0
    assert compute["completed"] is True
    assert compute["error_count"] == 0
    assert compute["warning_count"] == 0
    assert compute["volume_error_percent"] == pytest.approx(0.0014949932)
    assert validation["blockers"] == []


def test_st_joseph_is_validated_after_registered_index_repair():
    info = UsgsScienceBase.get_model_info("st-joseph")
    validation = info["validation"]

    assert validation["status"] == "validated"
    assert validation["paths_validated"] is True
    assert validation["compute_verified"] is True
    assert validation["validated_plan"] == "24"
    assert validation["result_row_count"] == 588
    assert validation["blockers"] == []
    assert len(info["repair"]["expected_missing"]["Plan"]) == 23
    assert len(info["repair"]["expected_missing"]["Geom"]) == 19


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("Fox River", "fox-chain-of-lakes"),
        ("P16H3TDH", "fox-chain-of-lakes"),
        ("Scott AFB", "silver-creek-safb"),
        ("P9GBYP2K", "silver-creek-safb"),
        ("P13CPA5B", "kalamazoo"),
        ("F7QZ2836", "st-joseph"),
    ],
)
def test_sciencebase_aliases(alias, expected):
    assert UsgsScienceBase.normalize_model_key(alias) == expected


@pytest.mark.parametrize(
    "removed_key",
    ["wabash", "srh-2d", "upper-illinois", "ce-qual-w2", "umrs-inundation"],
)
def test_non_hecras_keys_are_not_catalog_aliases(removed_key):
    with pytest.raises(ValueError, match="Unknown ScienceBase model"):
        UsgsScienceBase.normalize_model_key(removed_key)


def test_model_info_returns_nested_copy():
    info = UsgsScienceBase.get_model_info("fox-river")
    info["files"]["model_archive.zip"]["required"] = False
    info["validation"]["status"] = "validated"

    fresh_info = UsgsScienceBase.get_model_info("fox-river")
    assert fresh_info["files"]["model_archive.zip"]["required"] is True
    assert fresh_info["validation"]["status"] == "solver_ready"


def test_fox_river_is_solver_ready_and_publicly_promoted_by_curator():
    info = UsgsScienceBase.get_model_info("fox-river")
    validation = info["validation"]

    assert validation["status"] == "solver_ready"
    assert validation["paths_validated"] is True
    assert validation["compute_verified"] is False
    assert validation["evidence"]["path_issue_count"] == 0
    assert validation["evidence"]["repaired_reference_count"] == 3
    readiness = validation["evidence"]["readiness_run"]
    assert readiness["elapsed_seconds"] == 5877.91
    assert readiness["error_count"] == 0
    assert readiness["warning_count"] == 0
    assert readiness["completed"] is False
    assert info["runnable"] is True
    assert validation["blockers"] == []
    assert validation["caveats"]
    assert validation["public_acceptance"]["full_compute_waived"] is True
    assert info["dss_file"] is True
    assert info["project_file"].endswith("Fox_River_Chain_of_Lakes.prj")


def test_cloud_archive_requests_public_captcha_without_account(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        UsgsScienceBase,
        "_download_file",
        lambda *_args, **_kwargs: pytest.fail("File Manager HTML must not be downloaded"),
    )
    request_url = (
        "https://www.sciencebase.gov/catalog/item/managerRequestDownload/"
        "661e9565d34e7eb9eb7e3ce4?filePath=https%3A%2F%2Fexample.com%2Fmodel.zip"
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "get_download_manifest",
        lambda *_args, **_kwargs: [
            {
                "filename": "model_archive.zip",
                "required": True,
                "size_bytes": 11_959_830_006,
                "destination": str(
                    tmp_path / "fox-chain-of-lakes" / "model_archive.zip"
                ),
                "access": "public_cloud_captcha",
                "download_url": None,
                "request_url": request_url,
            },
            {
                "filename": "Fox_River_Chain_of_Lakes_model_archive.xml",
                "required": False,
                "size_bytes": 18_133,
                "destination": str(
                    tmp_path
                    / "fox-chain-of-lakes"
                    / "Fox_River_Chain_of_Lakes_model_archive.xml"
                ),
                "access": "direct",
                "download_url": "https://example.com/metadata.xml",
                "request_url": None,
            },
        ],
    )

    with pytest.raises(ScienceBaseInteractiveDownloadRequired) as exc_info:
        UsgsScienceBase.download_model(
            "fox-river",
            tmp_path,
            required_only=True,
            extract=False,
        )

    message = str(exc_info.value)
    expected_archive = tmp_path / "fox-chain-of-lakes" / "model_archive.zip"
    assert "public large-file cloud attachment" in message
    assert "account is not required" in message
    assert "interactive CAPTCHA" in message
    assert request_url in message
    assert str(expected_archive) in message
    assert expected_archive.parent.is_dir()
    assert not expected_archive.exists()


def test_direct_attachments_download_before_public_captcha(monkeypatch, tmp_path):
    calls = []
    request_url = (
        "https://www.sciencebase.gov/catalog/item/managerRequestDownload/"
        "661e9565d34e7eb9eb7e3ce4?filePath=https%3A%2F%2Fexample.com%2Fmodel.zip"
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "get_download_manifest",
        lambda *_args, **_kwargs: [
            {
                "filename": "model_archive.zip",
                "required": True,
                "size_bytes": 11_959_830_006,
                "destination": str(
                    tmp_path / "fox-chain-of-lakes" / "model_archive.zip"
                ),
                "access": "public_cloud_captcha",
                "download_url": None,
                "request_url": request_url,
            },
            {
                "filename": "Fox_River_Chain_of_Lakes_model_archive.xml",
                "required": False,
                "size_bytes": 18_133,
                "destination": str(
                    tmp_path
                    / "fox-chain-of-lakes"
                    / "Fox_River_Chain_of_Lakes_model_archive.xml"
                ),
                "access": "direct",
                "download_url": "https://example.com/metadata.xml",
                "request_url": None,
            },
        ],
    )

    def fake_download(url, destination, **_kwargs):
        calls.append((url, Path(destination).name))
        Path(destination).write_bytes(b"metadata")
        return Path(destination)

    monkeypatch.setattr(UsgsScienceBase, "_download_file", fake_download)

    with pytest.raises(ScienceBaseInteractiveDownloadRequired):
        UsgsScienceBase.download_model(
            "fox-river",
            tmp_path,
            extract=False,
        )

    assert calls == [
        (
            "https://example.com/metadata.xml",
            "Fox_River_Chain_of_Lakes_model_archive.xml",
        )
    ]


def test_parse_public_cloud_download_form():
    item_html = """
    <form
      action="/catalog/item/managerRequestDownload/661e9565d34e7eb9eb7e3ce4?filePath=https%3A%2F%2Fprod.example%2Fmodel_archive.zip"
      method="post"
      class="sb-s3file-download-form">
      <button type="submit" class="btn btn-link">model_archive.zip</button>
    </form>
    """

    forms = UsgsScienceBase._parse_cloud_download_forms(
        item_html,
        sciencebase_id="661e9565d34e7eb9eb7e3ce4",
    )

    assert forms == {
        "model_archive.zip": (
            "https://www.sciencebase.gov/catalog/item/managerRequestDownload/"
            "661e9565d34e7eb9eb7e3ce4?filePath=https%3A%2F%2Fprod.example%2Fmodel_archive.zip"
        )
    }


def test_registry_cloud_urls_are_public_catalog_requests():
    for slug, filename in (
        ("fox-river", "model_archive.zip"),
        ("silver-creek", "SilverCreek-SAFB_model_archive.7z"),
    ):
        info = UsgsScienceBase.get_model_info(slug)
        archive = info["files"][filename]
        request_url = UsgsScienceBase._build_public_cloud_request_url(
            info["sciencebase_id"],
            archive["cloud_object_url"],
        )

        assert archive["access"] == "public_cloud_captcha"
        assert request_url.startswith(
            "https://www.sciencebase.gov/catalog/item/managerRequestDownload/"
        )
        assert "sciencebase.usgs.gov/manager" not in request_url


def test_manifest_does_not_refresh_registered_captcha_form(monkeypatch, tmp_path):
    monkeypatch.setattr(UsgsScienceBase, "_get_public_item_files", lambda *_args: {})
    monkeypatch.setattr(
        UsgsScienceBase,
        "_get_public_cloud_download_url",
        lambda *_args, **_kwargs: pytest.fail(
            "registered cloud objects must not trigger a second ScienceBase request"
        ),
    )

    manifest = UsgsScienceBase.get_download_manifest("fox-river", tmp_path)
    archive = next(row for row in manifest if row["filename"] == "model_archive.zip")

    assert archive["access"] == "public_cloud_captcha"
    assert archive["request_url"].startswith(
        "https://www.sciencebase.gov/catalog/item/managerRequestDownload/"
    )
    assert "model_archive.zip" in archive["request_url"]


@pytest.mark.parametrize(
    "member_name",
    [
        "../outside.prj",
        r"model\..\outside.prj",
        r"C:\outside.prj",
        r"\\server\share\outside.prj",
    ],
)
def test_archive_member_validation_rejects_unsafe_paths(tmp_path, member_name):
    with pytest.raises(RuntimeError, match="Unsafe archive member path"):
        UsgsScienceBase._validated_archive_targets([member_name], tmp_path)


def test_archive_member_validation_does_not_resolve_each_target(monkeypatch, tmp_path):
    def fail_if_resolved(*_args, **_kwargs):
        raise AssertionError("archive target validation must remain lexical")

    monkeypatch.setattr(Path, "resolve", fail_if_resolved)

    targets = UsgsScienceBase._validated_archive_targets(
        [r"RAS Model\SilverCreek.prj"],
        tmp_path / "mapped-drive",
    )

    target = targets[r"RAS Model\SilverCreek.prj"]
    assert target.name == "SilverCreek.prj"
    assert target.parent.name == "RAS Model"


def test_7z_listing_parser_returns_only_archive_members():
    listing = """
--
Path = SilverCreek.7z
Type = 7z
Physical Size = 1234

----------
Path = RAS Model
Size = 0
Folder = +

Path = RAS Model\\SilverCreek.prj
Size = 4
Folder = -
"""

    records = UsgsScienceBase._parse_7z_listing(listing)

    assert [record["Path"] for record in records] == [
        "RAS Model",
        r"RAS Model\SilverCreek.prj",
    ]
    assert records[1]["Size"] == "4"


def test_7z_extraction_is_verified_and_idempotent(monkeypatch, tmp_path):
    archive_path = tmp_path / "SilverCreek.7z"
    archive_path.write_bytes(b"archive")
    destination = tmp_path / "extracted"
    destination.mkdir()
    listing = """
----------
Path = RAS Model
Size = 0
Folder = +

Path = RAS Model\\SilverCreek.prj
Size = 4
Folder = -
"""
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "l":
            return SimpleNamespace(returncode=0, stdout=listing, stderr="")
        model_dir = destination / "RAS Model"
        model_dir.mkdir(exist_ok=True)
        (model_dir / "SilverCreek.prj").write_bytes(b"test")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        UsgsScienceBase,
        "_find_7zip",
        lambda: Path(r"C:\Program Files\7-Zip\7z.exe"),
    )
    monkeypatch.setattr(
        "ras_commander.sources.federal.usgs_sciencebase.subprocess.run",
        fake_run,
    )

    UsgsScienceBase._extract_7z_archive(archive_path, destination)
    UsgsScienceBase._extract_7z_archive(archive_path, destination)

    assert sum(command[1] == "x" for command in calls) == 1
    assert (destination / "RAS Model" / "SilverCreek.prj").read_bytes() == b"test"


def test_7z_selective_extraction_uses_exact_utf8_member_list(
    monkeypatch,
    tmp_path,
):
    archive_path = tmp_path / "SilverCreek.7z"
    archive_path.write_bytes(b"archive")
    destination = tmp_path / "extracted"
    destination.mkdir()
    listing = r"""
----------
Path = model_run_files\HEC-RAS_model\SilverCreek.prj
Size = 4
Folder = -

Path = model_run_files\HEC-HMS_model\SilverCreek.hms
Size = 3
Folder = -
"""
    selected_members = []

    def fake_run(command, **_kwargs):
        if command[1] == "l":
            return SimpleNamespace(returncode=0, stdout=listing, stderr="")
        list_argument = next(part for part in command if str(part).startswith("@"))
        selected_members.extend(
            Path(str(list_argument)[1:]).read_text(encoding="utf-8").splitlines()
        )
        project = (
            destination
            / "model_run_files"
            / "HEC-RAS_model"
            / "SilverCreek.prj"
        )
        project.parent.mkdir(parents=True)
        project.write_bytes(b"test")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        UsgsScienceBase,
        "_find_7zip",
        lambda: Path(r"C:\Program Files\7-Zip\7z.exe"),
    )
    monkeypatch.setattr(
        "ras_commander.sources.federal.usgs_sciencebase.subprocess.run",
        fake_run,
    )

    UsgsScienceBase._extract_7z_archive(
        archive_path,
        destination,
        include_prefixes=[r"model_run_files\HEC-RAS_model"],
    )

    assert selected_members == [
        r"model_run_files\HEC-RAS_model\SilverCreek.prj"
    ]


def test_extract_local_model_accepts_external_archive_staging(
    monkeypatch,
    tmp_path,
):
    model_dir = tmp_path / "silver-creek-safb"
    model_dir.mkdir()
    archive_dir = tmp_path / "staging"
    archive_dir.mkdir()
    archive_path = archive_dir / "SilverCreek-SAFB_model_archive.7z"
    archive_path.write_bytes(b"archive")
    info = deepcopy(UsgsScienceBase._MODEL_REGISTRY["silver-creek-safb"])
    info.pop("repair", None)
    info["files"] = {
        archive_path.name: {
            "required": True,
            "size_bytes": archive_path.stat().st_size,
        }
    }
    extracted = []
    organized = []
    monkeypatch.setitem(
        UsgsScienceBase._MODEL_REGISTRY,
        "silver-creek-safb",
        info,
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "_extract_7z_archive",
        lambda path, destination, **kwargs: extracted.append(
            (path, destination, kwargs)
        ),
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "organize_model",
        lambda *args, **kwargs: organized.append((args, kwargs)),
    )

    result = UsgsScienceBase.extract_local_model(
        "silver-creek",
        tmp_path,
        organize=True,
        archive_dir=archive_dir,
        archive_prefixes=[r"model_run_files\HEC-RAS_model"],
    )

    assert result == model_dir
    assert extracted == [
        (
            archive_path,
            model_dir,
            {"include_prefixes": [r"model_run_files\HEC-RAS_model"]},
        )
    ]
    assert organized == [
        (("silver-creek-safb", tmp_path), {"archive_dir": archive_dir})
    ]


def test_download_model_uses_registered_ras_only_archive_prefixes(
    monkeypatch,
    tmp_path,
):
    filename = "SilverCreek-SAFB_model_archive.7z"
    model_dir = tmp_path / "silver-creek-safb"
    archive_path = model_dir / filename
    info = deepcopy(UsgsScienceBase._MODEL_REGISTRY["silver-creek-safb"])
    info["files"] = {
        filename: {
            "required": True,
            "size_mb": 0.000007,
            "size_bytes": 7,
            "access": "direct",
        }
    }
    monkeypatch.setitem(
        UsgsScienceBase._MODEL_REGISTRY,
        "silver-creek-safb",
        info,
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "get_download_manifest",
        lambda *_args, **_kwargs: [
            {
                "filename": filename,
                "required": True,
                "size_bytes": 7,
                "destination": str(archive_path),
                "access": "direct",
                "download_url": "https://example.test/silver.7z",
                "request_url": None,
            }
        ],
    )
    monkeypatch.setattr(
        UsgsScienceBase,
        "_download_file",
        lambda _url, destination, **_kwargs: Path(destination).write_bytes(
            b"archive"
        ),
    )
    extracted = []
    monkeypatch.setattr(
        UsgsScienceBase,
        "extract_local_model",
        lambda *args, **kwargs: extracted.append((args, kwargs)),
    )

    result = UsgsScienceBase.download_model("silver-creek", tmp_path)

    assert result == model_dir
    assert extracted == [
        (
            (("silver-creek-safb", tmp_path)),
            {
                "organize": True,
                "archive_prefixes": ["model_run_files/HEC-RAS_model"],
            },
        )
    ]


def test_extract_local_model_is_offline_and_checks_archive_size(monkeypatch, tmp_path):
    model_dir = tmp_path / "fox-chain-of-lakes"
    model_dir.mkdir()
    archive_path = model_dir / "model_archive.zip"
    archive_path.write_bytes(b"short")
    monkeypatch.setattr(
        UsgsScienceBase,
        "get_download_manifest",
        lambda *_args, **_kwargs: pytest.fail("offline extraction must not use ScienceBase"),
    )

    with pytest.raises(RuntimeError, match="Local byte count"):
        UsgsScienceBase.extract_local_model(
            "fox-river",
            tmp_path,
            organize=False,
        )


def test_unknown_ras_project_path_is_discovered_after_manual_extraction(tmp_path):
    project_file = (
        tmp_path
        / "fox-chain-of-lakes"
        / "model"
        / "ChainOfLakes.prj"
    )
    project_file.parent.mkdir(parents=True)
    project_file.write_text("Proj Title=Chain of Lakes\n", encoding="utf-8")
    (project_file.parent / "Terrain.prj").write_text(
        'PROJCS["NAD_1983_StatePlane_Illinois_East"]\n',
        encoding="utf-8",
    )

    assert UsgsScienceBase.get_project_path("fox-river", tmp_path) == project_file


def test_fox_registered_repair_replaces_only_the_missing_dss_dependency(
    monkeypatch,
    tmp_path,
):
    model_dir = tmp_path / "fox-chain-of-lakes"
    project_dir = model_dir / "published-layout"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "Fox.prj"
    project_file.write_text("Proj Title=Fox\n", encoding="ascii")
    unsteady_file = project_dir / "Fox.u01"
    old_line = (
        "DSS File=.\\Hydrology\\"
        "Fox_River_ILUSGS_Data_Request_2019_2022_part3.dss"
    )
    new_line = "DSS File=.\\Hydrology\\Fox_River_USGS_Data_Request.dss"
    unsteady_file.write_bytes(((old_line + "\r\n") * 3).encode("ascii"))
    hydrology_dir = project_dir / "Hydrology"
    hydrology_dir.mkdir()
    (hydrology_dir / "Fox_River_USGS_Data_Request.dss").write_bytes(b"dss")

    def fake_init(_project_file, _version, *, ras_object, **_kwargs):
        ras_object.unsteady_df = pd.DataFrame(
            [{"unsteady_number": "01", "full_path": unsteady_file}]
        )
        return ras_object

    monkeypatch.setattr("ras_commander.init_ras_project", fake_init)
    monkeypatch.setattr(
        ScienceBaseValidation,
        "inspect_project",
        lambda *_args, **_kwargs: {
            "paths_validated": True,
            "status": "passed",
            "issues": [],
        },
    )

    applied = UsgsScienceBase.repair_local_model("fox-river", tmp_path)
    repaired = unsteady_file.read_bytes().decode("ascii")

    assert applied["repair_status"] == "applied"
    assert applied["replaced_dependency"]["occurrences"] == 3
    assert old_line not in repaired
    assert repaired.count(new_line) == 3
    assert Path(applied["repair_artifact"]).is_file()

    repeated = UsgsScienceBase.repair_local_model("fox-river", tmp_path)
    assert repeated["repair_status"] == "already_applied"


def test_silver_registered_repair_redirects_retained_plan_and_prunes_orphans(
    monkeypatch,
    tmp_path,
):
    model_dir = tmp_path / "silver-creek-safb"
    project_dir = model_dir / "model_run_files" / "HEC-RAS_model"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "SAFB_RAS2D.prj"
    project_file.write_text(
        "Proj Title=Silver Creek\n"
        "Plan File=p07\n"
        "Unsteady File=u04\n"
        "Unsteady File=u05\n"
        "Unsteady File=u08\n"
        "Unsteady File=u09\n",
        encoding="ascii",
    )
    repair = UsgsScienceBase._MODEL_REGISTRY["silver-creek-safb"]["repair"]
    replacement = repair["replacements"][0]
    unsteady_files = {}
    for number in ("04", "05", "08", "09"):
        unsteady_file = project_dir / f"SAFB_RAS2D.u{number}"
        payload = (
            (
                (replacement["new_text"] + "\r\n")
                * replacement["expected_existing_new_occurrences"]
                + (replacement["old_text"] + "\r\n")
                * replacement["expected_occurrences"]
            )
            if number == "04"
            else "Flow Title=Unused\r\n"
        )
        unsteady_file.write_bytes(payload.encode("ascii"))
        unsteady_files[number] = unsteady_file
    dependency_path = project_dir / replacement["new_dependency"]
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_bytes(b"dss")

    def fake_init(_project_file, _version, *, ras_object, **_kwargs):
        project_lines = project_file.read_text(encoding="ascii").splitlines()
        present = [
            line.rsplit("u", 1)[-1]
            for line in project_lines
            if line.startswith("Unsteady File=u")
        ]
        ras_object.initialized = True
        ras_object.plan_df = pd.DataFrame(
            [{"plan_number": "07", "unsteady_number": "04"}]
        )
        ras_object.unsteady_df = pd.DataFrame(
            [
                {
                    "unsteady_number": number,
                    "full_path": unsteady_files[number],
                }
                for number in present
            ]
        )
        return ras_object

    monkeypatch.setattr("ras_commander.init_ras_project", fake_init)
    monkeypatch.setattr(
        ScienceBaseValidation,
        "inspect_project",
        lambda *_args, **_kwargs: {
            "paths_validated": True,
            "status": "passed",
            "issues": [],
        },
    )
    monkeypatch.setattr(
        RasDss,
        "check_pathname",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_valid=True,
            summary="validated",
        ),
    )

    applied = UsgsScienceBase.repair_local_model("silver-creek", tmp_path)
    repaired = unsteady_files["04"].read_bytes().decode("ascii")
    project_text = project_file.read_text(encoding="ascii")

    assert applied["repair_status"] == "applied"
    assert applied["removed_entries"] == {"Unsteady": ["05", "08", "09"]}
    assert len(applied["validated_dss_pathnames"]) == 2
    assert replacement["old_text"] not in repaired
    assert repaired.count(replacement["new_text"]) == 27
    assert "Unsteady File=u04" in project_text
    assert "Unsteady File=u05" not in project_text
    assert "Unsteady File=u08" not in project_text
    assert "Unsteady File=u09" not in project_text

    repeated = UsgsScienceBase.repair_local_model("silver-creek", tmp_path)
    assert repeated["repair_status"] == "already_applied"
    assert repeated["removed_entries"] == {"Unsteady": []}


def test_archive_inspection_aggregates_every_discovered_project(monkeypatch, tmp_path):
    project_a = tmp_path / "A" / "a.prj"
    project_b = tmp_path / "B" / "b.prj"
    monkeypatch.setattr(
        "ras_commander.sources.federal.sciencebase_validation."
        "RasUtils.find_valid_ras_folders",
        lambda *_args, **_kwargs: [
            {"prj_file": project_a, "plan_count": 2},
            {"prj_file": project_b, "plan_count": 1},
        ],
    )

    def fake_inspection(project_file, *_args, **_kwargs):
        passed = Path(project_file) == project_a
        return {
            "project_file": str(project_file),
            "paths_validated": passed,
            "status": "passed" if passed else "failed",
            "component_counts": {
                "plan": 2 if passed else 1,
                "geometry": 1,
                "steady_flow": 0,
                "unsteady_flow": 1,
            },
            "runnable_plans": ["01"] if passed else [],
            "issues": [] if passed else [
                {
                    "code": "missing_path",
                    "kind": "terrain",
                    "owner": str(project_file),
                    "path": "missing.hdf",
                }
            ],
        }

    monkeypatch.setattr(ScienceBaseValidation, "inspect_project", fake_inspection)

    report = ScienceBaseValidation.inspect_archive(
        tmp_path,
        "6.5",
        model_slug="test",
    )

    assert report["status"] == "failed"
    assert report["project_count"] == 2
    assert report["component_counts"]["plan"] == 3
    assert report["issue_count"] == 1
    assert report["issues"][0]["project_file"] == str(project_b)


def test_organize_model_preserves_tree_and_writes_ebfe_style_artifacts(
    monkeypatch,
    tmp_path,
):
    model_dir = tmp_path / "fox-chain-of-lakes"
    project_file = model_dir / "published-layout" / "fox.prj"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("Proj Title=Fox\n", encoding="utf-8")
    repair_report = model_dir / "agent" / "repair_report.json"
    repair_report.parent.mkdir()
    repair_report.write_text(
        '{"repair_status": "applied"}',
        encoding="utf-8",
    )
    archive_dir = tmp_path / "archive-staging"
    archive_dir.mkdir()
    archive_path = archive_dir / "model_archive.zip"
    archive_path.write_bytes(b"archive")
    info = deepcopy(UsgsScienceBase._MODEL_REGISTRY["fox-chain-of-lakes"])
    info["files"] = {
        archive_path.name: {
            "required": True,
            "size_bytes": archive_path.stat().st_size,
        }
    }
    monkeypatch.setitem(
        UsgsScienceBase._MODEL_REGISTRY,
        "fox-chain-of-lakes",
        info,
    )

    def fake_archive_inspection(*_args, report_path=None, **_kwargs):
        report = {
            "schema_version": 1,
            "model_slug": "fox-chain-of-lakes",
            "archive_root": str(model_dir),
            "ras_version": "6.5",
            "inspected_at": "2026-07-17T00:00:00+00:00",
            "status": "passed",
            "paths_validated": True,
            "project_count": 1,
            "component_counts": {
                "plan": 1,
                "geometry": 1,
                "steady_flow": 0,
                "unsteady_flow": 1,
            },
            "issue_count": 0,
            "issues": [],
            "projects": [
                {
                    "project_file": str(project_file),
                    "paths_validated": True,
                    "component_counts": {
                        "plan": 1,
                        "geometry": 1,
                        "steady_flow": 0,
                        "unsteady_flow": 1,
                    },
                    "runnable_plans": ["01"],
                    "issues": [],
                }
            ],
        }
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text("{}", encoding="utf-8")
        return report

    monkeypatch.setattr(
        ScienceBaseValidation,
        "inspect_archive",
        fake_archive_inspection,
    )

    report = UsgsScienceBase.organize_model(
        "fox-river",
        tmp_path,
        strict=True,
        archive_dir=archive_dir,
    )

    assert project_file.is_file()
    assert report["paths_validated"] is True
    assert (model_dir / "MANIFEST.md").is_file()
    assert (model_dir / "agent" / "model_log.md").is_file()
    assert (model_dir / "agent" / "validation_report.md").is_file()
    manifest = (model_dir / "MANIFEST.md").read_text(encoding="utf-8")
    audit_json = (model_dir / "agent" / "sciencebase_archive_validation.json").read_text(
        encoding="utf-8"
    )
    assert "source hierarchy preserved in place" in manifest
    assert "verified external staging" in manifest
    assert "agent/repair_report.json" in manifest
    model_log = (model_dir / "agent" / "model_log.md").read_text(encoding="utf-8")
    assert "Registered repair: `applied`" in model_log
    assert "`published-layout/fox.prj`" in manifest
    assert '"artifacts"' in audit_json


def test_dataframe_inspection_blocks_missing_plan_dependencies(tmp_path):
    plan = tmp_path / "model.p01"
    geom = tmp_path / "model.g01"
    plan.write_text("Plan Title=Test\n", encoding="utf-8")
    geom.write_text("Geom Title=Test\n", encoding="utf-8")

    ras_obj = SimpleNamespace(
        plan_df=pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "full_path": str(plan),
                    "Geom File": "01",
                    "Geom Path": str(geom),
                    "Flow File": "01",
                    "Flow Path": str(tmp_path / "missing.u01"),
                }
            ]
        ),
        geom_df=pd.DataFrame([{"full_path": str(geom)}]),
        flow_df=pd.DataFrame(),
        unsteady_df=pd.DataFrame(),
    )
    issues = []

    runnable, counts = ScienceBaseValidation._inspect_dataframe_paths(
        ras_obj,
        issues,
        tmp_path,
    )

    assert runnable == []
    assert counts["plan"] == 1
    assert any(
        issue["kind"] == "plan_flow" and issue["code"] == "missing_path"
        for issue in issues
    )


def test_dependency_inspection_rejects_absolute_and_external_paths(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    owner = project_root / "model.u01"
    owner.write_text("Flow Title=Test\n", encoding="utf-8")
    external = tmp_path / "outside.dss"
    external.write_text("dss", encoding="utf-8")
    issues = []

    ScienceBaseValidation._add_dependency_issue(
        issues,
        kind="boundary_dss",
        raw_path=external,
        resolved_path=external,
        owner=owner,
        project_root=project_root,
    )

    assert {issue["code"] for issue in issues} == {
        "absolute_reference",
        "external_reference",
    }


def test_validation_containment_does_not_resolve_mapped_paths(monkeypatch, tmp_path):
    def fail_if_resolved(*_args, **_kwargs):
        raise AssertionError("containment validation must remain lexical")

    monkeypatch.setattr(Path, "resolve", fail_if_resolved)
    project_root = tmp_path / "mapped-drive" / "project"

    assert ScienceBaseValidation._is_within(
        project_root / "model" / "plan.p01",
        project_root,
    )
    assert not ScienceBaseValidation._is_within(
        project_root.parent / "outside.dss",
        project_root,
    )


def test_verified_compute_requires_isolated_empty_output(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "model.prj"
    project_file.write_text("Proj Title=Test\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the source archive"):
        ScienceBaseValidation.run_verified_compute(
            project_file,
            "6.5",
            "01",
            project_root / "validation",
        )

    occupied = tmp_path / "validation"
    occupied.mkdir()
    (occupied / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError, match="new or empty isolated"):
        ScienceBaseValidation.run_verified_compute(
            project_file,
            "6.5",
            "01",
            occupied,
        )


def test_blocked_inspection_writes_audit_report(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "model.prj"
    project_file.write_text("Proj Title=Test\n", encoding="utf-8")
    output = tmp_path / "validation"
    issue = {
        "code": "missing_path",
        "kind": "plan_geometry",
        "owner": str(project_file),
        "path": "missing.g01",
    }
    monkeypatch.setattr(
        ScienceBaseValidation,
        "inspect_project",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "model_slug": "test",
            "project_file": str(project_file),
            "archive_root": str(project_root),
            "ras_version": "6.5",
            "inspected_at": "2026-07-17T00:00:00+00:00",
            "paths_validated": False,
            "status": "failed",
            "component_counts": {},
            "runnable_plans": [],
            "issues": [issue],
        },
    )

    report = ScienceBaseValidation.run_verified_compute(
        project_file,
        "6.5",
        "01",
        output,
        model_slug="test",
        archive_root=project_root,
    )

    report_path = output / ScienceBaseValidation.REPORT_FILENAME
    assert report["status"] == "blocked"
    assert report["issues"] == [issue]
    assert report_path.is_file()
    assert '"status": "blocked"' in report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("ras_version", "expected_backend"),
    [("4.1", "RasControl"), ("6.5", "RasCmdr")],
)
def test_verified_compute_routes_by_hecras_major_version(
    monkeypatch,
    tmp_path,
    ras_version,
    expected_backend,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "model.prj"
    project_file.write_text("Proj Title=Test\n", encoding="utf-8")
    output = tmp_path / "validation"
    monkeypatch.setattr(
        ScienceBaseValidation,
        "inspect_project",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "model_slug": "test",
            "project_file": str(project_file),
            "archive_root": str(project_root),
            "ras_version": ras_version,
            "inspected_at": "2026-07-17T00:00:00+00:00",
            "paths_validated": True,
            "status": "passed",
            "component_counts": {},
            "runnable_plans": ["01"],
            "issues": [],
        },
    )

    calls = []

    def fake_legacy(*_args):
        calls.append("RasControl")
        output.mkdir(parents=True)
        return True, {"execution_backend": "RasControl"}

    def fake_modern(*_args):
        calls.append("RasCmdr")
        output.mkdir(parents=True)
        return True, {"execution_backend": "RasCmdr"}

    monkeypatch.setattr(ScienceBaseValidation, "_run_legacy_compute", fake_legacy)
    monkeypatch.setattr(ScienceBaseValidation, "_run_modern_compute", fake_modern)

    report = ScienceBaseValidation.run_verified_compute(
        project_file,
        ras_version,
        "01",
        output,
        model_slug="test",
        archive_root=project_root,
    )

    assert report["status"] == "validated"
    assert report["compute_verified"] is True
    assert report["compute"]["execution_backend"] == expected_backend
    assert calls == [expected_backend]


def test_modern_compute_reports_missing_result_hdf_without_crashing(
    monkeypatch,
    tmp_path,
):
    project_file = tmp_path / "source" / "model.prj"
    project_file.parent.mkdir()
    project_file.write_text("Proj Title=Test\n", encoding="utf-8")
    output = tmp_path / "validation"
    output.mkdir()
    output_plan = output / "model.p01"
    output_plan.write_text("Plan Title=Test\n", encoding="utf-8")
    missing_hdf = output / "model.p01.hdf"

    def fake_init(_path, _version, *, ras_object, **_kwargs):
        ras_object.project_name = "model"
        ras_object.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "full_path": output_plan,
                    "HDF_Results_Path": missing_hdf,
                }
            ]
        )
        return ras_object

    monkeypatch.setattr(
        "ras_commander.sources.federal.sciencebase_validation.init_ras_project",
        fake_init,
    )
    monkeypatch.setattr(
        "ras_commander.sources.federal.sciencebase_validation.RasCmdr.compute_plan",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "ras_commander.sources.federal.sciencebase_validation."
        "HdfResultsPlan.get_compute_messages",
        lambda *_args, **_kwargs: pytest.fail("missing HDF must not be opened"),
    )

    verified, compute = ScienceBaseValidation._run_modern_compute(
        project_file,
        "6.5",
        "01",
        output,
        2,
    )

    assert verified is False
    assert compute["result_hdf_exists"] is False
    assert compute["message_line_count"] == 0
    assert compute["runtime"] is None


def test_rasexamples_facade_lists_promoted_models_and_blocks_candidates(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        RasExamples,
        "_load_project_data",
        lambda *_args, **_kwargs: pytest.fail("HEC example ZIP should not initialize"),
    )

    public_models = RasExamples.list_sciencebase_models()

    assert {model.source_id for model in public_models} == {
        "fox-chain-of-lakes",
        "kalamazoo",
        "silver-creek-safb",
        "st-joseph",
    }

    with pytest.raises(RuntimeError, match="has not been promoted"):
        RasExamples.download_sciencebase_model("squannacook", output_path=tmp_path)


def test_rasexamples_download_facade_forwards_temporary_url(monkeypatch, tmp_path):
    expected = tmp_path / "kalamazoo"
    calls = []

    def fake_download(model_key, output_dir, **kwargs):
        calls.append((model_key, output_dir, kwargs))
        return expected

    monkeypatch.setattr(UsgsScienceBase, "download_model", fake_download)
    result = RasExamples.download_sciencebase_model(
        "kalamazoo",
        output_path=tmp_path,
        signed_download_urls={"hec_ras_model.zip": "https://temporary.example"},
    )

    assert result == expected
    assert calls[0][2]["signed_download_urls"] == {
        "hec_ras_model.zip": "https://temporary.example"
    }


def test_rasexamples_validation_facade_delegates(monkeypatch, tmp_path):
    expected = {"status": "validated", "compute_verified": True}
    calls = []

    def fake_validation(model_key, base_dir, plan_number, output_dir, **kwargs):
        calls.append((model_key, base_dir, plan_number, output_dir, kwargs))
        return expected

    monkeypatch.setattr(UsgsScienceBase, "run_validation_plan", fake_validation)
    result = RasExamples.validate_sciencebase_model(
        "fox-river",
        tmp_path / "models",
        "01",
        tmp_path / "validation",
        num_cores=2,
    )

    assert result == expected
    assert calls == [
        (
            "fox-river",
            tmp_path / "models",
            "01",
            tmp_path / "validation",
            {"project_file": None, "ras_version": None, "num_cores": 2},
        )
    ]
