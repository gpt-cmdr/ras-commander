//! Checked Arrow/WKB rendering boundary. Tiling belongs entirely to freestiler.
//! A bundle contains tiles.pmtiles, identities.arrow and manifest.json. Reusing
//! a prior bundle preserves its IDs; new identities append in sorted order.
use crate::{contract::Contract, fail, Error, Result};
use arrow_array::{
    Array, ArrayRef, BinaryArray, BooleanArray, Float64Array, Int64Array, RecordBatch, StringArray,
    TimestampMillisecondArray, UInt64Array,
};
use arrow_ipc::{reader::FileReader, writer::FileWriter};
use arrow_schema::{DataType, Field, Schema, SchemaRef, TimeUnit};
use freestiler_core::{
    engine::{generate_pmtiles, SilentReporter, TileConfig},
    geo::CoordsIter,
    geo_types::Geometry as GeoGeometry,
    pmtiles_writer::TileFormat,
    tiler::{Feature, Geometry, LayerData, PropertyValue},
};
use geozero::{wkb::Wkb, ToGeo};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashSet},
    fs::{File, OpenOptions},
    path::{Path, PathBuf},
    sync::Arc,
    time::Instant,
};

type Identity = (String, i64);
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Options {
    pub layer: String,
    pub min_zoom: u8,
    pub max_zoom: u8,
    pub max_batch_rows: usize,
    /// Explicit UTC Unix-millisecond conversion, otherwise timestamp fields reject.
    pub timestamp_ms: bool,
    pub reuse_from: Option<PathBuf>,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            layer: "features".into(),
            min_zoom: 0,
            max_zoom: 12,
            max_batch_rows: 65536,
            timestamp_ms: false,
            reuse_from: None,
        }
    }
}
#[derive(Default, Debug, Serialize)]
pub struct Metrics {
    pub rows: usize,
    pub batches: usize,
    pub registry_rows: usize,
    pub validation_seconds: f64,
    pub conversion_seconds: f64,
    pub tiling_seconds: f64,
    pub provenance_seconds: f64,
    pub total_seconds: f64,
    pub output_bytes: u64,
}

