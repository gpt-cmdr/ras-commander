"""
RasDss - DSS File Operations for ras-commander

Summary:
    Provides static methods for interacting with HEC-DSS files (versions 6 and 7),
    enabling reading of time series, extracting catalogs, extracting boundary time
    series, and fetching file metadata, all using HEC Monolith libraries accessed
    via pyjnius. JVM setup and dependency downloads are handled automatically at
    runtime.

Functions:
    _ensure_monolith():
        Ensures HEC Monolith Java libraries are installed (downloads if needed).
    _configure_jvm():
        Configures the JVM and sets classpath/library paths for pyjnius.
    get_catalog(dss_file):
        Returns a list of all data pathnames in a DSS file.
    read_timeseries(dss_file, pathname, start_date=None, end_date=None):
        Reads a DSS time series by pathname and returns it as a pandas DataFrame.
    read_grid(dss_file, pathname, *, allow_unqualified_native=False):
        Reads one exact DSS spatial grid record and its metadata.
    read_paired_data(dss_file, pathname, *, ignore_d_part=True, dtype="stored"):
        Reads one paired-data record (every curve, labels, units, types,
        stored precision) as a DataFrame.
    write_paired_data(dss_file, pathname, x_values, y_values=None, ...):
        Writes one paired-data record; accepts the DataFrame read_paired_data returns.
    get_file_version(dss_file):
        Returns the major DSS version (6 or 7).
    get_capabilities():
        Returns the per-backend support matrix.
    read_multiple_timeseries(dss_file, pathnames):
        Reads multiple DSS time series, returning a dict of pathname to DataFrame
        (or None on failure).
    get_info(dss_file):
        Returns summary information and statistics for a DSS file, including
        partial catalog.
    extract_boundary_timeseries(boundaries_df, project_dir=None, ras_object=None):
        Extracts DSS time series for DSS-defined boundary conditions in a
        DataFrame and appends results as a new column.
    write_grid_timeseries(dss_file, pathname, data, times, grid_info):
        Writes spatial grid records such as SHG gridded precipitation to DSS.
    copy_grid_with_zero_tail(source_dss, output_dss, pathname, tail_intervals):
        Rewrites one validated grid family to an atomic derivative and appends
        explicit zero-valued intervals while preserving NoData cells.
    shutdown_jvm():
        Placeholder for JVM lifecycle management (not typically required with
        pyjnius). Deprecated no-op under the native backend.

Backends:
    Read methods (``get_catalog``, ``read_timeseries``,
    ``read_multiple_timeseries``, ``read_paired_data``, ``get_file_version``
    and everything built on them) use ``RasDss.backend``: ``"java"``
    (default), ``"native"`` (optional ras-commander-fast-dss package, no JVM) or
    ``"shadow"`` (native result, Java cross-check, differences logged). The
    environment variable ``RAS_COMMANDER_DSS_BACKEND`` overrides the
    attribute when set. ``read_grid`` under ``"native"`` requires a wheel
    advertising qualified grid CRS (``grid_srs_monolith_parity``) or
    ``allow_unqualified_native=True``. The writers (``write_timeseries``,
    ``write_timeseries_from_dataframe``, ``write_grid_timeseries``,
    ``copy_grid_with_zero_tail``, ``write_precip_grid_arrays``) switch too:
    ``"native"`` writes through ras-commander-fast-dss when the wheel has its writers
    (else ``DssCapabilityError``); ``"shadow"`` writes with Java and compares a
    native repeat on a temporary copy.

Lazy Loading:
    This module implements lazy loading for all heavy dependencies:
    - pyjnius: Only imported when DSS methods are actually called
    - jnius_config: Only imported during JVM configuration
    - HecMonolithDownloader: Only imported when ensuring monolith installation
    - Java classes: Only loaded after JVM is configured

    This ensures that importing RasDss has minimal overhead and users who don't
    use DSS functionality don't pay the cost of loading Java/pyjnius.
"""

import atexit
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

# Lazy imports - these are always needed for type hints and basic operations
import numpy as np
import pandas as pd

# Import decorator from parent package
from ..Decorators import log_call
from . import _backend, _errors

logger = logging.getLogger(__name__)

# Lines of the HEC-DSS library's message file that report a failure. Open and close
# messages name the file, so they are excluded: a path can contain any of these words.
_HEC_FAILURE_LINE = re.compile(
    r"ERROR;|ERROR DURING|Error:|Error Code|Error code|Damaged|Read Access Only|Cannot |Unable to"
)
_HEC_ROUTINE_LINE = re.compile(r"ZOPEN|zopen|ZCLOSE|zclose|\(Read Access Only\)|Read access")
# The message file restarts once it passes this size (a long run opens many files).
_HEC_MESSAGE_FILE_LIMIT = 4 * 1024 * 1024


