# HEC-Vortex v0.13.3 Decompilation Notes

Linear issue: CLB-675

Source inspected: `HydrologicEngineeringCenter/Vortex`, tag `v0.13.3`, commit `286565b`, cloned to `working/vortex` on 2026-05-09. File paths in this report are relative to that Vortex checkout unless explicitly prefixed with `ras_commander/`.

## Executive Summary

HEC-Vortex is primarily a Java API plus Swing wizard distribution. The official open-source `v0.13.3` source does not contain a `VortexCli` class, a `picocli` command tree, or an `import_gridded` command. The distributable launch scripts expose application modes such as `-importer` and `-image-exporter`, but those start Swing wizards through `mil.army.usace.hec.vortex.ui.VortexUi`.

The gridded import engine is `mil.army.usace.hec.vortex.io.BatchImporter`. It accepts one or more source files, selected variables, geographic processing options, write options, and a destination. It routes source formats through `DataReader`, processes grids through `GeographicProcessor` and `DataConverter`, and writes destinations through `DataWriter`.

Supported inputs are broader than the issue title list:

- NetCDF-family datasets through NetCDF-Java, including NetCDF, GRIB1/GRIB2, and HDF/HDF5 when NetCDF-Java can open them.
- GDAL rasters through specialized readers for ASCII grid, GeoTIFF, BIL, and zipped ASC/BIL products.
- SNODAS `.dat` and `snodas*.tar` products.
- HEC-DSS gridded records.

Supported normal importer outputs are:

- HEC-DSS grids and, for point outputs, HEC-DSS time series.
- NetCDF4.
- GeoTIFF.
- ASCII grid.

`DataWriter` also contains a specialized HEC-RAS plan HDF precipitation-values writer for `*.p##.hdf` and `*.p##.tmp.hdf`, but that writer does not appear to be reachable through the normal `BatchImporter` path in `v0.13.3`: non-DSS/ASC/TIFF destinations route to `NetcdfBatchImporter`, and that importer returns without writing unless `DataWriter.builder()` produced a `NetcdfDataWriter`.

Spatial operations are real but limited to raster operations. Vortex can reproject, resample, and clip to an envelope using GDAL Warp. If a shapefile is supplied, the shapefile contributes its bounding envelope and WKT; Vortex does not appear to polygon-mask cells against the shapefile geometry in the importer path.

For ras-commander, the near-term recommendation is to keep Vortex available as an external converter for complex GRIB/MRMS/HDF cases, but not to treat the current `vortex.bat -s script.py` assumption in `ras_commander/precip/VortexCli.py` as source-backed until it is verified against the installed CLB Vortex distribution. The Vortex Java/Jython API is real; the official open-source CLI contract assumed by the current wrapper is not present in `v0.13.3`.

## Source Map

Important source files:

