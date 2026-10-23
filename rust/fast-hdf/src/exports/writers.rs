use crate::{contract::Contract, fail, Format, Result};
#[allow(unused_imports)]
use arrow_array::*;
#[cfg(any(feature = "geojson", feature = "flatgeobuf"))]
use arrow_schema::DataType;
use arrow_schema::SchemaRef;
use std::{fs::File, path::Path};

#[cfg(any(feature = "geojson", feature = "flatgeobuf"))]
use std::io::{BufWriter, Write};

pub(crate) enum Writer<'a> {
    Arrow(Box<arrow_ipc::writer::FileWriter<File>>),
    #[cfg(feature = "geoparquet")]
    Parquet(
        Box<(
            geoparquet::writer::GeoParquetRecordBatchEncoder,
            parquet::arrow::ArrowWriter<File>,
        )>,
    ),
    #[cfg(feature = "geojson")]
    Json {
        file: BufWriter<File>,
        lines: bool,
        first: bool,
    },
    #[cfg(feature = "flatgeobuf")]
    Fgb(Box<flatgeobuf::FgbWriter<'a>>, File),
    #[cfg(feature = "geopackage")]
    Gpkg(geopackage::GeoPackage),
    #[doc(hidden)]
    #[allow(dead_code)]
    Lifetime(std::marker::PhantomData<&'a ()>),
}

impl<'a> Writer<'a> {
    pub fn new(path: &Path, schema: SchemaRef, c: &'a Contract, format: Format) -> Result<Self> {
        #[allow(unreachable_patterns)]
        match format {
            Format::Arrow => Ok(Self::Arrow(Box::new(
                arrow_ipc::writer::FileWriter::try_new(File::create(path)?, &schema)?,
            ))),
            #[cfg(feature = "geoparquet")]
            Format::GeoParquet => {
                let opts = geoparquet::writer::GeoParquetWriterOptionsBuilder::default()
                    .set_primary_column("geometry".into())
                    .build();
                let encoder =
                    geoparquet::writer::GeoParquetRecordBatchEncoder::try_new(&schema, &opts)?;
                let props = parquet::file::properties::WriterProperties::builder()
                    .set_compression(parquet::basic::Compression::SNAPPY)
                    .set_max_row_group_row_count(Some(65536))
                    .build();
                let writer = parquet::arrow::ArrowWriter::try_new(
                    File::create(path)?,
                    encoder.target_schema(),
                    Some(props),
                )?;
                Ok(Self::Parquet(Box::new((encoder, writer))))
            }
            #[cfg(feature = "geojson")]
            Format::GeoJson | Format::GeoJsonLines => {
                if !c.crs.geographic_wgs84 {
                    return Err(fail(
                        "GeoJSON requires explicitly transformed WGS84 XY coordinates",
                    ));
                }
                if schema
                    .fields()
                    .iter()
                    .enumerate()
                    .any(|(i, f)| i != c.geometry && f.data_type() == &DataType::Binary)
                {
                    return Err(fail(
                        "GeoJSON binary attributes unsupported; use a binary format",
                    ));
                }
                let mut file = BufWriter::new(File::create(path)?);
                let lines = matches!(format, Format::GeoJsonLines);
                if !lines {
                    file.write_all(b"{\"type\":\"FeatureCollection\",\"features\":[")?;
                }
                Ok(Self::Json {
                    file,
                    lines,
                    first: true,
                })
            }
            #[cfg(feature = "flatgeobuf")]
            Format::FlatGeobuf => {
                use flatgeobuf::*;
                let metadata = serde_json::to_string(schema.metadata())?;
                // Metadata string is copied by create_with_options; only WKT borrows c.
                let mut writer = FgbWriter::create_with_options(
                    "features",
                    GeometryType::Unknown,
                    FgbWriterOptions {
                        write_index: true,
                        detect_type: false,
                        promote_to_multi: false,
                        crs: FgbCrs {
                            wkt: Some(&c.crs.wkt),
                            ..Default::default()
                        },
                        metadata: Some(&metadata),
                        ..Default::default()
                    },
                )?;
                for (i, field) in schema
                    .fields()
                    .iter()
                    .filter(|f| f.name() != "geometry")
                    .enumerate()
                {
                    let typ = match field.data_type() {
                        DataType::Int64 | DataType::Timestamp(..) => ColumnType::Long,
                        DataType::UInt64 => ColumnType::Long,
                        DataType::Float64 => ColumnType::Double,
                        DataType::Boolean => ColumnType::Bool,
                        DataType::Utf8 => ColumnType::String,
                        DataType::Binary => ColumnType::Binary,
                        _ => return Err(fail("unsupported FGB field")),
                    };
                    writer.add_column(field.name(), typ, |_, col| {
                        col.nullable = field.is_nullable();
                        let _ = i;
                    });
                }
                Ok(Self::Fgb(Box::new(writer), File::create(path)?))
            }
            #[cfg(feature = "geopackage")]
            Format::GeoPackage => {
                use geopackage::{GeoPackage, GeometrySpec, Srs, TableSchemaBuilder};
                let gpkg = GeoPackage::create(path)?;
                let id = 100000;
                gpkg.add_srs(&Srs {
                    name: "Resolved source CRS".into(),
                    srs_id: id,
                    organization: "NONE".into(),
                    organization_coordsys_id: id,
                    definition: c.crs.wkt.clone(),
                    description: Some(c.crs.units.clone()),
                    definition_wkt2: Some(c.crs.wkt.clone()),
                    epoch: None,
                })?;
                let builder = TableSchemaBuilder::new("features")
                    .primary_key("_ras_fid")
                    .from_arrow_schema(&signed_schema(&schema))?
                    .geometry(
                        GeometrySpec::new(geopackage::core::types::GeometryType::Geometry, id)
                            .column_name("geometry"),
                    );
                gpkg.create_layer(&builder)?;
                Ok(Self::Gpkg(gpkg))
            }
            _ => {
                let _ = c;
                Err(fail("writer feature is disabled"))
            }
        }
    }

    pub fn write(&mut self, batch: &RecordBatch, c: &Contract) -> Result<()> {
        match self {
            Self::Arrow(w) => w.write(batch)?,
            #[cfg(feature = "geoparquet")]
            Self::Parquet(pair) => {
                let b = pair.0.encode_record_batch(batch)?;
                pair.1.write(&b)?;
            }
            #[cfg(feature = "geojson")]
            Self::Json { file, lines, first } => {
                use geozero::ToJson;
                let geometry = batch
                    .column(c.geometry)
                    .as_any()
                    .downcast_ref::<BinaryArray>()
                    .unwrap();
                for row in 0..batch.num_rows() {
                    if !*lines && !*first {
                        file.write_all(b",")?;
                    }
                    *first = false;
                    file.write_all(b"{\"type\":\"Feature\",\"geometry\":")?;
                    if geometry.is_null(row) {
                        file.write_all(b"null")?;
                    } else {
                        crate::contract::validate_geojson_wkb(geometry.value(row))?;
                        file.write_all(
                            geozero::wkb::Wkb(geometry.value(row)).to_json()?.as_bytes(),
                        )?;
                    }
                    file.write_all(b",\"properties\":{")?;
                    let mut first_property = true;
                    for (i, field) in batch.schema().fields().iter().enumerate() {
                        if i == c.geometry {
                            continue;
                        }
                        if !first_property {
                            file.write_all(b",")?;
                        }
                        first_property = false;
                        serde_json::to_writer(&mut *file, field.name())?;
                        file.write_all(b":")?;
                        serde_json::to_writer(
                            &mut *file,
                            &json_value(batch.column(i).as_ref(), row)?,
                        )?;
                    }
                    file.write_all(b"}}")?;
                    if *lines {
                        file.write_all(b"\n")?;
                    }
                }
            }
            #[cfg(feature = "flatgeobuf")]
            Self::Fgb(w, _) => {
                use geozero::{FeatureProcessor, GeozeroGeometry, PropertyProcessor};
                let geometry = batch
                    .column(c.geometry)
                    .as_any()
                    .downcast_ref::<BinaryArray>()
                    .unwrap();
                for row in 0..batch.num_rows() {
                    if geometry.is_null(row) {
                        return Err(fail("indexed FlatGeobuf rejects null geometry"));
                    }
                    crate::contract::validate_flatgeobuf_wkb(geometry.value(row))?;
                    w.feature_begin(row as u64)?;
                    geozero::wkb::Wkb(geometry.value(row)).process_geom(&mut **w)?;
                    let mut property_index = 0;
                    for (i, field) in batch.schema().fields().iter().enumerate() {
                        if i == c.geometry {
                            continue;
                        }
                        if !batch.column(i).is_null(row) {
                            let value = fgb_value(batch.column(i).as_ref(), row)?;
                            w.property(property_index, field.name(), &value)?;
                        }
                        property_index += 1;
                    }
                    w.feature_end(row as u64)?;
                }
            }
            #[cfg(feature = "geopackage")]
            Self::Gpkg(gpkg) => {
                gpkg.layer("features")?.write_arrow(
                    std::iter::once(Ok(signed_batch(batch)?)),
                    batch.num_rows().max(1),
                )?;
            }
            _ => {
                let _ = c;
                return Err(fail("uninitialized writer"));
            }
        }
        Ok(())
    }

    pub fn finish(self) -> Result<()> {
        match self {
            Self::Arrow(mut w) => w.finish()?,
            #[cfg(feature = "geoparquet")]
            Self::Parquet(pair) => {
                let (encoder, mut w) = *pair;
                w.append_key_value_metadata(encoder.into_keyvalue()?);
                w.close()?;
            }
            #[cfg(feature = "geojson")]
            Self::Json {
                mut file, lines, ..
            } => {
                if !lines {
                    file.write_all(b"]}")?;
                }
                file.flush()?;
            }
            #[cfg(feature = "flatgeobuf")]
            Self::Fgb(w, file) => {
                finalize_fgb(*w, file)?;
            }
            #[cfg(feature = "geopackage")]
            Self::Gpkg(gpkg) => {
                drop(gpkg);
            }
            _ => return Err(fail("uninitialized writer")),
        }
        Ok(())
    }
}

#[cfg(any(feature = "geojson", feature = "flatgeobuf"))]
fn as_array<T: 'static>(a: &dyn Array) -> &T {
    a.as_any()
        .downcast_ref::<T>()
        .expect("validated scalar schema")
}

