# Reference-line comma regression

`comma_name.g01` contains only the eight records of the delivered reference line
`Guadalupe Rv at Hunt, TX (USGS)` from the Upper Guadalupe UPGU1 geometry.
The excerpt preserves CRLF, trailing padding, position
records and packed 16-character coordinates are retained exactly (474 bytes).
No complete model or generated results are included.

`comma_points.g01` holds three native `Reference Point Name=`/`Position=` records
(two names contain commas) exactly as inserted into the HEC-RAS 6.6
BaldEagleCrkMulti2D example geometry (plan 03, `BaldEagleDamBrk.g09`, LF line
ends, 40-byte padded names). HEC-RAS 6.6 preprocessed and computed that plan
(1999-01-01 12:00 to 1999-01-02 12:00) and stored the three names verbatim in
`Geometry/Reference Points/Attributes` of both the geometry and plan HDF, with
`Water Surface` and `Velocity` series (145 x 3) for each point. Plan HDF
SHA-256 d67248fac5cf2a0c86a322510d1b364ce108b19bc1c07e8797727837c7d832a6
(not included).
