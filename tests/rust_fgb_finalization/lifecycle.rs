#[cfg(test)]
mod tests {
    use arrow_ipc::reader::FileReader;
    use ras_export::{export_batches, Format};
    use std::{cell::Cell, fs::File, path::Path};

    #[test]
    fn late_real_batch_producer_error_removes_staging() {
        let input = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../working/prepared/cells7/native.arrow");
        let mut reader = FileReader::try_new(File::open(input).unwrap(), None).unwrap();
        let batch = reader.next().unwrap().unwrap();
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("late.fgb");
        let batches = vec![
            Ok(batch),
            Err(std::io::Error::other("cancelled after real batch").into()),
        ];
        let error = export_batches(reader.schema(), batches, &output, Format::FlatGeobuf, 4096)
            .unwrap_err();
        assert!(error.to_string().contains("cancelled after real batch"));
        assert!(!output.exists());
        assert_eq!(temp.path().read_dir().unwrap().count(), 0);
    }

    #[test]
    fn existing_destination_preserved_without_consuming_producer() {
        let input = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../working/prepared/cells7/native.arrow");
        let reader = FileReader::try_new(File::open(input).unwrap(), None).unwrap();
        let schema = reader.schema();
        let consumed = Cell::new(false);
        let batches = reader.map(|batch| {
            consumed.set(true);
            batch.map_err(Into::into)
        });
        let temp = tempfile::tempdir().unwrap();
        let output = temp.path().join("existing.fgb");
        std::fs::write(&output, b"existing owner").unwrap();
        assert!(export_batches(schema, batches, &output, Format::FlatGeobuf, 4096).is_err());
        assert!(!consumed.get());
        assert_eq!(std::fs::read(output).unwrap(), b"existing owner");
    }
}