#[cfg(feature = "geojson")]
fn json_value(a: &dyn Array, row: usize) -> Result<serde_json::Value> {
    use serde_json::Value;
    if a.is_null(row) {
        return Ok(Value::Null);
    }
    Ok(match a.data_type() {
        DataType::Int64 => {
            let v = as_array::<Int64Array>(a).value(row);
            if v.unsigned_abs() > 9007199254740991 {
                Value::String(v.to_string())
            } else {
                v.into()
            }
        }
        DataType::UInt64 => {
            let v = as_array::<UInt64Array>(a).value(row);
            if v > 9007199254740991 {
                Value::String(v.to_string())
            } else {
                v.into()
            }
        }
        DataType::Timestamp(..) => as_array::<TimestampMillisecondArray>(a).value(row).into(),
        DataType::Float64 => as_array::<Float64Array>(a).value(row).into(),
        DataType::Boolean => as_array::<BooleanArray>(a).value(row).into(),
        DataType::Utf8 => as_array::<StringArray>(a).value(row).into(),
        _ => return Err(fail("unsupported GeoJSON attribute")),
    })
}

#[cfg(feature = "flatgeobuf")]
fn fgb_value(a: &dyn Array, row: usize) -> Result<geozero::ColumnValue<'_>> {
    use geozero::ColumnValue as V;
    Ok(match a.data_type() {
        DataType::Int64 => V::Long(as_array::<Int64Array>(a).value(row)),
        DataType::UInt64 => V::Long(
            i64::try_from(as_array::<UInt64Array>(a).value(row))
                .map_err(|_| fail("FlatGeobuf interoperable uint64 exceeds signed i64"))?,
        ),
        DataType::Timestamp(..) => V::Long(as_array::<TimestampMillisecondArray>(a).value(row)),
        DataType::Float64 => V::Double(as_array::<Float64Array>(a).value(row)),
        DataType::Boolean => V::Bool(as_array::<BooleanArray>(a).value(row)),
        DataType::Utf8 => V::String(as_array::<StringArray>(a).value(row)),
        DataType::Binary => V::Binary(as_array::<BinaryArray>(a).value(row)),
        _ => return Err(fail("unsupported FGB attribute")),
    })
}