| Area | Vortex source file | Notes |
| --- | --- | --- |
| Import API | `vortex-api/src/main/java/mil/army/usace/hec/vortex/io/BatchImporter.java` | Main builder entry point. Chooses concurrent importer for DSS/ASC/TIFF and NetCDF importer for `.nc*` destinations. |
| Import unit | `vortex-api/src/main/java/mil/army/usace/hec/vortex/io/ImportableUnit.java` | Connects `DataReader`, `GeographicProcessor`, `DataConverter`, and `DataWriter`. |
| Input routing | `vortex-api/src/main/java/mil/army/usace/hec/vortex/io/DataReader.java` | File extension and product routing. |
| Output routing | `vortex-api/src/main/java/mil/army/usace/hec/vortex/io/DataWriter.java` | Destination extension routing. |
| DSS writer | `vortex-api/src/main/java/mil/army/usace/hec/vortex/io/DssDataWriter.java` | DSS grid and point time-series writes. |
| DSS grid metadata | `vortex-api/src/main/java/mil/army/usace/hec/vortex/util/DssUtil.java` | Builds `GridInfo`, data units, data type, and grid times. |
| NetCDF/GRIB/HDF readers | `NetcdfDataReader.java`, `GridDatasetReader.java`, `VariableDsReader.java` | NetCDF-Java backed readers. |
| Raster readers | `AscDataReader.java`, `BilDataReader.java`, `AscZipDataReader.java`, `BilZipDataReader.java` | GDAL-backed raster readers. |
| SNODAS readers | `SnodasDataReader.java`, `SnodasTarDataReader.java` | SNODAS product parsing and archive extraction. |
| DSS reader | `DssDataReader.java` | HEC-DSS grid reader. |
| Spatial processing | `GeographicProcessor.java`, `Resampler.java`, `ResamplingMethod.java`, `WktFactory.java` | Envelope clipping, reprojection, resampling, SHG WKT factory. |
| Jython example | `examples/src/main/jython/met_data_import.py` | Official API usage example for `BatchImporter`. |
| UI launcher | `vortex-ui/src/main/java/mil/army/usace/hec/vortex/ui/VortexUi.java` | Parses Swing app flags only. |

ras-commander files inspected for integration context:

| Area | ras-commander source file | Notes |
| --- | --- | --- |
| Current Vortex wrapper | `ras_commander/precip/VortexCli.py` | Generates Jython `BatchImporter` scripts but assumes `vortex.bat -s script.py`. |
| Direct RAS gridded precip | `ras_commander/RasUnsteady.py` | `set_gridded_precipitation()` configures RAS to use GDAL Raster NetCDF inputs. |
| DSS API | `ras_commander/dss/RasDss.py` | Reads/catalogs DSS and writes time series; no DSS grid writer is present. |

## Package Map

```text
BatchImporter
  Builder: inFiles, variables, destination, geoOptions, writeOptions
  build()
    -> ConcurrentBatchImporter for *.dss, *.asc, *.tiff destinations
    -> NetcdfBatchImporter for other supported destinations, effectively *.nc*

ConcurrentBatchImporter / NetcdfBatchImporter
  -> create ImportableUnit list

ImportableUnit
  -> DataReader
       -> AscDataReader (.asc, .tif, .tiff)
       -> AscZipDataReader (asc.zip)
       -> BilDataReader (.bil)
       -> BilZipDataReader (bil.zip)
       -> SnodasDataReader (.dat)
       -> SnodasTarDataReader (snodas*.tar)
       -> DssDataReader (.dss)
       -> NetcdfDataReader (fallback)
            -> GridDatasetReader
            -> VariableDsReader
  -> GeographicProcessor
       -> Resampler (GDAL Warp)
  -> DataConverter
  -> DataWriter
       -> DssDataWriter (*.dss)
       -> TiffDataWriter (*.tif, *.tiff)
       -> AscDataWriter (*.asc)
       -> NetcdfDataWriter (*.nc*)
       -> Hdf5RasPrecipDataWriter (*.p##.hdf, *.p##.tmp.hdf; writer exists, not normal BatchImporter output)
```

## Input Format Support Matrix

