"""Map caller-prepared cell WSEL columns; no aggregation or hydraulic execution.

python scripts/examples/map_supplied_wsel.py plan.p02.hdf terrain.tif cells.csv output
CSV columns: mesh_name, cell_id, q100, q200, ... . Include all physical/ghost
cells in all meshes. Blank elevation entries mean explicitly dry, never absent
cell IDs. Values must use the source model's vertical units and datum.
"""

import argparse
from pathlib import Path
import pandas as pd
from ras_commander import RasFim


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("hdf", type=Path)
    parser.add_argument("terrain", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--inflight", type=int, default=2)
    parser.add_argument("--bbox", nargs=4, type=float)
    parser.add_argument("--polygon", type=Path)
    args = parser.parse_args()
    # CSV import/schema validation must preserve IDs; only elevation blanks
    # represent dry. Catalog aggregation/rounding must already be complete.
    values = pd.read_csv(args.csv, dtype={"mesh_name": str, "cell_id": "int64"})
    values.attrs["fim_source_hdf"] = str(args.hdf.resolve())
    products = RasFim.map_sloping_profiles(args.hdf, args.terrain, args.output,
        wsel_profiles=values, engine_path=args.engine, threads=args.threads,
        max_inflight_profiles=args.inflight, bbox=args.bbox, polygon=args.polygon)
    print(products.to_string(index=False))
    print(products.attrs["performance"])


if __name__ == "__main__":
    main()