#[cfg(feature = "geopackage")]
fn signed_schema(schema: &arrow_schema::Schema) -> arrow_schema::Schema {
    arrow_schema::Schema::new_with_metadata(
        schema
            .fields()
            .iter()
            .map(|f| {
                if f.data_type() == &arrow_schema::DataType::UInt64 {
                    f.as_ref()
                        .clone()
                        .with_data_type(arrow_schema::DataType::Int64)
                } else {
                    f.as_ref().clone()
                }
            })
            .collect::<Vec<_>>(),
        schema.metadata().clone(),
    )
}

#[cfg(feature = "geopackage")]
fn signed_batch(batch: &RecordBatch) -> Result<RecordBatch> {
    let mut columns = batch.columns().to_vec();
    for column in &mut columns {
        if let Some(values) = column.as_any().downcast_ref::<UInt64Array>() {
            let checked = values
                .iter()
                .map(|v| v.map(i64::try_from).transpose())
                .collect::<std::result::Result<Vec<_>, _>>()
                .map_err(|_| fail("GeoPackage uint64 exceeds signed i64"))?;
            *column = std::sync::Arc::new(Int64Array::from(checked));
        }
    }
    Ok(RecordBatch::try_new(
        std::sync::Arc::new(signed_schema(&batch.schema())),
        columns,
    )?)
}