class RasDss:
    """
    Static class for DSS file operations.

    Uses HEC Monolith libraries (auto-downloaded on first use).
    Supports both DSS V6 and V7 formats.

    All heavy dependencies (pyjnius, Java) are lazy-loaded on first use.

    Usage:
        from ras_commander import RasDss

        # Read time series
        df = RasDss.read_timeseries("file.dss", "/BASIN/LOC/FLOW//1HOUR/OBS/")

        # Get catalog
        paths = RasDss.get_catalog("file.dss")

    Backends:
        ``RasDss.backend`` selects how read and write methods access DSS files:
        ``"java"`` (default; HEC Monolith via pyjnius), ``"native"``
        (ras-commander-fast-dss, no JVM) or ``"shadow"`` (reads: native result plus a
        logged Java cross-check; writes: Java result plus a logged native
        repeat on a temporary copy). ``RAS_COMMANDER_DSS_BACKEND`` overrides it
        when set.
    """

    _jvm_configured = False
    _monolith = None
    _messages_routed = False
    _message_file: Optional[Path] = None
    _message_offset = 0
    _message_lock = threading.Lock()

    #: HEC-DSS library message level (``zset("MLEVEL")``) set before the first Java DSS
    #: call. The messages go to a private file (see ``_route_hec_messages``), never to
    #: the console. Level 1 keeps the library's failure messages, which are logged, and
    #: refused writes raise. Values below 1 are treated as 1, because level 0 hides
    #: refused writes. Set it before the first DSS call.
    hec_message_level = 1

    #: Backend: "java" (default in this release), "native" or "shadow".
    #: The environment variable RAS_COMMANDER_DSS_BACKEND overrides it when set.
    backend = _backend.DEFAULT_BACKEND

    #: Shadow writes copy an existing target up to this size (MB) before the Java write;
    #: larger targets are not compared. RAS_COMMANDER_DSS_SHADOW_COPY_LIMIT_MB overrides it.
    shadow_copy_limit_mb = _backend.SHADOW_COPY_LIMIT_MB_DEFAULT

    @staticmethod
    @log_call
    def get_backend() -> str:
        """Return the backend the next read or write call will use.

        Resolution order: ``RAS_COMMANDER_DSS_BACKEND`` (when set), then
        ``RasDss.backend``. ``"shadow"`` resolves to ``"java"`` when
        ras-commander-fast-dss is not installed (one warning is logged).

        Raises:
            ValueError: If the configured name is not java, native or shadow.
            ImportError: If ``"native"`` is selected and ras-commander-fast-dss is not
                installed.
        """
        return _backend.effective_backend(RasDss.backend)

    _WINDOWS_JAVA_ROOTS = (Path("C:/Program Files/Java"), Path("C:/Program Files (x86)/Java"))
    _WINDOWS_HEC_ROOT = Path("C:/Program Files/HEC")
    _POSIX_JAVA_ROOTS = (Path("/usr/lib/jvm"), Path("/usr/lib64/jvm"),
                         Path("/usr/java"), Path("/opt/java"), Path("/opt"))
    _MACOS_JAVA_ROOTS = (Path("/Library/Java/JavaVirtualMachines"),
                         Path("/System/Library/Java/JavaVirtualMachines"))

    @staticmethod
    def _jvm_library_names(system: Optional[str] = None) -> tuple:
        """Select platform library names without loading a JVM."""
        system = system or sys.platform
        if system.startswith("win"):
            return ("jvm.dll",)
        return ("libjvm.dylib",) if system == "darwin" else ("libjvm.so",)

    @staticmethod
    def _has_jvm_lib(java_dir: Path, system: Optional[str] = None) -> bool:
        """Check library-file presence; this does not qualify runtime compatibility."""
        try:
            return any(path.is_file() for name in RasDss._jvm_library_names(system)
                       for path in java_dir.rglob(name))
        except OSError:
            return False

    @staticmethod
    def _java_home_from_executable() -> Optional[Path]:
        """Resolve PATH's Java symlink chain to its installation directory."""
        import shutil
        found = shutil.which("java")
        if not found:
            return None
        try:
            executable = Path(found).resolve()
        except (OSError, RuntimeError):
            return None
        return executable.parent.parent if executable.parent.name.lower() == "bin" else executable.parent

    @staticmethod
    def _java_home_candidates(system: Optional[str] = None) -> List[Path]:
        """Keep installed roots first on Windows and PATH first on POSIX."""
        system = system or sys.platform
        executable_home = RasDss._java_home_from_executable()
        candidates = []
        if executable_home is not None and not system.startswith("win"):
            candidates.append(executable_home)
        if system.startswith("win"):
            for root in RasDss._WINDOWS_JAVA_ROOTS:
                for pattern in ("jre*", "jdk*", "jdk-*"):
                    candidates.extend(sorted(root.glob(pattern), reverse=True))
            for pattern in ("*/*/jre", "**/jre"):
                candidates.extend(sorted(RasDss._WINDOWS_HEC_ROOT.glob(pattern), reverse=True))
            if executable_home is not None:
                candidates.append(executable_home)
        else:
            if system == "darwin":
                for root in RasDss._MACOS_JAVA_ROOTS:
                    candidates.extend(bundle / "Contents" / "Home"
                                      for bundle in sorted(root.glob("*"), reverse=True))
            for root in RasDss._POSIX_JAVA_ROOTS:
                # Avoid recursively scanning unrelated application trees under /opt.
                patterns = ("java-*", "jdk*", "jre*", "temurin*") if root == Path("/opt") else ("*",)
                for pattern in patterns:
                    candidates.extend(sorted(root.glob(pattern), reverse=True))
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _discover_java_home(system: Optional[str] = None) -> Optional[Path]:
        """Find the first directory containing this platform's JVM library file."""
        for candidate in RasDss._java_home_candidates(system):
            if candidate.is_dir() and RasDss._has_jvm_lib(candidate, system):
                return candidate
        return None

    @staticmethod
    @log_call
    def get_capabilities() -> pd.DataFrame:
        """Return what each backend supports for every public DSS operation.

        Does not start a JVM or import the ras_commander_fast_dss engine beyond an import
        check.

        Returns:
            DataFrame with one row per operation and columns ``operation``,
            ``java``, ``native``, ``shadow`` and ``note``. Cell values:

            - ``"yes"``: supported on that backend;
            - ``"gated"``: needs a qualified or writer-capable engine, or an
              explicit opt-in, and otherwise raises ``DssCapabilityError``:
              ``read_grid`` under ``native`` (``attrs["native_grid_qualified"]``)
              and the writers under ``native``
              (``attrs["native_writes_available"]``);
            - ``"java"``: runs on Java, whatever the backend (shadow writes
              also repeat the write natively on a temporary copy);
            - ``"no"``: not provided.

            ``attrs``: ``requested_backend`` (``RasDss.backend`` or the
            environment override), ``native_installed`` (bool),
            ``native_grid_qualified`` (bool) and ``native_writes_available``
            (bool).

        Example:
            caps = RasDss.get_capabilities().set_index("operation")
            if caps.loc["read_paired_data", "native"] == "yes":
                rating = RasDss.read_paired_data(dss_file, pathname)
        """
        df = pd.DataFrame(
            list(_backend.CAPABILITIES),
            columns=["operation", "java", "native", "shadow", "note"],
        )
        df.attrs = {
            "requested_backend": _backend.requested_backend(RasDss.backend),
            "native_installed": _backend.native_available(),
            "native_grid_qualified": _backend.native_grid_qualified(),
            "native_writes_available": _backend.native_writes_available(),
        }
        return df

    @staticmethod
    def _ensure_monolith():
        """Ensure HEC Monolith is downloaded and available."""
        if RasDss._monolith is not None:
            return RasDss._monolith

        # Lazy import from same subpackage
        from ._hec_monolith import HecMonolithDownloader

        RasDss._monolith = HecMonolithDownloader()

        if not RasDss._monolith.is_installed():
            logger.info(
                "Installing HEC Monolith libraries for DSS operations "
                "(one-time download, ~20 MB)"
            )
            RasDss._monolith.install()

        return RasDss._monolith

    @staticmethod
    def _configure_jvm():
        """Configure JVM classpath for pyjnius (must be done before first import)."""
        if RasDss._jvm_configured:
            return

        # Ensure monolith is installed
        monolith = RasDss._ensure_monolith()

        # Lazy import pyjnius config
        try:
            import jnius_config
        except ImportError:
            raise ImportError(
                "pyjnius is required for DSS file operations.\n"
                "Install with: pip install pyjnius"
            )

        # Check if JVM already started using jnius_config (does NOT start the JVM)
        # IMPORTANT: Never import from jnius here - that would start the JVM with
        # an empty classpath before we can call jnius_config.add_classpath()
        if getattr(jnius_config, 'vm_running', False):
            RasDss._jvm_configured = True
            RasDss._route_hec_messages()
            return

        # Get classpath and library path
        classpath = monolith.get_classpath()
        library_path = monolith.get_library_path()

        logger.debug("Configuring Java VM for DSS operations")

        # Honor explicit JAVA_HOME; auto-discover only when it is absent.
        if 'JAVA_HOME' not in os.environ:
            java_home = RasDss._discover_java_home()
            if java_home is None:
                roots = (RasDss._WINDOWS_JAVA_ROOTS + (RasDss._WINDOWS_HEC_ROOT,)
                         if sys.platform.startswith("win") else
                         RasDss._MACOS_JAVA_ROOTS + RasDss._POSIX_JAVA_ROOTS
                         if sys.platform == "darwin" else RasDss._POSIX_JAVA_ROOTS)
                raise RuntimeError(
                    "Java not found. Please set JAVA_HOME environment variable "
                    "or install Java JDK/JRE.\nSearched: java on PATH and "
                    + ", ".join(str(root) for root in roots)
                )
            os.environ['JAVA_HOME'] = str(java_home)
            logger.debug("Found Java runtime: %s", java_home)

        # Set classpath (must be done before first import from jnius)
        jnius_config.add_classpath(*classpath)

        # Set library path for native libraries
        if 'LD_LIBRARY_PATH' in os.environ:
            os.environ['LD_LIBRARY_PATH'] = (
                library_path + ':' + os.environ['LD_LIBRARY_PATH']
            )
        else:
            os.environ['LD_LIBRARY_PATH'] = library_path

        # Windows: Add to PATH for native DLLs
        if os.name == 'nt':
            os.environ['PATH'] = (
                library_path + os.pathsep + os.environ.get('PATH', '')
            )

        RasDss._jvm_configured = True
        logger.debug("Java VM configured for DSS operations")
        RasDss._route_hec_messages()

    @staticmethod
    def _route_hec_messages() -> None:
        """Send the HEC-DSS library's messages to a private file before any DSS file opens.

        The library writes its messages to Fortran unit ``MUNIT``, which its Fortran
        runtime connects to the process's stdout handle at the first write and then
        keeps. When the process later redirects file descriptor 1 (pytest's output capture
        does this around every test, and any tool that captures fd-level output can), that
        handle is closed and Windows can give its value to the next file the library
        opens. Later messages are then written into that DSS file: reads return console
        text as values and later writes fail.

        ``HecDataManager.setMessageFile`` connects ``MUNIT`` to a file instead, so no
        library message depends on the stdout handle. Silencing the library is not an
        option: at level 0 a DSS6 time-series write to a read-only file returns normally
        with nothing written, and nothing reports it. ``_drain_hec_messages`` reads the
        failure lines back. If the file cannot be set up, the level drops to 0 and a
        warning is logged; writers still refuse read-only files, through
        ``_require_writable_dss_file``. Never raises.

        Called from ``_configure_jvm`` after the classpath is set, so this is the point
        where the JVM starts. pydsstools (``write_precip_grid_arrays``) is a separate
        library and is not affected.

        A few Fortran ``WRITE(*,*)`` statements (``zrrec6``, ``zabort6``) bypass ``MUNIT``
        and can still reach a stale handle. They run only after a failed read of a damaged
        DSS6 file.
        """
        if RasDss._messages_routed:
            return
        RasDss._messages_routed = True
        directory = None
        try:
            from jnius import autoclass

            heclib = autoclass('hec.heclib.util.Heclib')
            manager = autoclass('hec.heclib.dss.HecDataManager')
            directory = Path(tempfile.mkdtemp(prefix="rasdss_messages_"))
            message_file = directory / "hec_messages.txt"
            status = int(manager.setMessageFile(str(message_file)))
            if status != 0:
                raise RuntimeError(f"setMessageFile returned {status}")
            heclib.Hec_zset("MLEVEL", "", max(1, int(RasDss.hec_message_level)))
            RasDss._message_file = message_file
            RasDss._message_offset = 0
            atexit.register(RasDss._close_message_file)
        except Exception as exc:  # never block DSS I/O on message routing
            logger.warning(
                "Could not route HEC-DSS library messages to a file (%s). Their level is "
                "set to 0, so library failures are not reported and a redirected stdout "
                "can still receive library messages.", exc)
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            RasDss._message_file = None
            try:
                from jnius import autoclass

                autoclass('hec.heclib.util.Heclib').Hec_zset("MLEVEL", "", 0)
            except Exception as level_exc:
                logger.warning("Could not set the HEC-DSS message level: %s", level_exc)

    @staticmethod
    def _close_message_file() -> None:
        """Close and remove the private message file at interpreter exit. Never raises."""
        message_file, RasDss._message_file = RasDss._message_file, None
        if message_file is None:
            return
        try:
            from jnius import autoclass

            autoclass('hec.heclib.dss.HecDataManager').closeMessageFile()
        except Exception as exc:
            logger.debug("Could not close the HEC-DSS message file: %s", exc)
        shutil.rmtree(message_file.parent, ignore_errors=True)

    @staticmethod
    def _drain_hec_messages() -> List[str]:
        """Log and return the failure lines the HEC-DSS library wrote since the last call.

        Some failures reach the caller only here: HEC Monolith returns normally from a
        DSS6 time-series write to a read-only file, and a read of a damaged file looks
        like a record with no data. Never raises.
        """
        message_file = RasDss._message_file
        if message_file is None:
            return []
        try:
            from jnius import autoclass

            manager = autoclass('hec.heclib.dss.HecDataManager')
            with RasDss._message_lock:
                manager.flushMessageFile()
                with open(message_file, 'rb') as handle:
                    handle.seek(RasDss._message_offset)
                    text = handle.read()
                RasDss._message_offset += len(text)
                if RasDss._message_offset > _HEC_MESSAGE_FILE_LIMIT:
                    manager.windMessageFile()
                    RasDss._message_offset = 0
        except Exception as exc:
            logger.debug("Could not read the HEC-DSS message file: %s", exc)
            return []
        failures = []
        for line in text.decode('latin-1').splitlines():
            line = line.strip()
            if _HEC_FAILURE_LINE.search(line) and not _HEC_ROUTINE_LINE.search(line):
                failures.append(line)
        if failures:
            logger.warning("HEC-DSS library reported: %s", " | ".join(failures[:8]))
        return failures

    @staticmethod
    def _raise_hec_write_failures(failures: List[str], context: str = "") -> None:
        """Raise when the HEC-DSS library reported failures during a Java write.

        HEC Monolith can return normally from a write it refused, so a writer must not
        report success while such a line is outstanding.
        """
        if failures:
            suffix = f" ({context})" if context else ""
            raise RuntimeError(
                f"HEC-DSS library refused the write{suffix}: " + "; ".join(failures[:3])
            )

    @staticmethod
    def _require_java_record_stored(dss_file: str, pathname: str) -> None:
        """Reopen the file and raise unless ``pathname`` is in its catalog.

        HEC Monolith can return normally, with no message, from a DSS7 write to a damaged
        file: the file grows, but the catalog stays empty and the record cannot be read.
        Compares parts A, B, C and F without case or blanks, which DSS6 changes; the
        library sets the D part per block and can respell the E part. A non-ASCII pathname is not compared: Monolith
        stores replacement characters. Call it after the writing handle is released.
        """
        if not pathname.isascii():
            return

        def key(path: Any) -> Tuple[str, ...]:
            parts = re.sub(r"\s", "", str(path)).upper().split('/')
            return tuple(parts[i] for i in (1, 2, 3, 6)) if len(parts) == 8 else ()

        from jnius import autoclass

        dss = autoclass('hec.heclib.dss.HecDss').open(dss_file)
        try:
            catalog = dss.getCatalogedPathnames()
            stored = {key(catalog.get(i)) for i in range(catalog.size())}
        finally:
            try:
                dss.done()
            finally:
                RasDss._release_dss_file(dss_file)
        if key(pathname) not in stored:
            raise RuntimeError(
                f"DSS write reported no error, but {pathname} is not in the catalog of "
                f"{dss_file}. The file may be damaged."
            )

    @staticmethod
    def _require_writable_dss_file(dss_file: Union[str, Path]) -> None:
        """Refuse a read-only target before any Java call.

        The library's only report of a refused DSS6 time-series write is a message, which
        is unavailable if routing failed or another library in the process took the
        message unit. This check does not depend on either. Other refusals (access
        control lists, locks) still reach the caller through the Java calls.
        """
        if not os.access(dss_file, os.W_OK):
            raise RuntimeError(
                f"Cannot write to DSS file, it is read-only: {dss_file}. "
                "Nothing was written."
            )

    @staticmethod
    @log_call
    def get_catalog(dss_file: Union[str, Path]) -> pd.DataFrame:
        """
        Get catalog of all data paths in DSS file.

        Args:
            dss_file: Path to DSS file

        Returns:
            DataFrame with 'pathname' column containing all DSS pathnames

        Example:
            catalog = RasDss.get_catalog("sample.dss")
            print(f"Found {len(catalog)} pathnames")
            for pathname in catalog['pathname']:
                print(pathname)

        Backends:
            Under ``"native"`` and ``"shadow"`` a missing file raises
            ``FileNotFoundError`` (the Java path also refuses missing files)
            and a file that is not DSS raises
            ``ras_commander_fast_dss.DssFormatError`` (a ``RuntimeError``; Java
            returns zero rows).
        """
        backend = RasDss.get_backend()
        if backend == "native":
            return RasDss._get_catalog_native(dss_file)
        if backend == "shadow":
            return RasDss._get_catalog_shadow(dss_file)
        return RasDss._get_catalog_java(dss_file)

    @staticmethod
    def _get_catalog_native(dss_file: Union[str, Path]) -> pd.DataFrame:
        """Catalog through ras-commander-fast-dss (no JVM). Same frame as the Java path."""
        from ras_commander.RasUtils import RasUtils

        dc = _backend.import_native()
        resolved = RasUtils.safe_resolve(Path(dss_file))
        catalog = dc.get_catalog(resolved)
        df = catalog[['pathname']].reset_index(drop=True).copy()
        df.attrs = {}
        return df

    @staticmethod
    def _get_catalog_shadow(dss_file: Union[str, Path]) -> pd.DataFrame:
        """Native catalog, cross-checked against Java. Comparison never raises."""
        import time

        t0 = time.perf_counter()
        try:
            native_df = RasDss._get_catalog_native(dss_file)
        except Exception as native_exc:
            # Never run Java here: on a missing file it creates an empty DSS file.
            _backend.record(
                "catalog", "skipped",
                f"java skipped: native {type(native_exc).__name__}",
                dss_file=dss_file, native_error=native_exc,
                native_seconds=time.perf_counter() - t0,
            )
            raise
        native_s = time.perf_counter() - t0
        try:
            java_df, java_exc = None, None
            t1 = time.perf_counter()
            try:
                java_df = RasDss._get_catalog_java(dss_file)
            except Exception as exc:
                java_exc = exc
            java_s = time.perf_counter() - t1
            outcome, label, diffs = _backend.classify_catalog(java_df, java_exc, native_df)
            _backend.record(
                "catalog", outcome, label, dss_file=dss_file, diffs=diffs,
                java_seconds=java_s, native_seconds=native_s, java_error=java_exc,
                detail={"entries": len(native_df)},
            )
        except Exception as exc:  # the comparison must never break the read
            logger.warning("DSS shadow catalog comparison failed for %s: %s", dss_file, exc)
        return native_df

    @staticmethod
    def _get_catalog_java(dss_file: Union[str, Path]) -> pd.DataFrame:
        """Catalog through HEC Monolith (pyjnius)."""
        # Configure JVM (must be before first jnius import)
        RasDss._configure_jvm()

        # Import Java classes via pyjnius (lazy)
        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')

        dss_file = str(RasUtils.safe_resolve(Path(dss_file)))
        # HecDss.open() creates a new, empty DSS file when the path does not exist.
        # A read must never create a file.
        RasDss._require_existing_dss_file(dss_file)

        # Open DSS file
        dss = None
        try:
            dss = HecDss.open(dss_file)
            # Get catalog (returns Java Vector of pathname strings)
            catalog_vector = dss.getCatalogedPathnames()

            # Convert Java Vector to Python list
            paths = []
            for i in range(catalog_vector.size()):
                paths.append(str(catalog_vector.get(i)))

            # Return as DataFrame for easier manipulation
            return pd.DataFrame({'pathname': paths})

        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    RasDss._release_dss_file(dss_file)

    @staticmethod
    @log_call
    def read_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Read time series from DSS file.

        Args:
            dss_file: Path to DSS file
            pathname: DSS pathname (e.g., "/BASIN/LOC/FLOW//1HOUR/OBS/").
                The D part is ignored: the whole dataset is read.
            start_date: Optional start of the window (inclusive). HEC strings
                such as ``"01JAN2020 0000"``, ISO strings and datetimes are
                accepted. Honored by the native and shadow backends; the Java
                backend ignores it and returns the whole dataset.
            end_date: Optional end of the window (inclusive; with both ends
                given, an end between stamps moves forward to the next stamp).
                Same backend rules as ``start_date``.

        Returns:
            pandas DataFrame with DatetimeIndex and 'value' column

        Backends:
            ``"native"`` and ``"shadow"`` return NaN for HEC missing values
            (the Java path returns the raw -3.4028235e38 marker). A pathname
            without data raises ``ras_commander_fast_dss.DssPathnameNotFoundError``
            (a ``ValueError`` and ``RuntimeError``); paired data, grids and
            other non-time-series records raise
            ``ras_commander_fast_dss.DssUnsupportedRecordError`` (a ``RuntimeError``).

            All-missing DSS6 data differs between the paths. HEC Monolith
            reports a DSS6 regular request whose values are all -901/-902 as
            not found (heclib's DSS6 "no data" rule). The native engine finds
            the blocks and, after trimming the missing values, raises the same
            ``DssPathnameNotFoundError``; a window that also contains valid
            values is returned. ``"shadow"`` re-reads such a not-found case
            with the engine's opt-in ``no_data="refuse"`` (HEC's rule) only
            to label the comparison; that option is provided for Java/native
            parity checks and testing and never changes the returned result.
            Stored NaN values are values: the leading/trailing trim removes
            HEC missing markers only, as heclib's ``ztsTrim`` does.

        Example:
            df = RasDss.read_timeseries("file.dss", "/BASIN/LOC/FLOW//1HOUR/OBS/")
            print(df.head())
        """
        backend = RasDss.get_backend()
        if backend == "native":
            return RasDss._read_timeseries_native(dss_file, pathname, start_date, end_date)
        if backend == "shadow":
            return RasDss._read_timeseries_shadow(dss_file, pathname, start_date, end_date)
        return RasDss._read_timeseries_java(dss_file, pathname)

    @staticmethod
    def _read_timeseries_native(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        dss_handle: Any = None,
    ) -> pd.DataFrame:
        """Time series through ras-commander-fast-dss (no JVM).

        ``dss_handle`` is an open ``ras_commander_fast_dss.DssFile`` to reuse; when it is
        None the file is opened and closed for this call.
        """
        from ras_commander.RasUtils import RasUtils

        resolved = RasUtils.safe_resolve(Path(dss_file))
        if dss_handle is not None:
            df = dss_handle.read_timeseries(pathname, start_date, end_date)
        else:
            dc = _backend.import_native()
            with dc.open(resolved) as handle:
                df = handle.read_timeseries(pathname, start_date, end_date)
        # ras-commander's resolver stays authoritative for the dss_file attribute.
        df.attrs['dss_file'] = str(resolved)
        return df

    @staticmethod
    def _read_timeseries_shadow(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        dss_handle: Any = None,
    ) -> pd.DataFrame:
        """Native time series, cross-checked against Java. Comparison never raises.

        Java ignores the window, so its frame is cut to the same window before
        comparison.

        All-missing DSS6 data (Java/native difference): HEC Monolith reports a
        DSS6 regular time-series request as not found when every value it reads is
        -901 or -902 (heclib ``zrrtsi.f`` status 4). The native engine finds those
        blocks by default and, after its default trim, reports "no values" with the
        same ``DssPathnameNotFoundError`` type that an absent pathname raises. When
        the native read raises not-found, shadow mode repeats it with
        the engine's opt-in ``no_data="refuse"`` (HEC's rule; it raises
        ``DssNoDataError`` with ``status == 4``) to label the case as the HEC
        no-data rule rather than a missing record. The option exists for this
        parity check and for testing: the returned frame or error is always the
        default native result, as under ``"native"``. Wheels without
        ``DssNoDataError`` keep the broader D4 labels.
        """
        import time

        dc = _backend.import_native()
        native_df, native_exc = None, None
        t0 = time.perf_counter()
        try:
            native_df = RasDss._read_timeseries_native(
                dss_file, pathname, start_date, end_date, dss_handle=dss_handle
            )
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t0

        # Java runs only when it is safe and comparable: it crashes the JVM on
        # paired data, creates missing files, and has nothing to say about bad
        # arguments. Not-found is compared (it can expose native false negatives).
        run_java = native_exc is None or isinstance(native_exc, dc.DssPathnameNotFoundError)
        if not run_java:
            _backend.record(
                "read_timeseries", "skipped",
                f"java skipped: native {type(native_exc).__name__}",
                dss_file=dss_file, pathname=pathname, native_error=native_exc,
                native_seconds=native_s,
            )
            raise native_exc
        try:
            java_df, java_exc = None, None
            t1 = time.perf_counter()
            try:
                java_df = RasDss._read_timeseries_java(dss_file, pathname)
            except Exception as exc:
                java_exc = exc
            java_s = time.perf_counter() - t1
            windowed = start_date is not None or end_date is not None
            if java_df is not None and windowed:
                source = native_df if native_df is not None else java_df
                interval = source.attrs.get('interval') or 0
                java_df = _backend.cut_window(java_df, start_date, end_date, interval, dc)
                if len(java_df) == 0:
                    java_df, java_exc = None, ValueError(
                        f"No data found for pathname: {pathname}"
                    )
            java_window_df, java_window_error = None, None
            bounds = _backend.verification_window(native_df)
            if (java_df is None and bounds is not None
                    and isinstance(java_exc, ValueError)
                    and str(java_exc) == f"No data found for pathname: {pathname}"):
                try:
                    java_window_df = RasDss._read_timeseries_java(
                        dss_file, pathname, start_date=bounds[0], end_date=bounds[1]
                    )
                except Exception as exc:
                    java_window_error = f"{type(exc).__name__}: {exc}"
            def _native_reread(**options):
                if dss_handle is not None:
                    return dss_handle.read_timeseries(pathname, start_date, end_date, **options)
                from ras_commander.RasUtils import RasUtils
                with dc.open(RasUtils.safe_resolve(Path(dss_file))) as handle:
                    return handle.read_timeseries(pathname, start_date, end_date, **options)

            native_hec_no_data = native_exc is not None and _backend.native_refuses_no_data(
                _native_reread, native_exc
            )
            outcome, label, diffs = _backend.classify_timeseries(
                pathname, java_df, java_exc, native_df, native_exc,
                java_window_df=java_window_df, native_hec_no_data=native_hec_no_data,
            )
            java_s = time.perf_counter() - t1
            detail = {"windowed": windowed, "native_hec_no_data": native_hec_no_data,
                      "java_window_verified": java_window_df is not None and outcome == "expected"
                      and label.startswith("D3 "),
                      "java_window_error": java_window_error}
            if native_df is not None:
                detail["values"] = len(native_df)
            if java_df is not None:
                detail["java_markers"] = _backend.java_marker_count(java_df)
            _backend.record(
                "read_timeseries", outcome, label, dss_file=dss_file,
                pathname=pathname, diffs=diffs, java_seconds=java_s,
                native_seconds=native_s, java_error=java_exc,
                native_error=native_exc, detail=detail,
            )
        except Exception as exc:  # the comparison must never break the read
            logger.warning(
                "DSS shadow read_timeseries comparison failed for %s %s: %s",
                dss_file, pathname, exc,
            )
        if native_exc is not None:
            raise native_exc
        return native_df

    @staticmethod
    def _read_timeseries_java(
        dss_file: Union[str, Path],
        pathname: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Whole Java dataset, or an explicit private shadow-verification window."""
        if (start_date is None) != (end_date is None):
            raise ValueError("Java verification requires both window bounds")
        # Configure JVM (must be before first jnius import)
        RasDss._configure_jvm()

        # Import Java classes via pyjnius (lazy)
        from jnius import autoclass, cast
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')

        dss_file = str(RasUtils.safe_resolve(Path(dss_file)))
        # HecDss.open() creates a new, empty DSS file when the path does not exist.
        RasDss._require_existing_dss_file(dss_file)

        # Open DSS file
        dss = None
        try:
            dss = HecDss.open(dss_file)
            # Read time series
            # True = ignore D-part (date) for wildcards
            container = (dss.get(pathname, start_date, end_date)
                         if start_date is not None else dss.get(pathname, True))

            if container is None:
                raise ValueError(f"No data found for pathname: {pathname}")

            # Paired data, grids and other records come back as other container
            # classes; casting them to TimeSeriesContainer misreads their fields.
            container_class = str(container.getClass().getName())
            if container_class != 'hec.io.TimeSeriesContainer':
                raise TypeError(
                    f"Pathname is not a time series record ({container_class}): {pathname}"
                )

            # Cast to TimeSeriesContainer to access fields
            tsc = cast('hec.io.TimeSeriesContainer', container)

            # An absent or all-missing dataset comes back as an empty container.
            if int(tsc.numberValues) <= 0 or tsc.times is None or tsc.values is None:
                raise ValueError(f"No data found for pathname: {pathname}")

            # Extract values and times from Java container
            # pyjnius automatically converts Java arrays to Python lists
            values = np.array(tsc.values)  # Java double[] -> numpy array
            times = np.array(tsc.times, dtype=np.int64)

            # TimeSeriesContainer.times are counts of timeGranularitySeconds
            # (60 for minutes, 1 for seconds) after julianBaseDate days past the
            # HEC epoch (December 31, 1899 00:00). Older containers use minutes
            # from the epoch, which is base 0 and granularity 60.
            granularity = RasDss._tsc_granularity_seconds(tsc)
            base_days = int(getattr(tsc, 'julianBaseDate', 0) or 0)
            HEC_EPOCH = np.datetime64('1899-12-31T00:00:00', 's')
            datetimes = (
                HEC_EPOCH
                + np.timedelta64(base_days, 'D')
                + (times * granularity).astype('timedelta64[s]')
            )

            # Create DataFrame
            df = pd.DataFrame({
                'value': values
            }, index=pd.DatetimeIndex(datetimes, name='datetime'))

            # Add metadata as attributes
            df.attrs['pathname'] = pathname
            df.attrs['units'] = str(tsc.units) if tsc.units else ""
            df.attrs['type'] = str(tsc.type) if tsc.type else ""
            df.attrs['interval'] = RasDss._tsc_interval_minutes(tsc, granularity)
            df.attrs['dss_file'] = dss_file

            return df

        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    RasDss._release_dss_file(dss_file)

    @staticmethod
    def _release_dss_file(dss_file: str) -> List[str]:
        """Release the bridge's native handle on one DSS file.

        ``HecDss.done()`` and ``GriddedData.done()`` only drop the bridge's
        file-cache reference; the native file can stay open, and locked,
        until a deferred close runs. Pass the exact path string that was
        used to open the file. The handle is shared, so other open bridge
        objects on the same file reopen it on their next access. Failures
        are logged at DEBUG and never raised, so a primary error is not
        masked.

        Returns the failure lines the HEC-DSS library reported since the last
        drain, already logged; writers raise on them (see
        ``_raise_hec_write_failures``).
        """
        try:
            from jnius import autoclass

            HecDSSFileAccess = autoclass('hec.heclib.dss.HecDSSFileAccess')
            HecDSSFileAccess.close(dss_file, True)
        except Exception as exc:
            logger.debug("Could not release DSS file %s (%s)", dss_file, exc)
        return RasDss._drain_hec_messages()

    @staticmethod
    def _require_existing_dss_file(dss_file: Union[str, Path]) -> None:
        """Raise before HEC code can create a missing DSS file during a read."""
        path = Path(dss_file)
        if not path.exists():
            raise FileNotFoundError(f"DSS file not found: {dss_file}")
        if not path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_file}")

    @staticmethod
    def _tsc_granularity_seconds(tsc) -> int:
        """Seconds per unit of TimeSeriesContainer.times (60 when not reported)."""
        getter = getattr(tsc, 'getTimeGranularitySeconds', None)
        try:
            value = int(getter()) if getter is not None else 60
        except Exception:
            value = 60
        return value if value > 0 else 60

    @staticmethod
    def _tsc_interval_minutes(tsc, granularity: int) -> Optional[Union[int, float]]:
        """Regular interval in minutes; 0 for irregular data; float below one minute.

        TimeSeriesContainer.interval is counted in the container's time
        granularity, so a 15-second series reports 15 with granularity 1.
        """
        if not hasattr(tsc, 'interval'):
            return None
        raw = int(tsc.interval)
        seconds = raw * granularity
        if seconds % 60 == 0:
            return seconds // 60
        return seconds / 60

    # ------------------------------------------------------------------
    # Paired data
    # ------------------------------------------------------------------

    #: Paired-data record type codes: 200 (PD, float32) and 205 (PDD, float64).
    _PAIRED_DATA_RECORD_TYPES = (200, 205)
    _PAIRED_DATA_DTYPES = ("stored", "float64")

    @staticmethod
    @log_call
    def read_paired_data(
        dss_file: Union[str, Path],
        pathname: str,
        *,
        ignore_d_part: bool = True,
        dtype: str = "stored",
    ) -> pd.DataFrame:
        """
        Read one paired-data record (rating curve, damage curve, temporal
        pattern, elevation-storage table, ...) with every curve.

        Args:
            dss_file: Path to an existing DSS file. The file is never created.
            pathname: DSS pathname, for example
                ``"/BASIN/LOC/STAGE-FLOW///RATING/"``.
            ignore_d_part: When the exact pathname has no record, use the first
                paired-data record in catalog order whose A, B, C, E and F parts
                match (case-insensitive), as ``HecDss.get(pathname, True)``
                does. Default ``True``.
            dtype: ``"stored"`` (default) keeps the stored precision:
                ``float32`` for PD records (type 200) and ``float64`` for PDD
                records (type 205). ``"float64"`` widens both (exact).

        Returns:
            DataFrame with one row per ordinate and one column per curve:

            - Index: the independent-variable ordinates, named ``"ordinate"``,
              in stored order (not sorted).
            - Columns: one per curve, in stored order. Named after the curve
              labels when every curve has a distinct, non-blank label,
              otherwise ``"curve_1"`` .. ``"curve_n"``.
            - Values: stored bits (``dtype="stored"``). HEC missing markers
              (-901, -902, -3.4028235e38) are returned as stored, not NaN.
            - ``attrs`` (always these keys, in this order): ``pathname``
              (as requested), ``record_pathname`` (the record read; differs
              when the D part was ignored), ``dss_file``, ``record_type``
              (200 or 205), ``dss_version`` (6 or 7), ``stored_dtype``
              (``"float32"`` or ``"float64"``), ``n_ordinates``,
              ``n_curves``, ``x_parameter``, ``y_parameter`` (from the C
              part, for example ``"STAGE"``/``"FLOW"``), ``x_units``,
              ``x_type``, ``y_units``, ``y_type`` (for example ``"LINEAR"``,
              ``"LOG"``, ``"PROB"``), ``labels`` (one string per curve, ``""``
              when absent; trailing blanks removed, leading blanks kept),
              ``x_precision``, ``y_precision`` (``-1`` when not set),
              ``time_zone`` (DSS7 only, else ``None``; never applied).

        Backends:
            ``"java"`` reads ``hec.io.PairedDataContainer`` through HEC
            Monolith; ``"native"`` reads through ras-commander-fast-dss without a JVM;
            ``"shadow"`` returns the native frame, also reads through Java,
            and logs differences (see ``docs/user-guide/dss-native-backend.md``).
            Both backends return the same schema and raise the same classes.

        Raises:
            FileNotFoundError: If ``dss_file`` does not exist.
            IsADirectoryError: If ``dss_file`` is not a file.
            ValueError: If ``pathname`` is not a string or ``dtype`` is invalid.
            DssPathnameNotFoundError: No paired-data record matches (a
                ``ValueError``).
            DssRecordTypeError: The matching record is not paired data (a
                ``TypeError`` and ``DssUnsupportedRecordError``).
            DssReadError: The record exists but the backend failed to read it
                (a ``DssFormatError``; the cause is chained).
            ImportError: The selected backend's optional dependency (pyjnius or
                ras-commander-fast-dss) is not installed.

        Example:
            rating = RasDss.read_paired_data("model.dss", "/BASIN/LOC/STAGE-FLOW///RATING/")
            stage = rating.index.to_numpy()
            flow = rating.iloc[:, 0].to_numpy()
            print(rating.attrs["x_units"], rating.attrs["y_units"])
        """
        RasDss._check_paired_data_request(dss_file, pathname, dtype)
        backend = RasDss.get_backend()
        if backend == "native":
            return RasDss._read_paired_data_native(dss_file, pathname, ignore_d_part, dtype)
        if backend == "shadow":
            return RasDss._read_paired_data_shadow(dss_file, pathname, ignore_d_part, dtype)
        return RasDss._read_paired_data_java(dss_file, pathname, ignore_d_part, dtype)

    @staticmethod
    def _check_paired_data_request(dss_file: Union[str, Path], pathname: str, dtype: str) -> None:
        if not isinstance(pathname, str):
            raise ValueError(f"DSS pathname must be a string, got {type(pathname).__name__}")
        if dtype not in RasDss._PAIRED_DATA_DTYPES:
            raise ValueError(f"dtype must be one of {RasDss._PAIRED_DATA_DTYPES}, not {dtype!r}")
        RasDss._check_existing_file(dss_file)

    @staticmethod
    def _paired_data_column_names(labels: List[str], n_curves: int) -> List[str]:
        """Labels when every curve has a distinct non-blank label, else curve_1..n
        (the rule of ``ras_commander_fast_dss.PairedData.column_names``)."""
        if (len(labels) == n_curves and all(s.strip() for s in labels)
                and len(set(labels)) == n_curves):
            return list(labels)
        return [f"curve_{i + 1}" for i in range(n_curves)]

    @staticmethod
    def _paired_data_frame(
        *,
        pathname: str,
        record_pathname: str,
        dss_file: str,
        record_type: int,
        dss_version: int,
        ordinates: np.ndarray,
        values: np.ndarray,
        labels: List[str],
        x_parameter: str,
        y_parameter: str,
        x_units: str,
        x_type: str,
        y_units: str,
        y_type: str,
        x_precision: int,
        y_precision: int,
        time_zone: Optional[str],
        dtype: str,
    ) -> pd.DataFrame:
        """Assemble the canonical paired-data frame (shared by both backends)."""
        stored = np.dtype(np.float32 if int(record_type) == 200 else np.float64)
        target = stored if dtype == "stored" else np.dtype(np.float64)
        x = np.asarray(ordinates).astype(target, copy=True)
        n_ord = int(x.shape[0])
        v = np.asarray(values)
        n_curves = int(v.shape[0]) if v.ndim == 2 else (0 if v.size == 0 else 1)
        v = v.reshape(n_curves, n_ord).astype(target, copy=True)
        labels = [str(s).rstrip() for s in labels][:n_curves]
        labels += [""] * (n_curves - len(labels))
        names = RasDss._paired_data_column_names(labels, n_curves)
        index = pd.Index(x, name="ordinate", dtype=target)
        if n_curves:
            df = pd.DataFrame({name: v[i] for i, name in enumerate(names)}, index=index)
        else:
            df = pd.DataFrame(index=index)
        df.attrs = {
            "pathname": pathname,
            "record_pathname": record_pathname,
            "dss_file": dss_file,
            "record_type": int(record_type),
            "dss_version": int(dss_version),
            "stored_dtype": stored.name,
            "n_ordinates": n_ord,
            "n_curves": n_curves,
            "x_parameter": x_parameter or "",
            "y_parameter": y_parameter or "",
            "x_units": x_units or "",
            "x_type": x_type or "",
            "y_units": y_units or "",
            "y_type": y_type or "",
            "labels": labels,
            "x_precision": int(x_precision),
            "y_precision": int(y_precision),
            "time_zone": time_zone or None,
        }
        return df

    @staticmethod
    def _native_record_type(handle: Any, pathname: str) -> Optional[int]:
        """Record type of a catalog entry (exact, case-insensitive), or None."""
        try:
            cat = handle.catalog()
        except Exception:
            return None
        wanted = pathname.upper()
        for p, t in zip(cat["pathname"], cat["record_type"]):
            if str(p).upper() == wanted:
                return int(t)
        return None

    @staticmethod
    def _read_paired_data_native(
        dss_file: Union[str, Path],
        pathname: str,
        ignore_d_part: bool = True,
        dtype: str = "stored",
    ) -> pd.DataFrame:
        """Paired data through ras-commander-fast-dss (no JVM)."""
        from ras_commander.RasUtils import RasUtils

        dc = _backend.import_native()
        resolved = RasUtils.safe_resolve(Path(dss_file))
        with dc.open(resolved) as handle:
            try:
                pdata = handle.read_paired_data(
                    pathname, ignore_d_part=ignore_d_part, dtype="stored"
                )
            except dc.DssUnsupportedRecordError as exc:
                # A matching record of another kind (time series, grid, text):
                # same class as the Java path. An unsupported PD encoding stays
                # the plain native error.
                rtype = RasDss._native_record_type(handle, pathname)
                if rtype not in RasDss._PAIRED_DATA_RECORD_TYPES:
                    raise _errors.get("DssRecordTypeError")(
                        f"DSS pathname is not a paired-data record: {pathname}"
                        + (f" (record type {rtype})" if rtype is not None else "")
                    ) from exc
                raise
        return RasDss._paired_data_frame(
            pathname=pathname,
            record_pathname=pdata.pathname,
            dss_file=str(resolved),
            record_type=pdata.record_type,
            dss_version=pdata.dss_version,
            ordinates=pdata.ordinates,
            values=pdata.values,
            labels=list(pdata.labels),
            x_parameter=pdata.parameters[0],
            y_parameter=pdata.parameters[1],
            x_units=pdata.units_independent,
            x_type=pdata.type_independent,
            y_units=pdata.units_dependent,
            y_type=pdata.type_dependent,
            x_precision=pdata.x_precision,
            y_precision=pdata.y_precision,
            time_zone=pdata.time_zone,
            dtype=dtype,
        )

    @staticmethod
    def _read_paired_data_java(
        dss_file: Union[str, Path],
        pathname: str,
        ignore_d_part: bool = True,
        dtype: str = "stored",
    ) -> pd.DataFrame:
        """Paired data through HEC Monolith (``hec.io.PairedDataContainer``)."""
        RasDss._configure_jvm()

        from jnius import autoclass, cast
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')
        HecDataManager = autoclass('hec.heclib.dss.HecDataManager')
        dss_path = RasDss._check_existing_file(dss_file)
        dss_file_str = str(RasUtils.safe_resolve(dss_path))
        not_found = _errors.get("DssPathnameNotFoundError")

        dss = None
        try:
            dss = HecDss.open(dss_file_str)
            record = RasDss._java_matching_record(dss, pathname, ignore_d_part)
            if record is None:
                raise not_found(f"No data found for pathname: {pathname}")
            try:
                container = dss.get(pathname, bool(ignore_d_part))
            except Exception as exc:
                # The record exists, so this is a read failure, not "not found".
                raise _errors.get("DssReadError")(
                    f"HEC Monolith failed to read existing record {record}: {exc}"
                ) from exc
            if container is None:
                raise _errors.get("DssReadError")(
                    f"HEC Monolith returned no container for existing record {record}"
                )
            container_class = str(container.getClass().getName())
            if container_class != 'hec.io.PairedDataContainer':
                raise _errors.get("DssRecordTypeError")(
                    f"DSS pathname is not a paired-data record: {pathname} "
                    f"(container type: {container_class})"
                )
            pdc = cast('hec.io.PairedDataContainer', container)
            n_ord = int(pdc.numberOrdinates)
            n_curves = int(pdc.numberCurves)
            raw_x = pdc.xOrdinates
            x = np.asarray(raw_x if raw_x is not None else [], dtype=np.float64)[:n_ord]
            rows = pdc.yOrdinates
            if rows is not None and n_curves:
                y = np.stack([np.asarray(rows[i], dtype=np.float64)[:n_ord]
                              for i in range(n_curves)])
            else:
                y = np.empty((0, n_ord), dtype=np.float64)
            labels: List[str] = []
            if bool(pdc.labelsUsed) and pdc.labels is not None:
                labels = [str(s) if s is not None else "" for s in pdc.labels]
            # DataContainer.dataType is the record type (200 PD, 205 PDD).
            record_type = int(getattr(pdc, 'dataType', 0) or 0)
            if record_type not in RasDss._PAIRED_DATA_RECORD_TYPES:
                record_type = 205 if bool(getattr(pdc, 'storedAsdoubles', False)) else 200
            version = int(HecDataManager.getDssFileVersion(dss_file_str))

            def text(value: Any) -> str:
                return str(value) if value is not None else ""

            return RasDss._paired_data_frame(
                pathname=pathname,
                record_pathname=text(pdc.fullName) or pathname,
                dss_file=dss_file_str,
                record_type=record_type,
                dss_version=version,
                ordinates=x,
                values=y,
                labels=labels,
                x_parameter=text(pdc.xparameter),
                y_parameter=text(pdc.yparameter),
                x_units=text(pdc.xunits),
                x_type=text(pdc.xtype),
                y_units=text(pdc.yunits),
                y_type=text(pdc.ytype),
                x_precision=int(pdc.xprecision),
                y_precision=int(pdc.yprecision),
                time_zone=None,
                dtype=dtype,
            )
        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    RasDss._release_dss_file(dss_file_str)

    @staticmethod
    def _java_matching_record(dss: Any, pathname: str, ignore_d_part: bool) -> Optional[str]:
        """The record ``HecDss.get(pathname, ignore_d_part)`` would read, or None.

        Exact pathname first (``recordExists``); with ``ignore_d_part``, the first
        cataloged pathname whose A, B, C, E and F parts match case-insensitively.
        """
        if dss.recordExists(pathname):
            return pathname
        if not ignore_d_part:
            return None
        parts = pathname.split("/")
        if len(parts) != 8:
            return None
        key = tuple(parts[i].upper() for i in (1, 2, 3, 5, 6))
        catalog = dss.getCatalogedPathnames()
        for i in range(catalog.size()):
            candidate = str(catalog.get(i))
            cparts = candidate.split("/")
            if len(cparts) == 8 and tuple(cparts[i].upper() for i in (1, 2, 3, 5, 6)) == key:
                return candidate
        return None

    @staticmethod
    def _read_paired_data_shadow(
        dss_file: Union[str, Path],
        pathname: str,
        ignore_d_part: bool = True,
        dtype: str = "stored",
    ) -> pd.DataFrame:
        """Native paired data, cross-checked against Java. Comparison never raises."""
        import time

        not_found = _errors.get("DssPathnameNotFoundError")
        native_df, native_exc = None, None
        t0 = time.perf_counter()
        try:
            native_df = RasDss._read_paired_data_native(dss_file, pathname, ignore_d_part, dtype)
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t0
        # Java runs only where the result is comparable: data or not-found.
        if native_exc is not None and not isinstance(native_exc, not_found):
            _backend.record(
                "read_paired_data", "skipped",
                f"java skipped: native {type(native_exc).__name__}",
                dss_file=dss_file, pathname=pathname, native_error=native_exc,
                native_seconds=native_s,
            )
            raise native_exc
        try:
            java_df, java_exc = None, None
            t1 = time.perf_counter()
            try:
                java_df = RasDss._read_paired_data_java(dss_file, pathname, ignore_d_part, dtype)
            except Exception as exc:
                java_exc = exc
            java_s = time.perf_counter() - t1
            outcome, label, diffs = _backend.classify_paired_data(
                java_df, java_exc, native_df, native_exc
            )
            detail = {}
            if native_df is not None:
                detail = {"n_curves": native_df.attrs.get("n_curves"),
                          "n_ordinates": native_df.attrs.get("n_ordinates"),
                          "record_type": native_df.attrs.get("record_type")}
            _backend.record(
                "read_paired_data", outcome, label, dss_file=dss_file,
                pathname=pathname, diffs=diffs, java_seconds=java_s,
                native_seconds=native_s, java_error=java_exc,
                native_error=native_exc, detail=detail,
            )
        except Exception as exc:  # the comparison must never break the read
            logger.warning(
                "DSS shadow read_paired_data comparison failed for %s %s: %s",
                dss_file, pathname, exc,
            )
        if native_exc is not None:
            raise native_exc
        return native_df

    # ------------------------------------------------------------------
    # Grids: native and shadow routes (the Java route is _read_grid_java)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_hec_time_text(
        value: Optional[pd.Timestamp], end_of_period: bool = False
    ) -> Optional[str]:
        """``HecTime``-style text used in Java grid metadata (``1 January 2020, 01:00``).

        Monolith prints a midnight end time as ``24:00`` of the previous day.
        """
        if value is None or pd.isna(value):
            return None
        stamp = pd.Timestamp(value)
        if end_of_period and stamp == stamp.normalize():
            prev = stamp - pd.Timedelta(days=1)
            return f"{prev.day} {prev.strftime('%B %Y')}, 24:00"
        return f"{stamp.day} {stamp.strftime('%B %Y, %H:%M')}"

    @staticmethod
    def _read_grid_native(dss_file: Union[str, Path], pathname: str) -> Dict[str, Any]:
        """One grid record through ras-commander-fast-dss, in the ``read_grid`` schema.

        Cells, geometry, units and times are native. ``metadata["crs_qualified"]``
        reports whether the installed wheel advertises qualified grid CRS strings.
        """
        from ras_commander.RasUtils import RasUtils

        path_parts = RasDss._check_grid_request(dss_file, pathname)
        dc = _backend.import_native()
        dss_file_str = str(RasUtils.safe_resolve(Path(dss_file)))
        with dc.open(dss_file_str) as handle:
            try:
                grid = handle.read_grid(pathname, missing="nan", order="native")
            except dc.DssPathnameNotFoundError as exc:
                raise dc.DssPathnameNotFoundError(
                    f"No DSS record found for exact pathname {pathname} in {dss_file_str}"
                ) from exc
            except dc.DssUnsupportedRecordError as exc:
                rtype = RasDss._native_record_type(handle, pathname)
                if rtype is not None and not 400 <= rtype < 450:
                    raise _errors.get("DssRecordTypeError")(
                        f"DSS pathname is not a spatial grid record: {pathname} "
                        f"(record type {rtype})"
                    ) from exc
                raise
        return RasDss._grid_dict_from_native(grid, pathname, dss_file_str, path_parts)

    @staticmethod
    def _grid_dict_from_native(
        grid: Any, pathname: str, dss_file_str: str, path_parts: List[str]
    ) -> Dict[str, Any]:
        """Map a ``ras_commander_fast_dss.Grid`` onto the ``read_grid`` dictionary."""
        n_rows, n_cols = int(grid.ny), int(grid.nx)
        values = np.ascontiguousarray(grid.data, dtype=np.float32)
        grid_type = grid.grid_type if grid.grid_type != "undefined" else "GridInfo"
        class_names = {"albers": "AlbersInfo", "specified": "SpecifiedGridInfo",
                       "hrap": "HrapInfo", "GridInfo": "GridInfo"}
        cell_size = float(grid.cell_size)
        lower_left_cell = (int(grid.lower_left_cell_x), int(grid.lower_left_cell_y))
        md = dict(grid.metadata)
        projection: Dict[str, Any] = {}
        origin = None
        if grid.grid_type in ("albers", "specified"):
            x0 = float(grid.x_coord_of_grid_cell_zero)
            y0 = float(grid.y_coord_of_grid_cell_zero)
            projection.update({"x_coord_cell_zero": x0, "y_coord_cell_zero": y0})
            origin = (x0 + lower_left_cell[0] * cell_size, y0 + lower_left_cell[1] * cell_size)
        albers = md.get("albers")
        if grid.grid_type == "albers" and albers:
            projection.update({
                "datum_code": int(albers["datum"]),
                "units": str(albers["units"]),
                "standard_parallel_1": float(albers["first_standard_parallel"]),
                "standard_parallel_2": float(albers["second_standard_parallel"]),
                "central_meridian": float(albers["central_meridian"]),
                "latitude_of_origin": float(albers["latitude_of_projection_origin"]),
                "false_easting": float(albers["false_easting"]),
                "false_northing": float(albers["false_northing"]),
            })

        def native_time(value: Any) -> Optional[pd.Timestamp]:
            return None if value is None else pd.Timestamp(value)

        native_start, native_end = native_time(grid.start_time), native_time(grid.end_time)
        start_time = RasDss._parse_grid_dss_datetime(path_parts[3]) or native_start
        end_time = RasDss._parse_grid_dss_datetime(path_parts[4]) or native_end
        start_text = RasDss._format_hec_time_text(native_start)
        end_text = RasDss._format_hec_time_text(native_end, end_of_period=True)
        record_type = int(grid.record_type)
        metadata = {
            "pathname_parts": dict(zip("ABCDEF", path_parts)),
            "grid_class": f"hec.heclib.grid.{class_names.get(grid_type, grid_type)}",
            "grid_type_code": record_type - record_type % 10,
            "data_type_code": int(grid.data_type),
            "shape": (n_rows, n_cols),
            "number_of_cells_x": n_cols,
            "number_of_cells_y": n_rows,
            "lower_left_cell": lower_left_cell,
            "origin": origin,
            "projection": projection,
            "number_missing": int(np.isnan(values).sum()),
            "nodata_value": float(np.float32(-np.finfo(np.float32).max)),
            "compression": {
                "method": md.get("compression_method"),
                "base": md.get("compression_base"),
                "scale_factor": md.get("compression_scale_factor"),
                "element_size": md.get("sizeof_compressed_elements"),
            },
            "timing": {
                "start": start_text,
                "end": end_text,
                "period": f"{start_text} to {end_text}" if start_text and end_text else None,
            },
            "crs_qualified": _backend.native_grid_qualified(),
            "native": {
                "record_type": record_type,
                "dss_version": int(grid.dss_version),
                "null_value": float(grid.null_value),
                "srs_name": grid.srs_name,
                "srs_definition_type": int(grid.srs_definition_type),
                "extent": tuple(grid.extent),
                "min_value": grid.min_value,
                "max_value": grid.max_value,
                "mean_value": grid.mean_value,
                **md,
            },
        }
        return {
            "dss_file": dss_file_str,
            "pathname": pathname,
            "data": values,
            "shape": (n_rows, n_cols),
            "units": str(grid.data_units),
            "data_type": grid.data_type_name or "",
            "grid_type": grid_type,
            "crs": str(grid.srs_definition or ""),
            "cell_size": cell_size,
            "start_time": start_time,
            "end_time": end_time,
            "metadata": metadata,
            "row_order": "south_up",
        }

    @staticmethod
    def _read_grid_shadow(dss_file: Union[str, Path], pathname: str) -> Dict[str, Any]:
        """Grid read on both backends. Always returns Java's grid (or raises Java's
        error); the native grid is only compared. Cell and metadata differences are
        logged separately. The comparison never raises."""
        import time

        java_grid, java_exc, native_grid, native_exc = None, None, None, None
        t0 = time.perf_counter()
        try:
            native_grid = RasDss._read_grid_native(dss_file, pathname)
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t0
        t1 = time.perf_counter()
        try:
            java_grid = RasDss._read_grid_java(dss_file, pathname)
        except Exception as exc:
            java_exc = exc
        java_s = time.perf_counter() - t1
        try:
            outcome, label, diffs = _backend.classify_grid(
                java_grid, java_exc, native_grid, native_exc
            )
            _backend.record(
                "read_grid", outcome, label, dss_file=dss_file, pathname=pathname,
                diffs=diffs, java_seconds=java_s, native_seconds=native_s,
                java_error=java_exc, native_error=native_exc,
                detail={"returned": "java"},
            )
        except Exception as exc:  # the comparison must never break the read
            logger.warning("DSS shadow read_grid comparison failed for %s %s: %s",
                           dss_file, pathname, exc)
        if java_exc is not None:
            raise java_exc
        return java_grid

    @staticmethod
    @log_call
    def read_grid(
        dss_file: Union[str, Path],
        pathname: str,
        *,
        allow_unqualified_native: bool = False,
    ) -> Dict[str, Any]:
        """
        Read one spatial grid record from an exact DSS pathname.

        Args:
            dss_file: Path to an existing DSS file.
            pathname: Exact six-part DSS grid pathname. Wildcards are not
                accepted; D and E parts identify the record's time window.

        Returns:
            Dictionary containing:

            - ``dss_file``: Absolute DSS file path.
            - ``pathname``: Exact pathname requested.
            - ``data``: Two-dimensional ``float32`` array in HEC row-major order.
                Row zero is south, columns run west to east. Flip rows before
                using a north-up raster transform or the native precipitation writer.
                The HEC grid no-data sentinel is represented as ``numpy.nan``.
            - ``shape``: ``(rows, columns)``.
            - ``units`` and ``data_type``: DSS parameter metadata.
            - ``grid_type``: ``"albers"``, ``"specified"``, ``"hrap"``, or
                the runtime grid-info class name for another grid type.
            - ``crs`` and ``cell_size``: Spatial reference and resolution.
            - ``start_time`` and ``end_time``: Naive ``pandas.Timestamp``
                values parsed from pathname parts D and E when present.
            - ``metadata``: Grid dimensions, cell indexes, origin/projection,
                compression, type codes, missing-value count, and raw timing.

            - ``row_order``: Always ``"south_up"`` (row zero is the southern
                row), on every backend.

        Args (keyword-only):
            allow_unqualified_native: Opt in to the native grid reader under
                ``backend="native"`` when the installed ras-commander-fast-dss does not
                advertise qualified grid CRS strings (feature
                ``"grid_srs_monolith_parity"`` in ``ras_commander_fast_dss.FEATURES``).
                Cells, geometry, units and times are native; ``crs`` may be
                wrong or empty for legacy Albers grids, and
                ``metadata["crs_qualified"]`` is ``False``. Ignored, with a
                warning, under ``"java"`` and ``"shadow"``. Default ``False``.

        Backends:
            ``"java"`` (default) reads through HEC Monolith. ``"native"``
            raises ``DssCapabilityError`` unless the wheel advertises
            qualified grid CRS or ``allow_unqualified_native`` is ``True``; it
            never falls back to Java. ``"shadow"`` always returns Java's grid
            (and raises Java's error, even when the native read succeeded);
            the native grid is only compared. It reads natively,
            and logs cell and metadata differences separately; a CRS
            disagreement is logged as the known difference ``G-CRS``.

        Raises:
            FileNotFoundError: If ``dss_file`` does not exist.
            IsADirectoryError: If ``dss_file`` is not a file.
            ValueError: If the pathname is malformed or uses wildcards.
            DssPathnameNotFoundError: If no record has the exact pathname
                (a ``ValueError``).
            DssRecordTypeError: If the exact pathname identifies a non-grid
                record (a ``TypeError`` and ``DssUnsupportedRecordError``).
            DssCapabilityError: Native backend, unqualified wheel and no
                ``allow_unqualified_native`` (a ``NotImplementedError``).
            ImportError: If pyjnius (Java) or ras-commander-fast-dss (native) is not
                installed.
            RuntimeError: If the grid read fails or returns invalid data.
        """
        RasDss._check_grid_request(dss_file, pathname)
        backend = RasDss.get_backend()
        if backend == "native":
            if not (allow_unqualified_native or _backend.native_grid_qualified()):
                raise _errors.get("DssCapabilityError")(_backend.NATIVE_GRID_GATE_MESSAGE)
            return RasDss._read_grid_native(dss_file, pathname)
        if allow_unqualified_native:
            logger.warning(
                "read_grid: allow_unqualified_native=True is ignored under the %r "
                "backend; the Java grid is returned%s.", backend,
                " and the native grid is only compared" if backend == "shadow" else "",
            )
        if backend == "shadow":
            return RasDss._read_grid_shadow(dss_file, pathname)
        return RasDss._read_grid_java(dss_file, pathname)

    @staticmethod
    def _check_grid_request(dss_file: Union[str, Path], pathname: str) -> List[str]:
        """Backend-independent argument checks; returns the six pathname parts."""
        if not isinstance(pathname, str):
            raise ValueError(f"DSS pathname must be a string, got {type(pathname).__name__}")
        if "*" in pathname or "?" in pathname:
            raise ValueError(
                "read_grid requires an exact DSS pathname without wildcard "
                f"characters: {pathname}"
            )
        _, path_parts = RasDss._split_dss_pathname(pathname)
        dss_path = Path(dss_file)
        if not dss_path.exists():
            raise FileNotFoundError(f"DSS file not found: {dss_path}")
        if not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        return path_parts

    @staticmethod
    def _read_grid_java(dss_file: Union[str, Path], pathname: str) -> Dict[str, Any]:
        """One grid record through HEC Monolith (pyjnius). Internal Java-only
        callers (grid writers) use this directly."""
        path_parts = RasDss._check_grid_request(dss_file, pathname)
        dss_path = Path(dss_file)

        RasDss._configure_jvm()

        from jnius import autoclass, cast
        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass('hec.heclib.dss.HecDss')
        GridInfo = autoclass('hec.heclib.grid.GridInfo')
        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        dss = None
        try:
            dss = HecDss.open(dss_file_str)
            if not dss.recordExists(pathname):
                raise _errors.get("DssPathnameNotFoundError")(
                    f"No DSS record found for exact pathname {pathname} "
                    f"in {dss_file_str}"
                )

            container = dss.get(pathname)
            if container is None:
                raise RuntimeError(
                    f"HEC-DSS returned no container for existing pathname: {pathname}"
                )

            container_class = str(container.getClass().getName())
            if container_class != "hec.io.GridContainer":
                raise _errors.get("DssRecordTypeError")(
                    f"DSS pathname is not a spatial grid record: {pathname} "
                    f"(container type: {container_class})"
                )

            grid_container = cast('hec.io.GridContainer', container)
            grid_data = grid_container.getGridData()
            if grid_data is None:
                raise RuntimeError(f"Grid record contains no grid data: {pathname}")

            grid_info_base = grid_data.getGridInfo()
            if grid_info_base is None:
                raise RuntimeError(f"Grid record contains no grid metadata: {pathname}")

            grid_class = str(grid_info_base.getClass().getName())
            grid_info = cast(grid_class, grid_info_base)
            n_cols = int(grid_info.getNumberOfCellsX())
            n_rows = int(grid_info.getNumberOfCellsY())
            if n_rows <= 0 or n_cols <= 0:
                raise RuntimeError(
                    f"Grid record has invalid dimensions {n_rows}x{n_cols}: {pathname}"
                )

            values = np.asarray(grid_data.getData(), dtype=np.float32)
            expected_size = n_rows * n_cols
            if values.size != expected_size:
                raise RuntimeError(
                    f"Grid record returned {values.size} values for dimensions "
                    f"{n_rows}x{n_cols} ({expected_size} expected): {pathname}"
                )

            nodata_value = np.float32(GridInfo.getGridNodataValue())
            values = values.reshape((n_rows, n_cols), order="C").copy()
            values[values == nodata_value] = np.nan

            grid_class_name = grid_class.rsplit('.', 1)[-1]
            grid_type_names = {
                "AlbersInfo": "albers",
                "SpecifiedGridInfo": "specified",
                "HrapInfo": "hrap",
            }
            grid_type = grid_type_names.get(grid_class_name, grid_class_name)

            cell_size = float(grid_info.getCellSize())
            lower_left_cell = (
                int(grid_info.getLowerLeftCellX()),
                int(grid_info.getLowerLeftCellY()),
            )
            projection: Dict[str, Any] = {}
            origin = None

            if grid_class_name in {"AlbersInfo", "SpecifiedGridInfo"}:
                x_cell_zero = float(grid_info.getXCoordOfGridCellZero())
                y_cell_zero = float(grid_info.getYCoordOfGridCellZero())
                projection.update({
                    "x_coord_cell_zero": x_cell_zero,
                    "y_coord_cell_zero": y_cell_zero,
                })
                origin = (
                    x_cell_zero + lower_left_cell[0] * cell_size,
                    y_cell_zero + lower_left_cell[1] * cell_size,
                )

            if grid_class_name == "AlbersInfo":
                projection.update({
                    "datum_code": int(grid_info.getProjectionDatum()),
                    "units": str(grid_info.getProjectionUnits()),
                    "standard_parallel_1": float(grid_info.getFirstStandardParallel()),
                    "standard_parallel_2": float(grid_info.getSecondStandardParallel()),
                    "central_meridian": float(grid_info.getCentralMeridian()),
                    "latitude_of_origin": float(
                        grid_info.getLatitudeOfProjectionOrigin()
                    ),
                    "false_easting": float(grid_info.getFalseEasting()),
                    "false_northing": float(grid_info.getFalseNorthing()),
                })

            raw_start_time = str(grid_info.getStartTime())
            raw_end_time = str(grid_info.getEndTime())
            start_time = RasDss._parse_grid_dss_datetime(path_parts[3])
            end_time = RasDss._parse_grid_dss_datetime(path_parts[4])
            if start_time is None:
                try:
                    start_time = pd.Timestamp(pd.to_datetime(raw_start_time))
                except (TypeError, ValueError):
                    pass
            if end_time is None:
                try:
                    end_time = pd.Timestamp(pd.to_datetime(raw_end_time))
                except (TypeError, ValueError):
                    pass

            metadata = {
                "pathname_parts": dict(zip("ABCDEF", path_parts)),
                "grid_class": grid_class,
                "grid_type_code": int(grid_info.getGridType()),
                "data_type_code": int(grid_info.getDataType()),
                "shape": (n_rows, n_cols),
                "number_of_cells_x": n_cols,
                "number_of_cells_y": n_rows,
                "lower_left_cell": lower_left_cell,
                "origin": origin,
                "projection": projection,
                "number_missing": int(grid_data.getNumberMissing()),
                "nodata_value": float(nodata_value),
                "compression": {
                    "method": int(grid_info.getCompressionMethod()),
                    "base": float(grid_info.getCompressionBase()),
                    "scale_factor": float(grid_info.getCompressionScaleFactor()),
                    "element_size": int(grid_info.getSizeOfCompressedElements()),
                },
                "timing": {
                    "start": raw_start_time,
                    "end": raw_end_time,
                    "period": str(grid_info.getTimePeriod()),
                },
            }

            return {
                "dss_file": dss_file_str,
                "pathname": pathname,
                "data": values,
                "shape": (n_rows, n_cols),
                "units": str(grid_info.getDataUnits()),
                "data_type": str(grid_info.getDataTypeName()),
                "grid_type": grid_type,
                "crs": str(grid_info.getSpatialReferenceSystem()),
                "cell_size": cell_size,
                "start_time": start_time,
                "end_time": end_time,
                "metadata": metadata,
                "row_order": "south_up",
            }
        except (ValueError, TypeError):
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read DSS grid record: {exc}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname: {pathname}"
            ) from exc
        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    RasDss._release_dss_file(dss_file_str)

    @staticmethod
    @log_call
    def read_multiple_timeseries(
        dss_file: Union[str, Path],
        pathnames: List[str]
    ) -> Dict[str, pd.DataFrame]:
        """
        Read multiple time series from DSS file.

        Args:
            dss_file: Path to DSS file
            pathnames: List of DSS pathnames

        Returns:
            Dictionary mapping pathnames to DataFrames

        Example:
            paths = ["/BASIN/LOC1/FLOW//1HOUR/OBS/", "/BASIN/LOC2/FLOW//1HOUR/OBS/"]
            data = RasDss.read_multiple_timeseries("file.dss", paths)
            for path, df in data.items():
                print(f"{path}: {len(df)} points")
        """
        backend = RasDss.get_backend()
        if backend in ("native", "shadow"):
            return RasDss._read_multiple_timeseries_native(
                dss_file, pathnames, shadow=(backend == "shadow")
            )

        results = {}
        for pathname in pathnames:
            try:
                results[pathname] = RasDss.read_timeseries(dss_file, pathname)
            except Exception as e:
                logger.warning("Could not read DSS pathname: %s", pathname)
                logger.debug("DSS read failure for %s: %s", pathname, e)
                results[pathname] = None

        return results

    @staticmethod
    def _read_multiple_timeseries_native(
        dss_file: Union[str, Path],
        pathnames: List[str],
        shadow: bool = False,
    ) -> Dict[str, pd.DataFrame]:
        """Read several pathnames with one open ras-commander-fast-dss file.

        Keeps the Java contract: a pathname that fails maps to None and logs a
        warning.
        """
        from ras_commander.RasUtils import RasUtils

        dc = _backend.import_native()
        resolved = RasUtils.safe_resolve(Path(dss_file))
        reader = (
            RasDss._read_timeseries_shadow if shadow else RasDss._read_timeseries_native
        )
        results = {}
        try:
            handle = dc.open(resolved)
        except Exception as e:
            for pathname in pathnames:
                logger.warning("Could not read DSS pathname: %s", pathname)
                logger.debug("DSS read failure for %s: %s", pathname, e)
                results[pathname] = None
            return results
        with handle:
            for pathname in pathnames:
                try:
                    results[pathname] = reader(dss_file, pathname, dss_handle=handle)
                except Exception as e:
                    logger.warning("Could not read DSS pathname: %s", pathname)
                    logger.debug("DSS read failure for %s: %s", pathname, e)
                    results[pathname] = None
        return results

    @staticmethod
    @log_call
    def get_info(dss_file: Union[str, Path]) -> Dict:
        """
        Get summary information about DSS file.

        Args:
            dss_file: Path to DSS file

        Returns:
            Dictionary with file information

        Example:
            info = RasDss.get_info("sample.dss")
            print(f"Total paths: {info['total_paths']}")
            print(f"File size: {info['file_size_mb']:.2f} MB")
        """
        from ras_commander.RasUtils import RasUtils
        dss_path = Path(dss_file)

        catalog = RasDss.get_catalog(dss_file)

        return {
            'filepath': str(RasUtils.safe_resolve(dss_path)),
            'filename': dss_path.name,
            'file_size_mb': dss_path.stat().st_size / (1024 * 1024),
            'total_paths': len(catalog),
            'first_5_paths': catalog[:5] if len(catalog) > 5 else catalog,
        }

    @staticmethod
    @log_call
    def extract_boundary_timeseries(
        boundaries_df: pd.DataFrame,
        project_dir: Optional[Union[str, Path]] = None,
        ras_object=None
    ) -> pd.DataFrame:
        """
        Extract DSS time series data for all DSS-defined boundaries.

        Reads boundaries_df and extracts time series for any boundary condition
        defined by a DSS file. Adds the extracted data to the dataframe.

        Args:
            boundaries_df: DataFrame from ras.boundaries_df
            project_dir: Project directory (for resolving relative DSS paths)
            ras_object (RasPrj, optional): RasPrj object (alternative to project_dir)

        Returns:
            Enhanced DataFrame with 'dss_timeseries' column containing extracted data

        Example:
            from ras_commander import init_ras_project, RasDss

            ras = init_ras_project("project_path", "7.0")

            # Extract all DSS boundary data
            enhanced_boundaries = RasDss.extract_boundary_timeseries(
                ras.boundaries_df, ras_object=ras
            )

            # Now enhanced_boundaries has a 'dss_timeseries' column with DataFrames
            for idx, row in enhanced_boundaries.iterrows():
                if row['Use DSS']:
                    print(f"{row['bc_type']}: {len(row['dss_timeseries'])} points")
        """
        # Get project directory
        if ras_object is not None:
            project_dir = ras_object.project_folder
        elif project_dir is None:
            raise ValueError("Must provide either project_dir or ras_object")

        project_dir = Path(project_dir)

        # Create a copy to avoid modifying original
        result_df = boundaries_df.copy()

        # Add column for time series data
        result_df['dss_timeseries'] = None

        # Find DSS-defined boundaries
        # Note: 'Use DSS' column may be string 'True'/'False' or boolean True/False
        dss_boundaries = result_df[
            (result_df['Use DSS'] == True) | (result_df['Use DSS'] == 'True')
        ]

        if len(dss_boundaries) == 0:
            logger.debug("No DSS-defined boundaries found")
            return result_df

        logger.debug(f"Found {len(dss_boundaries)} DSS-defined boundaries")

        # Extract time series for each DSS boundary
        success_count = 0
        fail_count = 0

        for idx, row in dss_boundaries.iterrows():
            dss_file = row['DSS File']
            dss_path = row['DSS Path']

            if pd.isna(dss_file) or pd.isna(dss_path):
                logger.warning(f"Row {idx}: Missing DSS File or DSS Path")
                continue

            # Resolve DSS file path (may be relative to project directory)
            dss_file_path = Path(dss_file)
            if not dss_file_path.is_absolute():
                dss_file_path = project_dir / dss_file

            if not dss_file_path.exists():
                logger.warning(f"Row {idx}: DSS file not found: {dss_file_path}")
                fail_count += 1
                continue

            try:
                # Read time series
                df_ts = RasDss.read_timeseries(dss_file_path, dss_path)

                # Store in result
                result_df.at[idx, 'dss_timeseries'] = df_ts

                success_count += 1
                logger.debug(
                    f"Row {idx}: Extracted {len(df_ts)} points from "
                    f"{dss_file_path.name}"
                )

            except Exception as e:
                logger.warning(f"Row {idx}: Failed to read DSS data: {e}")
                fail_count += 1

        logger.info(
            "DSS boundary extraction complete: "
            f"{len(dss_boundaries)} found, {success_count} read, {fail_count} failed"
        )

        return result_df

    @staticmethod
    def shutdown_jvm():
        """
        Shutdown Java Virtual Machine.

        Note: With pyjnius, JVM shutdown is typically not needed.
        This is a placeholder for API compatibility.

        Deprecated: under the native backend no JVM is started and this method
        is a no-op that emits ``DeprecationWarning``. It will be removed with the
        Java backend.
        """
        try:
            backend = _backend.requested_backend(RasDss.backend)
        except ValueError:
            backend = None
        if backend == "native":
            import warnings

            warnings.warn(
                "RasDss.shutdown_jvm() is a no-op under the native DSS backend "
                "and will be removed with the Java backend.",
                DeprecationWarning,
                stacklevel=2,
            )
            return
        logger.debug("pyjnius handles JVM lifecycle automatically")
        pass

    # =========================================================================
    # Validation Methods
    # =========================================================================

    @staticmethod
    @log_call
    def check_pathname_format(pathname: str):
        """
        Check DSS pathname format validity.

        Validates against DSS pathname specification:
        - Format: /A/B/C/D/E/F/
        - A blank A-part is represented as //B/C/D/E/F/
        - Parts: A (basin/project), B (location), C (parameter),
                 D (date), E (interval), F (scenario)

        Args:
            pathname: DSS pathname to validate

        Returns:
            ValidationResult: Result with detailed diagnostics

        Example:
            >>> from ras_commander.dss import RasDss
            >>> result = RasDss.check_pathname_format("/BASIN/LOC/FLOW/01JAN2020/1HOUR/OBS/")
            >>> print(result.passed)
            True
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Return basic dict if validation framework not available
            if (
                pathname.startswith('/')
                and pathname.endswith('/')
                and len(pathname[1:-1].split('/')) == 6
            ):
                return {'passed': True, 'message': 'Format appears valid (validation framework not available)'}
            else:
                return {'passed': False, 'message': 'Format appears invalid (validation framework not available)'}

        # Check prefix and trailing slash
        if not pathname.startswith('/'):
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must start with '/': {pathname}",
                details={"pathname": pathname}
            )

        if not pathname.endswith('/'):
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"DSS path must end with '/': {pathname}",
                details={"pathname": pathname}
            )

        # Preserve empty components while removing only the required outer
        # separators.  ``//B/C/D/E/F/`` is a normal six-part DSS pathname with
        # an empty A-part; stripping all slashes would incorrectly reduce it to
        # five parts.
        part_values = pathname[1:-1].split('/')

        if len(part_values) != 6:
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=(
                    "DSS path must have 6 parts "
                    "(/A/B/C/D/E/F/), got "
                    f"{len(part_values)}: {pathname}"
                ),
                details={
                    "pathname": pathname,
                    "expected_parts": 6,
                    "actual_parts": len(part_values)
                }
            )

        # Extract parts into named components
        part_names = [
            'basin',
            'location',
            'parameter',
            'date',
            'interval',
            'scenario'
        ]

        # Check for empty parts (warning, not error - some DSS paths have empty parts)
        empty_parts = []
        for i, (name, value) in enumerate(zip(part_names, part_values), start=1):
            if not value:
                empty_parts.append((i, name))

        if empty_parts:
            empty_names = ", ".join(f"{name} (part {i})" for i, name in empty_parts)
            return ValidationResult(
                check_name="path_format",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message=f"DSS path has empty parts: {empty_names}",
                details={
                    "pathname": pathname,
                    "empty_parts": empty_names,
                    "parts": dict(zip(part_names, part_values))
                }
            )

        # All checks passed
        return ValidationResult(
            check_name="path_format",
            severity=ValidationSeverity.INFO,
            passed=True,
            message="DSS path format is valid",
            details={"parts": dict(zip(part_names, part_values))}
        )

    @staticmethod
    @log_call
    def check_file_exists(dss_file: Union[str, Path]):
        """
        Check if DSS file exists and is accessible.

        Args:
            dss_file: Path to DSS file (str or Path)

        Returns:
            ValidationResult: Result with file existence check outcome

        Example:
            >>> from pathlib import Path
            >>> result = RasDss.check_file_exists(Path("data.dss"))
            >>> if result.passed:
            ...     print("File exists and is accessible")
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            dss_file = Path(dss_file)
            if dss_file.exists() and dss_file.is_file():
                return {'passed': True, 'message': 'File exists (validation framework not available)'}
            else:
                return {'passed': False, 'message': 'File not found (validation framework not available)'}

        dss_file = Path(dss_file)

        if not dss_file.exists():
            return ValidationResult(
                check_name="file_existence",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"DSS file not found: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        if not dss_file.is_file():
            return ValidationResult(
                check_name="file_type",
                severity=ValidationSeverity.CRITICAL,
                passed=False,
                message=f"Path is not a file: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        # Check read permissions
        try:
            with open(dss_file, 'rb'):
                pass
        except PermissionError:
            return ValidationResult(
                check_name="file_accessibility",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Permission denied reading: {dss_file}",
                details={"dss_file": str(dss_file)}
            )

        # File exists and is readable
        file_size_mb = dss_file.stat().st_size / (1024 * 1024)
        return ValidationResult(
            check_name="file_existence",
            severity=ValidationSeverity.INFO,
            passed=True,
            message="DSS file exists and is readable",
            details={
                "dss_file": str(dss_file),
                "file_size_mb": round(file_size_mb, 2)
            }
        )

    @staticmethod
    @log_call
    def check_pathname_exists(
        dss_file: Union[str, Path],
        pathname: str
    ):
        """
        Check if pathname exists in DSS file catalog.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to check

        Returns:
            ValidationResult: Result with existence check outcome

        Example:
            >>> result = RasDss.check_pathname_exists(
            ...     "data.dss",
            ...     "//BASIN/FLOW/01JAN2020/1HOUR/RUN1/"
            ... )
            >>> if result.passed:
            ...     print("Pathname found in catalog")
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Try basic check without validation framework
            try:
                catalog = RasDss.get_catalog(dss_file)
                if isinstance(catalog, pd.DataFrame) and 'pathname' in catalog.columns:
                    catalog_paths = catalog['pathname'].astype(str).tolist()
                else:
                    catalog_paths = [str(p) for p in catalog]

                if pathname in catalog_paths:
                    return {'passed': True, 'message': 'Pathname exists (validation framework not available)'}
                else:
                    return {'passed': False, 'message': 'Pathname not found (validation framework not available)'}
            except Exception as e:
                return {'passed': False, 'message': f'Error checking: {e}'}

        dss_file = Path(dss_file)

        # Get catalog
        try:
            catalog = RasDss.get_catalog(str(dss_file))
        except Exception as e:
            return ValidationResult(
                check_name="catalog_access",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Failed to read DSS catalog: {e}",
                details={"error": str(e), "dss_file": str(dss_file)}
            )

        # Normalize catalog to a list of path strings
        if isinstance(catalog, pd.DataFrame) and 'pathname' in catalog.columns:
            catalog_paths = catalog['pathname'].astype(str).tolist()
        elif hasattr(catalog, 'pathname'):
            # Defensive: if a custom object exposes a pathname attribute
            catalog_paths = list(getattr(catalog, 'pathname'))
        else:
            catalog_paths = [str(p) for p in catalog]

        # Check exact match
        if pathname in catalog_paths:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.INFO,
                passed=True,
                message="Pathname exists in DSS file",
                details={"total_paths": len(catalog_paths)}
            )

        # Try case-insensitive match (DSS is case-sensitive but provide hint)
        pathname_upper = pathname.upper()
        if pathname_upper in [p.upper() for p in catalog_paths]:
            return ValidationResult(
                check_name="pathname_existence",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="Pathname exists but case differs (DSS is case-sensitive)",
                details={"total_paths": len(catalog_paths)}
            )

        # Find similar paths (match on location part - index 2)
        segments = pathname.strip('/').split('/')
        location = segments[1] if len(segments) >= 2 else ""
        if location:
            similar = [p for p in catalog_paths if location in p]
        else:
            similar = []

        return ValidationResult(
            check_name="pathname_existence",
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="Pathname not found in DSS file",
            details={
                "pathname": pathname,
                "total_paths": len(catalog_paths),
                "similar_paths": similar[:5]  # First 5 similar paths
            }
        )

    @staticmethod
    @log_call
    def check_data_availability(
        dss_file: Union[str, Path],
        pathname: str,
        expected_start: Optional[str] = None,
        expected_end: Optional[str] = None
    ):
        """
        Check if time series data is available for the expected date range.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname
            expected_start: Expected start date (optional, datetime or string)
            expected_end: Expected end date (optional, datetime or string)

        Returns:
            ValidationResult: Result with data availability check outcome

        Example:
            >>> from datetime import datetime
            >>> result = RasDss.check_data_availability(
            ...     "data.dss",
            ...     "//BASIN/FLOW/01JAN2020/1HOUR/RUN1/",
            ...     expected_start=datetime(2020, 1, 1),
            ...     expected_end=datetime(2020, 12, 31)
            ... )
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationResult, ValidationSeverity
        except ImportError:
            # Try basic check without validation framework
            try:
                df = RasDss.read_timeseries(dss_file, pathname)
                if df is not None and len(df) > 0:
                    return {'passed': True, 'message': f'Data available: {len(df)} points'}
                else:
                    return {'passed': False, 'message': 'No data found'}
            except Exception as e:
                return {'passed': False, 'message': f'Error reading data: {e}'}

        # Convert expected dates to datetime if strings
        if expected_start is not None and isinstance(expected_start, str):
            from datetime import datetime
            expected_start = datetime.strptime(expected_start, '%d%b%Y %H%M')
        if expected_end is not None and isinstance(expected_end, str):
            from datetime import datetime
            expected_end = datetime.strptime(expected_end, '%d%b%Y %H%M')

        # Read time series
        try:
            df = RasDss.read_timeseries(str(dss_file), pathname)
        except Exception as e:
            return ValidationResult(
                check_name="data_read",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Failed to read time series data: {e}",
                details={"error": str(e), "pathname": pathname}
            )

        # Check if data is empty
        if df is None or len(df) == 0:
            return ValidationResult(
                check_name="data_availability",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Time series data is empty",
                details={"pathname": pathname}
            )

        # Extract actual date range
        actual_start = df.index.min()
        actual_end = df.index.max()

        details = {
            "data_points": len(df),
            "actual_start": actual_start.strftime('%Y-%m-%d %H:%M:%S'),
            "actual_end": actual_end.strftime('%Y-%m-%d %H:%M:%S'),
            "units": df.attrs.get('units', 'unknown'),
            "interval": df.attrs.get('interval', 'unknown')
        }

        # Check date range coverage if expected dates provided
        if expected_start and expected_end:
            if actual_start > expected_start:
                return ValidationResult(
                    check_name="date_coverage",
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message=f"Data starts later than expected: {actual_start} > {expected_start}",
                    details={**details, "expected_start": expected_start.strftime('%Y-%m-%d %H:%M:%S')}
                )

            if actual_end < expected_end:
                return ValidationResult(
                    check_name="date_coverage",
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message=f"Data ends earlier than expected: {actual_end} < {expected_end}",
                    details={**details, "expected_end": expected_end.strftime('%Y-%m-%d %H:%M:%S')}
                )

        # All checks passed
        return ValidationResult(
            check_name="data_availability",
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Time series data available ({len(df)} points from {actual_start.strftime('%Y-%m-%d')} to {actual_end.strftime('%Y-%m-%d')})",
            details=details
        )

    @staticmethod
    @log_call
    def check_pathname(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """
        Comprehensive DSS pathname validation.

        Performs:
        1. Format validation
        2. File existence check
        3. Pathname existence check
        4. Data availability check (if date range provided)

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to validate
            start_date: Optional start date for availability check
            end_date: Optional end date for availability check

        Returns:
            ValidationReport: Result with all validation results

        Example:
            >>> report = RasDss.check_pathname(
            ...     dss_file="boundary.dss",
            ...     pathname="//BASIN/FLOW/STAGE/01JAN2020/1HOUR//",
            ...     start_date="01JAN2020 0000",
            ...     end_date="31DEC2020 2400"
            ... )
            >>> if not report.is_valid:
            ...     print(report.summary())
        """
        # Lazy import validation framework
        try:
            from ..RasValidation import ValidationReport
        except ImportError:
            # Return basic dict if validation framework not available
            results = []
            format_ok = RasDss.check_pathname_format(pathname).get('passed', False)
            results.append(f"Format: {'OK' if format_ok else 'FAIL'}")

            file_ok = RasDss.check_file_exists(dss_file).get('passed', False)
            results.append(f"File: {'OK' if file_ok else 'FAIL'}")

            if file_ok:
                exists_ok = RasDss.check_pathname_exists(dss_file, pathname).get('passed', False)
                results.append(f"Exists: {'OK' if exists_ok else 'FAIL'}")

            return {'results': results, 'is_valid': all('OK' in r for r in results)}

        from datetime import datetime

        report = ValidationReport(
            target=f"DSS Pathname: {pathname}",
            timestamp=datetime.now(),
            results=[]
        )

        # Check 1: Format
        result = RasDss.check_pathname_format(pathname)
        report.results.append(result)
        if not result.passed:
            return report  # Stop if format invalid

        # Check 2: File existence
        file_result = RasDss.check_file_exists(dss_file)
        report.results.append(file_result)
        if not file_result.passed:
            return report  # Stop if file doesn't exist

        # Check 3: Pathname existence
        exists_result = RasDss.check_pathname_exists(dss_file, pathname)
        report.results.append(exists_result)
        if not exists_result.passed:
            return report  # Stop if pathname doesn't exist

        # Check 4: Data availability (if dates provided)
        if start_date or end_date:
            avail_result = RasDss.check_data_availability(
                dss_file, pathname, start_date, end_date
            )
            report.results.append(avail_result)

        return report

    @staticmethod
    def is_valid_pathname(pathname: str) -> bool:
        """
        Quick boolean check for pathname format.

        Args:
            pathname: DSS pathname to validate

        Returns:
            True if pathname format is valid

        Example:
            >>> if RasDss.is_valid_pathname("//BASIN/LOC/FLOW/01JAN2020/1HOUR/OBS/"):
            ...     print("Valid format")
        """
        result = RasDss.check_pathname_format(pathname)
        # Handle both ValidationResult and dict return types
        if hasattr(result, 'passed'):
            return result.passed
        elif isinstance(result, dict):
            return result.get('passed', False)
        return False

    @staticmethod
    def is_pathname_available(
        dss_file: Union[str, Path],
        pathname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> bool:
        """
        Quick boolean check for pathname availability.

        Args:
            dss_file: Path to DSS file (str or Path)
            pathname: DSS pathname to check
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            True if pathname exists and has data

        Example:
            >>> if RasDss.is_pathname_available("data.dss", "//BASIN/FLOW/.../"):
            ...     print("Data is available")
        """
        report = RasDss.check_pathname(dss_file, pathname, start_date, end_date)
        # Handle both ValidationReport and dict return types
        if hasattr(report, 'is_valid'):
            return report.is_valid
        elif isinstance(report, dict):
            return report.get('is_valid', False)
        return False

    # =========================================================================
    # DSS Write Operations
    # =========================================================================

    @staticmethod
    @log_call
    def write_precip_grid_arrays(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        interval_bounds: Union[List, np.ndarray, pd.DatetimeIndex],
        *,
        transform: Any,
        crs: Any,
        units: str,
        nodata: Optional[float] = None,
        overwrite: bool = False,
        grid_reference_origin: Optional[Tuple[float, float]] = None,
    ) -> List[str]:
        """Write interval precipitation arrays directly to a new native DSS7 file.

        Uses optional MIT-licensed gyanz/pydsstools, without Java or Vortex.
        Install ``ras-commander[dss-native]`` on a supported Python/platform.
        NetCDF precipitation generation and existing Java DSS APIs are unchanged.

        Args:
            dss_file: Output file. Existing files require explicit overwrite;
                overwrite replaces the entire file, it does not append records.
            pathname: Six-part template, e.g. ``/UTM15/BASIN/PRECIP///ATLAS14/``.
                D/E must be blank and become each interval's start/end.
            data: Nonnegative interval depths, shape (time, row, column).
                Row zero is north, columns run west to east. NaN and masked
                cells are NoData. Infinity and negative depths are rejected.
            interval_bounds: Exactly n_times+1 increasing, timezone-naive,
                whole-minute datetimes. No timezone conversion is performed;
                use the same clock as the receiving model. Unequal intervals
                are supported; DSS end-of-day timestamps use 2400.
            transform: Rasterio/Affine transform or six coefficients in
                (a,b,c,d,e,f) order (not GDAL geotransform order), mapping
                pixel corners. Requires north-up, unrotated square cells.
            crs: Explicit projected CRS accepted by pyproj. No reprojection
                occurs. Reproject geographic Atlas 14 grids before calling.
            units: ``inches``/``IN`` or ``mm``. Numeric values are unchanged;
                the records represent PER-CUM depth over each D/E interval,
                not cumulative storm totals or precipitation rates.
            nodata: Optional input sentinel, in the same units as data.
            overwrite: Replace the whole output file after successful writing.
            grid_reference_origin: Optional physical (x, y) coordinate of the
                lower-left corner of cell (0, 0), in CRS units. The raster's
                lower-left corner must
                align with this reference at whole-cell offsets. Required when
                a receiving model addresses rainfall by fixed grid-cell indexes,
                such as legacy HMS HRAP file discretizations; use the model's
                reference, commonly (0, 0). None preserves local indexing from
                the raster lower-left corner. Neither choice reprojects data.

        Returns:
            Exact record pathnames written. Output uses DSS7 specified-time
            grids; no generic promise of RAS/HMS version compatibility is made.

        Raises:
            ImportError: Native optional dependencies are unavailable.
            ValueError: Array, pathname, units, geometry, or times are invalid.
            FileExistsError: Output exists and overwrite is false.
            RuntimeError: Written records could not be read back.

        Notes:
            A temporary sibling file is closed and its record metadata read
            back before publication. No per-timestep raster files are created.
            New output publication requires filesystem hard-link support to
            refuse a concurrently created target atomically.
            See https://github.com/gyanz/pydsstools for the upstream library.

        Backends:
            ``"java"`` (default) writes through pydsstools (this method never
            uses Java). ``"native"`` writes through ras-commander-fast-dss and does not
            need pydsstools (it still needs ``affine`` and ``pyproj``). It
            stores the records pydsstools stores: DSS7 specified grids,
            PER-CUM, ZLIB, the WKT1_GDAL CRS and its name, no time zone.
            ``"shadow"`` writes through pydsstools, repeats the write
            natively into a temporary file and logs any difference between
            the two read back natively.
        """
        from . import _native_grid

        backend = RasDss._write_backend()
        args = (dss_file, pathname, data, interval_bounds)
        kwargs = dict(
            transform=transform, crs=crs, units=units, nodata=nodata,
            overwrite=overwrite, grid_reference_origin=grid_reference_origin,
        )
        if backend == "native":
            return _native_grid.write_precip_grid_arrays_native(*args, **kwargs)
        paths = _native_grid.write_precip_grid_arrays(*args, **kwargs)
        if backend == "shadow":
            RasDss._write_precip_grid_arrays_shadow(paths, args, kwargs)
        return paths

    @staticmethod
    def _write_precip_grid_arrays_shadow(paths: List[str], args: tuple, kwargs: Dict) -> None:
        """Repeat a pydsstools precipitation write natively in a temporary directory
        and compare the native read-backs. Never raises."""
        import shutil
        import tempfile
        import time

        from . import _native_grid

        dss_file = Path(args[0])
        tmpdir = None
        try:
            tmpdir = Path(tempfile.mkdtemp(prefix="rasdss_shadow_precip_"))
            native_file = tmpdir / dss_file.name
            native_exc, diffs, labels = None, [], []
            t1 = time.perf_counter()
            try:
                native_paths = _native_grid.write_precip_grid_arrays_native(
                    native_file, *args[1:], **dict(kwargs, overwrite=False))
            except Exception as exc:
                native_exc, native_paths = exc, []
            native_s = time.perf_counter() - t1
            if native_exc is None:
                if native_paths != paths:
                    diffs.append("returned_pathnames")
                record_diffs, labels = RasDss._compare_written_grid_files(
                    dss_file, native_file, paths, RasDss._get_file_version_native(dss_file))
                diffs += record_diffs
            RasDss._shadow_write_record(
                "write_precip_grid_arrays", dss_file, args[1], native_exc, diffs, labels,
                None, native_s, detail={"records": len(paths)},
            )
        except Exception as exc:  # the comparison must never break the write
            logger.warning("DSS shadow write_precip_grid_arrays comparison failed for %s: %s",
                           dss_file, exc)
        finally:
            if tmpdir is not None:
                shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    @log_call
    def write_grid_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        grid_info: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> List[str]:
        """
        Write a time-varying spatial grid series to HEC-DSS.

        Creates one DSS grid record per timestep using the HEC Monolith Java
        bridge. The method is designed for HEC-RAS gridded precipitation DSS
        records such as::

            /SHG/MARFC/PRECIP/01SEP2018:0200/01SEP2018:0300/NEXRAD/

        Args:
            dss_file: Path to DSS file (created if missing and
                create_if_missing=True).
            pathname: DSS grid pathname template. Parts A, B, C, and F are
                preserved; Parts D and E are replaced with each timestep's
                start/end window.
            data: 3-D array with shape ``(n_times, n_rows, n_cols)``.
                HEC row order: row zero is south, columns run west to east.
                For north-up raster arrays pass ``data[:, ::-1, :]``.
                NaN/inf values and values equal to ``grid_info["nodata_value"]``
                are written as the HEC grid no-data sentinel.
            times: Timezone-naive datetime values. Pass ``n_times + 1`` values
                to provide explicit interval boundaries, or ``n_times`` values
                to provide interval end times. For ``n_times`` period data, the
                interval is inferred from ``grid_info["interval_minutes"]``,
                consecutive times, the pathname D/E parts, or 60 minutes.
            grid_info: Grid metadata. Common keys are:
                - ``cellsize`` or ``cell_size``: cell size in CRS units.
                - ``origin``: physical lower-left coordinate ``(x, y)``.
                - ``lower_left_cell_x`` / ``lower_left_cell_y``: explicit HEC
                  cell indexes, used instead of ``origin`` when provided.
                - ``x_coord_cell_zero`` / ``y_coord_cell_zero``: physical
                  coordinate of HEC cell zero, default 0.
                - ``crs``: ``"SHG"``/``"EPSG:5070"`` for HEC SHG Albers
                  metadata, or WKT for a specified grid.
                - ``units``: data units, default ``"mm"``.
                - ``data_type``: DSS grid data type, default ``"PER-CUM"``.
                - ``compression``: ``"PRECIP_2_BYTE"``, ``"ZLIB"``, or
                  ``None``. Defaults to ``"PRECIP_2_BYTE"``.
            create_if_missing: Create DSS file if it doesn't exist.
            dss_version: Major DSS version to use when creating a new file.
                Pass 6 or 7 explicitly, or omit it to preserve the bridge's
                current default. Existing files must match an explicit value.
                For DSS6, default precipitation compression is configured with
                the version-specific safe base/scale ordering.

        Returns:
            List of DSS pathnames written, one per timestep.

        Raises:
            FileNotFoundError: If DSS file doesn't exist and
                create_if_missing=False.
            ValueError: If inputs are malformed, timestamps are timezone-aware,
                grid metadata is incomplete, ``dss_version`` is invalid, or an
                existing file does not match the requested version.
            ImportError: If pyjnius is not installed.
            RuntimeError: If the Java grid write operation fails.

        Notes:
            HEC Monolith 3.3.x exposes ``hec.io.GridContainer`` and
            ``hec.heclib.grid.GridData/GridInfo`` for grid records. This method
            writes through ``hec.heclib.grid.GriddedData.storeGriddedData()``
            because it is the stable Java API path from pyjnius for grid data.

        Backends:
            ``"java"`` (default) writes through HEC Monolith. ``"native"``
            writes through ras-commander-fast-dss without a JVM and never falls back to
            Java. It stores what Monolith stores: DSS7 grids are always ZLIB
            compressed (Monolith ignores the requested method on DSS7); DSS6
            grids use the requested ZLIB or PRECIP_2_BYTE. Differences:
            ``compression_base`` and ``compression_scale_factor`` are stored
            as named (the Java path passes them to Monolith's setter in
            swapped positions, hence its DSS6 default workaround); without
            them DSS6 PRECIP_2_BYTE scale and base are chosen as Monolith
            chooses them, adjusted for negative minima, where the Java path
            stores cells below base 0 as missing. The native writer refuses,
            where the Java path writes an unreadable or lossy record:
            uncompressed DSS6 grids, PRECIP_2_BYTE cells that the given scale
            and base would turn into missing, data types other than
            PER-AVER, PER-CUM, INST-VAL and INST-CUM, and DSS6 unit strings
            longer than 12 characters. DSS7 HRAP and Albers grids store a null
            value of -FLT_MAX (Monolith stores 0.0; neither reader treats it as
            data). Instantaneous grids are stored with the time in part D and
            part E blank, as Monolith stores them; the native writer returns
            those stored pathnames, the Java path returns D/E-filled names.
            ``"shadow"`` writes with Java, repeats the write natively on a
            temporary copy and logs any difference between the native
            read-backs; the comparison never raises.
        """
        backend = RasDss._write_backend()
        args = (dss_file, pathname, data, times, grid_info, create_if_missing)
        if backend == "native":
            return RasDss._write_grid_timeseries_native(*args, dss_version=dss_version)
        if backend == "shadow":
            return RasDss._write_grid_timeseries_shadow(*args, dss_version=dss_version)
        return RasDss._write_grid_timeseries_java(*args, dss_version=dss_version)

    @staticmethod
    def _write_grid_timeseries_java(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        grid_info: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> List[str]:
        """``write_grid_timeseries`` through HEC Monolith (unchanged Java path)."""
        dss_version = RasDss._validate_dss_version(dss_version)
        if grid_info is None:
            raise ValueError("grid_info is required")
        grid_info = dict(grid_info)

        # HEC Monolith's DSS6 precipitation-compression setter exposes its
        # base and scale positions opposite to DSS7. Supply the known-safe V6
        # defaults when the caller selects DSS6 and has not overridden them.
        compression = grid_info.get("compression", "PRECIP_2_BYTE")
        if dss_version == 6 and isinstance(compression, str):
            compression_text = compression.upper().replace("-", "_")
            if compression_text in {"PRECIP", "PRECIP2BYTE", "PRECIP_2_BYTE"}:
                grid_info.setdefault("compression_base", 100.0)
                grid_info.setdefault("compression_scale_factor", 0.0)

        grid_array = np.asarray(data, dtype=np.float32)
        if grid_array.ndim != 3:
            raise ValueError(
                "data must have shape (n_times, n_rows, n_cols); "
                f"got {grid_array.shape}"
            )

        n_times, n_rows, n_cols = grid_array.shape
        if n_times == 0 or n_rows == 0 or n_cols == 0:
            raise ValueError(
                "data dimensions must be non-empty; "
                f"got {grid_array.shape}"
            )

        prefix, path_parts = RasDss._split_dss_pathname(pathname)
        data_type = str(grid_info.get("data_type", "PER-CUM")).upper().replace("_", "-")
        data_type_code = RasDss._grid_data_type_code(data_type)
        time_windows = RasDss._grid_time_windows(
            times=times,
            n_times=n_times,
            data_type_code=data_type_code,
            grid_info=grid_info,
            pathname_parts=path_parts,
        )

        dss_path = Path(dss_file)
        file_existed = dss_path.exists()
        if file_existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if file_existed:
            RasDss._require_writable_dss_file(dss_path)
        if file_existed and dss_version is not None:
            existing_version = RasDss._get_file_version_java(dss_path)
            if existing_version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {existing_version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        if not file_existed:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")

        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        # GriddedData creates a missing file with the bridge default. When the
        # caller requests DSS6 or DSS7 explicitly, create that empty database
        # first so the grid writer attaches to the requested file format.
        if not file_existed and dss_version is not None:
            RasDss._create_empty_dss(dss_path, dss_version)

        GridInfo = autoclass('hec.heclib.grid.GridInfo')
        GridData = autoclass('hec.heclib.grid.GridData')
        GriddedData = autoclass('hec.heclib.grid.GriddedData')
        HecTime = autoclass('hec.heclib.util.HecTime')
        AlbersInfo = autoclass('hec.heclib.grid.AlbersInfo')
        SpecifiedGridInfo = autoclass('hec.heclib.grid.SpecifiedGridInfo')
        HrapInfo = autoclass('hec.heclib.grid.HrapInfo')

        hec_nodata = float(GridInfo.getGridNodataValue())
        source_nodata = grid_info.get("nodata_value", None)
        written_pathnames: List[str] = []

        RasDss._drain_hec_messages()  # earlier calls' lines are not this write's
        closing_failures: List[str] = []
        writer = None
        try:
            writer = GriddedData()
            status = writer.setDSSFileName(dss_file_str)
            if status != 0:
                raise RuntimeError(f"setDSSFileName returned status {status}")

            for index, (start_time, end_time) in enumerate(time_windows):
                d_part = RasDss._format_grid_dss_datetime(start_time)
                e_part = RasDss._format_native_grid_end_datetime(end_time)
                record_parts = list(path_parts)
                record_parts[3] = d_part
                record_parts[4] = e_part
                record_pathname = RasDss._build_dss_pathname(prefix, record_parts)

                java_grid_info = RasDss._create_java_grid_info(
                    grid_info=grid_info,
                    n_rows=n_rows,
                    n_cols=n_cols,
                    start_part=d_part,
                    end_part=e_part,
                    data_type_code=data_type_code,
                    GridInfo=GridInfo,
                    AlbersInfo=AlbersInfo,
                    SpecifiedGridInfo=SpecifiedGridInfo,
                    HrapInfo=HrapInfo,
                )

                frame = np.asarray(grid_array[index], dtype=np.float32)
                flat = frame.ravel(order="C").astype(np.float32, copy=True)
                nodata_mask = ~np.isfinite(flat)
                if source_nodata is not None:
                    nodata_mask |= flat == np.float32(source_nodata)
                flat[nodata_mask] = np.float32(hec_nodata)

                java_grid_data = GridData(flat.tolist(), java_grid_info)
                java_grid_data.updateStatistics()

                writer.setPathname(record_pathname)
                writer.setGriddedPathnameParts(
                    record_parts[0],
                    record_parts[1],
                    record_parts[2],
                    record_parts[5],
                )

                start_date, start_clock = RasDss._split_grid_datetime_part(d_part)
                end_date, end_clock = RasDss._split_grid_datetime_part(e_part)
                if data_type_code in (2, 3):  # INST-VAL or INST-CUM
                    writer.setGridTime(HecTime(end_date, end_clock))
                else:
                    writer.setGriddedTimeWindow(
                        HecTime(start_date, start_clock),
                        HecTime(end_date, end_clock),
                    )

                status = writer.storeGriddedData(java_grid_info, java_grid_data)
                if status != 0:
                    raise RuntimeError(
                        f"storeGriddedData returned status {status} for {record_pathname}"
                    )

                written_pathnames.append(record_pathname)

            RasDss._raise_hec_write_failures(RasDss._drain_hec_messages())
        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to write grid time series to DSS: {e}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname template: {pathname}\n"
                f"  Data shape: {grid_array.shape}"
            ) from e
        finally:
            if writer is not None:
                try:
                    writer.done()
                finally:
                    closing_failures = RasDss._release_dss_file(dss_file_str)
        RasDss._raise_hec_write_failures(closing_failures, dss_file_str)
        logger.info(
            f"Wrote {len(written_pathnames)} grid records to {Path(dss_file_str).name} "
            f"(shape={n_rows}x{n_cols}, units={grid_info.get('units', 'mm')}, "
            f"type={data_type})"
        )
        return written_pathnames

    #: ``grid_info["compression"]`` names and HEC method codes -> ras-commander-fast-dss names.
    _NATIVE_GRID_COMPRESSION_NAMES = {
        "PRECIP": "precip_2_byte", "PRECIP2BYTE": "precip_2_byte",
        "PRECIP_2_BYTE": "precip_2_byte", "ZLIB": "zlib", "ZLIB_DEFLATE": "zlib",
        "NONE": "none", "UNDEFINED": "none",
    }
    _NATIVE_GRID_COMPRESSION_CODES = {101001: "precip_2_byte", 26: "zlib", 0: "none"}

    @staticmethod
    def _native_grid_compression(compression: Any, version: int) -> str:
        """ras-commander-fast-dss compression for a ``grid_info["compression"]`` value.

        DSS7: always ``"zlib"``. HEC Monolith stores every DSS7 grid ZLIB compressed
        whatever method it is given (verified with Monolith 3.3.27 for PRECIP_2_BYTE,
        ZLIB, NONE and ``None``). DSS6: the requested method; ``None`` (Monolith's
        default) is ZLIB.
        """
        if compression is None:
            name = "zlib"
        elif isinstance(compression, (int, np.integer)) and not isinstance(compression, bool):
            name = RasDss._NATIVE_GRID_COMPRESSION_CODES.get(int(compression))
        else:
            name = RasDss._NATIVE_GRID_COMPRESSION_NAMES.get(
                str(compression).upper().replace("-", "_")
            )
        if name is None:
            raise ValueError(f"Unsupported grid compression: {compression}")
        return "zlib" if version == 7 else name

    @staticmethod
    def _native_grid_kwargs(
        grid_info: Dict[str, Any], data_type: str, version: int
    ) -> Dict[str, Any]:
        """``ras_commander_fast_dss.write_grid`` keyword arguments for a RasDss ``grid_info``.

        Follows ``_create_java_grid_info``: the same keys and defaults, the same
        lower-left cell (explicit indexes, else ``origin`` rounded to whole cells from
        cell zero), and the same grid-type inference from ``crs``.
        """
        cell_size = RasDss._grid_info_number(
            grid_info, ["cellsize", "cell_size", "cell_size_m", "dx", "resolution"],
        )
        if cell_size is None:
            raise ValueError("grid_info must include cellsize or cell_size")
        cell_size = float(cell_size)
        if cell_size <= 0:
            raise ValueError(f"cellsize must be positive, got {cell_size}")
        x_cell_zero = float(RasDss._grid_info_number(
            grid_info, ["x_coord_cell_zero", "x_coord_of_grid_cell_zero", "x_cell_zero"], 0.0))
        y_cell_zero = float(RasDss._grid_info_number(
            grid_info, ["y_coord_cell_zero", "y_coord_of_grid_cell_zero", "y_cell_zero"], 0.0))
        origin_x, origin_y = RasDss._grid_origin_xy(grid_info)
        lower_left_cell_x = RasDss._grid_info_number(
            grid_info, ["lower_left_cell_x", "lowerLeftCellX", "ll_cell_x"])
        lower_left_cell_y = RasDss._grid_info_number(
            grid_info, ["lower_left_cell_y", "lowerLeftCellY", "ll_cell_y"])
        if lower_left_cell_x is None:
            lower_left_cell_x = (0 if origin_x is None
                                 else int(round((float(origin_x) - x_cell_zero) / cell_size)))
        if lower_left_cell_y is None:
            lower_left_cell_y = (0 if origin_y is None
                                 else int(round((float(origin_y) - y_cell_zero) / cell_size)))

        crs = str(grid_info.get("crs", "SHG"))
        grid_type = str(grid_info.get("grid_type", "")).lower()
        crs_upper = crs.upper()
        if not grid_type:
            if crs_upper in {"SHG", "EPSG:5070", "5070"} or "ALBERS" in crs_upper:
                grid_type = "albers"
            else:
                grid_type = "specified"

        kwargs: Dict[str, Any] = {
            "cell_size": cell_size,
            "lower_left_cell": (int(lower_left_cell_x), int(lower_left_cell_y)),
            "units": str(grid_info.get("units", "mm")),
            "data_type": data_type,
            "version": int(version),
        }
        if grid_type == "hrap":
            kwargs.update(grid_type="hrap", data_source=str(grid_info.get("data_source") or ""))
        elif grid_type == "specified":
            # Monolith's SpecifiedGridInfo defaults: time zone UTC, offset 0, interval.
            kwargs.update(
                grid_type="specified", srs_definition=crs,
                srs_name=str(grid_info.get("crs_name", "Specified Grid")),
                cell_zero=(x_cell_zero, y_cell_zero),
                time_zone="UTC", time_zone_offset_ms=0, is_interval=True,
            )
        else:
            datum = grid_info.get("projection_datum", "NAD83")
            if not (isinstance(datum, (int, np.integer)) and not isinstance(datum, bool)):
                datum = {"NAD27": 1, "UNDEFINED": 0}.get(
                    str(datum or "NAD83").upper().replace("_", ""), 2)
            kwargs.update(
                grid_type="albers", cell_zero=(x_cell_zero, y_cell_zero),
                albers={
                    "datum": int(datum),
                    "units": str(grid_info.get("projection_units", "METERS")),
                    "first_standard_parallel": float(grid_info.get("standard_parallel_1", 29.5)),
                    "second_standard_parallel": float(grid_info.get("standard_parallel_2", 45.5)),
                    "central_meridian": float(grid_info.get("central_meridian", -96.0)),
                    "latitude_of_origin": float(grid_info.get("latitude_of_origin", 23.0)),
                    "false_easting": float(grid_info.get("false_easting", 0.0)),
                    "false_northing": float(grid_info.get("false_northing", 0.0)),
                },
            )

        compression = RasDss._native_grid_compression(
            grid_info.get("compression", "PRECIP_2_BYTE"), version
        )
        kwargs["compression"] = compression
        if compression == "precip_2_byte":
            base = grid_info.get("compression_base")
            scale = grid_info.get("compression_scale_factor")
            if (base is None) != (scale is None):
                raise ValueError(
                    "give both compression_base and compression_scale_factor, or neither "
                    "(the native writer then chooses them as HEC Monolith does)"
                )
            if base is not None:
                kwargs.update(base=float(base), scale_factor=float(scale))
        return kwargs

    @staticmethod
    def _write_grid_timeseries_native(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        grid_info: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> List[str]:
        """``write_grid_timeseries`` through ras-commander-fast-dss (no JVM).

        Same argument checks, time windows and pathnames as the Java path; one
        ``ras_commander_fast_dss.write_grid`` call per record. Returns the stored pathnames.
        """
        dss_version = RasDss._validate_dss_version(dss_version)
        if grid_info is None:
            raise ValueError("grid_info is required")
        grid_info = dict(grid_info)
        grid_array = np.asarray(data, dtype=np.float32)
        if grid_array.ndim != 3:
            raise ValueError(
                "data must have shape (n_times, n_rows, n_cols); "
                f"got {grid_array.shape}"
            )
        n_times, n_rows, n_cols = grid_array.shape
        if n_times == 0 or n_rows == 0 or n_cols == 0:
            raise ValueError(
                "data dimensions must be non-empty; "
                f"got {grid_array.shape}"
            )
        prefix, path_parts = RasDss._split_dss_pathname(pathname)
        data_type = str(grid_info.get("data_type", "PER-CUM")).upper().replace("_", "-")
        data_type_code = RasDss._grid_data_type_code(data_type)
        time_windows = RasDss._grid_time_windows(
            times=times, n_times=n_times, data_type_code=data_type_code,
            grid_info=grid_info, pathname_parts=path_parts,
        )
        dc = _backend.require_native_writes()
        target, version, existed, created_dirs = RasDss._native_write_target(
            dss_file, dss_version, create_if_missing
        )
        written: List[str] = []
        with RasDss._native_new_file(dc, target, version, existed, created_dirs):
            kwargs = RasDss._native_grid_kwargs(grid_info, data_type, version)
            source_nodata = grid_info.get("nodata_value", None)
            for index, (start_time, end_time) in enumerate(time_windows):
                record_parts = list(path_parts)
                if data_type_code in (2, 3):
                    # Instantaneous: Monolith stores the time in D and leaves E blank.
                    record_parts[3] = RasDss._format_native_grid_end_datetime(end_time)
                    record_parts[4] = ""
                else:
                    record_parts[3] = RasDss._format_grid_dss_datetime(start_time)
                    record_parts[4] = RasDss._format_native_grid_end_datetime(end_time)
                record_pathname = RasDss._build_dss_pathname(prefix, record_parts)
                frame = np.array(grid_array[index], dtype=np.float32, copy=True)
                nodata_mask = ~np.isfinite(frame)
                if source_nodata is not None:
                    nodata_mask |= frame == np.float32(source_nodata)
                frame[nodata_mask] = np.nan
                dc.write_grid(str(target), record_pathname, frame, **kwargs)
                written.append(record_pathname)
        logger.info(
            f"Wrote {len(written)} grid records to {target.name} "
            f"(shape={n_rows}x{n_cols}, units={kwargs['units']}, type={data_type}, "
            f"DSS{version}, {kwargs['compression']})"
        )
        return written

    @staticmethod
    def _write_grid_timeseries_shadow(
        dss_file: Union[str, Path],
        pathname: str,
        data: np.ndarray,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        grid_info: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> List[str]:
        """Java write (returned); the native writer repeats it on a temporary copy and
        each written record is read back natively from both files and compared."""
        import time

        ctx = RasDss._shadow_write_snapshot(dss_file)
        try:
            t0 = time.perf_counter()
            written = RasDss._write_grid_timeseries_java(
                dss_file, pathname, data, times, grid_info, create_if_missing,
                dss_version=dss_version,
            )
            java_s = time.perf_counter() - t0
            try:
                if ctx.get("skip"):
                    _backend.record("write_grid_timeseries", "skipped", ctx["skip"],
                                    dss_file=dss_file, pathname=pathname, java_seconds=java_s)
                else:
                    version = RasDss._get_file_version_native(dss_file)
                    native_exc, native_paths = None, []
                    t1 = time.perf_counter()
                    try:
                        native_paths = RasDss._write_grid_timeseries_native(
                            ctx["copy"], pathname, data, times, grid_info, True,
                            dss_version=None if ctx["existed"] else version,
                        )
                    except Exception as exc:
                        native_exc = exc
                    native_s = time.perf_counter() - t1
                    diffs, labels = RasDss._compare_written_grid_files(
                        dss_file, ctx["copy"], native_paths, version
                    ) if native_exc is None else ([], [])
                    RasDss._shadow_write_record(
                        "write_grid_timeseries", dss_file, pathname, native_exc, diffs,
                        labels, java_s, native_s,
                        detail={"dss_version": version, "records": len(native_paths)},
                    )
            except Exception as exc:  # the comparison must never break the write
                logger.warning("DSS shadow write_grid_timeseries comparison failed for %s: %s",
                               dss_file, exc)
            return written
        finally:
            RasDss._shadow_write_cleanup(ctx)

    @staticmethod
    def _compare_written_grid_files(
        java_file: Union[str, Path],
        native_file: Union[str, Path],
        pathnames: List[str],
        version: int,
    ) -> Tuple[List[str], List[str]]:
        """Read each pathname natively from both files and compare (shadow writes)."""
        diffs: List[str] = []
        labels: List[str] = []
        for record_pathname in pathnames:
            readback = record_pathname.upper() if version == 6 else record_pathname
            try:
                java_grid = RasDss._read_grid_native(java_file, readback)
            except Exception as exc:
                diffs.append(f"{readback}: java-written record unreadable "
                             f"({type(exc).__name__})")
                continue
            native_grid = RasDss._read_grid_native(native_file, readback)
            record_diffs, record_labels = _backend.compare_written_grids(java_grid, native_grid)
            diffs += [f"{readback}: {d}" for d in record_diffs]
            labels += [label for label in record_labels if label not in labels]
        return diffs, labels

    @staticmethod
    @log_call
    def copy_grid_with_zero_tail(
        source_dss: Union[str, Path],
        output_dss: Union[str, Path],
        pathname: str,
        tail_intervals: int,
        *,
        time_shift_minutes: int = 0,
        output_pathname: Optional[str] = None,
        x_shift: float = 0.0,
        y_shift: float = 0.0,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Create a non-destructive grid derivative with an explicit zero tail.

        The output contains only the uniquely matched source grid family and
        the appended tail. Source records are streamed one frame at a time and
        rewritten with their decoded values and write-relevant metadata;
        unrelated source records are not copied. Optional time, pathname, and
        whole-cell origin translations are mechanical metadata transforms.

        The intended workflow is upstream preparation of a run-local gridded
        precipitation or rainfall-excess DSS derivative for a HEC-RAS
        rain-on-grid scenario. A caller can preserve an immutable AORC-like
        source, express UTC grid timestamps on the model clock with an
        explicitly chosen shift, rename the forcing family, apply an approved
        whole-cell origin translation, and append explicit zero-forcing
        intervals so post-storm routing or recession can continue after the
        source rainfall ends. In the source PR workflow, ``RasScenario``
        accepted the already-prepared ``forcing_excess_dss`` and wired it to
        Gridded/DSS precipitation; it did not call this preparation method.

        This method does not calculate rainfall or rainfall excess,
        scientifically transpose a storm, reproject, resample, or interpolate
        grids, infer a time zone, or decide engineering suitability. Those
        scientific and study-specific decisions remain caller responsibilities.

        ``overwrite=False`` publishes with an atomic hard-link create-if-absent
        operation. Filesystems without compatible hard-link support fail closed
        with ``OSError``; the method never falls back to a clobbering replace.
        ``overwrite=True`` atomically replaces the destination and therefore
        replaces its file metadata and hard-link identity. Output symlinks,
        junctions, and other reparse points are rejected before resolution.

        Args:
            source_dss: Existing source DSS file, which is never modified.
            output_dss: Destination DSS file for the derivative.
            pathname: Six-part family selector whose D and E parts are blank.
            tail_intervals: Positive number of zero-valued records to append.
            time_shift_minutes: Signed whole-minute shift for every window.
            output_pathname: Optional output family selector with blank D/E.
                When omitted, caller-supplied A/B/C/F casing is preserved even
                though source-family selection is case-insensitive.
            x_shift: Signed x-origin translation in source grid units. It must
                be an exact whole-cell increment.
            y_shift: Signed y-origin translation in source grid units. It must
                be an exact whole-cell increment.
            overwrite: Atomically replace an existing destination after full
                temporary readback. When false, publish only by atomic hard
                link if the destination still does not exist.

        Returns:
            A dictionary describing source coverage, translations, DSS
            version, accepted source SHA-256, rewritten source paths, and
            appended tail paths.

        Raises:
            FileNotFoundError: If the source DSS does not exist.
            FileExistsError: If the destination exists without ``overwrite``.
            IsADirectoryError: If a DSS path is not a regular file.
            ValueError: If inputs, family timing, metadata, or NoData masks are
                unsafe or ambiguous.
            ImportError: If the optional Java bridge is unavailable.
            OSError: If directory, hard-link publication, or replacement fails.
            RuntimeError: If source stability, grid I/O, or complete temporary
                readback verification fails.

        Notes:
            D/E tokens must use exact ``DDMMMYYYY:HHMM`` minute syntax. A
            narrow ``2400`` token is accepted as next-day midnight. Native
            HEC-DSS grid catalogs spell midnight record ends as prior-day
            ``2400`` and midnight record starts as same-day ``0000``; returned
            pathnames follow that role-specific convention. The source is
            SHA-256 checked before access, after the validation pass, and after
            the streaming write pass. Any detected mismatch aborts before
            publication. Every temporary record is reopened and compared
            exactly before publish.

        Backends:
            ``"java"`` (default) reads, writes and verifies through HEC
            Monolith. ``"native"`` does all three through ras-commander-fast-dss with
            the same checks and no JVM; it keeps the source's PRECIP_2_BYTE
            scale and base (DSS6) and the source's DSS version. ZLIB scale and
            base words, which ZLIB does not use, are not compared. ``"shadow"``
            returns the Java derivative, builds a native derivative in a
            temporary directory, and logs any difference between the two
            read back natively.
        """
        backend = RasDss.get_backend()
        args = (source_dss, output_dss, pathname, tail_intervals)
        kwargs = dict(
            time_shift_minutes=time_shift_minutes, output_pathname=output_pathname,
            x_shift=x_shift, y_shift=y_shift, overwrite=overwrite,
        )
        if backend == "native":
            return RasDss._copy_grid_with_zero_tail_impl(*args, native=True, **kwargs)
        if backend == "shadow":
            return RasDss._copy_grid_with_zero_tail_shadow(*args, **kwargs)
        return RasDss._copy_grid_with_zero_tail_impl(*args, native=False, **kwargs)

    @staticmethod
    def _copy_grid_with_zero_tail_impl(
        source_dss: Union[str, Path],
        output_dss: Union[str, Path],
        pathname: str,
        tail_intervals: int,
        *,
        time_shift_minutes: int = 0,
        output_pathname: Optional[str] = None,
        x_shift: float = 0.0,
        y_shift: float = 0.0,
        overwrite: bool = False,
        native: bool = False,
    ) -> Dict[str, Any]:
        """``copy_grid_with_zero_tail`` on one backend.

        ``native=False`` is the Java path, unchanged. ``native=True`` reads the source,
        writes the temporary derivative and verifies it through ras-commander-fast-dss, with the
        same checks; no JVM is started.
        """
        from ras_commander.RasUtils import RasUtils

        raw_output = Path(output_dss)
        if RasDss._is_reparse_point(raw_output):
            raise ValueError(
                "output_dss must not be a symlink, junction, or reparse point"
            )
        source = RasUtils.safe_resolve(Path(source_dss))
        output_parent = RasUtils.safe_resolve(raw_output.parent)
        output = output_parent / raw_output.name
        if not source.exists():
            raise FileNotFoundError(f"DSS file not found: {source}")
        if not source.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {source}")

        same_file = source == output
        if output.exists() and not same_file:
            try:
                same_file = os.path.samefile(source, output)
            except OSError:
                same_file = False
        if same_file:
            raise ValueError("output_dss must differ from source_dss")

        if type(tail_intervals) is not int or tail_intervals <= 0:
            raise ValueError("tail_intervals must be a positive integer")
        if type(time_shift_minutes) is not int:
            raise ValueError("time_shift_minutes must be an integer")
        if type(overwrite) is not bool:
            raise ValueError("overwrite must be a boolean")
        x_shift = RasDss._normalize_finite_real(x_shift, "x_shift")
        y_shift = RasDss._normalize_finite_real(y_shift, "y_shift")

        _, selector_parts = RasDss._validate_grid_family_selector(
            pathname,
            "pathname",
        )
        derivative_pathname = (
            pathname if output_pathname is None else output_pathname
        )
        _, derivative_parts = RasDss._validate_grid_family_selector(
            derivative_pathname,
            "output_pathname",
        )
        canonical_derivative_pathname = RasDss._build_dss_pathname(
            "/",
            derivative_parts,
        )

        if output.exists() and not output.is_file():
            raise IsADirectoryError(f"Output DSS path is not a file: {output}")
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output DSS already exists: {output}")

        ops = RasDss._copy_grid_ops(native)
        ops["best_effort_close"](source, "before initial source hash")
        source_sha256 = RasDss._sha256_file(source)
        reference: Optional[Dict[str, Any]] = None
        reference_signature: Optional[Dict[str, Any]] = None
        nodata_mask: Optional[np.ndarray] = None
        try:
            catalog = ops["catalog"](source)
            records = RasDss._select_grid_family_records(
                catalog,
                pathname,
                selector_parts,
            )
            for record in records:
                grid = ops["read_grid"](source, record[2])
                signature, mask = RasDss._validate_grid_record_metadata(
                    grid,
                    record,
                    reference_signature,
                    nodata_mask,
                )
                if reference is None:
                    reference = grid
                    reference_signature = signature
                    nodata_mask = mask
            source_version = ops["file_version"](source)
        finally:
            ops["best_effort_close"](
                source,
                "after source catalog/prevalidation",
            )

        if reference is None or reference_signature is None or nodata_mask is None:
            raise ValueError("Grid family records could not be read completely")
        del grid
        if RasDss._sha256_file(source) != source_sha256:
            raise RuntimeError("Source DSS changed during grid-family validation")

        metadata = reference["metadata"]
        cell_size = float(reference["cell_size"])
        x_shift_cells = RasDss._whole_grid_cell_shift(
            x_shift,
            cell_size,
            "x_shift",
        )
        y_shift_cells = RasDss._whole_grid_cell_shift(
            y_shift,
            cell_size,
            "y_shift",
        )
        lower_left = tuple(metadata["lower_left_cell"])
        output_lower_left = (
            int(lower_left[0]) + x_shift_cells,
            int(lower_left[1]) + y_shift_cells,
        )
        RasDss._validate_java_int32(output_lower_left[0], "lower-left x cell")
        RasDss._validate_java_int32(output_lower_left[1], "lower-left y cell")

        interval = records[0][1] - records[0][0]
        source_boundaries = [records[0][0]] + [
            end for _, end, _ in records
        ]
        output_boundaries = RasDss._translated_grid_boundaries(
            source_boundaries,
            interval,
            time_shift_minutes,
            tail_intervals,
        )
        output_source_end = output_boundaries[len(records)]

        expected_catalog_pathnames = RasDss._expected_native_grid_pathnames(
            canonical_derivative_pathname,
            output_boundaries,
        )

        zero_frame = np.where(
            nodata_mask,
            np.float32(np.nan),
            np.float32(0.0),
        )
        grid_info = RasDss._grid_write_info_from_record(
            reference,
            output_lower_left,
        )
        if native:
            grid_info = RasDss._native_write_info_from_record(reference, grid_info)
        expected_output_signature = dict(reference_signature)
        expected_output_signature["lower_left_cell"] = output_lower_left
        projection = reference_signature["projection"]
        expected_output_signature["origin"] = (
            float(projection["x_coord_cell_zero"])
            + output_lower_left[0] * cell_size,
            float(projection["y_coord_cell_zero"])
            + output_lower_left[1] * cell_size,
        )
        del reference

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(
            f".{output.stem}.{uuid4().hex}.tmp{output.suffix or '.dss'}"
        )
        while temporary.exists():
            temporary = output.with_name(
                f".{output.stem}.{uuid4().hex}.tmp{output.suffix or '.dss'}"
            )

        written_count = 0
        source_value_digests: List[str] = []
        try:
            ops["create_empty"](temporary, source_version)
            try:
                for index, record in enumerate(records):
                    grid = ops["read_grid"](source, record[2])
                    RasDss._validate_grid_record_metadata(
                        grid,
                        record,
                        reference_signature,
                        nodata_mask,
                    )
                    frame = np.asarray(grid["data"], dtype=np.float32)
                    source_value_digests.append(RasDss._grid_value_digest(frame))
                    returned = ops["write_grid"](
                        dss_file=temporary,
                        pathname=canonical_derivative_pathname,
                        data=frame[np.newaxis, :, :],
                        times=[
                            output_boundaries[index].to_pydatetime(),
                            output_boundaries[index + 1].to_pydatetime(),
                        ],
                        grid_info=grid_info,
                        create_if_missing=False,
                    )
                    RasDss._validate_grid_writer_return(
                        returned,
                        canonical_derivative_pathname,
                        output_boundaries[index],
                        output_boundaries[index + 1],
                    )
                    written_count += 1
            finally:
                ops["best_effort_close"](
                    source,
                    "after source reread/write",
                )

            if RasDss._sha256_file(source) != source_sha256:
                raise RuntimeError("Source DSS changed during grid-family rewrite")
            del frame, grid

            source_count = len(records)
            for tail_index in range(tail_intervals):
                index = source_count + tail_index
                returned = ops["write_grid"](
                    dss_file=temporary,
                    pathname=canonical_derivative_pathname,
                    data=zero_frame[np.newaxis, :, :],
                    times=[
                        output_boundaries[index].to_pydatetime(),
                        output_boundaries[index + 1].to_pydatetime(),
                    ],
                    grid_info=grid_info,
                    create_if_missing=False,
                )
                RasDss._validate_grid_writer_return(
                    returned,
                    canonical_derivative_pathname,
                    output_boundaries[index],
                    output_boundaries[index + 1],
                )
                written_count += 1

            if written_count != len(expected_catalog_pathnames):
                raise RuntimeError(
                    "Grid derivative writer return count does not match the "
                    "independently expected record count"
                )

            temporary_version = ops["file_version"](temporary)
            if temporary_version != source_version:
                raise RuntimeError(
                    "Grid derivative changed DSS major version: "
                    f"source={source_version}, output={temporary_version}"
                )
            temporary_paths = list(
                ops["catalog"](temporary)["pathname"].astype(str)
            )
            if (
                len(temporary_paths) != len(expected_catalog_pathnames)
                or set(temporary_paths) != set(expected_catalog_pathnames)
            ):
                raise RuntimeError(
                    "Temporary grid derivative catalog does not match the "
                    "independently expected pathnames"
                )

            for index, expected_pathname in enumerate(expected_catalog_pathnames):
                output_grid = ops["read_grid"](temporary, expected_pathname)
                RasDss._validate_grid_record_metadata(
                    output_grid,
                    (
                        output_boundaries[index],
                        output_boundaries[index + 1],
                        expected_pathname,
                    ),
                    expected_output_signature,
                    nodata_mask,
                )
                output_frame = np.asarray(output_grid["data"], dtype=np.float32)
                if index < len(records):
                    if (
                        RasDss._grid_value_digest(output_frame)
                        != source_value_digests[index]
                    ):
                        raise RuntimeError(
                            "Temporary grid derivative changed decoded source "
                            f"values or orientation: {expected_pathname}"
                        )
                else:
                    output_mask = ~np.isfinite(output_frame)
                    if not np.array_equal(output_mask, nodata_mask):
                        raise RuntimeError(
                            "Temporary grid derivative changed the tail NoData "
                            f"footprint: {expected_pathname}"
                        )
                    if np.any(output_frame[~output_mask] != np.float32(0.0)):
                        raise RuntimeError(
                            "Temporary grid derivative tail contains nonzero "
                            f"data: {expected_pathname}"
                        )

            ops["close"](temporary)
            if overwrite:
                os.replace(temporary, output)
            else:
                try:
                    os.link(temporary, output)
                except FileExistsError as exc:
                    raise FileExistsError(
                        "Output DSS appeared while the derivative was being built: "
                        f"{output}"
                    ) from exc
                except OSError as exc:
                    raise OSError(
                        "Atomic no-clobber DSS publication requires hard-link "
                        f"support in the output directory: {output.parent}"
                    ) from exc
                try:
                    temporary.unlink()
                except OSError as exc:
                    logger.warning(
                        "Published derivative but could not remove temporary "
                        "hard-link alias: %s (%s)",
                        temporary,
                        exc,
                    )
        finally:
            ops["cleanup"](temporary)

        rewritten_count = len(records)
        rewritten_pathnames = expected_catalog_pathnames[:rewritten_count]
        shifted_pathnames = []
        for record, rewritten_pathname in zip(records, rewritten_pathnames):
            _, record_parts = RasDss._split_dss_pathname(record[2])
            canonical_source_pathname = RasDss._build_dss_pathname(
                "/",
                record_parts,
            )
            if canonical_source_pathname != rewritten_pathname:
                shifted_pathnames.append(rewritten_pathname)
        return {
            "source_dss": str(source),
            "output_dss": str(output),
            "source_sha256": source_sha256,
            "dss_version": source_version,
            "pathname": pathname,
            "output_pathname": canonical_derivative_pathname,
            "source_record_count": rewritten_count,
            "appended_record_count": tail_intervals,
            "interval_minutes": int(interval.total_seconds() // 60),
            "time_shift_minutes": time_shift_minutes,
            "x_shift": x_shift,
            "y_shift": y_shift,
            "output_lower_left_cell": output_lower_left,
            "source_start": records[0][0].isoformat(),
            "source_end": records[-1][1].isoformat(),
            "output_start": output_boundaries[0].isoformat(),
            "output_source_end": output_source_end.isoformat(),
            "padded_end": output_boundaries[-1].isoformat(),
            "written_source_pathnames": rewritten_pathnames,
            "shifted_pathnames": shifted_pathnames,
            "appended_pathnames": expected_catalog_pathnames[rewritten_count:],
        }

    @staticmethod
    def _copy_grid_ops(native: bool) -> Dict[str, Any]:
        """File operations of ``copy_grid_with_zero_tail`` for one backend.

        Java: the historical calls (looked up now, so test doubles apply). Native:
        ras-commander-fast-dss reads and writes; there are no JVM handles to close.
        """
        if not native:
            return {
                "catalog": RasDss.get_catalog,
                "read_grid": RasDss._read_grid_java,
                "file_version": RasDss._get_file_version_java,
                "create_empty": RasDss._create_empty_dss,
                "close": RasDss._close_dss_file,
                "best_effort_close": RasDss._best_effort_close_dss_file,
                "cleanup": RasDss._cleanup_temporary_dss,
                "write_grid": RasDss.write_grid_timeseries,
            }
        dc = _backend.require_native_writes()

        def create_empty(dss_file: Path, dss_version: int) -> None:
            if dss_file.exists():
                raise FileExistsError(f"Temporary DSS path already exists: {dss_file}")
            dc.create(str(dss_file), int(dss_version))

        def cleanup(dss_file: Path) -> None:
            try:
                dss_file.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Could not remove temporary DSS during cleanup: %s (%s)",
                               dss_file, exc)

        return {
            "catalog": RasDss._get_catalog_native,
            "read_grid": lambda dss_file, path: RasDss._zlib_neutral_grid(
                RasDss._read_grid_native(dss_file, path)),
            "file_version": RasDss._get_file_version_native,
            "create_empty": create_empty,
            "close": lambda dss_file: None,
            "best_effort_close": lambda dss_file, phase: None,
            "cleanup": cleanup,
            "write_grid": RasDss._write_grid_timeseries_native,
        }

    @staticmethod
    def _zlib_neutral_grid(grid: Dict[str, Any]) -> Dict[str, Any]:
        """Blank the scale and base words of a ZLIB grid (native ``copy_grid``).

        ZLIB does not use them, and writers fill them differently (Monolith writes
        0 and 100 to DSS6, ras-commander-fast-dss -FLT_MAX), so the native derivative compares
        the compression method only. PRECIP_2_BYTE keeps both: they decode the cells.
        """
        metadata = grid.get("metadata") or {}
        compression = metadata.get("compression") or {}
        if compression.get("method") == 26:
            metadata["compression"] = dict(compression, base=None, scale_factor=None)
        return grid

    @staticmethod
    def _native_write_info_from_record(
        reference: Dict[str, Any], grid_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Writer metadata for the native ``copy_grid`` derivative.

        ``_grid_write_info_from_record`` swaps scale and base for the Java setter;
        the native writer takes them as named, so the source's own values are used.
        """
        compression = reference["metadata"].get("compression") or {}
        return dict(
            grid_info,
            compression_base=compression.get("base"),
            compression_scale_factor=compression.get("scale_factor"),
        )

    @staticmethod
    def _copy_grid_with_zero_tail_shadow(
        source_dss: Union[str, Path],
        output_dss: Union[str, Path],
        pathname: str,
        tail_intervals: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Java derivative (returned); a native derivative is built in a temporary
        directory and both are read back natively and compared. Never raises for the
        comparison."""
        import shutil
        import tempfile
        import time

        t0 = time.perf_counter()
        with _backend.forced_java_writes():
            result = RasDss._copy_grid_with_zero_tail_impl(
                source_dss, output_dss, pathname, tail_intervals, native=False, **kwargs
            )
        java_s = time.perf_counter() - t0
        tmpdir = None
        try:
            tmpdir = Path(tempfile.mkdtemp(prefix="rasdss_shadow_copy_"))
            native_output = tmpdir / Path(result["output_dss"]).name
            native_exc, native_result, diffs, labels = None, None, [], []
            t1 = time.perf_counter()
            try:
                native_result = RasDss._copy_grid_with_zero_tail_impl(
                    source_dss, native_output, pathname, tail_intervals, native=True,
                    **dict(kwargs, overwrite=False),
                )
            except Exception as exc:
                native_exc = exc
            native_s = time.perf_counter() - t1
            if native_result is not None:
                for key in sorted(set(result) | set(native_result)):
                    if key != "output_dss" and result.get(key) != native_result.get(key):
                        diffs.append(f"result:{key}")
                java_paths = list(RasDss._get_catalog_native(result["output_dss"])["pathname"])
                native_paths = list(RasDss._get_catalog_native(native_output)["pathname"])
                if sorted(java_paths) != sorted(native_paths):
                    diffs.append("catalog")
                else:
                    record_diffs, labels = RasDss._compare_written_grid_files(
                        result["output_dss"], native_output, java_paths,
                        int(result["dss_version"]))
                    diffs += record_diffs
            RasDss._shadow_write_record(
                "copy_grid_with_zero_tail", result["output_dss"], pathname, native_exc,
                diffs, labels, java_s, native_s,
                detail={"dss_version": result.get("dss_version")},
            )
        except Exception as exc:  # the comparison must never break the copy
            logger.warning("DSS shadow copy_grid_with_zero_tail comparison failed for %s: %s",
                           output_dss, exc)
        finally:
            if tmpdir is not None:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return result

    @staticmethod
    @log_call
    def get_file_version(dss_file: Union[str, Path]) -> int:
        """Return the major HEC-DSS file version (6 or 7).

        Args:
            dss_file: Existing DSS file to inspect. The file is never created
                or modified.

        Returns:
            ``6`` or ``7`` (``int``).

        Backends:
            ``"java"`` asks HEC Monolith (``HecDataManager.getDssFileVersion``).
            ``"native"`` reads the file header through ras-commander-fast-dss without a
            JVM. ``"shadow"`` returns the native answer and logs any
            disagreement with Java.

        Raises:
            FileNotFoundError: If the path does not exist.
            IsADirectoryError: If the path is not a file.
            DssInvalidFileError: If the file is not a supported DSS 6 or DSS 7
                database (a ``ValueError`` and ``DssFormatError``).
        """
        RasDss._check_existing_file(dss_file)
        backend = RasDss.get_backend()
        if backend == "native":
            return RasDss._get_file_version_native(dss_file)
        if backend == "shadow":
            return RasDss._get_file_version_shadow(dss_file)
        return RasDss._get_file_version_java(dss_file)

    @staticmethod
    def _check_existing_file(dss_file: Union[str, Path]) -> Path:
        dss_path = Path(dss_file)
        if not dss_path.exists():
            raise FileNotFoundError(f"DSS file not found: {dss_path}")
        if not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        return dss_path

    @staticmethod
    def _get_file_version_native(dss_file: Union[str, Path]) -> int:
        """Header version through ras-commander-fast-dss (no JVM)."""
        from ras_commander.RasUtils import RasUtils

        dss_path = RasDss._check_existing_file(dss_file)
        dc = _backend.import_native()
        try:
            signature = dc.file_signature(RasUtils.safe_resolve(dss_path))
        except dc.DssFormatError as exc:
            raise _errors.get("DssInvalidFileError")(
                f"File is not a supported HEC-DSS database: {dss_path}"
            ) from exc
        version = int(signature["version"])
        if version not in (6, 7):
            raise _errors.get("DssInvalidFileError")(
                f"File is not a supported HEC-DSS database: {dss_path}"
            )
        return version

    @staticmethod
    def _get_file_version_shadow(dss_file: Union[str, Path]) -> int:
        """Native version, cross-checked against Java. Comparison never raises."""
        import time

        invalid = _errors.get("DssInvalidFileError")
        native_version, native_exc = None, None
        t0 = time.perf_counter()
        try:
            native_version = RasDss._get_file_version_native(dss_file)
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t0
        if native_exc is not None and not isinstance(native_exc, invalid):
            _backend.record(
                "file_version", "skipped",
                f"java skipped: native {type(native_exc).__name__}",
                dss_file=dss_file, native_error=native_exc, native_seconds=native_s,
            )
            raise native_exc
        try:
            java_version, java_exc = None, None
            t1 = time.perf_counter()
            try:
                java_version = RasDss._get_file_version_java(dss_file)
            except Exception as exc:
                java_exc = exc
            java_s = time.perf_counter() - t1
            outcome, label, diffs = _backend.classify_file_version(
                java_version, java_exc, native_version, native_exc
            )
            _backend.record(
                "file_version", outcome, label, dss_file=dss_file, diffs=diffs,
                java_seconds=java_s, native_seconds=native_s, java_error=java_exc,
                native_error=native_exc,
                detail={"java_version": java_version, "native_version": native_version},
            )
        except Exception as exc:  # the comparison must never break the read
            logger.warning("DSS shadow file_version comparison failed for %s: %s", dss_file, exc)
        if native_exc is not None:
            raise native_exc
        return native_version

    @staticmethod
    def _get_file_version_java(dss_file: Union[str, Path]) -> int:
        """Header version through HEC Monolith. Internal Java-only callers
        (writers) use this directly."""
        dss_path = RasDss._check_existing_file(dss_file)

        RasDss._configure_jvm()

        from jnius import autoclass
        from ras_commander.RasUtils import RasUtils

        HecDataManager = autoclass('hec.heclib.dss.HecDataManager')
        resolved_path = str(RasUtils.safe_resolve(dss_path))
        version = int(HecDataManager.getDssFileVersion(resolved_path))
        if version not in (6, 7):
            raise _errors.get("DssInvalidFileError")(
                f"File is not a supported HEC-DSS database: {dss_path}"
            )
        return version

    @staticmethod
    def _validate_dss_version(dss_version: Optional[int]) -> Optional[int]:
        """Validate an optional explicit HEC-DSS creation version."""
        if dss_version is None:
            return None
        if type(dss_version) is not int or dss_version not in (6, 7):
            raise ValueError("dss_version must be the integer 6, 7, or None")
        return dss_version

    @staticmethod
    @log_call
    def write_timeseries(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """
        Write a time series to a DSS file.

        Creates or updates a time series record in a DSS file using the
        HEC Monolith Java bridge. Supports DSS V6 and V7 formats.

        Args:
            dss_file: Path to DSS file (created if missing and create_if_missing=True)
            pathname: DSS pathname (e.g., "//BASIN/LOCATION/FLOW//1HOUR/FORECAST/")
            times: Array of timezone-naive datetime values (datetime objects,
                   DatetimeIndex, or numpy datetime64 array). Values must be
                   aligned exactly to whole minutes.
            values: Array of numeric values (same length as times)
            units: Data units string (e.g., "CFS", "FEET", "MM", "IN")
            data_type: DSS data type string:
                - "INST-VAL" - Instantaneous values (default)
                - "PER-AVER" - Period average (e.g., precipitation)
                - "PER-CUM"  - Period cumulative
                - "INST-CUM" - Instantaneous cumulative
            create_if_missing: Create DSS file if it doesn't exist (default True)
            dss_version: Major DSS version to use when creating a new file.
                Pass 6 or 7 explicitly, or omit it to preserve the bridge's
                current default. Existing files must match an explicit value.

        Raises:
            FileNotFoundError: If DSS file doesn't exist and create_if_missing=False
            ValueError: If times and values have different lengths, are empty,
                or contain timestamps that cannot be represented exactly as
                HEC int32 epoch minutes; if ``dss_version`` is invalid; or if
                an existing file does not match the requested version. Under
                ``native``, also when the engine refuses the input (see
                Backends).
            ImportError: If pyjnius (``java``) or ras-commander-fast-dss (``native``) is
                not installed
            DssCapabilityError: ``native`` with a ras-commander-fast-dss wheel that
                has no writers (a ``NotImplementedError``)
            RuntimeError: If Java write operation fails, including a read-only target,
                a refusal the HEC-DSS library only reports as a message, and a record
                missing from the file's catalog afterwards. Native engine errors
                (``DssLockedError`` when HEC software has the file open, other
                ``DssError`` subclasses) are ``RuntimeError`` subclasses too.

        Backends:
            ``"java"`` (default) writes through HEC Monolith. ``"native"``
            writes through ras-commander-fast-dss without a JVM and never falls back to
            Java: an existing file keeps its DSS version, a new file is DSS7
            unless ``dss_version=6`` (the Java default). The E part decides
            regular or irregular (``IR-DAY`` .. ``IR-CENTURY``) storage on both
            backends. The native writer refuses, where Java truncates or
            reinterprets: times that are not exactly regular for a regular E
            part, DSS6 units or types longer than 8 characters, malformed
            pathnames, and infinite values. ``NaN`` is stored as Java stores
            it: as ``NaN`` in DSS7 files and as -901 in DSS6 files. A failed
            native write that created the file removes it. ``"shadow"``
            writes with Java, repeats the write natively on a temporary copy
            and logs any difference between the native read-back of the two
            files; the comparison never raises. See
            ``docs/user-guide/dss-native-backend.md``.

        Example:
            >>> import pandas as pd
            >>> import numpy as np
            >>> from ras_commander import RasDss
            >>>
            >>> # Create time series data
            >>> times = pd.date_range("2024-01-01", periods=24, freq="h")
            >>> values = np.random.uniform(100, 500, 24)
            >>>
            >>> # Write to DSS file
            >>> RasDss.write_timeseries(
            ...     "output.dss",
            ...     "//BASIN/UPSTREAM/FLOW//1HOUR/FORECAST/",
            ...     times, values,
            ...     units="CFS",
            ...     data_type="INST-VAL"
            ... )

        Note:
            The Java bridge (pyjnius + HEC Monolith) is configured automatically
            on first use. The HEC epoch is 1899-12-31 00:00:00; times are stored
            as integer minutes since that epoch.
        """
        backend = RasDss._write_backend()
        args = (dss_file, pathname, times, values, units, data_type, create_if_missing)
        if backend == "native":
            return RasDss._write_timeseries_native(*args, dss_version=dss_version)
        if backend == "shadow":
            return RasDss._write_timeseries_shadow(*args, dss_version=dss_version)
        return RasDss._write_timeseries_java(*args, dss_version=dss_version)

    @staticmethod
    def _write_timeseries_java(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """``write_timeseries`` through HEC Monolith (unchanged Java path)."""
        from ras_commander.RasUtils import RasUtils

        dss_version = RasDss._validate_dss_version(dss_version)

        # Validate inputs
        values = np.asarray(values, dtype=np.float64)
        if len(times) != len(values):
            raise ValueError(
                f"times ({len(times)}) and values ({len(values)}) must have same length"
            )
        if len(times) == 0:
            raise ValueError("times and values must not be empty")

        # Validate the model-clock representation before JVM setup or any
        # filesystem mutation.
        hec_times = RasDss._datetimes_to_hec_times(times)

        # Resolve DSS file path
        dss_path = Path(dss_file)
        file_existed = dss_path.exists()
        if file_existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if file_existed:
            RasDss._require_writable_dss_file(dss_path)
        if file_existed and dss_version is not None:
            existing_version = RasDss._get_file_version_java(dss_path)
            if existing_version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {existing_version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        if not file_existed:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            # HecDss.open() will create the file
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")

        dss_file_str = str(RasUtils.safe_resolve(dss_path))

        # Detect interval from time spacing
        if len(hec_times) > 1:
            intervals = np.diff(hec_times)
            interval_minutes = int(np.median(intervals))
        else:
            interval_minutes = 60  # Default 1 hour

        RasDss._configure_jvm()

        from jnius import autoclass, cast

        # Load Java classes
        HecDss = autoclass('hec.heclib.dss.HecDss')
        TimeSeriesContainer = autoclass('hec.io.TimeSeriesContainer')
        HecTimeArray = autoclass('hec.heclib.util.HecTimeArray')

        # Create TimeSeriesContainer
        tsc = TimeSeriesContainer()
        tsc.fullName = pathname
        tsc.units = units
        tsc.type = data_type
        tsc.interval = interval_minutes
        tsc.setStoreAsDoubles(True)

        # Use typed Java setters. PyJNIus cannot reliably assign primitive
        # array fields directly, and HecDss.put() has an ambiguous overload.
        n = len(values)
        time_status = tsc.setTimes(HecTimeArray(hec_times.tolist()))
        value_status = tsc.setValues(values.tolist())
        if time_status != 0 or value_status != 0:
            raise RuntimeError(
                "HEC time-series container rejected input arrays: "
                f"times={time_status}, values={value_status}"
            )
        tsc.numberValues = n

        # Open DSS file and write
        RasDss._drain_hec_messages()  # earlier calls' lines are not this write's
        closing_failures: List[str] = []
        dss = None
        try:
            dss = (
                HecDss.open(dss_file_str, dss_version)
                if dss_version is not None and not file_existed
                else HecDss.open(dss_file_str)
            )
            dss.put(cast('hec.io.DataContainer', tsc))
            # HEC Monolith returns normally from a DSS6 write it refused.
            RasDss._raise_hec_write_failures(RasDss._drain_hec_messages())
        except Exception as e:
            raise RuntimeError(
                f"Failed to write time series to DSS: {e}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname: {pathname}\n"
                f"  Values: {n} points, range [{values.min():.2f}, {values.max():.2f}]"
            ) from e
        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    closing_failures = RasDss._release_dss_file(dss_file_str)
        RasDss._raise_hec_write_failures(closing_failures, dss_file_str)
        RasDss._require_java_record_stored(dss_file_str, pathname)
        logger.info(f"Wrote {n} values to {Path(dss_file_str).name}")
        logger.debug(
            f"DSS write details: file={dss_file_str}, pathname={pathname}, "
            f"units={units}, type={data_type}, interval={interval_minutes}min"
        )

    # ------------------------------------------------------------------
    # Native writers (ras-commander-fast-dss) and shadow write comparison
    # ------------------------------------------------------------------

    #: DSS version a native writer gives a new file when ``dss_version`` is omitted.
    #: It is the Java path's default: HEC Monolith 3.3.27 creates DSS7 files.
    _NATIVE_NEW_FILE_VERSION = 7

    @staticmethod
    def _write_backend() -> str:
        """Backend for a write call. Java when a shadow comparison is already running
        (``copy_grid_with_zero_tail`` writes its records through the public writer)."""
        backend = RasDss.get_backend()
        if backend == "shadow" and _backend.java_writes_forced():
            return "java"
        return backend

    @staticmethod
    def _native_write_target(
        dss_file: Union[str, Path],
        dss_version: Optional[int],
        create_if_missing: bool,
    ) -> Tuple[Path, int, bool, List[Path]]:
        """Resolved target, its DSS version, whether it existed, and the parent
        directories created for it (deepest first), for a native write.

        Mirrors the Java writers' file checks: a directory raises
        ``IsADirectoryError``; an existing file must match an explicit
        ``dss_version``; a missing file needs ``create_if_missing``.
        """
        from ras_commander.RasUtils import RasUtils

        dss_path = Path(dss_file)
        existed = dss_path.exists()
        created_dirs: List[Path] = []
        if existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if existed:
            version = RasDss._get_file_version_native(dss_path)
            if dss_version is not None and version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        else:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            created_dirs = _backend.make_parents(dss_path)
            version = dss_version if dss_version is not None else RasDss._NATIVE_NEW_FILE_VERSION
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")
        return RasUtils.safe_resolve(dss_path), int(version), existed, created_dirs

    @staticmethod
    @contextmanager
    def _native_new_file(
        dc: Any, target: Path, version: int, existed: bool,
        created_dirs: Optional[List[Path]] = None,
    ):
        """Create ``target`` when it did not exist, and remove it (and the empty
        parent directories made for it) again if the write inside the block fails,
        so a refused native write leaves no new file or directory."""
        try:
            if not existed:
                dc.create(str(target), version)
            yield
        except BaseException:
            if not existed and target.exists():
                try:
                    target.unlink()
                except OSError as exc:
                    logger.warning("Could not remove DSS file after a failed native write: %s (%s)",
                                   target, exc)
            _backend.remove_created_dirs(created_dirs or [])
            raise

    @staticmethod
    def _write_timeseries_native(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """``write_timeseries`` through ras-commander-fast-dss (no JVM).

        Same argument checks as the Java path. Values are stored as doubles (Java
        stores doubles too). DSS7 files keep ``NaN`` as stored bits (``raw=True``),
        as Monolith stores them; DSS6 files store ``NaN`` as -901, as Monolith
        does. Infinite values are refused.
        """
        dss_version = RasDss._validate_dss_version(dss_version)
        values = np.asarray(values, dtype=np.float64)
        if len(times) != len(values):
            raise ValueError(
                f"times ({len(times)}) and values ({len(values)}) must have same length"
            )
        if len(times) == 0:
            raise ValueError("times and values must not be empty")
        hec_times = RasDss._datetimes_to_hec_times(times)
        if np.isinf(values).any():
            index = int(np.flatnonzero(np.isinf(values))[0])
            raise ValueError(
                f"value {index} is infinite; HEC-DSS has no infinity convention "
                "(the native writer refuses it; the Java path stores the bits)"
            )
        dc = _backend.require_native_writes()
        target, version, existed, created_dirs = RasDss._native_write_target(
            dss_file, dss_version, create_if_missing
        )
        stamps = (
            np.datetime64("1899-12-31T00:00", "m")
            + hec_times.astype(np.int64).astype("timedelta64[m]")
        ).astype("datetime64[s]")
        with RasDss._native_new_file(dc, target, version, existed, created_dirs):
            report = dc.write_timeseries(
                str(target), pathname, values, times=stamps, units=units,
                data_type=data_type, version=version, value_type="double",
                raw=(version == 7),
            )
        logger.info(f"Wrote {len(values)} values to {target.name}")
        logger.debug(
            f"DSS native write details: file={target}, pathname={pathname}, units={units}, "
            f"type={data_type}, version={version}, blocks={report.get('blocks')}"
        )

    @staticmethod
    def _shadow_write_snapshot(dss_file: Union[str, Path]) -> Dict[str, Any]:
        """Prepare a shadow write: copy an existing target to a temporary directory
        (before the Java write changes it). Never raises."""
        import shutil
        import tempfile

        ctx: Dict[str, Any] = {"tmpdir": None, "copy": None, "existed": False, "skip": None}
        try:
            target = Path(dss_file)
            ctx["existed"] = target.is_file()
            tmpdir = Path(tempfile.mkdtemp(prefix="rasdss_shadow_write_"))
            ctx["tmpdir"] = tmpdir
            ctx["copy"] = tmpdir / (target.name or "shadow.dss")
            if ctx["existed"]:
                size = target.stat().st_size
                limit = _backend.shadow_copy_limit_bytes(RasDss.shadow_copy_limit_mb)
                if size > limit:
                    ctx["skip"] = (
                        f"target is {size} bytes, above the shadow copy limit "
                        f"({limit} bytes; RasDss.shadow_copy_limit_mb or "
                        f"{_backend.SHADOW_COPY_LIMIT_ENV})"
                    )
                else:
                    # copyfile, not copy2: a read-only attribute would survive on the copy.
                    shutil.copyfile(target, ctx["copy"])
        except Exception as exc:
            ctx["skip"] = f"snapshot failed: {type(exc).__name__}: {exc}"
        return ctx

    @staticmethod
    def _shadow_write_cleanup(ctx: Dict[str, Any]) -> None:
        import shutil

        if ctx.get("tmpdir") is not None:
            shutil.rmtree(ctx["tmpdir"], ignore_errors=True)

    @staticmethod
    def _shadow_write_record(
        operation: str,
        dss_file: Any,
        pathname: Optional[str],
        native_exc: Optional[BaseException],
        diffs: List[str],
        labels: List[str],
        java_seconds: Optional[float],
        native_seconds: Optional[float],
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        outcome, label, diffs = _backend.classify_write(native_exc, diffs, labels)
        _backend.record(
            operation, outcome, label, dss_file=dss_file, pathname=pathname, diffs=diffs,
            java_seconds=java_seconds, native_seconds=native_seconds,
            native_error=native_exc, detail=detail,
        )

    @staticmethod
    def _readback_pathname(pathname: str, version: int) -> str:
        """Dataset pathname for a native read-back: D part blank; on DSS6 upper case
        with the DSS6 interval names (``1Minute`` -> ``1MIN``, ``1Month`` -> ``1MON``),
        as DSS6 stores them."""
        parts = pathname.split("/")
        if len(parts) == 8:
            parts[4] = ""
        if version != 6:
            return "/".join(parts)
        parts = [part.upper() for part in parts]
        if len(parts) == 8:
            parts[5] = re.sub(r"^(\d+)MINUTES?$", r"\1MIN", parts[5])
            parts[5] = re.sub(r"^(\d+)MONTHS?$", r"\1MON", parts[5])
        return "/".join(parts)

    @staticmethod
    def _write_timeseries_shadow(
        dss_file: Union[str, Path],
        pathname: str,
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        values: Union[List, np.ndarray],
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """Java write (its result and errors are returned); the native writer repeats
        the write on a temporary copy and the native read-backs of both files are
        compared and logged. The comparison never raises."""
        import time

        ctx = RasDss._shadow_write_snapshot(dss_file)
        try:
            t0 = time.perf_counter()
            RasDss._write_timeseries_java(
                dss_file, pathname, times, values, units, data_type, create_if_missing,
                dss_version=dss_version,
            )
            java_s = time.perf_counter() - t0
            try:
                RasDss._shadow_compare_timeseries_write(
                    ctx, dss_file, pathname, times, values, units, data_type, java_s
                )
            except Exception as exc:  # the comparison must never break the write
                logger.warning("DSS shadow write_timeseries comparison failed for %s: %s",
                               dss_file, exc)
        finally:
            RasDss._shadow_write_cleanup(ctx)

    @staticmethod
    def _shadow_compare_timeseries_write(
        ctx: Dict[str, Any], dss_file, pathname, times, values, units, data_type, java_s
    ) -> None:
        import time

        if ctx.get("skip"):
            _backend.record("write_timeseries", "skipped", ctx["skip"], dss_file=dss_file,
                            pathname=pathname, java_seconds=java_s)
            return
        version = RasDss._get_file_version_native(dss_file)
        native_exc, diffs = None, []
        t1 = time.perf_counter()
        try:
            RasDss._write_timeseries_native(
                ctx["copy"], pathname, times, values, units, data_type, True,
                dss_version=None if ctx["existed"] else version,
            )
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t1
        if native_exc is None:
            readback = RasDss._readback_pathname(pathname, version)
            java_df = RasDss._read_timeseries_native(dss_file, readback)
            native_df = RasDss._read_timeseries_native(ctx["copy"], readback)
            diffs = _backend.compare_written_timeseries(java_df, native_df)
        RasDss._shadow_write_record(
            "write_timeseries", dss_file, pathname, native_exc, diffs, [], java_s, native_s,
            detail={"dss_version": version},
        )

    @staticmethod
    @log_call
    def write_timeseries_from_dataframe(
        dss_file: Union[str, Path],
        pathname: str,
        df: pd.DataFrame,
        value_column: str = "value",
        units: str = "CFS",
        data_type: str = "INST-VAL",
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """
        Write a time series DataFrame to a DSS file.

        Convenience wrapper around write_timeseries() that accepts a DataFrame
        with a DatetimeIndex and a value column.

        Args:
            dss_file: Path to DSS file
            pathname: DSS pathname
            df: DataFrame with a timezone-naive DatetimeIndex and value column
            value_column: Name of column containing values (default "value")
            units: Data units string
            data_type: DSS data type string
            create_if_missing: Create DSS file if it doesn't exist
            dss_version: Major DSS version (6 or 7) for new-file creation.
                Omit it to preserve the current default. Existing files must
                match an explicit value.

        Example:
            >>> # Read from one DSS file, write to another
            >>> df = RasDss.read_timeseries("input.dss", pathname)
            >>> RasDss.write_timeseries_from_dataframe(
            ...     "output.dss", new_pathname, df, units="CFS"
            ... )
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(
                f"DataFrame must have DatetimeIndex, got {type(df.index).__name__}"
            )
        if value_column not in df.columns:
            raise ValueError(
                f"Column '{value_column}' not found. Available: {list(df.columns)}"
            )

        RasDss.write_timeseries(
            dss_file=dss_file,
            pathname=pathname,
            times=df.index,
            values=df[value_column].values,
            units=units,
            data_type=data_type,
            create_if_missing=create_if_missing,
            dss_version=dss_version,
        )

    # ------------------------------------------------------------------
    # Paired-data writer
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def write_paired_data(
        dss_file: Union[str, Path],
        pathname: str,
        x_values: Any,
        y_values: Any = None,
        x_units: Optional[str] = None,
        y_units: Optional[str] = None,
        x_type: Optional[str] = None,
        y_type: Optional[str] = None,
        labels: Optional[Sequence[str]] = None,
        create_if_missing: bool = True,
        *,
        x_precision: Optional[int] = None,
        y_precision: Optional[int] = None,
        value_type: str = "auto",
        dss_version: Optional[int] = None,
    ) -> None:
        """
        Write one paired-data record (rating curve, damage curve, temporal pattern,
        elevation-storage table, ...) with one or more curves.

        A new record is added; a record already at ``pathname`` is replaced whole.
        Passing the DataFrame from ``read_paired_data`` as ``x_values`` writes the same
        ordinates, curves, stored precision, labels, units, types and display precision
        (the record time zone is not written; see Backends).

        Args:
            dss_file: Path to DSS file (created if missing and create_if_missing=True)
            pathname: DSS pathname with exactly six parts, for example
                ``"/BASIN/LOC/STAGE-FLOW///RATING/"``. The C part usually names the
                two parameters. D, E and F are free text and kept as given.
            x_values: The ordinates (1-D array-like), or a DataFrame or Series indexed
                by the ordinates with one column per curve. With a DataFrame or Series,
                omit ``y_values``. ``attrs`` from ``read_paired_data`` supply any
                metadata argument left as ``None``.
            y_values: The curves: 1-D for one curve, or 2-D with shape
                ``(len(x_values), n_curves)``.
            x_units: Units of the ordinates (for example ``"FEET"``). ``None``: from
                ``attrs``, otherwise blank.
            y_units: Units of the curves. ``None``: as ``x_units``.
            x_type: Axis type of the ordinates (for example ``"LINEAR"``, ``"LOG"``,
                ``"PROB"``). ``None``: as ``x_units``.
            y_type: Axis type of the curves. ``None``: as ``x_units``.
            labels: Curve names, one per curve. ``None``: a DataFrame's string column
                names (the default ``curve_1`` .. ``curve_n`` names are not labels; then
                ``attrs["labels"]`` when it has one entry per curve), a Series' name,
                otherwise no labels.
            create_if_missing: Create the DSS file if it doesn't exist (default True).
            x_precision: Decimal places to display for the ordinates, 0-9, or -1 for
                unset. Give both precisions or neither; they must be both -1 or both
                0-9. ``None``: from ``attrs`` when usable in the target file, otherwise
                -1. Inherited precision that DSS6 cannot store is dropped: see Backends.
            y_precision: Decimal places to display for the curves, as ``x_precision``.
            value_type: ``"auto"`` (default) stores float32 (record type 200, PD) when
                both the ordinates and the curves are float32 and float64 (type 205,
                PDD) otherwise, so a frame read with ``dtype="stored"`` keeps its type.
                ``"float"`` or ``"double"`` choose.
            dss_version: Major DSS version (6 or 7) for a new file. Omit it for DSS7.
                An existing file must match an explicit value.

        Returns:
            None. As with ``write_timeseries``, a failed write raises.

        Raises:
            FileNotFoundError: If the DSS file doesn't exist and create_if_missing=False
            IsADirectoryError: If ``dss_file`` is a directory
            TypeError: If ``pathname`` or a unit, type or label is not a string
            ValueError: If ``pathname`` does not have exactly six parts; the arrays are
                not numeric, empty, or have mismatched shapes; ``labels`` does not have
                one entry per curve; a precision or ``value_type`` is invalid;
                ``dss_version`` is invalid or does not match an existing file. Under
                ``native``, also when the engine refuses the input (see Backends).
            ImportError: If pyjnius (``java``) or ras-commander-fast-dss (``native``) is
                not installed
            DssCapabilityError: ``native`` with a ras-commander-fast-dss wheel that has
                no writers (a ``NotImplementedError``)
            DssUnsupportedRecordError: ``native``, when the pathname holds a record of
                another kind, or for the ELEV cases below
            RuntimeError: If the Java write fails, or returns without the record being
                in the file. Native engine errors (``DssLockedError`` when HEC software
                has the file open, other ``DssError`` subclasses) are ``RuntimeError``
                subclasses too.

        Backends:
            ``"java"`` (default) writes ``hec.io.PairedDataContainer`` through HEC
            Monolith. ``"native"`` writes through ras-commander-fast-dss without a JVM
            and never falls back to Java: an existing file keeps its DSS version, a new
            file is DSS7 unless ``dss_version=6``. Both store ``NaN`` as stored bits, and
            DSS6 pathnames in upper case. The native writer refuses input the Java path
            accepts; the user guide lists each case: DSS6 units or types longer than 8
            characters (Java truncates them), some DSS6 labels and precisions, non-ASCII
            pathnames, infinite values, a record of another kind at the pathname, and
            two ELEV cases (a ``|`` in an elevation-side unit and, for DSS7, a location
            record holding vertical-datum information). A failed native write that
            created the file removes it. ``"shadow"`` writes with Java, repeats the write
            natively on a temporary copy and logs any difference between the native
            read-back of the two files; the comparison never raises. The ``time_zone``
            that ``read_paired_data`` reports is not written on any backend, because
            ``PairedDataContainer`` does not store it. DSS6 cannot store
            ``x_precision=0``; a value inherited from ``attrs`` becomes -1 there (the
            native reader reports 0 for some DSS6 records written without precision).
            See ``docs/user-guide/dss-native-backend.md``.

        Example:
            >>> from ras_commander import RasDss
            >>> RasDss.write_paired_data(
            ...     "rating.dss", "/BASIN/LOC/STAGE-FLOW///RATING/",
            ...     [1.0, 2.0, 3.0], [10.0, 25.0, 60.0],
            ...     x_units="FEET", y_units="CFS", x_type="LINEAR", y_type="LINEAR",
            ... )
            >>> rating = RasDss.read_paired_data("rating.dss", "/BASIN/LOC/STAGE-FLOW///RATING/")
            >>> RasDss.write_paired_data("copy.dss", "/BASIN/LOC/STAGE-FLOW///COPY/", rating)
        """
        spec = RasDss._paired_data_spec(
            pathname, x_values, y_values, x_units, y_units, x_type, y_type, labels,
            x_precision, y_precision, value_type,
        )
        dss_version = RasDss._validate_dss_version(dss_version)
        backend = RasDss._write_backend()
        if backend == "native":
            return RasDss._write_paired_data_native(
                dss_file, pathname, spec, create_if_missing, dss_version=dss_version
            )
        if backend == "shadow":
            return RasDss._write_paired_data_shadow(
                dss_file, pathname, spec, create_if_missing, dss_version=dss_version
            )
        return RasDss._write_paired_data_java(
            dss_file, pathname, spec, create_if_missing, dss_version=dss_version
        )

    @staticmethod
    def _paired_data_numeric(values: Any, what: str) -> np.ndarray:
        array = np.asarray(values)
        if array.dtype.kind not in "fiu":
            raise ValueError(f"{what} must be numeric, not {array.dtype}")
        return array

    @staticmethod
    def _paired_data_labels_from_frame(frame: pd.DataFrame) -> Optional[List[str]]:
        """Labels of a frame: its string column names, unless they are the reader's
        default ``curve_n`` names; then ``attrs["labels"]`` when it has one per curve
        (the reader falls back to default names when labels are blank or repeated)."""
        columns = list(frame.columns)
        default = [f"curve_{i + 1}" for i in range(len(columns))]
        if columns == default:
            stored = frame.attrs.get("labels")
            if isinstance(stored, (list, tuple)) and len(stored) == len(columns):
                return [str(label) for label in stored]
            return None
        if all(isinstance(column, str) for column in columns):
            return columns
        return None

    @staticmethod
    def _paired_data_spec(
        pathname, x_values, y_values, x_units, y_units, x_type, y_type, labels,
        x_precision, y_precision, value_type,
    ) -> Dict[str, Any]:
        """Check and normalize the writer's arguments, the same way for every backend.
        Runs before any JVM start or file change."""
        if not isinstance(pathname, str):
            raise TypeError(f"DSS pathname must be a string, got {type(pathname).__name__}")
        if pathname.count("/") != 7 or not pathname.startswith("/") or not pathname.endswith("/"):
            raise ValueError(f"DSS pathname must have exactly six parts: {pathname!r}")
        if value_type not in ("auto", "float", "double"):
            raise ValueError('value_type must be "auto", "float" or "double"')

        attrs: Dict[str, Any] = {}
        frame_labels = None
        if isinstance(x_values, pd.Series):
            x_values = x_values.to_frame()
        if isinstance(x_values, pd.DataFrame):
            if y_values is not None:
                raise ValueError("y_values must be omitted when x_values is a DataFrame or Series")
            attrs = dict(x_values.attrs)
            frame_labels = RasDss._paired_data_labels_from_frame(x_values)
            x = RasDss._paired_data_numeric(x_values.index.to_numpy(), "the ordinates")
            y = RasDss._paired_data_numeric(x_values.to_numpy(), "the curves")
        else:
            if y_values is None:
                raise ValueError("y_values is required unless x_values is a DataFrame or Series")
            x = RasDss._paired_data_numeric(x_values, "x_values")
            y = RasDss._paired_data_numeric(y_values, "y_values")
        if x.ndim != 1:
            raise ValueError("x_values must be one-dimensional")
        if y.ndim == 1:
            y = y.reshape(-1, 1)
        elif y.ndim != 2:
            raise ValueError("y_values must be 1-D (one curve) or 2-D (one column per curve)")
        if x.shape[0] == 0:
            raise ValueError("x_values must not be empty")
        if y.shape[0] != x.shape[0]:
            raise ValueError(
                f"y_values has {y.shape[0]} rows for {x.shape[0]} ordinates "
                "(shape must be (len(x_values), n_curves))"
            )
        n_curves = int(y.shape[1])
        if n_curves == 0:
            raise ValueError("y_values has no curves")

        if labels is None:
            labels = frame_labels
        elif isinstance(labels, (str, bytes)):
            raise ValueError("labels must be a sequence of strings, one per curve")
        if labels is not None:
            labels = list(labels)
            for index, label in enumerate(labels):
                if not isinstance(label, str):
                    raise TypeError(f"labels[{index}] must be a string, not {type(label).__name__}")
            if len(labels) != n_curves:
                raise ValueError(f"{len(labels)} labels for {n_curves} curves (give one per curve)")
            if not any(label.strip() for label in labels):
                labels = None

        text: Dict[str, str] = {}
        for key, value in (("x_units", x_units), ("y_units", y_units),
                           ("x_type", x_type), ("y_type", y_type)):
            if value is None:
                value = attrs.get(key) or ""
            if not isinstance(value, str):
                raise TypeError(f"{key} must be a string, not {type(value).__name__}")
            text[key] = value

        explicit = x_precision is not None or y_precision is not None
        if explicit and (x_precision is None or y_precision is None):
            raise ValueError("give both x_precision and y_precision, or neither")
        if explicit:
            for name, value in (("x_precision", x_precision), ("y_precision", y_precision)):
                if type(value) is not int or not -1 <= value <= 9:
                    raise ValueError(f"{name} must be an integer from -1 to 9, not {value!r}")
            if (x_precision == -1) != (y_precision == -1):
                raise ValueError("x_precision and y_precision must be both -1 or both 0-9")

        if value_type == "auto":
            single = x.dtype == np.float32 and y.dtype == np.float32
            value_type = "float" if single else "double"

        return {
            "x": x,
            "y": y,
            "n_curves": n_curves,
            "labels": labels,
            "precision": (x_precision, y_precision) if explicit else None,
            "attr_precision": (attrs.get("x_precision"), attrs.get("y_precision")),
            "value_type": value_type,
            **text,
        }

    @staticmethod
    def _paired_data_precision(spec: Dict[str, Any], version: int) -> Tuple[int, int]:
        """Display precision for a target file: explicit values as given; inherited
        ``attrs`` values when the target can store them, otherwise unset. DSS6 cannot
        store an x precision of 0, and the native reader reports 0 for some DSS6 records
        written without precision, so that value must not block copying a frame to DSS6."""
        if spec["precision"] is not None:
            return spec["precision"]
        x_precision, y_precision = spec["attr_precision"]
        usable = (
            isinstance(x_precision, (int, np.integer))
            and isinstance(y_precision, (int, np.integer))
            and 0 <= x_precision <= 9 and 0 <= y_precision <= 9
            and not (version == 6 and x_precision == 0)
        )
        return (int(x_precision), int(y_precision)) if usable else (-1, -1)

    @staticmethod
    def _write_paired_data_java(
        dss_file: Union[str, Path],
        pathname: str,
        spec: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """``write_paired_data`` through HEC Monolith (``hec.io.PairedDataContainer``)."""
        from ras_commander.RasUtils import RasUtils

        dss_path = Path(dss_file)
        file_existed = dss_path.exists()
        if file_existed and not dss_path.is_file():
            raise IsADirectoryError(f"DSS path is not a file: {dss_path}")
        if file_existed:
            RasDss._require_writable_dss_file(dss_path)
            version = RasDss._get_file_version_java(dss_path)
            if dss_version is not None and version != dss_version:
                raise ValueError(
                    f"Existing DSS file is version {version}, not "
                    f"requested version {dss_version}: {dss_path}"
                )
        else:
            if not create_if_missing:
                raise FileNotFoundError(f"DSS file not found: {dss_path}")
            dss_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"DSS file will be created: {dss_path.name}")
            logger.debug(f"DSS file creation path: {dss_path}")
            version = dss_version if dss_version is not None else RasDss._NATIVE_NEW_FILE_VERSION

        dss_file_str = str(RasUtils.safe_resolve(dss_path))
        x_precision, y_precision = RasDss._paired_data_precision(spec, version)

        RasDss._configure_jvm()

        from jnius import autoclass, cast

        HecDss = autoclass('hec.heclib.dss.HecDss')
        PairedDataContainer = autoclass('hec.io.PairedDataContainer')

        container = PairedDataContainer()
        container.setFullName(pathname)
        container.setXUnits(spec["x_units"])
        container.setYUnits(spec["y_units"])
        container.setXType(spec["x_type"])
        container.setYType(spec["y_type"])
        container.setXOrdinates(spec["x"].astype(np.float64).tolist())
        # Java holds the curves curve-major: yOrdinates[curve][ordinate].
        container.setYOrdinates(spec["y"].astype(np.float64).T.tolist())
        container.setNumberOrdinates(int(spec["x"].shape[0]))
        container.setNumberCurves(spec["n_curves"])
        container.setStoreAsDoubles(spec["value_type"] == "double")
        # -1 does not clear a precision that an earlier DSS6 write in this process set:
        # Monolith keeps it (shadow label W10).
        container.xprecision = x_precision
        container.yprecision = y_precision
        if spec["labels"] is not None:
            container.setLabels(spec["labels"])
            container.labelsUsed = True

        RasDss._drain_hec_messages()  # earlier calls' lines are not this write's
        closing_failures: List[str] = []
        dss = None
        try:
            dss = (
                HecDss.open(dss_file_str, dss_version)
                if dss_version is not None and not file_existed
                else HecDss.open(dss_file_str)
            )
            # HecDss.put has DataContainer and DataContainerTransformer overloads; without
            # the cast pyjnius can select the wrong one and nothing is written.
            dss.put(cast('hec.io.DataContainer', container))
            RasDss._raise_hec_write_failures(RasDss._drain_hec_messages())
        except Exception as e:
            raise RuntimeError(
                f"Failed to write paired data to DSS: {e}\n"
                f"  File: {dss_file_str}\n"
                f"  Pathname: {pathname}"
            ) from e
        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    closing_failures = RasDss._release_dss_file(dss_file_str)
        RasDss._raise_hec_write_failures(closing_failures, dss_file_str)
        RasDss._require_java_record_stored(dss_file_str, pathname)
        logger.info(
            f"Wrote {spec['n_curves']} curve(s) of {spec['x'].shape[0]} ordinates "
            f"to {Path(dss_file_str).name}"
        )

    @staticmethod
    def _write_paired_data_native(
        dss_file: Union[str, Path],
        pathname: str,
        spec: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """``write_paired_data`` through ras-commander-fast-dss (no JVM).

        Same argument checks as the Java path. ``NaN`` keeps its stored bits on both DSS
        versions (``raw=True``), as Monolith stores it; infinite values are refused.
        """
        for name, values in (("x_values", spec["x"]), ("y_values", spec["y"])):
            if values.dtype.kind == "f" and np.isinf(values).any():
                raise ValueError(
                    f"{name} contain infinity; HEC-DSS has no infinity convention "
                    "(the native writer refuses it; the Java path stores the bits)"
                )
        dc = _backend.require_native_writes()
        target, version, existed, created_dirs = RasDss._native_write_target(
            dss_file, dss_version, create_if_missing
        )
        x_precision, y_precision = RasDss._paired_data_precision(spec, version)
        with RasDss._native_new_file(dc, target, version, existed, created_dirs):
            report = dc.write_paired_data(
                str(target), pathname, spec["x"], spec["y"],
                x_units=spec["x_units"], x_type=spec["x_type"],
                y_units=spec["y_units"], y_type=spec["y_type"],
                labels=spec["labels"], value_type=spec["value_type"], raw=True,
                x_precision=x_precision, y_precision=y_precision, version=version,
            )
        logger.info(
            f"Wrote {spec['n_curves']} curve(s) of {spec['x'].shape[0]} ordinates to {target.name}"
        )
        logger.debug(
            f"DSS native write details: file={target}, pathname={pathname}, version={version}, "
            f"blocks={report.get('blocks')}"
        )

    @staticmethod
    def _write_paired_data_shadow(
        dss_file: Union[str, Path],
        pathname: str,
        spec: Dict[str, Any],
        create_if_missing: bool = True,
        *,
        dss_version: Optional[int] = None,
    ) -> None:
        """Java write (its result and errors are returned); the native writer repeats
        the write on a temporary copy and the native read-backs of both files are
        compared and logged. The comparison never raises."""
        import time

        ctx = RasDss._shadow_write_snapshot(dss_file)
        try:
            t0 = time.perf_counter()
            RasDss._write_paired_data_java(
                dss_file, pathname, spec, create_if_missing, dss_version=dss_version
            )
            java_s = time.perf_counter() - t0
            try:
                RasDss._shadow_compare_paired_data_write(ctx, dss_file, pathname, spec, java_s)
            except Exception as exc:  # the comparison must never break the write
                logger.warning("DSS shadow write_paired_data comparison failed for %s: %s",
                               dss_file, exc)
        finally:
            RasDss._shadow_write_cleanup(ctx)

    @staticmethod
    def _shadow_compare_paired_data_write(
        ctx: Dict[str, Any], dss_file, pathname, spec, java_s
    ) -> None:
        import time

        if ctx.get("skip"):
            _backend.record("write_paired_data", "skipped", ctx["skip"], dss_file=dss_file,
                            pathname=pathname, java_seconds=java_s)
            return
        version = RasDss._get_file_version_native(dss_file)
        native_exc, diffs, labels = None, [], []
        t1 = time.perf_counter()
        try:
            RasDss._write_paired_data_native(
                ctx["copy"], pathname, spec, True,
                dss_version=None if ctx["existed"] else version,
            )
        except Exception as exc:
            native_exc = exc
        native_s = time.perf_counter() - t1
        if native_exc is None:
            readback = pathname.upper() if version == 6 else pathname
            java_df = RasDss._read_paired_data_native(dss_file, readback, False)
            native_df = RasDss._read_paired_data_native(ctx["copy"], readback, False)
            diffs, labels = _backend.compare_written_paired_data(java_df, native_df)
        RasDss._shadow_write_record(
            "write_paired_data", dss_file, pathname, native_exc, diffs, labels, java_s, native_s,
            detail={"dss_version": version},
        )

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        """Return whether an existing path is a symlink/junction/reparse point."""
        if not os.path.lexists(path):
            return False
        try:
            path_stat = os.lstat(path)
        except OSError as exc:
            raise OSError(f"Could not safely inspect output path: {path}") from exc
        file_attributes = int(getattr(path_stat, "st_file_attributes", 0))
        if file_attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            return True
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())

    @staticmethod
    def _normalize_finite_real(value: Real, label: str) -> float:
        """Normalize one accepted Real scalar to a finite float."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{label} must be a finite number")
        try:
            normalized = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} must be a finite number") from exc
        if not isfinite(normalized):
            raise ValueError(f"{label} must be a finite number")
        return normalized

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Return a streaming SHA-256 digest without materializing the file."""
        digest = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_java_int32(value: int, label: str) -> None:
        """Reject values that cannot be passed safely to a Java int."""
        if value < -(2**31) or value > 2**31 - 1:
            raise ValueError(f"Translated {label} exceeds Java int32 bounds: {value}")

    @staticmethod
    def _translated_grid_boundaries(
        source_boundaries: List[pd.Timestamp],
        interval: pd.Timedelta,
        time_shift_minutes: int,
        tail_intervals: int,
    ) -> List[pd.Timestamp]:
        """Translate source boundaries and append tail boundaries safely."""
        try:
            shift = pd.Timedelta(minutes=time_shift_minutes)
            translated = [pd.Timestamp(value) + shift for value in source_boundaries]
            boundary = translated[-1]
            for _ in range(tail_intervals):
                boundary = boundary + interval
                translated.append(boundary)
        except Exception as exc:
            raise ValueError(
                "Time shift or zero-tail extension exceeds supported datetime bounds"
            ) from exc
        return translated

    @staticmethod
    def _format_native_grid_end_datetime(value: pd.Timestamp) -> str:
        """Format a grid-window end using native HEC-DSS midnight spelling."""
        timestamp = pd.Timestamp(value)
        if timestamp == timestamp.normalize():
            try:
                previous_day = timestamp - pd.Timedelta(days=1)
            except Exception as exc:
                raise ValueError(
                    "Grid end time cannot be represented with native 2400 syntax"
                ) from exc
            return previous_day.strftime("%d%b%Y:2400").upper()
        return RasDss._format_grid_dss_datetime(timestamp)

    @staticmethod
    def _expected_native_grid_pathnames(
        pathname: str,
        boundaries: List[pd.Timestamp],
    ) -> List[str]:
        """Build exact pathnames as stored by native HEC-DSS grid catalogs."""
        _, parts = RasDss._split_dss_pathname(pathname)
        expected = []
        for start, end in zip(boundaries, boundaries[1:]):
            record_parts = list(parts)
            record_parts[3] = RasDss._format_grid_dss_datetime(start)
            record_parts[4] = RasDss._format_native_grid_end_datetime(end)
            expected.append(RasDss._build_dss_pathname("/", record_parts))
        return expected

    @staticmethod
    def _validate_grid_writer_return(
        returned: Any,
        pathname: str,
        expected_start: pd.Timestamp,
        expected_end: pd.Timestamp,
    ) -> str:
        """Require one exact-family writer result with the expected time window."""
        if not isinstance(returned, list) or len(returned) != 1:
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            )
        returned_pathname = returned[0]
        try:
            prefix, returned_parts = RasDss._split_dss_pathname(returned_pathname)
            _, family_parts = RasDss._split_dss_pathname(pathname)
            start = RasDss._parse_strict_grid_dss_datetime(returned_parts[3])
            end = RasDss._parse_strict_grid_dss_datetime(returned_parts[4])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            ) from exc
        if (
            prefix != "/"
            or tuple(returned_parts[index] for index in (0, 1, 2, 5))
            != tuple(family_parts[index] for index in (0, 1, 2, 5))
            or start != pd.Timestamp(expected_start)
            or end != pd.Timestamp(expected_end)
        ):
            raise RuntimeError(
                "Grid derivative writer returned an unexpected ordered pathname: "
                f"{returned}"
            )
        return returned_pathname

    @staticmethod
    def _grid_value_digest(data: np.ndarray) -> str:
        """Hash float32 grid values with canonical NaN and signed-zero bits."""
        normalized = np.array(data, dtype="<f4", order="C", copy=True)
        if normalized.ndim != 2:
            raise ValueError("Grid data digest requires a two-dimensional frame")
        nan_mask = ~np.isfinite(normalized)
        zero_mask = normalized == np.float32(0.0)
        bits = normalized.view("<u4")
        bits[nan_mask] = np.uint32(0x7FC00000)
        bits[zero_mask] = np.uint32(0)
        return sha256(bits.tobytes(order="C")).hexdigest()

    @staticmethod
    def _validate_grid_family_selector(
        pathname: str,
        label: str,
    ) -> Tuple[str, List[str]]:
        """Validate an exact A/B/C/F grid-family selector."""
        prefix, parts = RasDss._split_dss_pathname(pathname)
        if parts[3] or parts[4]:
            raise ValueError(
                f"{label} must select a grid family with blank D and E parts"
            )
        if any("*" in part or "?" in part for part in parts):
            raise ValueError(f"{label} must not contain wildcard characters")
        return prefix, parts

    @staticmethod
    def _select_grid_family_records(
        catalog: pd.DataFrame,
        pathname: str,
        selector_parts: List[str],
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, str]]:
        """Return one validated, ordered grid family from a DSS catalog."""
        if not isinstance(catalog, pd.DataFrame) or "pathname" not in catalog:
            raise ValueError("DSS catalog must contain a pathname column")

        selector_key = tuple(
            selector_parts[index].casefold() for index in (0, 1, 2, 5)
        )
        family_variants = set()
        records: List[Tuple[pd.Timestamp, pd.Timestamp, str]] = []
        for candidate in catalog["pathname"].astype(str):
            try:
                _, candidate_parts = RasDss._split_dss_pathname(candidate)
            except ValueError:
                continue
            candidate_key = tuple(
                candidate_parts[index].casefold() for index in (0, 1, 2, 5)
            )
            if candidate_key != selector_key:
                continue

            family_variants.add(
                tuple(candidate_parts[index] for index in (0, 1, 2, 5))
            )
            start = RasDss._parse_strict_grid_dss_datetime(candidate_parts[3])
            end = RasDss._parse_strict_grid_dss_datetime(candidate_parts[4])
            if start is None or end is None or end <= start:
                raise ValueError(
                    f"Grid record has an invalid time window: {candidate}"
                )
            records.append((start, end, candidate))

        if not records:
            raise ValueError(
                f"No grid records matched pathname family {pathname}"
            )
        if len(family_variants) != 1:
            raise ValueError(
                "Grid family selector is ambiguous across case-distinct "
                f"A/B/C/F parts: {sorted(family_variants)}"
            )

        records.sort(key=lambda item: (item[0], item[1], item[2]))
        windows = [(start, end) for start, end, _ in records]
        if len(set(windows)) != len(windows):
            raise ValueError(
                "Grid family selector is ambiguous because multiple records "
                "use the same time window"
            )

        intervals = {end - start for start, end, _ in records}
        if len(intervals) != 1:
            raise ValueError("Matched grid records do not use one uniform interval")
        for previous, current in zip(records, records[1:]):
            if current[0] != previous[1]:
                raise ValueError(
                    "Matched grid records are not contiguous: "
                    f"{previous[2]} then {current[2]}"
                )
        return records

    @staticmethod
    def _grid_record_metadata_signature(grid: Dict[str, Any]) -> Dict[str, Any]:
        """Return all available write-relevant metadata for comparison."""
        metadata = grid.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Grid record is missing metadata")
        if metadata.get("lower_left_cell") is None:
            raise ValueError("Grid record is missing lower-left cell metadata")
        compression = metadata.get("compression")
        if not isinstance(compression, dict):
            raise ValueError("Grid record is missing compression metadata")

        return {
            "shape": tuple(grid.get("shape", ())),
            "metadata_shape": tuple(metadata.get("shape", ())),
            "number_of_cells": (
                metadata.get("number_of_cells_x"),
                metadata.get("number_of_cells_y"),
            ),
            "cell_size": grid.get("cell_size"),
            "lower_left_cell": tuple(metadata["lower_left_cell"]),
            "origin": metadata.get("origin"),
            "grid_type": grid.get("grid_type"),
            "grid_class": metadata.get("grid_class"),
            "grid_type_code": metadata.get("grid_type_code"),
            "crs": grid.get("crs"),
            "units": grid.get("units"),
            "data_type": grid.get("data_type"),
            "data_type_code": metadata.get("data_type_code"),
            "nodata_value": metadata.get("nodata_value"),
            "projection": metadata.get("projection"),
            # element_size is the compressed payload length and legitimately
            # varies by record. Method/base/scale are the write configuration.
            "compression": {
                key: compression.get(key)
                for key in ("method", "base", "scale_factor")
            },
        }

    @staticmethod
    def _validate_grid_family_metadata(
        grids: List[Dict[str, Any]],
        records: List[Tuple[pd.Timestamp, pd.Timestamp, str]],
    ) -> np.ndarray:
        """Validate family metadata and return its stable NoData footprint."""
        if len(grids) != len(records) or not grids:
            raise ValueError("Grid family records could not be read completely")
        reference_signature = None
        reference_mask = None
        for grid, record in zip(grids, records):
            signature, mask = RasDss._validate_grid_record_metadata(
                grid,
                record,
                reference_signature,
                reference_mask,
            )
            if reference_signature is None:
                reference_signature = signature
                reference_mask = mask
        if reference_mask is None:
            raise ValueError("Grid family records could not be read completely")
        return reference_mask

    @staticmethod
    def _validate_grid_record_metadata(
        grid: Dict[str, Any],
        record: Tuple[pd.Timestamp, pd.Timestamp, str],
        reference_signature: Optional[Dict[str, Any]],
        reference_mask: Optional[np.ndarray],
    ) -> Tuple[Dict[str, Any], np.ndarray]:
        """Validate one streamed grid record against a compact reference."""
        start, end, record_path = record
        RasDss._validate_grid_raw_timing(grid, start, end, record_path)
        signature = RasDss._grid_record_metadata_signature(grid)
        data = np.asarray(grid.get("data"), dtype=np.float32)
        if data.ndim != 2 or data.shape != tuple(signature["shape"]):
            raise ValueError(
                f"Grid record data shape does not match its metadata: {record_path}"
            )
        if tuple(signature["metadata_shape"]) != data.shape:
            raise ValueError(
                f"Grid record metadata shape does not match its data: {record_path}"
            )
        expected_cells = (data.shape[1], data.shape[0])
        if tuple(signature["number_of_cells"]) != expected_cells:
            raise ValueError(
                f"Grid record cell counts do not match its data: {record_path}"
            )

        nodata = ~np.isfinite(data)
        reported_missing = grid["metadata"].get("number_missing")
        if reported_missing is None or int(reported_missing) != int(nodata.sum()):
            raise ValueError(
                f"Grid record NoData count disagrees with its data: {record_path}"
            )

        if reference_signature is None:
            cell_size = signature["cell_size"]
            if (
                isinstance(cell_size, bool)
                or not isinstance(cell_size, Real)
                or not isfinite(float(cell_size))
                or float(cell_size) <= 0
            ):
                raise ValueError(f"Grid family has invalid cell size: {cell_size}")
            if signature["grid_type"] not in {"albers", "specified"}:
                raise ValueError(
                    "Grid family uses an unsupported metadata class for safe "
                    f"rewrite: {signature['grid_class']}"
                )
            if signature["origin"] is None:
                raise ValueError("Grid family is missing a physical grid origin")
            return signature, nodata.copy()

        mismatched = [
            name
            for name, value in signature.items()
            if value != reference_signature[name]
        ]
        if mismatched:
            raise ValueError(
                "Matched grid records have inconsistent write metadata "
                f"({', '.join(mismatched)}): {record_path}"
            )
        if reference_mask is None or not np.array_equal(nodata, reference_mask):
            raise ValueError(
                "Matched grid records do not share one stable NoData footprint: "
                f"{record_path}"
            )
        return signature, nodata

    @staticmethod
    def _validate_grid_raw_timing(
        grid: Dict[str, Any],
        expected_start: pd.Timestamp,
        expected_end: pd.Timestamp,
        record_path: str,
    ) -> None:
        """Require independent raw and normalized timing to match a pathname."""
        metadata = grid.get("metadata")
        timing = metadata.get("timing") if isinstance(metadata, dict) else None
        if not isinstance(timing, dict):
            raise ValueError(
                f"Grid record is missing raw timing metadata: {record_path}"
            )
        raw_start = RasDss._parse_grid_raw_datetime(timing.get("start"))
        raw_end = RasDss._parse_grid_raw_datetime(timing.get("end"))
        if raw_start is None or raw_end is None:
            raise ValueError(
                f"Grid record has missing or invalid raw timing metadata: {record_path}"
            )
        if raw_start != expected_start or raw_end != expected_end:
            raise ValueError(
                "Grid record raw timing metadata disagrees with its pathname: "
                f"{record_path}"
            )
        top_start = grid.get("start_time")
        top_end = grid.get("end_time")
        if (
            top_start is None
            or top_end is None
            or pd.Timestamp(top_start) != expected_start
            or pd.Timestamp(top_end) != expected_end
        ):
            raise ValueError(
                "Grid record normalized timing disagrees with its pathname: "
                f"{record_path}"
            )

    @staticmethod
    def _parse_grid_raw_datetime(value: Any) -> Optional[pd.Timestamp]:
        """Parse only the exact pathname or Java raw grid time spellings."""
        parsed = RasDss._parse_strict_grid_dss_datetime(value)
        if parsed is not None:
            return parsed
        if not isinstance(value, str):
            return None
        match = re.fullmatch(
            r"(\d{1,2}) "
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December) "
            r"(\d{4}), (\d{2}):(\d{2})",
            value,
        )
        if match is None:
            return None
        day_text, month_text, year_text, hour_text, minute_text = match.groups()
        months = {
            "January": 1,
            "February": 2,
            "March": 3,
            "April": 4,
            "May": 5,
            "June": 6,
            "July": 7,
            "August": 8,
            "September": 9,
            "October": 10,
            "November": 11,
            "December": 12,
        }
        hour = int(hour_text)
        minute = int(minute_text)
        if hour == 24:
            if minute != 0:
                return None
            hour = 0
            day_offset = 1
        elif 0 <= hour <= 23 and 0 <= minute <= 59:
            day_offset = 0
        else:
            return None
        try:
            parsed_datetime = datetime(
                int(year_text),
                months[month_text],
                int(day_text),
                hour,
                minute,
            ) + timedelta(days=day_offset)
            return pd.Timestamp(parsed_datetime)
        except (OverflowError, ValueError):
            return None

    @staticmethod
    def _whole_grid_cell_shift(
        shift: float,
        cell_size: float,
        label: str,
    ) -> int:
        """Return an exact whole-cell quotient for a spatial translation."""
        try:
            quotient = Decimal(str(shift)) / Decimal(str(cell_size))
        except (InvalidOperation, ZeroDivisionError) as exc:
            raise ValueError(f"{label} cannot be resolved in grid cells") from exc
        integral = quotient.to_integral_value()
        if quotient != integral:
            raise ValueError(f"{label} must be an exact whole grid-cell increment")
        return int(integral)

    @staticmethod
    def _grid_write_info_from_record(
        grid: Dict[str, Any],
        output_lower_left: Tuple[int, int],
    ) -> Dict[str, Any]:
        """Map one validated read-grid result back to writer metadata."""
        metadata = grid["metadata"]
        projection = dict(metadata.get("projection") or {})
        compression = dict(metadata.get("compression") or {})
        required_compression = {"method", "base", "scale_factor"}
        missing_compression = sorted(required_compression - compression.keys())
        if missing_compression:
            raise ValueError(
                "Grid record is missing compression fields required for rewrite: "
                f"{missing_compression}"
            )
        required_projection = {
            "x_coord_cell_zero",
            "y_coord_cell_zero",
        }
        if grid["grid_type"] == "albers":
            required_projection.update(
                {
                    "datum_code",
                    "units",
                    "standard_parallel_1",
                    "standard_parallel_2",
                    "central_meridian",
                    "latitude_of_origin",
                    "false_easting",
                    "false_northing",
                }
            )
        missing_projection = sorted(required_projection - projection.keys())
        if missing_projection:
            raise ValueError(
                "Grid record is missing projection fields required for rewrite: "
                f"{missing_projection}"
            )
        grid_info = {
            "cell_size": float(grid["cell_size"]),
            "lower_left_cell_x": int(output_lower_left[0]),
            "lower_left_cell_y": int(output_lower_left[1]),
            "crs": grid["crs"],
            "grid_type": grid["grid_type"],
            "units": grid["units"],
            "data_type": grid["data_type"],
            "nodata_value": metadata.get("nodata_value"),
            "compression": compression.get("method"),
            "compression_element_size": 0,
            # The Java setter's final two positional values are exposed in the
            # opposite order by getCompressionBase()/getCompressionScaleFactor().
            "compression_base": compression.get("scale_factor", 0.0),
            "compression_scale_factor": compression.get("base", 100.0),
        }
        if grid["grid_type"] in {"albers", "specified"}:
            grid_info.update(
                {
                    "x_coord_cell_zero": projection.get(
                        "x_coord_cell_zero",
                        0.0,
                    ),
                    "y_coord_cell_zero": projection.get(
                        "y_coord_cell_zero",
                        0.0,
                    ),
                }
            )
        if grid["grid_type"] == "albers":
            grid_info.update(
                {
                    "projection_datum": projection.get("datum_code"),
                    "projection_units": projection.get("units"),
                    "standard_parallel_1": projection.get("standard_parallel_1"),
                    "standard_parallel_2": projection.get("standard_parallel_2"),
                    "central_meridian": projection.get("central_meridian"),
                    "latitude_of_origin": projection.get("latitude_of_origin"),
                    "false_easting": projection.get("false_easting"),
                    "false_northing": projection.get("false_northing"),
                }
            )
        return grid_info

    @staticmethod
    def _create_empty_dss(dss_file: Path, dss_version: int) -> None:
        """Create an empty DSS file at an explicit major version."""
        if dss_file.exists():
            raise FileExistsError(f"Temporary DSS path already exists: {dss_file}")
        if dss_version not in (6, 7):
            raise ValueError(f"Unsupported DSS version: {dss_version}")

        RasDss._configure_jvm()

        from jnius import autoclass

        from ras_commander.RasUtils import RasUtils

        HecDss = autoclass("hec.heclib.dss.HecDss")
        resolved_path = str(RasUtils.safe_resolve(dss_file))
        dss = None
        try:
            dss = HecDss.open(resolved_path, dss_version)
            if dss is None:
                raise RuntimeError(
                    f"HEC-DSS did not create version {dss_version}: {dss_file}"
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"HEC-DSS could not create version {dss_version} file {dss_file}: {e}"
            ) from e
        finally:
            if dss is not None:
                try:
                    dss.done()
                finally:
                    RasDss._release_dss_file(resolved_path)
        if not dss_file.is_file():
            raise RuntimeError(
                f"HEC-DSS did not create temporary file: {dss_file}"
            )

    @staticmethod
    def _close_dss_file(dss_file: Path) -> None:
        """Release native DSS handles associated with one resolved path."""
        RasDss._configure_jvm()

        from jnius import autoclass

        from ras_commander.RasUtils import RasUtils

        GriddedData = autoclass("hec.heclib.grid.GriddedData")
        GriddedData.close(str(RasUtils.safe_resolve(dss_file)), True)

    @staticmethod
    def _best_effort_close_dss_file(dss_file: Path, phase: str) -> None:
        """Path-close one DSS without masking a phase's primary exception."""
        try:
            RasDss._close_dss_file(dss_file)
        except Exception as exc:
            logger.warning(
                "Could not close DSS %s %s (%s)",
                dss_file,
                phase,
                exc,
            )

    @staticmethod
    def _cleanup_temporary_dss(dss_file: Path) -> None:
        """Best-effort close and removal that never masks a primary error."""
        try:
            if dss_file.exists():
                RasDss._close_dss_file(dss_file)
        except Exception as exc:
            logger.warning(
                "Could not close temporary DSS during cleanup: %s (%s)",
                dss_file,
                exc,
            )
        try:
            dss_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(
                "Could not remove temporary DSS during cleanup: %s (%s)",
                dss_file,
                exc,
            )

    @staticmethod
    def _split_dss_pathname(pathname: str) -> Tuple[str, List[str]]:
        """Return DSS pathname prefix and six A-F parts."""
        if (
            not isinstance(pathname, str)
            or not pathname.startswith("/")
            or not pathname.endswith("/")
        ):
            raise ValueError(f"DSS pathname must start and end with '/': {pathname}")

        prefix = "//" if pathname.startswith("//") else "/"
        parts = pathname.split("/")
        path_parts = parts[2:-1] if prefix == "//" else parts[1:-1]
        if len(path_parts) != 6:
            raise ValueError(
                "DSS pathname must have 6 parts (/A/B/C/D/E/F/), "
                f"got {len(path_parts)}: {pathname}"
            )
        return prefix, path_parts

    @staticmethod
    def _build_dss_pathname(prefix: str, parts: List[str]) -> str:
        """Build a DSS pathname from a prefix and A-F parts."""
        if len(parts) != 6:
            raise ValueError(f"Expected 6 DSS pathname parts, got {len(parts)}")
        if prefix == "//":
            return f"//{'/'.join(parts)}/"
        return f"/{'/'.join(parts)}/"

    @staticmethod
    def _format_grid_dss_datetime(value: pd.Timestamp) -> str:
        """Format datetime for DSS grid D/E pathname parts."""
        return pd.Timestamp(value).strftime("%d%b%Y:%H%M").upper()

    @staticmethod
    def _parse_grid_dss_datetime(value: str) -> Optional[pd.Timestamp]:
        """Parse a DSS grid D/E datetime part, returning None when blank."""
        if not value:
            return None
        if value.endswith(":2400"):
            day = pd.Timestamp(pd.to_datetime(value[:-5], format="%d%b%Y"))
            return day + pd.Timedelta(days=1)
        try:
            return pd.Timestamp(pd.to_datetime(value, format="%d%b%Y:%H%M"))
        except ValueError:
            try:
                return pd.Timestamp(pd.to_datetime(value.replace(":", " ")))
            except Exception:
                return None

    @staticmethod
    def _parse_strict_grid_dss_datetime(value: str) -> Optional[pd.Timestamp]:
        """Parse exact minute-granularity DSS grid time with a 2400 exception."""
        if not isinstance(value, str) or not value:
            return None
        match = re.fullmatch(
            r"(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
            r"(\d{4}):(\d{2})(\d{2})",
            value,
        )
        if match is None:
            return None
        day_text, month_text, year_text, hour_text, minute_text = match.groups()
        months = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }
        hour = int(hour_text)
        minute = int(minute_text)
        if hour == 24:
            if minute != 0:
                return None
            hour = 0
            day_offset = 1
        elif 0 <= hour <= 23 and 0 <= minute <= 59:
            day_offset = 0
        else:
            return None
        try:
            parsed = datetime(
                int(year_text),
                months[month_text],
                int(day_text),
                hour,
                minute,
            ) + timedelta(days=day_offset)
            return pd.Timestamp(parsed)
        except (OverflowError, ValueError):
            return None

    @staticmethod
    def _split_grid_datetime_part(value: str) -> Tuple[str, str]:
        """Split a DSS grid datetime part into HecTime date and time strings."""
        if ":" not in value:
            raise ValueError(f"Grid datetime part must contain ':': {value}")
        date_part, time_part = value.split(":", 1)
        return date_part, time_part

    @staticmethod
    def _grid_data_type_code(data_type: str) -> int:
        """Return HEC grid data type code for a DSS data type string."""
        data_type_codes = {
            "PER-AVER": 0,
            "PER-CUM": 1,
            "INST-VAL": 2,
            "INST-CUM": 3,
            "FREQ": 4,
            "PER-MIN": 6,
            "PER-MAX": 7,
        }
        normalized = str(data_type).upper().replace("_", "-")
        if normalized not in data_type_codes:
            raise ValueError(
                f"Unsupported grid data_type '{data_type}'. "
                f"Valid values: {sorted(data_type_codes)}"
            )
        return data_type_codes[normalized]

    @staticmethod
    def _reject_timezone_aware_times(
        times: Union[List, np.ndarray, pd.DatetimeIndex],
    ) -> None:
        """Reject timestamps whose model-clock representation is ambiguous.

        HEC-DSS records store calendar-clock values without timezone metadata.
        Silently converting aware timestamps would choose a model clock on the
        caller's behalf, so writers require callers to convert to the intended
        clock and remove timezone metadata explicitly.
        """
        if isinstance(times, pd.DatetimeIndex):
            if times.tz is not None:
                raise ValueError(
                    "times must be timezone-naive; explicitly convert to the "
                    "intended HEC-RAS model clock and remove timezone metadata "
                    "before writing"
                )
            return

        if (
            isinstance(times, np.ndarray)
            and np.issubdtype(times.dtype, np.datetime64)
        ):
            return

        values = [times] if isinstance(times, (str, bytes)) else list(times)
        for value in values:
            parsed = value
            if isinstance(value, str):
                try:
                    parsed = pd.Timestamp(value)
                except (TypeError, ValueError, OverflowError):
                    continue
            if getattr(parsed, "tzinfo", None) is not None or getattr(
                parsed,
                "tz",
                None,
            ) is not None:
                raise ValueError(
                    "times must be timezone-naive; explicitly convert to the "
                    "intended HEC-RAS model clock and remove timezone metadata "
                    "before writing"
                )

    @staticmethod
    def _grid_time_windows(
        times: Union[List, np.ndarray, pd.DatetimeIndex],
        n_times: int,
        data_type_code: int,
        grid_info: Dict[str, Any],
        pathname_parts: List[str],
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
        """Convert user times into per-grid start/end windows."""
        RasDss._reject_timezone_aware_times(times)
        dt_index = pd.DatetimeIndex(pd.to_datetime(times))

        if len(dt_index) == n_times + 1:
            return [
                (pd.Timestamp(dt_index[i]), pd.Timestamp(dt_index[i + 1]))
                for i in range(n_times)
            ]

        if len(dt_index) != n_times:
            raise ValueError(
                "times must contain n_times end times or n_times + 1 boundary "
                f"times; got {len(dt_index)} times for {n_times} grid frames"
            )

        end_times = [pd.Timestamp(value) for value in dt_index]
        if data_type_code in (2, 3):  # INST-VAL or INST-CUM
            return [(value, value) for value in end_times]

        interval_minutes = grid_info.get("interval_minutes")
        if interval_minutes is None and len(end_times) > 1:
            deltas = np.diff(np.array(end_times, dtype="datetime64[m]")).astype(int)
            positive_deltas = deltas[deltas > 0]
            if len(positive_deltas):
                interval_minutes = int(np.median(positive_deltas))

        if interval_minutes is None:
            pathname_start = RasDss._parse_grid_dss_datetime(pathname_parts[3])
            pathname_end = RasDss._parse_grid_dss_datetime(pathname_parts[4])
            if pathname_start is not None and pathname_end is not None:
                delta = pathname_end - pathname_start
                interval_minutes = int(delta.total_seconds() // 60)

        if interval_minutes is None:
            interval_minutes = 60

        interval = pd.Timedelta(minutes=int(interval_minutes))
        if interval <= pd.Timedelta(0):
            raise ValueError(
                f"Grid interval must be positive, got {interval_minutes} minutes"
            )

        return [(value - interval, value) for value in end_times]

    @staticmethod
    def _grid_info_number(
        grid_info: Dict[str, Any],
        keys: List[str],
        default: Any = None,
    ) -> Any:
        """Return first present grid_info numeric value."""
        for key in keys:
            if key in grid_info and grid_info[key] is not None:
                return grid_info[key]
        return default

    @staticmethod
    def _grid_origin_xy(
        grid_info: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float]]:
        """Extract optional physical lower-left origin from grid_info."""
        if "origin" not in grid_info or grid_info["origin"] is None:
            return (
                grid_info.get("origin_x"),
                grid_info.get("origin_y"),
            )

        origin = grid_info["origin"]
        if isinstance(origin, dict):
            return (
                origin.get("x", origin.get("origin_x")),
                origin.get("y", origin.get("origin_y")),
            )
        if isinstance(origin, (list, tuple)) and len(origin) >= 2:
            return origin[0], origin[1]
        raise ValueError("grid_info['origin'] must be (x, y) or a dict with x/y")

    @staticmethod
    def _hec_projection_datum(GridInfo: Any, datum: Any) -> int:
        """Normalize projection datum to a HEC GridInfo datum code."""
        if isinstance(datum, int):
            return datum
        datum_text = str(datum or "NAD83").upper().replace("_", "")
        if datum_text == "NAD27":
            return GridInfo.getNad27()
        if datum_text == "UNDEFINED":
            return GridInfo.getUndefinedProjectionDatum()
        return GridInfo.getNad83()

    @staticmethod
    def _create_java_grid_info(
        grid_info: Dict[str, Any],
        n_rows: int,
        n_cols: int,
        start_part: str,
        end_part: str,
        data_type_code: int,
        GridInfo: Any,
        AlbersInfo: Any,
        SpecifiedGridInfo: Any,
        HrapInfo: Any,
    ) -> Any:
        """Create and populate the Java GridInfo subclass for one record."""
        cell_size = RasDss._grid_info_number(
            grid_info,
            ["cellsize", "cell_size", "cell_size_m", "dx", "resolution"],
        )
        if cell_size is None:
            raise ValueError("grid_info must include cellsize or cell_size")
        cell_size = float(cell_size)
        if cell_size <= 0:
            raise ValueError(f"cellsize must be positive, got {cell_size}")

        x_cell_zero = float(
            RasDss._grid_info_number(
                grid_info,
                ["x_coord_cell_zero", "x_coord_of_grid_cell_zero", "x_cell_zero"],
                0.0,
            )
        )
        y_cell_zero = float(
            RasDss._grid_info_number(
                grid_info,
                ["y_coord_cell_zero", "y_coord_of_grid_cell_zero", "y_cell_zero"],
                0.0,
            )
        )

        origin_x, origin_y = RasDss._grid_origin_xy(grid_info)
        lower_left_cell_x = RasDss._grid_info_number(
            grid_info,
            ["lower_left_cell_x", "lowerLeftCellX", "ll_cell_x"],
        )
        lower_left_cell_y = RasDss._grid_info_number(
            grid_info,
            ["lower_left_cell_y", "lowerLeftCellY", "ll_cell_y"],
        )
        if lower_left_cell_x is None:
            if origin_x is None:
                lower_left_cell_x = 0
            else:
                lower_left_cell_x = int(
                    round((float(origin_x) - x_cell_zero) / cell_size)
                )
        if lower_left_cell_y is None:
            if origin_y is None:
                lower_left_cell_y = 0
            else:
                lower_left_cell_y = int(
                    round((float(origin_y) - y_cell_zero) / cell_size)
                )

        crs = str(grid_info.get("crs", "SHG"))
        grid_type = str(grid_info.get("grid_type", "")).lower()
        crs_upper = crs.upper()
        if not grid_type:
            if crs_upper in {"SHG", "EPSG:5070", "5070"} or "ALBERS" in crs_upper:
                grid_type = "albers"
            else:
                grid_type = "specified"

        if grid_type == "hrap":
            java_grid_info = HrapInfo()
            data_source = grid_info.get("data_source")
            if data_source:
                java_grid_info.setDataSource(str(data_source))
        elif grid_type == "specified":
            java_grid_info = SpecifiedGridInfo()
            java_grid_info.setSpatialReference(
                str(grid_info.get("crs_name", "Specified Grid")),
                crs,
                x_cell_zero,
                y_cell_zero,
            )
        else:
            java_grid_info = AlbersInfo()
            java_grid_info.setProjectionInfo(
                RasDss._hec_projection_datum(
                    GridInfo,
                    grid_info.get("projection_datum", "NAD83"),
                ),
                str(grid_info.get("projection_units", "METERS")),
                float(grid_info.get("standard_parallel_1", 29.5)),
                float(grid_info.get("standard_parallel_2", 45.5)),
                float(grid_info.get("central_meridian", -96.0)),
                float(grid_info.get("latitude_of_origin", 23.0)),
                float(grid_info.get("false_easting", 0.0)),
                float(grid_info.get("false_northing", 0.0)),
                x_cell_zero,
                y_cell_zero,
            )

        java_grid_info.setCellInfo(
            int(lower_left_cell_x),
            int(lower_left_cell_y),
            int(n_cols),
            int(n_rows),
            cell_size,
        )
        java_grid_info.setParameterInfo(str(grid_info.get("units", "mm")), data_type_code)
        java_grid_info.setGridTimes(start_part, end_part)

        compression = grid_info.get("compression", "PRECIP_2_BYTE")
        if compression is not None:
            if isinstance(compression, int):
                compression_method = compression
            else:
                compression_text = str(compression).upper().replace("-", "_")
                if compression_text in {"PRECIP", "PRECIP2BYTE", "PRECIP_2_BYTE"}:
                    compression_method = GridInfo.getPrecip2Byte()
                elif compression_text in {"ZLIB", "ZLIB_DEFLATE"}:
                    compression_method = GridInfo.getZlibDeflate()
                elif compression_text in {"NONE", "UNDEFINED"}:
                    compression_method = GridInfo.getUndefinedCompressionMethod()
                else:
                    raise ValueError(f"Unsupported grid compression: {compression}")
            java_grid_info.setCompressionInfo(
                int(compression_method),
                int(grid_info.get("compression_element_size", 0)),
                float(grid_info.get("compression_base", 0.0)),
                float(grid_info.get("compression_scale_factor", 100.0)),
            )

        return java_grid_info

    @staticmethod
    def _datetimes_to_hec_times(
        times: Union[List, np.ndarray, pd.DatetimeIndex]
    ) -> np.ndarray:
        """
        Convert datetime values to HEC epoch times (minutes since 1899-12-31).

        Args:
            times: Array of datetime-like values

        Returns:
            numpy int32 array of minutes since HEC epoch
            (1899-12-31 00:00:00)
        """
        hec_epoch = np.datetime64('1899-12-31T00:00:00', 'm')
        RasDss._reject_timezone_aware_times(times)

        try:
            if isinstance(times, pd.DatetimeIndex):
                datetime_values = times.values.astype('datetime64[us]')
            elif isinstance(times, np.ndarray):
                datetime_values = times.astype('datetime64[us]')
            else:
                datetime_values = pd.to_datetime(times).to_numpy(
                    dtype='datetime64[us]'
                )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("times must contain valid datetime values") from exc

        if np.isnat(datetime_values).any():
            raise ValueError("times must not contain NaT values")

        minute_values = datetime_values.astype('datetime64[m]')
        if not np.array_equal(
            datetime_values,
            minute_values.astype('datetime64[us]'),
        ):
            raise ValueError("times must be aligned exactly to whole minutes")

        minutes = (
            (minute_values - hec_epoch)
            .astype('timedelta64[m]')
            .astype(np.int64)
        )
        if minutes.size:
            int32_info = np.iinfo(np.int32)
            if minutes.min() < int32_info.min or minutes.max() > int32_info.max:
                raise ValueError("times exceed the supported HEC int32 minute range")

        return minutes.astype(np.int32)


if __name__ == "__main__":
    """Test RasDss class"""
    import sys

    print("="*80)
    print("RasDss Test")
    print("="*80)

    # Test file (from TestData)
    test_data_dir = Path(__file__).parent.parent.parent / "TestData"

    # Find a DSS file to test with
    dss_files = list(test_data_dir.glob("*.dss"))

    if not dss_files:
        print("No DSS files found in TestData/")
        sys.exit(1)

    # Use BaldEagleDamBrk.dss (V7 file that we know works)
    test_file = test_data_dir / "BaldEagleDamBrk.dss"

    if not test_file.exists():
        # Use first available file
        test_file = dss_files[0]

    print(f"\nTest file: {test_file.name}")
    print(f"Size: {test_file.stat().st_size / 1024:.2f} KB")

    # Get file info
    print("\n" + "-"*80)
    print("Getting file info...")
    print("-"*80)
    info = RasDss.get_info(test_file)
    for key, value in info.items():
        if key == 'first_5_paths':
            print(f"{key}:")
            for path in value:
                print(f"  - {path}")
        else:
            print(f"{key}: {value}")

    # Get full catalog
    print("\n" + "-"*80)
    print("Getting catalog...")
    print("-"*80)
    catalog = RasDss.get_catalog(test_file)
    print(f"Total paths: {len(catalog)}")

    if len(catalog) > 0:
        # Read first time series
        print("\n" + "-"*80)
        print(f"Reading time series: {catalog[0]}")
        print("-"*80)
        df = RasDss.read_timeseries(test_file, catalog[0])

        print(f"\nDataFrame shape: {df.shape}")
        print(f"Date range: {df.index.min()} to {df.index.max()}")
        print(f"Value range: {df['value'].min():.2f} to {df['value'].max():.2f}")
        print(f"Units: {df.attrs.get('units', 'N/A')}")

        print("\nFirst 10 rows:")
        print(df.head(10))

        print("\nLast 10 rows:")
        print(df.tail(10))

    print("\n" + "="*80)
    print("Test complete!")
    print("="*80)
