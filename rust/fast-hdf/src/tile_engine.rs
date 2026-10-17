//! Bounded tile orchestration using freestiler kernels with final integer-grid
//! repair inserted before compression/spooling. No dropping or coalescing.
use freestiler_core::{
    clip,
    engine::compute_all_bounds,
    mvt,
    pmtiles_writer::{self, LayerMeta, TileFormat, TileSpool},
    tiler::{self, Feature, LayerData},
};
use rayon::prelude::*;
use std::collections::HashSet;

pub(crate) fn write(
    layers: &[LayerData],
    output: &str,
    min_zoom: u8,
    max_zoom: u8,
) -> Result<(), String> {
    let mut spool = TileSpool::new()?;
    for zoom in min_zoom..=max_zoom {
        let assignments: Vec<_> = layers
            .iter()
            .map(|layer| {
                tiler::assign_features_to_tiles_with_geoms(&layer.features, None, None, zoom)
            })
            .collect();
        let mut coords: Vec<_> = assignments
            .iter()
            .flat_map(|a| a.keys().copied())
            .collect::<HashSet<_>>()
            .into_iter()
            .collect();
        coords.sort_by_key(|c| (c.z, c.x, c.y));
        // Bound encoded working storage independently of the archive tile count.
        for batch in coords.chunks(32) {
            let encoded: Vec<_> = batch
                .par_iter()
                .map(|coord| -> Result<_, String> {
                    let bounds = tiler::tile_bounds(coord);
                    let mut tile_layers = Vec::new();
                    for (layer, map) in layers.iter().zip(&assignments) {
                        let Some(indices) = map.get(coord) else {
                            continue;
                        };
                        let mut features: Vec<_> = indices
                            .par_iter()
                            .filter_map(|&i| {
                                let f = &layer.features[i];
                                clip::clip_geometry_to_tile(&f.geometry, coord).map(|geometry| {
                                    Feature {
                                        id: f.id,
                                        geometry,
                                        properties: f.properties.clone(),
                                    }
                                })
                            })
                            .collect();
                        features.sort_by_cached_key(|f| {
                            (
                                tiler::tile_morton_key(
                                    &f.geometry,
                                    bounds.min().x,
                                    bounds.max().x,
                                    bounds.min().y,
                                    bounds.max().y,
                                ),
                                f.id,
                            )
                        });
                        if !features.is_empty() {
                            tile_layers.push((layer, features));
                        }
                    }
                    if tile_layers.is_empty() {
                        return Ok(None);
                    }
                    let refs: Vec<_> = tile_layers
                        .iter()
                        .map(|(l, f)| (l.name.as_str(), l.prop_names.as_slice(), f.as_slice()))
                        .collect();
                    let encoded = mvt::encode_tile_multilayer(coord, &refs);
                    if encoded.is_empty() {
                        return Ok(None);
                    }
                    let repaired = crate::tile_repair::repair(encoded)
                        .map_err(|e| format!("tile {}/{}/{}: {e}", coord.z, coord.x, coord.y))?;
                    Ok(Some((*coord, pmtiles_writer::gzip_compress(&repaired)?)))
                })
                .collect();
            for tile in encoded {
                if let Some((coord, bytes)) = tile? {
                    spool.write_compressed_tile(coord, &bytes)?;
                }
            }
        }
    }
    let metadata: Vec<_> = layers
        .iter()
        .map(|layer| LayerMeta {
            name: layer.name.clone(),
            property_names: layer.prop_names.clone(),
            property_types: layer.prop_types.clone(),
            min_zoom: layer.min_zoom,
            max_zoom: layer.max_zoom,
            geometry_type: Some("Polygon".to_string()),
        })
        .collect();
    pmtiles_writer::write_pmtiles_from_spool(
        output,
        &mut spool,
        TileFormat::Mvt,
        &metadata,
        min_zoom,
        max_zoom,
        compute_all_bounds(layers),
    )
}