| Input family | Extensions/products | Reader class | Variable required | Projection handling | Time metadata handling | Import notes |
| --- | --- | --- | --- | --- | --- | --- |
| NetCDF | `.nc`, `.nc4` | `NetcdfDataReader` -> `GridDatasetReader` or `VariableDsReader` | Yes | NetCDF-Java coordinate systems; WKT created by `WktFactory` | CF/grid time axes, with special file-name overrides for several products | Main path for AORC, GFS, HRRR, Livneh, UA SWE, and similar grids. |
| GRIB1/GRIB2 | `.grib`, `.gb2`, `.grb2`, `.grib2`, `.grb` | `NetcdfDataReader` -> `GridDatasetReader` | Yes | NetCDF-Java grid coordinate system | Product-specific overrides for ABRFC gauge/radar QPE, MRMS IDP, NLDAS, HRRR, GEFS, GFS, and other cases | Supported through NetCDF-Java rather than a Vortex-owned GRIB parser. |
| HDF/HDF5 | `.hdf`, `.hdf5`, `.h5` | `NetcdfDataReader` when NetCDF-Java can open the dataset | Yes | NetCDF-Java coordinate system | Dataset time axes plus product-specific overrides, such as GPM | The UI exposes HDF filters; practical support depends on NetCDF-Java compatibility with the file. |
| ASCII grid | `.asc` | `AscDataReader` | No | GDAL raster projection | Mostly parsed from known file-name patterns | Single-band GDAL read. Also supports PRISM and precipitation-frequency naming conventions. |
| GeoTIFF | `.tif`, `.tiff` | `AscDataReader` | No | GDAL raster projection | Mostly parsed from known file-name patterns | The class name is misleading: `AscDataReader` also reads GeoTIFF. |
| BIL | `.bil` | `BilDataReader` | No | GDAL raster projection | PRISM file-name parsing | Primarily PRISM BIL support. |
| Zipped ASC | `asc.zip` | `AscZipDataReader` | No | GDAL virtual file system | Delegates to ASC handling | `DataReader` explicitly whitelists `asc.zip` as a supported archive. |
| Zipped BIL | `bil.zip` | `BilZipDataReader` | No | GDAL virtual file system | Delegates to BIL handling | `DataReader` explicitly whitelists `bil.zip` as a supported archive. |
| SNODAS DAT | `.dat` | `SnodasDataReader` | No | Fixed WGS84 lon/lat extent from SNODAS metadata assumptions | Parsed from SNODAS product file names | Product-code map covers SWE, snow depth, snow melt runoff, sublimation, solid/liquid precipitation, and snow-pack temperature. |
| SNODAS TAR | `snodas*.tar` | `SnodasTarDataReader` | Effectively yes in the UI flow | Extracts and delegates to `SnodasDataReader` | Parsed from inner SNODAS files | Extracts to a sibling `<tar>_unzip` directory, so it mutates local scratch beside the source archive. |
| HEC-DSS grids | `.dss` plus grid pathname or wildcard | `DssDataReader` | Yes | DSS `GridInfo` converted to WKT by `WktFactory.fromGridInfo()` | DSS grid times and D/E parts | Reads undefined, HRAP, Albers, and specified DSS grid record types. |

The importer UI file chooser in `ImportMetWizard.java` exposes these recognized extensions: `.nc`, `.nc4`, `.hdf`, `.hdf5`, `.h5`, `.grib`, `.gb2`, `.grb2`, `.grib2`, `.grb`, `.asc`, `.bil`, `bil.zip`, `.dss`, `.tif`, `.tiff`, `.dat`, and `.tar`.

`DataReader` also defines a broader archive-extension detector, but only `snodas*.tar`, `bil.zip`, and `asc.zip` are explicitly accepted as supported archive products. Generic `.zip`, `.tar.gz`, `.7z`, `.rar`, and related archive names are recognized as archives but are not automatically supported import formats unless routed by one of the supported product patterns.

## Output Support Matrix

| Destination | Writer class | Supported data | Projection/Grid handling | Notes |
| --- | --- | --- | --- | --- |
| `.dss` | `DssDataWriter` | Vortex grids and Vortex points | Builds HEC `GridInfo`; Albers CRS becomes `AlbersInfo`, other CRS becomes `SpecifiedGridInfo` | Stores grids with `GriddedData.storeGriddedData()`. Point data are written as DSS time series. |
| `.tif`, `.tiff` | `TiffDataWriter` | Vortex grids | Writes raster georeferencing | Float32 GeoTIFF with tiled/deflate options and nodata handling. |
| `.asc` | `AscDataWriter` | Vortex grids | Writes AAIGrid-style raster | Forces cell size; can expand names for multi-grid output. |
| `.nc*` | `NetcdfDataWriter` | Vortex grids | Writes CF-style coordinates and projection variable | NetCDF4 with compression, `time`, `time_bnds`, coordinate arrays, and `crs_wkt`. |
| `.p##.hdf`, `.p##.tmp.hdf` | `Hdf5RasPrecipDataWriter` | Vortex grids for RAS precipitation | Writes values into an existing or target RAS plan HDF precipitation path | Specialized writer for `Event Conditions/Meteorology/Precipitation/Values`; it flattens grid rows and replaces all negative values with zero. The writer exists in `DataWriter`, but the normal `BatchImporter` route does not appear to reach it in `v0.13.3`. It should not be treated as a complete RAS met-HDF authoring API. |

