from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts" / "example_library"


def read_script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_ct230_provisioner_uses_status_aware_cache_and_capacity_limits():
    source = read_script("provision_webgis_raster_service.sh")

    assert 'default "no-store";' in source
    assert "max-age=31536000, immutable, no-transform" in source
    assert "current/|catalog\\.json$|example-projects\\.geojson$" in source
    assert "RAS2CNG_RASTER_MAX_CONCURRENT_OPERATIONS=8" in source
    assert "limit_req zone=ras_raster_requests" in source
    assert "limit_conn ras_raster_connections 16" in source
    assert "/ras-raster/ready" in source
    assert "cache-control: no-store" in source


def test_publisher_stages_immutable_release_and_switches_current_atomically():
    source = read_script("clb03_rascommander_webgis_publisher.sh")

    assert '/.incoming/${incoming_name}' in source
    assert "/releases/${release_id}" in source
    assert '--link-dest="$link_destination"' in source
    assert 'mv -T -- "$remote_incoming_path" "$remote_release_path"' in source
    assert 'mv -Tf -- "$temporary_current" "$current_path"' in source
    assert "raster-service-catalog-merge" in source
    assert "--release-id \"$release_id\"" in source
    assert 'python3 "$PUBLIC_VALIDATOR"' in source
    assert "prepare_pointer_backup" in source
    assert "finalize_current_release" in source
    assert "Restored the previous public release pointers" in source
    assert "leaving validated release" not in source
    assert '"${release_dir}/data/rasexamples/"' not in source


def test_clb03_installer_deploys_release_helpers():
    source = read_script("install_clb03_rascommander_webgis_publisher.sh")

    assert "version_webgis_release.py" in source
    assert "validate_public_webgis_release.py" in source
    assert "/usr/local/libexec" in source


def test_library_uses_atomic_current_release_pointer():
    page = (ROOT / "docs" / "examples" / "example-projects.md").read_text(
        encoding="utf-8"
    )
    javascript = (
        ROOT / "docs" / "assets" / "javascripts" / "ras-example-library.js"
    ).read_text(encoding="utf-8")

    expected = "hec-ras-7.0/current/example-projects.geojson"
    assert expected in page
    assert expected in javascript