/// Buffer the official writer's per-feature output writes. Explicitly propagate
/// both buffered-write and sink-flush failures before file sync/publication.
#[cfg(feature = "flatgeobuf")]
fn finalize_fgb(writer: flatgeobuf::FgbWriter<'_>, sink: impl Write) -> Result<()> {
    let mut buffered = BufWriter::with_capacity(1024 * 1024, sink);
    writer.write(&mut buffered)?;
    buffered.flush()?;
    Ok(())
}

#[cfg(all(test, feature = "flatgeobuf"))]
mod finalization_tests {
    use super::*;
    struct FailingSink {
        fail_write: bool,
    }
    impl Write for FailingSink {
        fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
            if self.fail_write {
                Err(std::io::Error::other("injected output write failure"))
            } else {
                Ok(data.len())
            }
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Err(std::io::Error::other("injected sink flush failure"))
        }
    }
    #[test]
    fn propagates_buffered_write_failure() {
        let writer =
            flatgeobuf::FgbWriter::create("fault", flatgeobuf::GeometryType::Unknown).unwrap();
        let error = finalize_fgb(writer, FailingSink { fail_write: true }).unwrap_err();
        assert!(error.to_string().contains("output write failure"));
    }
    #[test]
    fn propagates_explicit_sink_flush_failure() {
        let writer =
            flatgeobuf::FgbWriter::create("fault", flatgeobuf::GeometryType::Unknown).unwrap();
        let error = finalize_fgb(writer, FailingSink { fail_write: false }).unwrap_err();
        assert!(error.to_string().contains("sink flush failure"));
    }
}
