# CLB-672 Davis MRMS Event Selection

## Recommendation

Use the 29 December 2022 - 1 January 2023 atmospheric river event, with the
MRMS notebook window set to:

- Start UTC: `2022-12-31T00:00:00Z`
- End UTC: `2023-01-01T12:00:00Z`
- Duration/files: 37 hourly MRMS `MultiSensor_QPE_01H_Pass2` grids

This is a local Davis/Sacramento Valley event, unlike the current Hurricane
Beryl/Houston example. It is long enough for animation while staying under the
48-hour target.

If a tighter 24-hour demonstration window is needed, the strongest Davis-domain
MRMS period in the checked range is:

- Start UTC: `2022-12-31T06:00:00Z`
- End UTC: `2023-01-01T05:00:00Z`
- Davis-domain mean: `42.16 mm` / `1.66 in`

## Event Description

A strong atmospheric river made landfall over Northern California on 29
December 2022. Two later moisture pulses produced heavy precipitation across
Northern and Central California on 30-31 December. The event produced riverine
and urban flooding, including multiple Cosumnes River levee breaks and major
flooding near Highway 99, with documented Sacramento-area power impacts.

The selected Davis-domain MRMS window totals:

- Davis buffered-domain mean: `44.08 mm` / `1.74 in`
- Peak 24-hour Davis buffered-domain mean: `42.16 mm` / `1.66 in`
- Peak hourly Davis buffered-domain mean: `0.215 in` at
  `2022-12-31T14:00:00Z`

Official event context:

- NCEI Storm Events event `1078765`: southern Sacramento/northern San Joaquin
  Valley 24-hour precipitation was around 1-3 inches, with widespread flooding
  and Cosumnes River flooding.
- NASA Earth Observatory: some Sacramento County areas recorded up to 4 inches
  in 24 hours, with January 1 satellite imagery showing floodwater.
- CW3E event summary: the 29 December 2022 - 1 January 2023 atmospheric river
  caused heavy precipitation, urban and riverine flooding, Cosumnes levee
  breaks, and Sacramento-area power outages.

## Davis Model Spatial Extent

Derived from the packaged Davis example project:

- Project: `DavisStormSystem`
- Geometry HDF: `DavisStormSystem.g02.hdf`
- Meshes: `area2`, `DS Channel`
- CRS: `EPSG:2871` from the RASMapper projection path

Model-domain bounding box in `EPSG:2871`:

```text
min_x = 6628341.54307014
min_y = 1960003.24300895
max_x = 6639684.19321551
max_y = 1969942.10700703
```

Model-domain bounding box in `EPSG:4326`:

```text
west  = -121.76689244974507
south =   38.54387089894101
east  = -121.72713010751232
north =   38.57124858409331
```

MRMS extraction used this buffered `EPSG:4326` box to include surrounding grid
cells:

```text
west  = -121.78689244974507
south =   38.523870898941006
east  = -121.70713010751233
north =   38.591248584093314
```

## MRMS S3 Availability

The public NOAA MRMS bucket contains the hourly Pass 2 product under the actual
prefix:

```text
s3://noaa-mrms-pds/CONUS/MultiSensor_QPE_01H_Pass2_00.00/
```

The shorter issue prefix without `_00.00` was checked and had zero keys for the
analysis dates:

```text
s3://noaa-mrms-pds/CONUS/MultiSensor_QPE_01H_Pass2/
```

Confirmed available hourly key counts from the actual prefix:

```text
2022-12-30: 24
2022-12-31: 24
2023-01-01: 24
2023-01-02: 24
```

Selected window first and last keys:

```text
CONUS/MultiSensor_QPE_01H_Pass2_00.00/20221231/MRMS_MultiSensor_QPE_01H_Pass2_00.00_20221231-000000.grib2.gz
CONUS/MultiSensor_QPE_01H_Pass2_00.00/20230101/MRMS_MultiSensor_QPE_01H_Pass2_00.00_20230101-120000.grib2.gz
```

## Generated Evidence

Persistent artifacts:

- `H:/Symphony/ras-commander/CLB-672/davis_event_selection.md`
- `H:/Symphony/ras-commander/CLB-672/davis_mrms_analysis.json`
- `H:/Symphony/ras-commander/CLB-672/davis_mrms_hourly_domain_mean.csv`

Workspace proof:

- Terminal recording: `terminal-logs/20260509_120547_davis_mrms_event_analysis.terminal.log`
- Analysis script: `working/CLB-672/analyze_davis_mrms_event.py`

## Sources

- NCEI Storm Events Database:
  https://www.ncei.noaa.gov/stormevents/eventdetails.jsp?id=1078765
- NASA Earth Observatory:
  https://science.nasa.gov/earth/earth-observatory/floodwater-inundates-north-central-california-150792/
- CW3E Event Summary:
  https://cw3e.ucsd.edu/cw3e-event-summary-29-december-2022-1-january-2023/
- NWS Bay Area atmospheric river overview:
  https://www.weather.gov/mtr/AtmosphericRivers_12_2022-01_2023
- NOAA MRMS S3 listing example:
  https://noaa-mrms-pds.s3.amazonaws.com/?list-type=2&prefix=CONUS/MultiSensor_QPE_01H_Pass2_00.00/20221231/
