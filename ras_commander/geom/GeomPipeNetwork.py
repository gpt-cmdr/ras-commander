"""Pipe-network and pump-station geometry scenario edits.

HEC-RAS 7 stores pipe-network attributes in the geometry HDF. Pump HQ curves
also remain in the plain-text geometry file. This module keeps both
representations synchronized and preserves the native HDF compound datatype
when conduit dimensions are changed.
"""

from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple, Union

import h5py
import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomPipeNetwork:
    """Static helpers for pipe-network and pump-station scenario edits."""

    CONDUIT_ATTRIBUTES = "/Geometry/Pipe Conduits/Attributes"
    PUMP_GROUPS = "/Geometry/Pump Stations/Pump Groups"

    @staticmethod
    def _resolve_geometry_paths(geom_file: Union[str, Path]) -> Tuple[Path, Path]:
        path = Path(geom_file)
        if path.suffix.lower() == ".hdf":
            hdf_path = path
            text_path = Path(str(path)[:-4])
        else:
            text_path = path
            hdf_path = Path(f"{path}.hdf")

        if not text_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {text_path}")
        if not hdf_path.exists():
            raise FileNotFoundError(
                f"Geometry HDF not found: {hdf_path}. Run the geometry preprocessor first."
            )
        return text_path, hdf_path

    @staticmethod
    def _decode(value) -> str:
        return value.decode("utf-8", errors="replace").strip() if isinstance(value, bytes) else str(value).strip()

    @staticmethod
    def _normalize_dimensions(
        dimensions: Mapping[str, Sequence[float]],
    ) -> Mapping[str, Tuple[float, float]]:
        if not dimensions:
            raise ValueError("dimensions must contain at least one conduit")

        normalized = {}
        for name, values in dimensions.items():
            if len(values) != 2:
                raise ValueError(
                    f"Conduit '{name}' dimensions must be a (rise, span) pair"
                )
            rise, span = (float(values[0]), float(values[1]))
            if not np.isfinite(rise) or not np.isfinite(span) or rise <= 0 or span <= 0:
                raise ValueError(
                    f"Conduit '{name}' rise and span must be finite positive values"
                )
            normalized[str(name).strip()] = (rise, span)
        return normalized

    @staticmethod
    @log_call
    def set_conduit_dimensions(
        geom_file: Union[str, Path],
        dimensions: Mapping[str, Sequence[float]],
        *,
        create_backup: bool = True,
    ) -> pd.DataFrame:
        """Set absolute rise/span values for named pipe conduits.

        The write uses the dataset's native HDF datatype. This is required for
        HEC-RAS compound datasets because ordinary high-level assignment can
        corrupt fixed-width string members on some h5py/HDF5 combinations.

        Args:
            geom_file: Plain-text geometry path (``.g##``) or its ``.hdf``.
            dimensions: Mapping of conduit name to ``(rise, span)``.
            create_backup: Create an HDF backup before a material change.

        Returns:
            DataFrame containing the prior and requested dimensions and a
            ``changed`` flag for each requested conduit.
        """
        _, hdf_path = GeomPipeNetwork._resolve_geometry_paths(geom_file)
        requested = GeomPipeNetwork._normalize_dimensions(dimensions)

        with h5py.File(hdf_path, "r") as hdf:
            if GeomPipeNetwork.CONDUIT_ATTRIBUTES not in hdf:
                raise KeyError(
                    f"Geometry HDF is missing '{GeomPipeNetwork.CONDUIT_ATTRIBUTES}'"
                )
            dataset = hdf[GeomPipeNetwork.CONDUIT_ATTRIBUTES]
            attributes = dataset[()]
            required_fields = {"Name", "Rise", "Span"}
            available_fields = set(attributes.dtype.names or ())
            if not required_fields.issubset(available_fields):
                missing = sorted(required_fields - available_fields)
                raise KeyError(f"Conduit attributes are missing fields: {missing}")

            name_to_index = {
                GeomPipeNetwork._decode(row["Name"]): index
                for index, row in enumerate(attributes)
            }
            missing_names = sorted(set(requested) - set(name_to_index))
            if missing_names:
                raise KeyError(
                    f"Conduits not found: {missing_names}. Available names include: "
                    f"{sorted(name_to_index)[:20]}"
                )

            rows = []
            for name, (new_rise, new_span) in requested.items():
                index = name_to_index[name]
                old_rise = float(attributes["Rise"][index])
                old_span = float(attributes["Span"][index])
                changed = not (
                    np.isclose(old_rise, new_rise) and np.isclose(old_span, new_span)
                )
                rows.append(
                    {
                        "Name": name,
                        "old_rise": old_rise,
                        "old_span": old_span,
                        "new_rise": new_rise,
                        "new_span": new_span,
                        "changed": bool(changed),
                    }
                )
                if changed:
                    attributes["Rise"][index] = new_rise
                    attributes["Span"][index] = new_span

        if any(row["changed"] for row in rows):
            if create_backup:
                GeomParser.create_backup(hdf_path)
            with h5py.File(hdf_path, "r+") as hdf:
                dataset = hdf[GeomPipeNetwork.CONDUIT_ATTRIBUTES]
                dataset.id.write(
                    h5py.h5s.ALL,
                    h5py.h5s.ALL,
                    attributes,
                    mtype=dataset.id.get_type(),
                )
                hdf.flush()

        return pd.DataFrame(rows)

    @staticmethod
    def _find_text_hq_curve(
        lines: Sequence[str], group_name: str
    ) -> Tuple[int, int, int, np.ndarray]:
        group_prefix = "Pump Station Group="
        group_index = None
        for index, line in enumerate(lines):
            if not line.startswith(group_prefix):
                continue
            current_name = line.split("=", 1)[1].split(",", 1)[0].strip()
            if current_name == group_name:
                group_index = index
                break
        if group_index is None:
            raise KeyError(f"Pump group '{group_name}' was not found in the geometry file")

        hq_index = None
        count = None
        for index in range(group_index + 1, len(lines)):
            if lines[index].startswith(group_prefix):
                break
            if lines[index].startswith("Pump Station Group HQ="):
                hq_index = index
                count = int(lines[index].split("=", 1)[1].strip().split()[0])
                break
        if hq_index is None or count is None:
            raise KeyError(f"Pump group '{group_name}' has no HQ curve")

        values = []
        end_index = hq_index + 1
        while end_index < len(lines) and len(values) < count * 2:
            values.extend(GeomParser.parse_fixed_width(lines[end_index], 8))
            end_index += 1
        if len(values) < count * 2:
            raise ValueError(
                f"Pump group '{group_name}' declares {count} HQ points but only "
                f"{len(values) // 2} were found"
            )
        curve = np.asarray(values[: count * 2], dtype=float).reshape(count, 2)
        return hq_index, hq_index + 1, end_index, curve

    @staticmethod
    def _normalize_curve(curve: Sequence[Sequence[float]]) -> np.ndarray:
        array = np.asarray(curve, dtype=float)
        if array.ndim != 2 or array.shape[1] != 2 or len(array) < 2:
            raise ValueError("curve must contain at least two (head, flow) pairs")
        if not np.isfinite(array).all():
            raise ValueError("curve values must be finite")
        if (array[:, 1] < 0).any():
            raise ValueError("pump curve flows cannot be negative")
        return array

    @staticmethod
    @log_call
    def set_pump_group_hq_curve(
        geom_file: Union[str, Path],
        group_name: str,
        curve: Sequence[Sequence[float]],
        *,
        create_backup: bool = True,
    ) -> pd.DataFrame:
        """Set an absolute pump-group HQ curve in text and geometry HDF.

        This is an idempotent setter. To represent identical pumps in parallel,
        keep the head ordinates and multiply the flow ordinates by the number of
        pumps before calling this method.
        """
        text_path, hdf_path = GeomPipeNetwork._resolve_geometry_paths(geom_file)
        target = GeomPipeNetwork._normalize_curve(curve)
        lines = text_path.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        hq_index, data_start, data_end, text_curve = GeomPipeNetwork._find_text_hq_curve(
            lines, group_name
        )

        with h5py.File(hdf_path, "r") as hdf:
            if GeomPipeNetwork.PUMP_GROUPS not in hdf:
                raise KeyError(
                    f"Geometry HDF is missing '{GeomPipeNetwork.PUMP_GROUPS}'"
                )
            group = hdf[GeomPipeNetwork.PUMP_GROUPS]
            for required in (
                "Attributes",
                "Efficiency Curves Info",
                "Efficiency Curves Values",
            ):
                if required not in group:
                    raise KeyError(
                        f"Pump group geometry is missing '{GeomPipeNetwork.PUMP_GROUPS}/{required}'"
                    )

            attributes = group["Attributes"][()]
            names = [GeomPipeNetwork._decode(value) for value in attributes["Name"]]
            if group_name not in names:
                raise KeyError(
                    f"Pump group '{group_name}' was not found in the geometry HDF. "
                    f"Available groups: {names}"
                )
            group_index = names.index(group_name)
            start, count = (int(value) for value in group["Efficiency Curves Info"][group_index])
            if len(target) != count:
                raise ValueError(
                    f"Pump group '{group_name}' has {count} HQ points; received {len(target)}"
                )
            hdf_values = group["Efficiency Curves Values"][()]
            hdf_curve = np.asarray(hdf_values[start : start + count], dtype=float)

            text_changed = text_curve.shape != target.shape or not np.allclose(text_curve, target)
            hdf_changed = hdf_curve.shape != target.shape or not np.allclose(hdf_curve, target)

        if text_changed or hdf_changed:
            hdf_backup: Optional[Path] = None
            if create_backup:
                hdf_backup = GeomParser.create_backup(hdf_path)
            if hdf_changed:
                with h5py.File(hdf_path, "r+") as hdf:
                    group = hdf[GeomPipeNetwork.PUMP_GROUPS]
                    group["Efficiency Curves Values"][start : start + count] = target
                    hdf.flush()

            if text_changed:
                lines[hq_index] = f"Pump Station Group HQ= {len(target)} \n"
                flat_values = target.reshape(-1).tolist()
                replacement = GeomParser.format_fixed_width(
                    flat_values,
                    column_width=8,
                    values_per_line=10,
                    precision=2,
                )
                lines[data_start:data_end] = replacement
                try:
                    GeomParser.safe_write_geometry(
                        text_path, lines, create_backup=create_backup
                    )
                except Exception:
                    if hdf_changed and hdf_backup is not None:
                        import shutil

                        shutil.copy2(hdf_backup, hdf_path)
                    raise

        return pd.DataFrame(
            {
                "group_name": group_name,
                "head": target[:, 0],
                "old_flow": hdf_curve[:, 1],
                "new_flow": target[:, 1],
                "changed": [bool(text_changed or hdf_changed)] * len(target),
            }
        )
