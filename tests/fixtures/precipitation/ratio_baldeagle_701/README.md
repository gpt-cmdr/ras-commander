# HEC-RAS 7.0.1 precipitation Ratio fixture

`BaldEagleDamBrk.u03.hdf` is the unsteady-flow HDF that HEC-RAS 7.0.1 wrote
for the public USACE example project `2D Unsteady Flow Hydraulics/
BaldEagleCrkMulti2D` (HEC-RAS 7.0 example projects), unsteady file `u03`
("Gridded Precipitation"), after one edit to the text file:

```
Met BC=Precipitation|Mode=Gridded
Met BC=Precipitation|Expanded View=-1
Met BC=Precipitation|Ratio=0.5          <- added
```

Plan `p06` (which uses `u03`) was then computed with HEC-RAS 7.0.1 through
`RasCmdr.compute_plan` (simulation window shortened to one hour). HEC-RAS
rewrote `BaldEagleDamBrk.u03.hdf`; the file is kept unmodified. It stores the
ratio as a scalar float32 attribute `Ratio` on
`Event Conditions/Meteorology/Precipitation` (value 0.5), next to `Mode`,
`Source`, `DSS Filename`, `DSS Pathname`, `Interpolation Method` and
`Enabled`. The computed plan HDF stored the same attribute at the same path.
RASMapper reads it from that path (`RasMapperLib` `MetParser`/
`PrecipitationLayer`, `TryReadSingleAttributeScalar(..., "Ratio")`).

SHA-256: `f2a742f60b093e685545adf110d9484079f096f3f312b173183a290b192272d9`
