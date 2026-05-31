from ras_commander.sources.base import ModelMetadata, ModelType, SourceStatus
from ras_commander.sources.catalog import ModelCatalog
from ras_commander.sources.federal.noaa_ras2fim import NoaaRas2fimModels
from ras_commander.sources.state.co_champ import _parse_champ_item


def test_model_metadata_accepts_source_optional_fields():
    metadata = ModelMetadata(
        source_name="test",
        source_id="model-1",
        name="Model 1",
        file_size_mb=12.5,
        study_date="2024-01-02",
        last_modified="2024-01-03T04:05:06Z",
        projection="EPSG:4326",
        spatial_extent={"xmin": -90.0, "ymin": 30.0, "xmax": -89.0, "ymax": 31.0},
        effective_date="2024-01-04",
    )

    assert metadata.file_size_mb == 12.5
    assert metadata.study_date == "2024-01-02"
    assert metadata.last_modified == "2024-01-03T04:05:06Z"
    assert metadata.projection == "EPSG:4326"
    assert metadata.spatial_extent["xmin"] == -90.0
    assert metadata.effective_date == "2024-01-04"


def test_source_status_requires_auth_member_exists():
    assert SourceStatus.REQUIRES_AUTH.value == "requires_auth"


def test_colorado_champ_metadata_file_size_regression():
    metadata = _parse_champ_item(
        "12345678-1234-1234-1234-123456789abc",
        {
            "title": "Example HEC-RAS 2D Study",
            "description": {"html": "HEC-RAS 6.0 two-dimensional model"},
            "file": {"fileSizeBytes": 10 * 1024 * 1024},
        },
    )

    assert metadata.file_size_mb == 10.0
    assert metadata.model_type == ModelType.UNSTEADY_2D


def test_noaa_ras2fim_imports_and_lists_catalog_models():
    from ras_commander.sources.federal import NoaaRas2fimModels as FederalNoaaRas2fim

    assert FederalNoaaRas2fim is NoaaRas2fimModels
    models = NoaaRas2fimModels.list_models(limit=2)

    assert len(models) == 2
    assert all(model.source_name == "NOAA ras2fim" for model in models)
    assert all(model.model_type == ModelType.STEADY_1D for model in models)
    assert all(model.url.startswith("s3://noaa-nws-owp-fim/") for model in models)


def test_noaa_ras2fim_catalog_registration_searches_models():
    catalog = ModelCatalog()
    source = NoaaRas2fimModels()

    catalog.register_source(source)
    models = catalog.search_models(sources=[source.source_name], limit_per_source=1)

    assert catalog._source_status[source.source_name] == SourceStatus.REQUIRES_AUTH
    assert len(models) == 1
    assert models[0].source_name == source.source_name
