//! Terrio ownership on an exact admitted grid. Input polygons are validated by the caller.
use crate::MapError;
use std::{
    fs::File,
    io::{BufReader, Read},
    path::Path,
};
use terrio::ops::rasterize::{Grid, RasterizeOptions, rasterize};
use wbraster::{DataType, raster::RasterData};
use wbvector::{Feature, FieldDef, FieldType, FieldValue, Geometry, Layer};

fn invalid(message: &str) -> MapError {
    MapError::Invalid(message.into())
}

// The transport deliberately accepts only little-endian 2D Polygon/MultiPolygon WKB.
// Check counts against remaining bytes before the general WKB decoder allocates vectors.
fn check_wkb(data: &[u8], multipart: bool) -> Result<usize, MapError> {
    if data.len() < 9 || data[0] != 1 {
        return Err(invalid("invalid ownership WKB header"));
    }
    let kind = u32::from_le_bytes(data[1..5].try_into().unwrap());
    let n = u32::from_le_bytes(data[5..9].try_into().unwrap()) as usize;
    let mut pos = 9_usize;
    match kind {
        3 => {
            if n == 0 || n > (data.len() - pos) / 4 {
                return Err(invalid("invalid polygon ring count"));
            }
            for _ in 0..n {
                let raw = data
                    .get(pos..pos + 4)
                    .ok_or_else(|| invalid("truncated ring"))?;
                let points = u32::from_le_bytes(raw.try_into().unwrap()) as usize;
                pos += 4;
                if points < 4 || points > (data.len() - pos) / 16 {
                    return Err(invalid("invalid polygon point count"));
                }
                for pair in data[pos..pos + points * 16].as_chunks::<8>().0 {
                    if !f64::from_le_bytes(*pair).is_finite() {
                        return Err(invalid("nonfinite polygon coordinate"));
                    }
                }
                pos += points * 16;
            }
        }
        6 if multipart => {
            if n == 0 || n > (data.len() - pos) / 9 {
                return Err(invalid("invalid multipolygon count"));
            }
            for _ in 0..n {
                pos += check_wkb(&data[pos..], false)?;
            }
        }
        _ => {
            return Err(invalid(
                "ownership requires 2D Polygons; AOI may be MultiPolygon",
            ));
        }
    }
    Ok(pos)
}

pub fn load(path: &Path, count: usize, multipart: bool) -> Result<Layer, MapError> {
    let mut reader = BufReader::new(File::open(path)?);
    let mut remaining = std::fs::metadata(path)?.len();
    let mut layer = Layer::new("ownership");
    layer
        .schema
        .add_field(FieldDef::new("id", FieldType::Integer));
    for i in 0..count {
        if remaining < 4 {
            return Err(invalid("truncated geometry framing"));
        }
        let mut header = [0; 4];
        reader.read_exact(&mut header)?;
        remaining -= 4;
        let size = u32::from_le_bytes(header) as usize;
        if size as u64 > remaining {
            return Err(invalid("truncated geometry WKB"));
        }
        let mut raw = vec![0; size];
        reader.read_exact(&mut raw)?;
        remaining -= size as u64;
        if check_wkb(&raw, multipart)? != size {
            return Err(invalid("trailing WKB bytes"));
        }
        let g = Geometry::from_wkb(&raw).map_err(|e| MapError::Invalid(e.to_string()))?;
        layer.features.push(Feature {
            fid: i as u64,
            geometry: Some(g),
            attributes: vec![FieldValue::Integer(i as i64 + 1)],
        });
    }
    let mut extra = [0];
    if remaining != 0 || reader.read(&mut extra)? != 0 {
        return Err(invalid("geometry count/length mismatch"));
    }
    Ok(layer)
}

pub fn burn(layer: Layer, grid: Grid) -> Result<Vec<u32>, MapError> {
    let options = RasterizeOptions {
        attribute: Some("id".into()),
        grid: Some(grid),
        data_type: Some(DataType::U32),
        ..Default::default()
    };
    let result = rasterize(&[layer], &options).map_err(|e| MapError::Invalid(e.to_string()))?;
    match result.raster.data {
        RasterData::U32(values) => Ok(values),
        _ => Err(MapError::Internal("unexpected ownership data type".into())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn malformed_counts_rejected_before_decoder_allocation() {
        let mut data = vec![1, 3, 0, 0, 0];
        data.extend(u32::MAX.to_le_bytes());
        assert!(check_wkb(&data, false).is_err());
        assert!(check_wkb(&[0; 16], false).is_err());
    }
}