There are two destination-routing edge cases:

- `BatchImporter` chooses the concurrent importer for destinations matching `.*\.(dss|asc|tiff)`, while `DataWriter` supports both `.tif` and `.tiff`. A `.tif` destination is valid at the writer layer but does not match the `BatchImporter` concurrent-importer predicate.
- `DataWriter` supports the specialized RAS HDF precipitation writer, but `BatchImporter` routes that extension to `NetcdfBatchImporter`, whose write buffer exits unless the resolved writer is a `NetcdfDataWriter`.

## DSS Output Details

### Pathname Parts

`DssDataWriter` starts with an empty `DSSPathname`, sets the C part from the source variable mapping, then applies write options:

- `partA`
- `partB`
- `partC`
- `partD`
- `partE`
- `partF`
- `units`
- `dataType`

For any DSS part option, a value of `*` means preserve the incoming part when Vortex has an incoming pathname available. In the importer UI, the C, D, and E fields are not editable, while A, B, and F can be supplied.

The C part is inferred by `DssDataWriter.getCPart()` from `VortexVariable` mappings. Known outputs include:

- `PRECIPITATION`
- `TEMPERATURE`
- `RADIATION-SHORT`
- `RADIATION-LONG`
- `CROP COEFFICIENT`
- `STORAGE CAPACITY`
- `PERCOLATION`
- `STORAGE COEFFICIENT`
- `MOISTURE DEFICIT`
- `IMPERVIOUS AREA`
- `CURVE NUMBER`
- `COLD CONTENT`
- `COLD CONTENT ATI`
- `MELTRATE ATI`
- `LIQUID WATER`
- `SWE`
- `WATER CONTENT`
- `WATER POTENTIAL`
- `HUMIDITY`
- `WINDSPEED`
- `PRESSURE`
- `PRECIPITATION-FREQUENCY`
- `ALBEDO`
- `ENERGY`
- `SNOWFALL ACCUMULATION`
- `SNOW DEPTH`
- `SNOW SUBLIMATION`
- `SNOW MELT`

Unknown variables fall back to an uppercase source short name.

### Grid Type

`DssUtil.getGridInfo()` decides DSS grid metadata from the grid WKT:

- If the CRS name contains `albers`, Vortex creates an HEC `AlbersInfo`.
- Otherwise, Vortex creates `SpecifiedGridInfo` and stores the WKT.

`WktFactory.getShg()` returns the Standard Hydrologic Grid WKT as a NAD83 Albers Equal Area projection for the contiguous United States. `ReferenceUtils.isShg()` recognizes SHG-like Albers grid metadata.

Vortex can read HRAP DSS grid records through `DssDataReader`, but no symmetric HRAP writer factory was found in the import writer path. On write, the path is Albers or specified-grid metadata.

### Data Type and Units

Default data type is derived in two places:

- `DssUtil.getGridInfo()` sets:
  - `PER-AVER` for nonzero-duration Celsius-compatible data.
  - `INST-VAL` for zero-duration data.
  - `PER-CUM` for other nonzero-duration data, which covers precipitation accumulation behavior.
