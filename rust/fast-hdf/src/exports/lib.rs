//! Typed, batch-fed source exports. This library never runs HEC-RAS or reprojects.
pub mod contract;
#[cfg(feature = "pmtiles")]
pub mod pmtiles_bridge;
mod writers;

use arrow_array::RecordBatch;
use arrow_ipc::reader::FileReader;
use arrow_schema::SchemaRef;
use serde::Serialize;
use std::{fs::File, path::Path, time::Instant};

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

pub(crate) fn fail(message: impl Into<String>) -> Error {
    std::io::Error::new(std::io::ErrorKind::InvalidInput, message.into()).into()
}

#[derive(Clone, Copy, Debug)]
pub enum Format {
    Arrow,
    GeoParquet,
    FlatGeobuf,
    GeoJson,
    GeoJsonLines,
    GeoPackage,
}

impl std::str::FromStr for Format {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "arrow" => Ok(Self::Arrow),
            "parquet" => Ok(Self::GeoParquet),
            "fgb" => Ok(Self::FlatGeobuf),
            "geojson" => Ok(Self::GeoJson),
            "jsonl" => Ok(Self::GeoJsonLines),
            "gpkg" => Ok(Self::GeoPackage),
            _ => Err(fail("unknown export format")),
        }
    }
}

#[derive(Debug, Default, Serialize)]
pub struct Metrics {
    pub rows: usize,
    pub batches: usize,
    pub validation_seconds: f64,
    /// Includes per-format geometry encoding/compression/index accumulation.
    pub write_seconds: f64,
    /// Includes footer/index flush and file synchronization, excludes atomic rename.
    pub finalize_seconds: f64,
    pub total_seconds: f64,
    pub output_bytes: u64,
}

/// File transport for Python without constructing per-feature Python objects.
/// Rust callers should use `export_batches` directly to avoid the IPC spool.
pub fn export_ipc(
    input: &Path,
    output: &Path,
    format: Format,
    max_batch_rows: usize,
) -> Result<Metrics> {
    let reader = FileReader::try_new(File::open(input)?, None)?;
    let schema = reader.schema();
    export_batches(
        schema,
        reader.map(|r| r.map_err(Error::from)),
        output,
        format,
        max_batch_rows,
    )
}

/// Atomically install a new file after all batches and finalization succeed.
/// Existing destinations are rejected; failures remove only our private staging directory.
pub fn export_batches<I>(
    schema: SchemaRef,
    batches: I,
    output: &Path,
    format: Format,
    max_batch_rows: usize,
) -> Result<Metrics>
where
    I: IntoIterator<Item = Result<RecordBatch>>,
{
    let started = Instant::now();
    if output.exists() {
        return Err(fail("destination already exists"));
    }
    if max_batch_rows == 0 {
        return Err(fail("max_batch_rows must be positive"));
    }
    let contract = contract::Contract::new(schema.clone())?;
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let stage = tempfile::tempdir_in(parent)?;
    let staged = stage.path().join("export");
    let mut writer = writers::Writer::new(&staged, schema.clone(), &contract, format)?;
    let mut metrics = Metrics::default();
    for batch in batches {
        let batch = batch?;
        let time = Instant::now();
        contract.validate(&batch, max_batch_rows)?;
        metrics.validation_seconds += time.elapsed().as_secs_f64();
        let time = Instant::now();
        writer.write(&batch, &contract)?;
        metrics.write_seconds += time.elapsed().as_secs_f64();
        metrics.rows += batch.num_rows();
        metrics.batches += 1;
    }
    let time = Instant::now();
    writer.finish()?;
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&staged)?
        .sync_all()?;
    metrics.finalize_seconds = time.elapsed().as_secs_f64();
    // persist_noclobber prevents a destination creation race from overwriting data.
    let temporary = tempfile::NamedTempFile::from_parts(
        File::open(&staged)?,
        tempfile::TempPath::try_from_path(staged)?,
    );
    temporary.persist_noclobber(output).map_err(|e| e.error)?;
    metrics.output_bytes = output.metadata()?.len();
    metrics.total_seconds = started.elapsed().as_secs_f64();
    Ok(metrics)
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::{ArrayRef, BinaryArray, Int64Array, StringArray};
    use arrow_schema::{DataType, Field, Schema};
    use std::{collections::HashMap, sync::Arc};

    fn batch() -> RecordBatch {
        let json = serde_json::json!({"type":"GeographicCRS","name":"test"});
        let crs = contract::Crs {
            wkt: "test WKT".into(),
            projjson: json.clone(),
            units: "degree".into(),
            axis_order: "xy".into(),
            resolved: true,
            geographic_wgs84: true,
        };
        let field = Field::new("geometry", DataType::Binary, true).with_metadata(HashMap::from([
            ("ARROW:extension:name".into(), "geoarrow.wkb".into()),
            (
                "ARROW:extension:metadata".into(),
                serde_json::json!({"crs":json,"crs_type":"projjson"}).to_string(),
            ),
        ]));
        let schema = Arc::new(Schema::new_with_metadata(
            vec![
                Field::new("mesh_name", DataType::Utf8, false),
                Field::new("cell_id", DataType::Int64, false),
                field,
            ],
            HashMap::from([(
                contract::CONTRACT_KEY.into(),
                serde_json::to_string(&crs).unwrap(),
            )]),
        ));
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec!["a"])) as ArrayRef,
                Arc::new(Int64Array::from(vec![1])),
                Arc::new(BinaryArray::from(vec![None as Option<&[u8]>])),
            ],
        )
        .unwrap()
    }

    #[test]
    fn rejects_schema_change_and_late_cancellation_atomically() {
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("out.arrow");
        let batch = batch();
        let changed = RecordBatch::try_new(
            Arc::new(Schema::new(batch.schema().fields().clone())),
            batch.columns().to_vec(),
        )
        .unwrap();
        for second in [Ok(changed), Err(fail("cancelled producer"))] {
            assert!(export_batches(
                batch.schema(),
                vec![Ok(batch.clone()), second],
                &output,
                Format::Arrow,
                2
            )
            .is_err());
            assert!(!output.exists());
            assert_eq!(temp.path().read_dir().unwrap().count(), 0);
        }
    }

    #[test]
    fn empty_stream_finalizes_with_schema() {
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("out.arrow");
        let m = export_batches(
            batch().schema(),
            std::iter::empty(),
            &output,
            Format::Arrow,
            2,
        )
        .unwrap();
        assert_eq!(m.rows, 0);
        assert!(m.output_bytes > 0);
    }

    #[test]
    fn malformed_wkb_fails_without_allocation_from_untrusted_counts() {
        for bytes in [
            vec![],
            vec![1, 3, 0, 0, 0, 255, 255, 255, 255],
            vec![2, 1, 0, 0, 0],
            vec![1, 7, 0, 0, 0, 0, 0, 0, 0],
            vec![1, 1, 0, 0, 128],
        ] {
            assert!(contract::validate_wkb(&bytes, false).is_err());
        }
    }

    #[test]
    fn destination_race_preserves_competing_file_and_removes_stage() {
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("raced.arrow");
        let batch = batch();
        let input = std::iter::once_with(|| {
            std::fs::write(&output, b"competing owner").unwrap();
            Ok(batch.clone())
        });
        assert!(export_batches(batch.schema(), input, &output, Format::Arrow, 2).is_err());
        assert_eq!(std::fs::read(&output).unwrap(), b"competing owner");
        assert_eq!(temp.path().read_dir().unwrap().count(), 1);
    }
}
