"""Compare vendor-native conversion with explicit interval math on real fixture."""

import hashlib, json, shutil, traceback
from pathlib import Path
import numpy as np
import xarray as xr
from ras_commander import RasUnsteady, RasPrecipHdf


def run(root, install, out, source, template):
    source = Path(source)
    template = Path(template)
    with xr.open_dataset(source) as ds:
        dataset = ds.load()
    rates = dataset["APCP_surface"].values.astype(np.float64)
    times = dataset["time"].values
    dt = np.diff(times) / np.timedelta64(1, "h")
    expected = np.zeros_like(rates)
    expected[1:] = np.cumsum(rates[1:] * dt[:, None, None], axis=0)
    inst = np.zeros_like(rates)
    inst[1:] = np.cumsum(0.5 * (rates[:-1] + rates[1:]) * dt[:, None, None], axis=0)
    amounts = np.zeros_like(rates)
    amounts[1:] = rates[1:] * dt[:, None, None]
    cases = [
        ("per-avg", rates, "mm/hr", expected),
        ("cumulative", expected, "mm", expected),
    ]
    irregular = np.array([0.0, 0.5, 1.5, 2.25, 4.0])
    irregular_expected = np.zeros_like(rates)
    irregular_expected[1:] = np.cumsum(
        rates[1:] * np.diff(irregular)[:, None, None], axis=0
    )
    cases.append(("per-avg-irregular", rates, "mm/hr", irregular_expected))
    cases.append(("per-avg-date-only", rates, "mm/hr", expected))

    def write_source(ds, nc, offsets=None, date_only=False, bad_units=False):
        offsets = np.arange(len(times), dtype=float) if offsets is None else offsets
        ds = ds.assign_coords(time=("time", offsets))
        ds["time"].attrs = {
            "units": "hours since 2020-01-01"
            if date_only
            else "hours since 2020-01-01 00:00:00",
            "calendar": "proleptic_gregorian",
        }
        if bad_units:
            ds["time"].attrs["units"] = "furlongs since not-a-date"
        ds.to_netcdf(nc)

    result = {}
    for kind, data, units, wanted in cases:
        folder = root / kind
        folder.mkdir(parents=True)
        ds = dataset.copy(deep=True)
        ds["APCP_surface"].values[:] = data
        ds["APCP_surface"].attrs["units"] = units
        nc = folder / "rain.nc"
        write_source(
            ds,
            nc,
            irregular if kind == "per-avg-irregular" else None,
            date_only=kind == "per-avg-date-only",
        )
        u = folder / "Model.u01"
        shutil.copyfile(template, u)
        RasUnsteady.configure_gridded_gdal_precipitation(
            u, nc, "APCP_surface", historic=True
        )
        receipt = RasUnsteady.import_gridded_gdal_precipitation(
            u,
            units=units,
            data_type="per-avg" if kind.startswith("per-avg") else kind,
            hecras_dir=install,
        )
        evidence = RasPrecipHdf.inspect_gridded_precipitation(Path(str(u) + ".hdf"))
        oriented, _, _ = RasPrecipHdf.orient_north_up(
            wanted, dataset["x"].values, dataset["y"].values
        )
        values = np.asarray(oriented, dtype="<f4").reshape(len(times), -1)
        digest = hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()
        actual = evidence["datasets"][
            "Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values"
        ]
        result[kind] = {
            "passed": actual["sha256"] == digest,
            "expected_sha256": digest,
            "actual": actual,
            "receipt": receipt,
        }
        (out / "source-semantics.json").write_text(json.dumps(result, indent=2))
        assert result[kind]["passed"], (
            kind + " native conversion did not match independent interval math"
        )
    # Native read failures and semantic guards must preserve the target byte-for-byte.
    negatives = {}
    for case in [
        "wrong-units",
        "wrong-selector",
        "corrupt",
        "missing",
        "first-nonzero",
        "decreasing",
        "invalid-time-units",
        "per-cum-not-implemented",
        "inst-val-not-implemented",
    ]:
        folder = root / case
        folder.mkdir(parents=True)
        ds = dataset.copy(deep=True)
        ds["APCP_surface"].values[:] = expected
        ds["APCP_surface"].attrs["units"] = "mm"
        if case == "first-nonzero":
            ds["APCP_surface"].values[0] = 1.0
            ds["APCP_surface"].attrs["units"] = "mm/hr"
        if case == "decreasing":
            ds["APCP_surface"].values[-1] = 0.0
        nc = folder / "rain.nc"
        write_source(ds, nc, bad_units=case == "invalid-time-units")
        u = folder / "Model.u01"
        shutil.copyfile(template, u)
        RasUnsteady.configure_gridded_gdal_precipitation(
            u,
            nc,
            "not_a_variable" if case == "wrong-selector" else "APCP_surface",
            historic=True,
        )
        if case == "corrupt":
            nc.write_bytes(b"not NetCDF")
        if case == "missing":
            nc.unlink()
        hdf = Path(str(u) + ".hdf")
        before = (hdf.read_bytes(), u.read_bytes())
        try:
            RasUnsteady.import_gridded_gdal_precipitation(
                u,
                units="in"
                if case == "wrong-units"
                else "mm/hr"
                if case in ("first-nonzero", "inst-val-not-implemented")
                else "mm",
                data_type="per-avg"
                if case == "first-nonzero"
                else "per-cum"
                if case == "per-cum-not-implemented"
                else "inst-val"
                if case == "inst-val-not-implemented"
                else "cumulative",
                hecras_dir=install,
            )
        except (ValueError, RuntimeError, FileNotFoundError) as error:
            unchanged = before == (hdf.read_bytes(), u.read_bytes())
            negatives[case] = {
                "rejected": True,
                "unchanged": unchanged,
                "error": str(error),
            }
            assert unchanged
        else:
            raise AssertionError("Native negative case unexpectedly passed: " + case)
        (out / "negative-cases.json").write_text(json.dumps(negatives, indent=2))
    return result, negatives


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-netcdf",
        type=Path,
        required=True,
        help="Real Davis fixture NetCDF (APCP_surface, x/y/time)",
    )
    parser.add_argument("--unsteady-template", type=Path, required=True)
    parser.add_argument("--hecras-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=False)
    run(
        args.workspace,
        args.hecras_dir,
        args.workspace,
        args.source_netcdf,
        args.unsteady_template,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