- `DssDataWriter` then forces non-precipitation grids without an explicit `dataType` option to:
  - `PER-AVER` when the grid interval is nonzero.
  - `INST-VAL` when the interval is null or zero.

Explicit `dataType` write options can set:

- `INST-VAL`
- `PER-AVER`
- `PER-CUM`
- `INST-CUM`

`DataConverter` is important for ras-commander integration because the DSS writer is not always a raw-value copy. It converts precipitation rates such as `mm/s`, `mm/hr`, and `mm/day` to period depth in millimeters, converts meter precipitation to millimeters, converts Kelvin to Celsius, converts humidity fractions to percent, and normalizes pressure units.

### Time Window

`GridInfo` receives start and end `HecTime` values when source grids have times. During write:

- `INST-VAL` grids use the end time as the grid time.
- Other time-varying grids use a gridded time window from start to end.

Several meteorological products have product-specific time-window fixes in `GridDatasetReader.SpecialFileType`, including ABRFC QPE, MRMS IDP, GPM, AORC precipitation and temperature, NLDAS precipitation, HRRR, GEFS, GFS, UA SWE, CMORPH, and Livneh precipitation.

## Spatial Operations

`GeographicProcessor` accepts these practical options:

| Option | Meaning |
| --- | --- |
| `pathToShp` | Use a shapefile as the clipping envelope and envelope WKT source. |
| `minX`, `maxX`, `minY`, `maxY`, `envWkt` | Explicit clipping envelope. |
| `targetWkt` | Target projection WKT. The official Jython example uses `WktFactory.shg()`. |
| `targetEpsg` | API-level target EPSG option. |
| `targetCellSize` | Requested output cell size. |
| `targetCellSizeUnits` | Units for target cell size; defaults to meters. |
| `resamplingMethod` | Resampling method by display name or key. |

`ResamplingMethod` supports:

- `near` / Nearest Neighbor
- `bilinear` / Bilinear
- `average` / Average

`Resampler` builds GDAL Warp options including source SRS, target SRS, source nodata, optional target envelope (`-te`), optional target resolution (`-tr`), and resampling method (`-r`). It writes to GDAL `MEM` datasets before Vortex writes the final destination.

The importer path clips to an envelope. Supplying a shapefile does not appear to mask the output to the polygon boundary; it uses vector metadata to determine the bounds for the raster warp.

## CLI Findings

The official open-source `v0.13.3` source has no command-line class matching the issue's presumed `VortexCli` or `import_gridded` interface.

Searches of the Vortex checkout found:

- No `VortexCli` class.
- No `import_gridded` string in source history.
- No `picocli`, `@Command`, or comparable command parser.
- `public static void main()` methods only for Swing wizards and UI test launchers.

The shipped launch scripts expose Swing application modes:

- `-calculator`
- `-clipper`
- `-grid-to-point`
- `-gap-filler`
- `-image-exporter`
- `-importer`
- `-normalizer`
- `-sanitizer`
- `-time-shifter`
- `-time-step-resampler`

For example, Windows `vortex-ui/package/windows/importer.bat` runs Java with `mil.army.usace.hec.vortex.ui.VortexUi -importer`. Linux and macOS `run-vortex.sh` print similar app-mode help.

This conflicts with the current ras-commander wrapper assumption in `ras_commander/precip/VortexCli.py`, which generates a Jython script and executes:

```text
vortex.bat -s <script.py>
```

The generated Jython script itself uses real Vortex API classes (`BatchImporter`, `WktFactory`), but the `vortex.bat -s` launcher contract was not found in the official open-source Vortex `v0.13.3` source. Treat it as an installed-distribution assumption that needs direct CLB workstation verification.

## Jython and Python API Findings

The official Jython importer example is `examples/src/main/jython/met_data_import.py`:

