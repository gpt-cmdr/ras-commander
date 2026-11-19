"""Lossless repacking ("slim") of finished HEC-RAS 2D plan result HDF files.

A 2D unsteady plan result stores many time-by-cell and time-by-face series under
``Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas``.
With short output intervals these series dominate the file. :class:`HdfSlim` writes a copy
that keeps only the series a policy names, re-chunks them for fast spatial and temporal
reads, and copies everything else unchanged:

- Kept series are bit-identical to the source, stored in tiles of 16 time steps x 16,384
  cells or faces (by default) with the HDF5 shuffle and deflate level 4 filters.
- Geometry, plan and event data, summary maxima, boundary-condition line series, other
  output blocks and every attribute are copied unchanged, with the same dataset paths.
- The copy is written as ``<output>.partial``, every kept object is compared with the source
  (shape, dtype, attributes, exact bytes), and only then is it renamed into place.
- A JSON manifest (schema ``ras-commander-hdf-slim/v1``) records the policy, every dropped
  and re-chunked dataset, sizes, SHA-256 values (file names only, never host paths), the
  verification result and the software versions.

The algorithm lives in the self-contained module ``_hdf_slim_engine.py`` (standard library,
h5py and numpy only), so a Linux job can run that exact file; see
``RasApptainer.render_job(hdf_slim=...)``. Its SHA-256 is ``software.implementation_sha256``.

Command line::

    python -m ras_commander.hdf.HdfSlim SOURCE.hdf OUTPUT.hdf --manifest OUTPUT.hdf_slim.json
    python -m ras_commander.hdf.HdfSlim SOURCE.hdf --dry-run

Example::

    from ras_commander import HdfSlim

    report = HdfSlim.plan("Muncie.p04.hdf")              # read-only dry run
    manifest = HdfSlim.slim("Muncie.p04.hdf", "slim/Muncie.p04.hdf",
                            manifest_path="slim/Muncie.p04.hdf_slim.json")

No values, units, CRS or vertical datum are converted. A slim copy is a storage
optimization, not hydraulic review or approval of the results.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Union

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from . import _hdf_slim_engine as _engine

logger = get_logger(__name__)

#: Policy dataclass (defined in the engine so a Linux job can run that file alone).
HdfSlimPolicy = _engine.HdfSlimPolicy
#: Error raised with a stable ``reason_code`` (defined in the engine).
HdfSlimError = _engine.HdfSlimError

PolicySpec = Union[str, Mapping[str, Any], "HdfSlimPolicy", None]


class HdfSlim:
    """Write, plan and verify lossless slim copies of 2D plan result HDF files.

    All methods are static. Policies are given as a preset name (default
    ``"inundation-mapping"``), a policy mapping, or an :class:`HdfSlimPolicy`.

    The ``inundation-mapping`` preset keeps, for every 2D flow area:

    - required: ``Water Surface`` and ``Face Flow`` (``Face Velocity`` instead, for a mesh
      that has no Face Flow);
    - kept when present: ``Cell Cumulative Precipitation Depth``,
      ``Cell Cumulative Excess Depth`` and ``Depth``.

    A user-defined policy is a mapping with ``required``, ``keep_if_present``,
    ``fallbacks`` (required series -> substitute), ``extra_series``, ``time_chunk_steps``,
    ``space_chunk_size`` and ``deflate_level``; every key except ``required`` is optional.
    """

    MANIFEST_SCHEMA = _engine.SCHEMA
    PLAN_SCHEMA = _engine.PLAN_SCHEMA
    SERIES_ROOT = _engine.SERIES_ROOT
    DEFAULT_PRESET = _engine.DEFAULT_PRESET
    REASON_CODES = _engine.REASON_CODES

    @staticmethod
    @log_call
    def get_policy(
        policy: PolicySpec = None,
        extra_series: Sequence[str] | None = None,
        **overrides: Any,
    ) -> HdfSlimPolicy:
        """Resolve and validate a policy.

        Args:
            policy: Preset name, policy mapping (input form, or a manifest ``policy``),
                :class:`HdfSlimPolicy`, or None for ``inundation-mapping``. ``name`` keeps the
                base preset name when extras or overrides are applied.
            extra_series: Additional required series names, appended to the policy's own
                ``extra_series``.
            **overrides: ``time_chunk_steps``, ``space_chunk_size`` or ``deflate_level``.

        Returns:
            HdfSlimPolicy: The validated policy.

        Raises:
            HdfSlimError: ``HDF_SLIM_INVALID_POLICY`` for an unknown preset, unknown keys,
                repeated or empty names, or out-of-range chunk/deflate settings.
        """
        unknown = set(overrides) - {"time_chunk_steps", "space_chunk_size", "deflate_level"}
        if unknown:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"unknown policy options {sorted(unknown)}")
        if policy is None:
            resolved = HdfSlimPolicy.preset(_engine.DEFAULT_PRESET)
        elif isinstance(policy, str):
            resolved = HdfSlimPolicy.preset(policy)
        elif isinstance(policy, HdfSlimPolicy):
            resolved = policy
        elif isinstance(policy, Mapping):
            resolved = HdfSlimPolicy.from_dict(policy)
        else:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"unsupported policy type {type(policy).__name__}")
        if extra_series is not None:
            if isinstance(extra_series, (str, bytes)) or not isinstance(extra_series, Sequence):
                raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "extra_series must be a list of names")
            resolved = replace(resolved, extra_series=(*resolved.extra_series, *extra_series))
        if overrides:
            resolved = replace(resolved, **overrides)
        resolved.validate()
        return resolved

    @staticmethod
    @log_call
    def list_presets() -> dict[str, dict[str, Any]]:
        """Return every named preset as its manifest policy mapping."""
        return {name: HdfSlimPolicy.preset(name).to_dict() for name in _engine.PRESETS}

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def plan(
        hdf_path: str | Path | int,
        policy: PolicySpec = None,
        extra_series: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Report what :meth:`slim` would keep and drop, without writing anything.

        Read-only: inspects dataset metadata and stored sizes, never series values.

        Args:
            hdf_path: Plan result HDF path, or plan number (pass ``ras_object=`` to
                resolve it in a project other than the global one).
            policy: Preset name, policy mapping or :class:`HdfSlimPolicy`.
            extra_series: Additional required series names.

        Returns:
            dict: Schema ``ras-commander-hdf-slim-plan/v1`` with ``meshes``,
            ``applied_keep`` (mesh -> sorted kept dataset paths), ``kept`` and ``dropped``
            datasets, ``kept_series_raw_bytes``, ``kept_series_source_stored_bytes``,
            ``dropped_stored_bytes``, ``other_stored_bytes`` and ``required_free_bytes``
            (scratch space :meth:`slim` checks for). The compressed output size is not
            estimated.

        Raises:
            FileNotFoundError: ``hdf_path`` does not exist (raised by input resolution).
            HdfSlimError: Where :meth:`slim` would fail before writing, for example
                ``HDF_SLIM_REQUIRED_DATASET_MISSING`` or ``HDF_SLIM_NO_2D_SERIES``.
        """
        return _engine.plan(Path(hdf_path), HdfSlim.get_policy(policy, extra_series))

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def slim(
        hdf_path: str | Path | int,
        output_hdf: str | Path,
        policy: PolicySpec = None,
        extra_series: Sequence[str] | None = None,
        *,
        manifest_path: str | Path | None = None,
        workers: int | None = None,
        hash_source: bool = True,
    ) -> dict[str, Any]:
        """Write a verified, lossless slim copy of a 2D plan result HDF.

        The source is opened read-only and never modified. ``output_hdf`` must not exist;
        ``<output_hdf>.partial`` is written first and renamed only after every kept object
        is verified. On failure neither file remains.

        Args:
            hdf_path: Plan result HDF path, or plan number (pass ``ras_object=`` to
                resolve it in a project other than the global one).
            output_hdf: Destination HDF path (its folder must exist).
            policy: Preset name, policy mapping or :class:`HdfSlimPolicy`.
            extra_series: Additional required series names.
            manifest_path: When given, the manifest is also written there as JSON.
            workers: Compression threads; default is the CPUs available, at most 8.
            hash_source: Hash the source (``source.sha256_verified: true``). Pass False
                only when the caller hashes the source itself.

        Returns:
            dict: The ``ras-commander-hdf-slim/v1`` manifest.

        Raises:
            FileNotFoundError: ``hdf_path`` does not exist (raised by input resolution).
            HdfSlimError: With a ``reason_code`` from :attr:`REASON_CODES`. A manifest that
                cannot be written afterwards raises ``HDF_SLIM_IO_ERROR``; the verified
                output is then left in place.
        """
        source, output = Path(hdf_path), Path(output_hdf)
        if manifest_path is not None:
            manifest_path = Path(manifest_path)
            protected = [source, output, output.with_name(output.name + ".partial")]
            if _engine.manifest_aliases(manifest_path, protected):
                raise HdfSlimError("HDF_SLIM_INPUT_INVALID", "manifest_path aliases a protected HDF path")
            if not manifest_path.parent.is_dir():
                raise HdfSlimError("HDF_SLIM_INPUT_INVALID", "manifest_path folder does not exist")
        manifest = _engine.slim(
            source,
            output,
            HdfSlim.get_policy(policy, extra_series),
            workers=workers,
            hash_source=hash_source,
        )
        logger.info(
            "Slimmed %s: %d of %d bytes (ratio %.4f), %d datasets dropped",
            source.name, manifest["output"]["bytes"], manifest["source"]["bytes"],
            manifest["size_ratio"], len(manifest["dropped"]),
        )
        if manifest_path is not None:
            try:
                _engine.write_manifest(manifest_path, manifest)
            except OSError as exc:
                raise HdfSlimError("HDF_SLIM_IO_ERROR", f"manifest not written: {exc}") from exc
        return manifest

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def verify(
        hdf_path: str | Path | int,
        output_hdf: str | Path,
        manifest: Mapping[str, Any] | str | Path,
        *,
        check_source_sha256: bool = True,
    ) -> dict[str, Any]:
        """Re-verify an existing slim copy against its source and manifest. Read-only.

        Repeats the object-by-object comparison (every non-dropped source path present
        with equal shape, dtype, attributes and bytes; hard links shared exactly as in the
        source; dropped datasets absent; nothing extra) and checks the output's SHA-256
        and size against the manifest.

        Args:
            hdf_path: Source plan result HDF path, or plan number (pass ``ras_object=``
                to resolve it in a project other than the global one).
            output_hdf: The slim HDF.
            manifest: Manifest mapping, or path to its JSON file.
            check_source_sha256: Also hash the source and compare with
                ``manifest.source.sha256`` when the manifest recorded one.

        Returns:
            dict: ``passed`` (bool), ``objects_checked``, ``problem_count`` and
            ``problems`` (first 50 messages).

        Raises:
            FileNotFoundError: ``hdf_path`` does not exist (raised by input resolution).
            HdfSlimError: ``HDF_SLIM_INPUT_INVALID`` when the slim HDF is missing or the
                manifest file cannot be read.
        """
        if not isinstance(manifest, Mapping):
            try:
                manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"manifest unreadable: {exc}") from exc
        source, output = Path(hdf_path), Path(output_hdf)
        if not output.is_file():
            raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"slim HDF not found: {output.name}")
        problems = []
        if manifest.get("schema") != _engine.SCHEMA or manifest.get("status") != "completed":
            problems.append("manifest is not a completed ras-commander-hdf-slim/v1 manifest")
        recorded = manifest.get("output") or {}
        if output.stat().st_size != recorded.get("bytes"):
            problems.append("output size differs from manifest")
        elif _engine.sha256_file(output) != recorded.get("sha256"):
            problems.append("output sha256 differs from manifest")
        source_record = manifest.get("source") or {}
        if source_record.get("name") != source.name or source_record.get("bytes") != source.stat().st_size:
            problems.append("source name or size differs from manifest")
        elif (check_source_sha256 and source_record.get("sha256") is not None
              and _engine.sha256_file(source) != source_record["sha256"]):
            problems.append("source sha256 differs from manifest")
        dropped = manifest.get("dropped")
        if not isinstance(dropped, list) or not all(isinstance(d, Mapping) and "path" in d for d in dropped):
            problems.append("manifest dropped list is malformed")
            dropped = []
        try:
            result = _engine.verify(source, output, [d["path"] for d in dropped])
        except OSError as exc:
            result = {"objects_checked": 0, "problems": [f"not readable as HDF5: {exc}"], "problem_count": 1}
        count = len(problems) + result["problem_count"]
        problems += result["problems"]
        return {
            "passed": count == 0,
            "objects_checked": result["objects_checked"],
            "problem_count": count,
            "problems": problems[:50],
        }

    @staticmethod
    @log_call
    def write_manifest(path: str | Path, manifest: Mapping[str, Any]) -> None:
        """Write a manifest as indented, key-sorted UTF-8 JSON with LF line endings."""
        _engine.write_manifest(Path(path), manifest)

    @staticmethod
    @log_call
    def engine_path() -> Path:
        """Path of the self-contained engine file (the file staged into Linux jobs)."""
        return Path(_engine.__file__)

    @staticmethod
    @log_call
    def implementation_sha256() -> str:
        """SHA-256 of the engine file, as recorded in ``software.implementation_sha256``."""
        return _engine.implementation_sha256()


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point (see the module docstring)."""
    return _engine.main(argv)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
