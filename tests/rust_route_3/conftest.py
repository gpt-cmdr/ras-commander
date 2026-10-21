def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_pr565: needs ras-commander PR #565 (HdfResultsMesh._mesh_series_id_dim); "
        "skips on bases without it and runs after reconciliation (R2.4)")