fn mapping_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("export_id", DataType::Int64, false),
        Field::new("mesh_name", DataType::Utf8, false),
        Field::new("cell_id", DataType::Int64, false),
        Field::new("present", DataType::Boolean, false),
    ]))
}
fn load_registry(path: &Path) -> Result<BTreeMap<Identity, i64>> {
    let manifest: serde_json::Value =
        serde_json::from_reader(File::open(path.join("manifest.json"))?)?;
    if manifest["bridge_version"] != 1 {
        return Err(fail("unsupported registry version"));
    }
    let reader = FileReader::try_new(File::open(path.join("identities.arrow"))?, None)?;
    if reader.schema() != mapping_schema() {
        return Err(fail("identity registry schema mismatch"));
    }
    let mut map = BTreeMap::new();
    let mut ids = HashSet::new();
    for batch in reader {
        let batch = batch?;
        if batch.columns().iter().any(|c| c.null_count() > 0) {
            return Err(fail("null identity registry value"));
        }
        let exported = batch
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        let meshes = batch
            .column(1)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        let cells = batch
            .column(2)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();
        for i in 0..batch.num_rows() {
            if exported.value(i) < 0
                || meshes.value(i).is_empty()
                || cells.value(i) < 0
                || !ids.insert(exported.value(i))
                || map
                    .insert((meshes.value(i).into(), cells.value(i)), exported.value(i))
                    .is_some()
            {
                return Err(fail("duplicate/invalid registry identity or export ID"));
            }
        }
    }
    Ok(map)
}
fn scalar(array: &dyn Array, row: usize, timestamp_ms: bool) -> Result<PropertyValue> {
    if array.is_null(row) {
        return Ok(PropertyValue::Null);
    }
    Ok(match array.data_type() {
        DataType::Int64 => PropertyValue::Int(
            array
                .as_any()
                .downcast_ref::<Int64Array>()
                .unwrap()
                .value(row),
        ),
        DataType::UInt64 => PropertyValue::Int(
            i64::try_from(
                array
                    .as_any()
                    .downcast_ref::<UInt64Array>()
                    .unwrap()
                    .value(row),
            )
            .map_err(|_| fail("UInt64 exceeds exact signed-i64 PMTiles range"))?,
        ),
        DataType::Float64 => PropertyValue::Double(
            array
                .as_any()
                .downcast_ref::<Float64Array>()
                .unwrap()
                .value(row),
        ),
        DataType::Boolean => PropertyValue::Bool(
            array
                .as_any()
                .downcast_ref::<BooleanArray>()
                .unwrap()
                .value(row),
        ),
        DataType::Utf8 => PropertyValue::String(
            array
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .value(row)
                .into(),
        ),
        DataType::Timestamp(TimeUnit::Millisecond, None) if timestamp_ms => PropertyValue::Int(
            array
                .as_any()
                .downcast_ref::<TimestampMillisecondArray>()
                .unwrap()
                .value(row),
        ),
        _ => return Err(fail("unsupported PMTiles scalar conversion")),
    })
}
fn geometry(wkb: &[u8]) -> Result<Geometry> {
    let decoded = Wkb(wkb).to_geo()?;
    if decoded
        .coords_iter()
        .any(|p| p.x.abs() > 180. || p.y.abs() > 85.0511287798066)
    {
        return Err(fail(
            "PMTiles coordinates outside WGS84/Web Mercator domain",
        ));
    }
    match decoded {
        GeoGeometry::Polygon(p) if !p.exterior().0.is_empty() => Ok(Geometry::Polygon(p)),
        GeoGeometry::MultiPolygon(p)
            if !p.0.is_empty() && p.0.iter().all(|p| !p.exterior().0.is_empty()) =>
        {
            Ok(Geometry::MultiPolygon(p))
        }
        _ => Err(fail(
            "PMTiles bridge requires nonempty Polygon/MultiPolygon geometry",
        )),
    }
}

pub fn export_ipc(input: &Path, output: &Path, options: &Options) -> Result<Metrics> {
    let reader = FileReader::try_new(File::open(input)?, None)?;
    export_batches(
        reader.schema(),
        reader.map(|b| b.map_err(Error::from)),
        output,
        options,
    )
}

