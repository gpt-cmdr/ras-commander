//! Thin adapter to the pinned freestiler pipeline. Geometry clipping, tile
//! assignment, quantization, compression and archive writing belong upstream.
use freestiler_core::{
    engine::{generate_pmtiles, SilentReporter, TileConfig},
    pmtiles_writer::TileFormat,
    tiler::LayerData,
};

pub(crate) fn write(
    layers: &[LayerData],
    output: &str,
    min_zoom: u8,
    max_zoom: u8,
) -> Result<(), String> {
    let config = TileConfig {
        tile_format: TileFormat::Mvt,
        min_zoom,
        max_zoom,
        base_zoom: None,
        // Preserve the existing packed API's no-simplification configuration.
        // MVT integer quantization and upstream clipping still apply.
        simplification: false,
        drop_rate: None,
        cluster_distance: None,
        cluster_maxzoom: None,
        coalesce: false,
    };
    generate_pmtiles(layers, output, &config, &SilentReporter)
}