```python
from mil.army.usace.hec.vortex.io import BatchImporter
from mil.army.usace.hec.vortex.geo import WktFactory

geo_options = {
    'pathToShp': clip_shp,
    'targetCellSize': '2000',
    'targetWkt': WktFactory.shg(),
    'resamplingMethod': 'Bilinear'
}
write_options = {'partF': 'my script import'}

myImport = BatchImporter.builder() \
    .inFiles(in_files) \
    .variables(variables) \
    .geoOptions(geo_options) \
    .destination(destination) \
    .writeOptions(write_options) \
    .build()

myImport.process()
```

Conclusion:

- Vortex can be called as a Java library from Jython.
- Vortex does not expose a CPython package.
- Calling Vortex from CPython without subprocess would require embedding or bridging to the JVM, for example through pyjnius or JPype, while also resolving Vortex jars and native GDAL/NetCDF/HDF libraries.
- ras-commander already uses pyjnius for DSS time-series operations, so a CPython-to-Java integration is feasible in principle, but it would need careful JVM lifecycle and native-library path management. It should not be added as a quick wrapper around the existing `VortexCli` module without integration tests.

## Version Matrix and Compatibility Notes

| Vortex version | Date observed | Java source/target | Bundled runtime/deps observed | Compatibility implication |
| --- | --- | --- | --- | --- |
| `v0.13.3` | 2026-05-01 tag, current upstream HEAD when cloned | Java 17 | Bundled JRE `21.0.9_10`; Java Heclib `7-IR-6`; HEC monolith `3.+`; NetCDF-Java `5.5.3`; GDAL 3.x natives | This is the source version inspected for CLB-675. Expected DSS behavior is through the current Java Heclib/DSS7 stack. |
| `v0.13.2` | 2026-04-29 tag | Java 21 according to adjacent commit history | Same general dependency family | `v0.13.3` immediately changed source/target compatibility back to Java 17. |
| `v0.13.0` to `v0.13.1` | 2026-03 to 2026-04 tags | Not fully audited for this report | Same project family | Use only if a specific installed HEC package requires them; not the recommended target for new ras-commander work. |

The Vortex source does not contain an authoritative HEC-RAS or HEC-HMS version matrix. The defensible compatibility statement from source inspection is:

- DSS grid read/write uses HEC Java Heclib classes, so output compatibility depends on the receiving HEC application's support for those DSS grid records.
- NetCDF/GeoTIFF/ASC outputs depend on the receiving application's GDAL/raster import support and projection expectations.
- HEC-RAS gridded precipitation workflows in ras-commander already prefer SHG NetCDF for direct GDAL raster input, as reflected in `RasUnsteady.set_gridded_precipitation()`.

For CLB use, Vortex `v0.13.3` should be treated as the source-backed reference version until an installed HEC-Vortex package proves that it ships additional CLI or script-launcher behavior not present in the open-source repository.

## Can ras-commander Bypass Vortex?

### Yes for simple HEC-RAS rain-on-grid cases

ras-commander already has a direct path for HEC-RAS gridded precipitation:

- `RasUnsteady.set_gridded_precipitation()` edits the unsteady flow file to use `GDAL Raster File(s)`.
- `PrecipAorc` already uses that route for NetCDF precipitation products.
- For products we can produce as compatible SHG NetCDF or raster files, a DSS intermediate is not necessary.

This is the preferred path for AORC and other workflows where ras-commander owns the data retrieval and can write RAS-compatible NetCDF/raster output.

### Not yet for DSS-grid workflows

ras-commander's `RasDss` API currently writes time series but not DSS grids. A direct DSS-grid bypass would require one of these:

- Add a Java Heclib grid writer to `RasDss` using pyjnius and the same classes Vortex uses (`GridInfo`, `AlbersInfo`, `SpecifiedGridInfo`, `GridData`, `GriddedData`).
- Validate whether `pydsstools` can write the specific DSS grid records needed by HEC-RAS/HMS and add it as an optional dependency if it is reliable.
- Continue using Vortex for DSS grid production.