/// Batches are validated once and converted natively; freestiler retains all
/// features in memory. Bounded batch sizes do not imply bounded total memory.
/// Existing bundles always reject. A private stage and cooperating-writer lock
/// protect publication; directory rename is qualified on Windows. No append,
/// overwrite, crash-proof fs transaction or noncooperating Unix race guarantee.
pub fn export_batches<I>(
    schema: SchemaRef,
    batches: I,
    output: &Path,
    options: &Options,
) -> Result<Metrics>
where
    I: IntoIterator<Item = Result<RecordBatch>>,
{
    let started = Instant::now();
    if output.symlink_metadata().is_ok() {
        return Err(fail("destination already exists"));
    }
    if options.layer.is_empty()
        || options.max_batch_rows == 0
        || options.min_zoom > options.max_zoom
        || options.max_zoom > 22
    {
        return Err(fail("invalid layer, batch limit or zoom range"));
    }
    let contract = Contract::new(schema.clone())?;
    if !contract.crs.geographic_wgs84
        || contract.crs.projjson["type"] != "GeographicCRS"
        || !["degree", "degrees"].contains(&contract.crs.units.as_str())
    {
        return Err(fail(
            "PMTiles requires declared resolved WGS84 degree coordinates; transform explicitly",
        ));
    }
    let fields: Vec<_> = schema
        .fields()
        .iter()
        .enumerate()
        .filter(|(i, _)| *i != contract.geometry)
        .collect();
    let mut prop_names = Vec::new();
    let mut prop_types = Vec::new();
    for (_, field) in &fields {
        let kind = match field.data_type() {
            DataType::Utf8 => "string",
            DataType::Boolean => "boolean",
            DataType::Int64 | DataType::UInt64 | DataType::Float64 => "numeric",
            DataType::Timestamp(TimeUnit::Millisecond, None) if options.timestamp_ms => "integer",
            _ => {
                return Err(fail(format!(
                    "PMTiles rejects field {} ({}) without an explicit supported conversion",
                    field.name(),
                    field.data_type()
                )))
            }
        };
        prop_names.push(field.name().clone());
        prop_types.push(kind.into());
    }
    let mut registry = match &options.reuse_from {
        Some(p) => load_registry(p)?,
        None => BTreeMap::new(),
    };
    let mut features = BTreeMap::new();
    let mut metrics = Metrics::default();
    for batch in batches {
        let batch = batch?;
        let time = Instant::now();
        contract.validate(&batch, options.max_batch_rows)?;
        metrics.validation_seconds += time.elapsed().as_secs_f64();
        let time = Instant::now();
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
        let wkbs = batch
            .column(contract.geometry)
            .as_any()
            .downcast_ref::<BinaryArray>()
            .unwrap();
        for row in 0..batch.num_rows() {
            let key = (meshes.value(row).to_owned(), cells.value(row));
            if features.contains_key(&key) {
                return Err(fail("duplicate composite identity across batches"));
            }
            if wkbs.is_null(row) {
                return Err(fail("PMTiles rejects null geometry"));
            }
            let feature = Feature {
                id: None,
                geometry: geometry(wkbs.value(row))?,
                properties: fields
                    .iter()
                    .map(|(i, _)| scalar(batch.column(*i).as_ref(), row, options.timestamp_ms))
                    .collect::<Result<_>>()?,
            };
            features.insert(key, feature);
        }
        metrics.rows += batch.num_rows();
        metrics.batches += 1;
        metrics.conversion_seconds += time.elapsed().as_secs_f64();
    }
    if features.is_empty() {
        return Err(fail("PMTiles requires nonempty features"));
    }
    let mut next = registry.values().max().copied();
    for key in features.keys() {
        if !registry.contains_key(key) {
            let id = match next {
                None => 0,
                Some(n) => n
                    .checked_add(1)
                    .ok_or_else(|| fail("export ID registry exhausted signed-i64 range"))?,
            };
            registry.insert(key.clone(), id);
            next = Some(id);
        }
    }
    let present: HashSet<_> = features.keys().cloned().collect();
    for (key, feature) in &mut features {
        feature.id = Some(registry[key] as u64);
    }
    let layer = LayerData {
        name: options.layer.clone(),
        features: features.into_values().collect(),
        prop_names,
        prop_types,
        min_zoom: options.min_zoom,
        max_zoom: options.max_zoom,
    };
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let stage = tempfile::tempdir_in(parent)?;
    let tile_path = stage.path().join("tiles.pmtiles");
    let time = Instant::now();
    generate_pmtiles(
        &[layer],
        tile_path
            .to_str()
            .ok_or_else(|| fail("non-UTF8 PMTiles path"))?,
        &TileConfig {
            tile_format: TileFormat::Mvt,
            min_zoom: options.min_zoom,
            max_zoom: options.max_zoom,
            base_zoom: None,
            simplification: false,
            drop_rate: None,
            cluster_distance: None,
            cluster_maxzoom: None,
            coalesce: false,
        },
        &SilentReporter,
    )
    .map_err(fail)?;
    metrics.tiling_seconds = time.elapsed().as_secs_f64();
    let time = Instant::now();
    let mapping = RecordBatch::try_new(
        mapping_schema(),
        vec![
            Arc::new(Int64Array::from(
                registry.values().copied().collect::<Vec<_>>(),
            )) as ArrayRef,
            Arc::new(StringArray::from(
                registry.keys().map(|k| k.0.as_str()).collect::<Vec<_>>(),
            )),
            Arc::new(Int64Array::from(
                registry.keys().map(|k| k.1).collect::<Vec<_>>(),
            )),
            Arc::new(BooleanArray::from(
                registry
                    .keys()
                    .map(|k| present.contains(k))
                    .collect::<Vec<_>>(),
            )),
        ],
    )?;
    let identity_path = stage.path().join("identities.arrow");
    let mut writer = FileWriter::try_new(File::create(&identity_path)?, &mapping.schema())?;
    writer.write(&mapping)?;
    writer.finish()?;
    drop(writer);
    let manifest = serde_json::json!({"bridge_version":1,"options":options,"crs":contract.crs,
        "schema_metadata":schema.metadata(), "field_metadata":schema.fields().iter().map(|f|(f.name(),f.metadata())).collect::<BTreeMap<_,_>>(),
        "rows":metrics.rows,"registry_rows":registry.len(),"identity_policy":"sorted new composite identities append to reusable registry; duplicates reject",
        "null_policy":"MVT omits null attributes; null/empty geometry rejects", "uint64_policy":"checked signed i64", "timestamp_policy":if options.timestamp_ms {"UTC Unix milliseconds i64"} else {"reject"},
        "geometry_policy":"freestiler clipping/quantization without repair; low-zoom validity not guaranteed"});
    serde_json::to_writer_pretty(File::create(stage.path().join("manifest.json"))?, &manifest)?;
    for name in ["tiles.pmtiles", "identities.arrow", "manifest.json"] {
        let path = stage.path().join(name);
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)?
            .sync_all()?;
        metrics.output_bytes += path.metadata()?.len();
    }
    metrics.registry_rows = registry.len();
    metrics.provenance_seconds = time.elapsed().as_secs_f64();
    // Exclusive create serializes cooperating bridge writers; retain stage until
    // publication succeeds. The lock is never stolen or deleted on acquisition error.
    let lock_path = parent.join(format!(
        ".{}.pmtiles.lock",
        output
            .file_name()
            .ok_or_else(|| fail("output requires bundle name"))?
            .to_string_lossy()
    ));
    let lock = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)?;
    let result = if output.symlink_metadata().is_ok() {
        Err(fail("destination appeared before publication"))
    } else {
        std::fs::rename(stage.path(), output).map_err(Error::from)
    };
    drop(lock);
    std::fs::remove_file(lock_path)?;
    result?;
    metrics.total_seconds = started.elapsed().as_secs_f64();
    Ok(metrics)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::Crs;
    use std::collections::HashMap;

    fn batch(mesh: &str, cell: i64) -> RecordBatch {
        let json = serde_json::json!({"type":"GeographicCRS","name":"WGS 84"});
        let crs = Crs {
            wkt: "declared WGS84".into(),
            projjson: json.clone(),
            units: "degree".into(),
            axis_order: "xy".into(),
            resolved: true,
            geographic_wgs84: true,
        };
        let schema = Arc::new(Schema::new_with_metadata(
            vec![
                Field::new("mesh_name", DataType::Utf8, false),
                Field::new("cell_id", DataType::Int64, false),
                Field::new("geometry", DataType::Binary, true).with_metadata(HashMap::from([
                    ("ARROW:extension:name".into(), "geoarrow.wkb".into()),
                    (
                        "ARROW:extension:metadata".into(),
                        serde_json::json!({"crs":json,"crs_type":"projjson"}).to_string(),
                    ),
                ])),
            ],
            HashMap::from([(
                crate::contract::CONTRACT_KEY.into(),
                serde_json::to_string(&crs).unwrap(),
            )]),
        ));
        let mut wkb = vec![1];
        wkb.extend(3u32.to_le_bytes());
        wkb.extend(1u32.to_le_bytes());
        wkb.extend(5u32.to_le_bytes());
        for (x, y) in [
            (-77f64, 40f64),
            (-76., 40.),
            (-76., 41.),
            (-77., 41.),
            (-77., 40.),
        ] {
            wkb.extend(x.to_le_bytes());
            wkb.extend(y.to_le_bytes());
        }
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec![mesh])) as ArrayRef,
                Arc::new(Int64Array::from(vec![cell])),
                Arc::new(BinaryArray::from(vec![wkb.as_slice()])),
            ],
        )
        .unwrap()
    }
    fn opts() -> Options {
        Options {
            min_zoom: 0,
            max_zoom: 0,
            ..Default::default()
        }
    }

    #[test]
    fn late_producer_error_duplicate_and_schema_change_publish_nothing() {
        let temp = tempfile::tempdir().unwrap();
        let a = batch("a", 1);
        let b = batch("b", 1);
        let changed = RecordBatch::try_new(
            Arc::new(Schema::new(b.schema().fields().clone())),
            b.columns().to_vec(),
        )
        .unwrap();
        for late in [Err(fail("producer cancelled")), Ok(a.clone()), Ok(changed)] {
            assert!(export_batches(
                a.schema(),
                vec![Ok(a.clone()), late],
                &temp.path().join("out"),
                &opts()
            )
            .is_err());
            assert_eq!(temp.path().read_dir().unwrap().count(), 0);
        }
    }
    #[test]
    fn destination_created_during_input_is_preserved() {
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("out");
        let a = batch("a", 1);
        let batches = std::iter::once_with(|| {
            std::fs::create_dir(&output).unwrap();
            std::fs::write(output.join("sentinel"), b"other owner").unwrap();
            Ok(a.clone())
        });
        assert!(export_batches(a.schema(), batches, &output, &opts()).is_err());
        assert_eq!(
            std::fs::read(output.join("sentinel")).unwrap(),
            b"other owner"
        );
        assert_eq!(temp.path().read_dir().unwrap().count(), 1);
    }
    #[test]
    fn extension_retains_existing_ids_and_detects_exhaustion() {
        let temp = tempfile::tempdir().unwrap();
        let first = temp.path().join("first");
        let a = batch("b", 9);
        export_batches(a.schema(), [Ok(a.clone())], &first, &opts()).unwrap();
        let original = load_registry(&first).unwrap();
        assert_eq!(original[&("b".into(), 9)], 0);
        let mut options = opts();
        options.reuse_from = Some(first.clone());
        let next = temp.path().join("next");
        let b = batch("a", 9);
        export_batches(b.schema(), [Ok(b.clone())], &next, &options).unwrap();
        let ids = load_registry(&next).unwrap();
        assert_eq!(ids[&("b".into(), 9)], 0);
        assert_eq!(ids[&("a".into(), 9)], 1);
        let m = RecordBatch::try_new(
            mapping_schema(),
            vec![
                Arc::new(Int64Array::from(vec![i64::MAX])) as ArrayRef,
                Arc::new(StringArray::from(vec!["b"])),
                Arc::new(Int64Array::from(vec![9])),
                Arc::new(BooleanArray::from(vec![true])),
            ],
        )
        .unwrap();
        let mut writer = FileWriter::try_new(
            File::create(first.join("identities.arrow")).unwrap(),
            &m.schema(),
        )
        .unwrap();
        writer.write(&m).unwrap();
        writer.finish().unwrap();
        drop(writer);
        assert!(
            export_batches(b.schema(), [Ok(b)], &temp.path().join("overflow"), &options)
                .unwrap_err()
                .to_string()
                .contains("exhausted")
        );
        assert!(!temp.path().join("overflow").exists());
    }
    #[test]
    fn competing_bridge_lock_is_never_stolen() {
        let temp = tempfile::tempdir().unwrap();
        let lock = temp.path().join(".out.pmtiles.lock");
        std::fs::write(&lock, b"other worker").unwrap();
        let a = batch("a", 0);
        assert!(export_batches(
            a.schema(),
            [Ok(a.clone())],
            &temp.path().join("out"),
            &opts()
        )
        .is_err());
        assert_eq!(std::fs::read(lock).unwrap(), b"other worker");
        assert_eq!(temp.path().read_dir().unwrap().count(), 1);
    }
}
