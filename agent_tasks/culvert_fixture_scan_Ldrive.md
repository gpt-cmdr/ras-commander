# L: Drive Culvert Fixture Scan — HEC-RAS 1D Plain-Text Geometry

**Date:** 2026-06-12
**Purpose:** Identify validation fixtures with varied inline culvert configurations for a culvert reader/writer API.
**Scope scanned:** `L:\USB_Archive` (Regions 1–7, LA LWI models). Accessible and populated.

## Field layout confirmed (verbatim samples below)

Single barrel (13 comma fields before name + flag + US distance):
```
Culvert=Shape,Span,Rise,Length,n,Ke,Kex,Chart,Scale,USinv,USsta,DSinv,DSsta,Name, flag ,USdistance
```
Multiple barrel (11 fields, then NumBarrels, then a station line on the NEXT row):
```
Multiple Barrel Culv=Shape,Span,Rise,Length,n,Ke,Kex,Chart,Scale,USinv,DSinv,NumBarrels,Name, flag ,USdistance
     <station line of barrel offsets>
```

## Recommended fixtures (primary models, backups excluded)

| File | Region | Version | single `Culvert=` | multi `Multiple Barrel Culv=` | structs w/ 2+ groups | max groups/struct |
|------|--------|---------|------|------|------|------|
| **TA_Tangipahoa.g14** | R7 Tangipahoa | 6.31 | 53 | 98 | 14 | 4 |
| **TA_ChappepeelaCreek.g01** | R7 Tangipahoa | **6.60** | 43 | 37 | 8 | 4 |
| **AR.g02** (Bayou Darbonne) | R2 | 6.30 | 54 | 21 | 16 | 4 |
| BogueChittoRAS.g01 | R7 Bogue Chitto | 6.31 | 114 | 3 | 7 | 3 |
| WestCarroll.g06 | R3 (FEMA Boeuf) | **4.00** | 31 | 0 | — | — |

### Absolute paths
- `L:\USB_Archive\Region 7\Tangipahoa\Models\RAS\TA_RAS\TA_Tangipahoa.g14`  (Geom Title=2023_Existing_Conditions)
- `L:\USB_Archive\Region 7\Tangipahoa\Models\RAS\TA_ChappepeelaCreek\TA_ChappepeelaCreek.g01`  (Geom Title=2023_ChappepeelaCreek)
- `L:\USB_Archive\Region 2\Bayou Darbonne\By Darbonne_RAS\ByDArbonne_v63 - DesignStorm_v2\RAS63 - RREC\AR.g02`  (Geom Title=2021_Existing Conditions)
- `L:\USB_Archive\Region 7\Bogue Chitto\Models\RAS\DesignStorm_RAS_SST\BC_SST\BogueChittoRAS.g01`  (Geom Title=BogueChitto1D2D_Geometry)
- `L:\USB_Archive\Region 3\7.0 TO1 Data Collection\1.0 Previous Watershed Studies\05_DFIRM_Hydraulic\FEMA_Data\WestCarroll\01\HUC_08050001\Hydraulic_Models\Boeuf\Simulations\West Carroll Parish\RAS\LittleColewaBayou_TigerBayou\WestCarroll.g06`

## BEST file for "multiple barrels + multiple culvert groups"
**`L:\USB_Archive\Region 7\Tangipahoa\Models\RAS\TA_RAS\TA_Tangipahoa.g14`** (v6.31)
- Best raw multi-barrel volume: **98** `Multiple Barrel Culv=` records (+ 53 single).
- 14 structures carry 2+ culvert groups; one carries **4 groups** (ConnorCr RS 11663.34, four `Culvert #1..#4` lines).
- Mixes single-barrel and multi-barrel groups, integer and non-integer trailing US Distance fields.

Runner-up for cross-region independence: **AR.g02** (Bayou Darbonne, Region 2, different HUC) — 16 multi-group structures, plus Shape=5 (irregular/conspan) records not present in the Tangipahoa box/circular set.
Newest format coverage: **TA_ChappepeelaCreek.g01** is the only **v6.60** file found.
Legacy format coverage: **WestCarroll.g06** is **v4.00** (single-barrel only) — good for backward-compat parsing.

## Verbatim example records

Single-barrel (Tangipahoa, integer US distance `17`):
```
Culvert=1,6.67,6.67,49,0.024,0.9,1,2,3,248,420.5,247.75,452,Culvert #1  , 0 ,17
```

Multi-barrel (Tangipahoa) — NumBarrels=2, then station line:
```
Multiple Barrel Culv=1,4.83,4.83,20,0.024,0.5,1,2,1,253.8,253.5, 2,Culvert #1  , 0 ,25
     337     303     343     309
```

Multi-barrel with NON-INTEGER trailing US Distance (`20.5`), 3 barrels (Tangipahoa):
```
Multiple Barrel Culv=2,6,10,51,0.013,0.5,1,10,1,250.65,250.63, 3,Culvert #1  , 0 ,20.5
     600     582     611     593     622     604
```

TWO culvert groups at the SAME structure (Tangipahoa, Reach `BigCrUnT8.1`, Type-2 struct RS `3843.08`):
```
Type RM Length L Ch R = 2 ,3843.08 ,,,
...
Culvert=1,6.67,6.67,49,0.024,0.9,1,2,3,248,420.5,247.75,452,Culvert #1  , 0 ,17
Culvert=1,5,5,49,0.024,0.5,1,2,3,249,427.67,248.75,459.17,Culvert #2  , 0 ,17
```

FOUR culvert groups at one structure (Tangipahoa, Reach `ConnorCr`, RS `11663.34`, non-integer US dist `39.7`):
```
Culvert=2,7,7,166,0.013,0.5,1,58,1,110.47,618,109.41,620,Culvert #1  , 0 ,39.7
Culvert=2,7,7,166,0.013,0.5,1,58,1,110.5,625.5,109.47,627.5,Culvert #2  , 0 ,39.7
Culvert=2,7,7,166,0.013,0.5,1,58,1,110.49,633,109.43,635,Culvert #3  , 0 ,39.7
Culvert=2,7,7,166,0.013,0.5,1,58,1,110.55,640.5,109.35,642.5,Culvert #4  , 0 ,39.7
```

Bayou Darbonne (R2) Shape=5 irregular single-barrel + 6-barrel multi (shape diversity):
```
Culvert=5,6.64,14.23,176,0.04,0.5,1,41,1,231.22,470.04,228.61,492.71,Culvert #1  , 0 ,20.5
Multiple Barrel Culv=2,8,8,307,0.015,0.5,1,8,1,188.06,185.97, 6,Culvert #1  , 0 ,90
    1852    1860  1861.6 1869.56  1870.9 1878.56  1879.6 1887.56  1888.6 1896.56
```

## Notes for the parser
- The multi-barrel station line is a SEPARATE row immediately following the `Multiple Barrel Culv=` line (whitespace-delimited, fixed-ish columns; count of values relates to NumBarrels and barrel geometry).
- Trailing US Distance can be integer (`17`, `25`, `90`) or decimal (`20.5`, `39.7`, `7.2`).
- A single Type-2 structure block can contain 1–4 culvert groups; group boundary is the next `Culvert=`/`Multiple Barrel Culv=`, next `Type RM ...`, or next `River Reach=`.
- The flag field is ` 0 ` (space-padded) in all observed records.
- Multi-group counts were computed by walking River Reach / Type-2 headers and counting culvert lines per block.