Given the current ras-commander dependency and JVM patterns, the Java Heclib route is the more natural extension if DSS-grid write support becomes a core library feature.

### Partial pure-Python reimplementation is realistic

Pure-Python importers are realistic for a narrow supported subset:

- NetCDF through `xarray`, `netCDF4`, `rioxarray`, or similar.
- GRIB2 through `cfgrib`/ecCodes where installation constraints are acceptable.
- GeoTIFF/ASC through `rasterio`.
- Reprojection/resampling through `rasterio.warp` or GDAL bindings.

It is not realistic to immediately match Vortex's full source behavior without significant product-specific work. Vortex embeds meteorological product time-window corrections, unit normalization, PRISM/SNODAS conventions, and DSS grid metadata behavior that would need tests against real HEC workflows.

## ras-commander Integration Recommendations

1. Keep Vortex as an optional external converter for complex MRMS/GRIB/HDF/DSS-grid workflows.

   Vortex already handles NetCDF-Java edge cases, GDAL raster inputs, SNODAS, special meteorological time windows, unit conversion, reprojection, and DSS grid writes. Reimplementing all of that immediately would be high risk.

2. Do not document `vortex.bat -s script.py` as the official Vortex source contract.

   The current `ras_commander/precip/VortexCli.py` wrapper may work with a CLB-installed distribution, but the open-source `v0.13.3` package scripts do not show that launcher interface. Add an integration test or discovery probe against the actual installed Vortex package before relying on it for CLB-642 style workflows.

3. Prefer a Java/Jython API wrapper over a fictional CLI.

   The source-backed API is `BatchImporter.builder()...process()`. If Vortex is wrapped, ras-commander should either:

   - invoke a verified Jython launcher from the installed distribution, or
   - build a controlled Java/Jython launch command against the Vortex jars and native library folders.

4. Use direct RAS GDAL NetCDF/raster workflows when DSS is not required.

   For AORC and similar workflows, continue producing RAS-compatible SHG NetCDF or raster files and configure them with `RasUnsteady.set_gridded_precipitation()`.

5. Add DSS grid writer support to `RasDss` only if the product roadmap needs HMS/DSS-grid production without Vortex.

   The implementation should mirror Vortex's `DssUtil` and `DssDataWriter` behavior rather than inventing a new DSS grid convention. Required tests should use real HEC-DSS grid files and real HEC-RAS/HMS consumers.

6. Reimplement only narrow readers in pure Python first.

   Good candidates are local GeoTIFF/ASC to RAS-compatible NetCDF, AORC-like NetCDF normalization, and simple gridded precipitation accumulation. Avoid claiming MRMS/GRIB parity until product-specific time-window and unit-conversion tests are in place.

## Open Risks

- Official source inspection does not prove what CLB's installed HEC-Vortex package contains. The installed package may include launcher behavior absent from the open-source repository.
- Vortex can read HRAP DSS grids, but the importer write path found in source creates Albers or specified-grid metadata, not a clear HRAP writer path.
- `SnodasTarDataReader` extracts beside the source archive, which can be surprising in automated workflows.
- The `.tif` destination edge case in `BatchImporter` should be tested before using `.tif` as an import destination. `.tiff` is the safer spelling for the current importer route.
- `Hdf5RasPrecipDataWriter` writes only the precipitation values dataset path, and the normal `BatchImporter` path does not appear to reach it. It should not be used as evidence that Vortex can author full RAS plan HDF meteorology metadata.

## Bottom Line

Use Vortex as an optional, source-backed Java import engine for complex gridded meteorological conversion and DSS-grid output. Bypass it for ras-commander-controlled HEC-RAS rain-on-grid workflows that can use SHG NetCDF or raster inputs directly. If ras-commander needs first-class DSS grid writing, add a focused `RasDss` grid writer using HEC Java classes and use Vortex's `DssUtil` behavior as the reference implementation.
