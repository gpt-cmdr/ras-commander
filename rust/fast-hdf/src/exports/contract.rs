//! Contract v1: XY OGC WKB + nullable typed Arrow fields; no implicit CRS defaults.
use crate::{fail, Result};
use arrow_array::{Array, BinaryArray, Float64Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, SchemaRef, TimeUnit};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub const CONTRACT_KEY: &str = "ras:export:v1";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Crs {
    pub wkt: String,
    pub projjson: serde_json::Value,
    pub units: String,
    /// All geometry buffers use x/y, regardless of authority axis ordering.
    pub axis_order: String,
    /// Filled only after semantic CRS comparison at the pyproj/resolver boundary.
    pub resolved: bool,
    /// True only for WGS84 longitude/latitude coordinates, after transformation.
    pub geographic_wgs84: bool,
}

pub struct Contract {
    pub schema: SchemaRef,
    pub crs: Crs,
    pub geometry: usize,
}
impl Contract {
    pub fn new(schema: SchemaRef) -> Result<Self> {
        let crs: Crs = serde_json::from_str(
            schema
                .metadata()
                .get(CONTRACT_KEY)
                .ok_or_else(|| fail("missing resolved source CRS contract"))?,
        )?;
        if !crs.resolved
            || crs.wkt.trim().is_empty()
            || crs.units.trim().is_empty()
            || !crs.projjson.is_object()
            || crs.axis_order != "xy"
        {
            return Err(fail(
                "CRS evidence unresolved, missing or unsupported axis order",
            ));
        }
        let mut names = HashSet::new();
        for field in schema.fields() {
            if field.name().is_empty()
                || field.name().contains('\0')
                || !names.insert(field.name().to_lowercase())
            {
                return Err(fail("empty/NUL/duplicate case-insensitive field name"));
            }
            if ["fid", "_ras_fid"].contains(&field.name().to_lowercase().as_str()) {
                return Err(fail("reserved GeoPackage primary key name"));
            }
            if !matches!(
                field.data_type(),
                DataType::Int64
                    | DataType::UInt64
                    | DataType::Float64
                    | DataType::Boolean
                    | DataType::Utf8
                    | DataType::Binary
                    | DataType::Timestamp(TimeUnit::Millisecond, None)
            ) {
                return Err(fail(format!(
                    "unsupported field type: {}",
                    field.data_type()
                )));
            }
        }
        for (name, dtype) in [
            ("mesh_name", DataType::Utf8),
            ("cell_id", DataType::Int64),
            ("geometry", DataType::Binary),
        ] {
            let f = schema.field_with_name(name)?;
            if f.data_type() != &dtype {
                return Err(fail(format!("{name} has incorrect type")));
            }
            if name != "geometry" && f.is_nullable() {
                return Err(fail("identity fields must be nonnullable"));
            }
        }
        let geometry = schema.index_of("geometry")?;
        let field = schema.field(geometry);
        if field
            .metadata()
            .get("ARROW:extension:name")
            .map(String::as_str)
            != Some("geoarrow.wkb")
        {
            return Err(fail("geometry requires geoarrow.wkb extension"));
        }
        let geo: serde_json::Value = serde_json::from_str(
            field
                .metadata()
                .get("ARROW:extension:metadata")
                .ok_or_else(|| fail("missing GeoArrow CRS"))?,
        )?;
        if geo.get("crs_type").and_then(|v| v.as_str()) != Some("projjson")
            || geo.get("crs") != Some(&crs.projjson)
        {
            return Err(fail("conflicting GeoArrow and source CRS"));
        }
        Ok(Self {
            schema,
            crs,
            geometry,
        })
    }

    pub fn validate(&self, batch: &RecordBatch, max: usize) -> Result<()> {
        if batch.schema() != self.schema {
            return Err(fail("batch schema mismatch"));
        }
        if batch.num_rows() > max {
            return Err(fail("batch exceeds max_batch_rows"));
        }
        let meshes = batch
            .column_by_name("mesh_name")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        let cells = batch
            .column_by_name("cell_id")
            .unwrap()
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        let mut identities = HashSet::new();
        for row in 0..batch.num_rows() {
            if meshes.is_null(row)
                || cells.is_null(row)
                || meshes.value(row).is_empty()
                || cells.value(row) < 0
                || !identities.insert((meshes.value(row), cells.value(row)))
            {
                return Err(fail(
                    "null/empty/negative or duplicate within-batch composite identity",
                ));
            }
        }
        for (field, array) in self.schema.fields().iter().zip(batch.columns()) {
            if !field.is_nullable() && array.null_count() > 0 {
                return Err(fail("null in nonnullable field"));
            }
            if let Some(values) = array.as_any().downcast_ref::<Float64Array>() {
                if values.iter().flatten().any(|v| !v.is_finite()) {
                    return Err(fail("nonfinite attribute: supply null explicitly"));
                }
            }
        }
        let geometry = batch
            .column(self.geometry)
            .as_any()
            .downcast_ref::<BinaryArray>()
            .unwrap();
        for wkb in geometry.iter().flatten() {
            validate_wkb(wkb, self.crs.geographic_wgs84)?;
        }
        Ok(())
    }
}

// Bound-check before third-party decoders. Reject EWKB/SRID, Z/M, collections,
// nonfinite coordinates, unclosed/undersized rings and trailing/truncated input.
// Full topology validity remains the source geometry producer's responsibility.
pub fn validate_wkb(bytes: &[u8], geographic: bool) -> Result<()> {
    validate_wkb_profile(bytes, geographic, false, false)
}

pub fn validate_geojson_wkb(bytes: &[u8]) -> Result<()> {
    validate_wkb_profile(bytes, true, true, false)
}

pub fn validate_flatgeobuf_wkb(bytes: &[u8]) -> Result<()> {
    validate_wkb_profile(bytes, false, false, true)
}

fn validate_wkb_profile(
    bytes: &[u8],
    geographic: bool,
    winding: bool,
    reject_empty: bool,
) -> Result<()> {
    struct Reader<'a> {
        bytes: &'a [u8],
        pos: usize,
        geographic: bool,
        winding: bool,
        reject_empty: bool,
    }
    impl Reader<'_> {
        fn read<const N: usize>(&mut self) -> Result<[u8; N]> {
            let end = self
                .pos
                .checked_add(N)
                .ok_or_else(|| fail("WKB overflow"))?;
            let slice = self
                .bytes
                .get(self.pos..end)
                .ok_or_else(|| fail("truncated WKB"))?;
            self.pos = end;
            Ok(slice.try_into()?)
        }
        fn uint(&mut self, le: bool) -> Result<usize> {
            let b = self.read()?;
            Ok(if le {
                u32::from_le_bytes(b)
            } else {
                u32::from_be_bytes(b)
            } as usize)
        }
        fn xy(&mut self, le: bool) -> Result<[f64; 2]> {
            let mut xy = [0.; 2];
            for v in &mut xy {
                let b = self.read()?;
                *v = if le {
                    f64::from_le_bytes(b)
                } else {
                    f64::from_be_bytes(b)
                };
            }
            if xy.iter().any(|v| !v.is_finite())
                || (self.geographic && (xy[0].abs() > 180. || xy[1].abs() > 90.))
            {
                return Err(fail(
                    "nonfinite/out-of-domain WKB coordinates; empty points unsupported",
                ));
            }
            Ok(xy)
        }
        fn count(&mut self, le: bool) -> Result<usize> {
            let n = self.uint(le)?;
            if n > self.bytes.len().saturating_sub(self.pos) / 4 {
                return Err(fail("WKB count exceeds remaining bytes"));
            }
            Ok(n)
        }
        fn geometry(&mut self, expected: Option<usize>) -> Result<()> {
            let endian = self.read::<1>()?[0];
            if endian > 1 {
                return Err(fail("invalid WKB byte order"));
            }
            let le = endian == 1;
            let kind = self.uint(le)?;
            if expected.is_some_and(|k| k != kind) {
                return Err(fail("multipart WKB member type mismatch"));
            }
            match kind {
                1 => {
                    self.xy(le)?;
                }
                2 => {
                    let n = self.count(le)?;
                    if self.reject_empty && n == 0 {
                        return Err(fail("indexed FlatGeobuf rejects empty geometry"));
                    }
                    if n == 1 {
                        return Err(fail("undersized line"));
                    }
                    for _ in 0..n {
                        self.xy(le)?;
                    }
                }
                3 => {
                    let rings = self.count(le)?;
                    if self.reject_empty && rings == 0 {
                        return Err(fail("indexed FlatGeobuf rejects empty geometry"));
                    }
                    for ring in 0..rings {
                        let n = self.count(le)?;
                        if n < 4 {
                            return Err(fail("undersized polygon ring"));
                        }
                        let first = self.xy(le)?;
                        let mut previous = first;
                        let mut twice_area = 0.;
                        for _ in 1..n {
                            let next = self.xy(le)?;
                            twice_area += previous[0] * next[1] - next[0] * previous[1];
                            previous = next;
                        }
                        if previous != first {
                            return Err(fail("unclosed ring"));
                        }
                        if self.winding
                            && ((ring == 0 && twice_area <= 0.) || (ring > 0 && twice_area >= 0.))
                        {
                            return Err(fail(
                                "GeoJSON requires CCW exterior/CW holes; orient explicitly",
                            ));
                        }
                    }
                }
                4..=6 => {
                    let n = self.count(le)?;
                    if self.reject_empty && n == 0 {
                        return Err(fail("indexed FlatGeobuf rejects empty geometry"));
                    }
                    for _ in 0..n {
                        self.geometry(Some(kind - 3))?;
                    }
                }
                _ => return Err(fail("unsupported WKB type/dimension/SRID")),
            }
            Ok(())
        }
    }
    let mut r = Reader {
        bytes,
        pos: 0,
        geographic,
        winding,
        reject_empty,
    };
    r.geometry(None)?;
    if r.pos != bytes.len() {
        return Err(fail("trailing WKB bytes"));
    }
    Ok(())
}
