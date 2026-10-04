"""Read selected non-spatial metadata from HEC-RAS text snapshots.

These pure readers accept bytes or text, never paths. They do not initialize a
project, resolve external references, inspect binaries, or require an executable.
The caller owns file access, size limits, and trust boundaries.
"""

from typing import Iterable
from .Decorators import log_call


class RasText:
    """Focused metadata readers for bounded text-information clients."""

    PROJECT_FIELDS = frozenset({
        "Proj Title", "Current Plan", "Plan File", "Geom File", "Flow File",
        "Unsteady File", "Units",
    })
    PLAN_FIELDS = frozenset({
        "Plan Title", "Short Identifier", "Program Version", "Geom File",
        "Flow File", "Simulation Date", "Computation Interval",
        "Output Interval", "Instantaneous Interval", "Mapping Interval",
        "Run HTab", "Run UNet", "Run UNET", "Run WQNET", "Run Sediment",
        "Run Post Process", "Run PostProcess", "Run WQNet", "Friction Slope Method", "UNET D1 Cores",
        "UNET D2 Cores", "PS Cores", "UNET 1D Methodology",
        "UNET D2 Solver Type", "Description",
    })

    @staticmethod
    def _text(content: str | bytes) -> tuple[str, str]:
        if isinstance(content, str):
            text, encoding = content, "unicode"
        elif isinstance(content, bytes):
            try:
                text, encoding = content.decode("utf-8-sig"), "utf-8-sig"
            except UnicodeDecodeError:
                # HEC-RAS text readers historically permit Latin-1 input. Keep
                # a reversible decoding and report it rather than replacing bytes.
                text, encoding = content.decode("latin-1"), "latin-1"
        else:
            raise TypeError("content must be text or bytes")
        if "\x00" in text:
            raise ValueError("NUL-containing input is not eligible text")
        return text, encoding

    @staticmethod
    def _metadata(content: str | bytes, fields: Iterable[str] | None,
                  allowed: frozenset[str], project: bool) -> dict:
        text, encoding = RasText._text(content)
        selected = set(allowed if fields is None else fields)
        unknown = selected - allowed
        if unknown:
            raise ValueError(f"Unsupported metadata fields: {sorted(unknown)}")
        values: dict[str, list[str]] = {key: [] for key in sorted(selected)}
        description: list[str] = []
        in_description = False
        description_seen = False
        for line in text.splitlines():
            stripped = line.strip()
            upper = stripped.upper().rstrip(":")
            if upper == "BEGIN DESCRIPTION":
                in_description = True
                description_seen = True
                continue
            if in_description:
                if upper == "END DESCRIPTION":
                    in_description = False
                elif "Description" in selected:
                    description.append(stripped)
                continue
            if project and "Units" in selected:
                marker = stripped.casefold()
                if marker in {"english units", "si units"}:
                    values["Units"].append("English" if marker == "english units" else "SI")
                elif marker.startswith("si units="):
                    flag = marker.split("=", 1)[1].strip()
                    if flag in {"1", "true", "yes", "on"}:
                        values["Units"].append("SI")
                    elif flag in {"0", "false", "no", "off"}:
                        values["Units"].append("English")
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                if key in selected and key != "Description":
                    values[key].append(value.strip())
        if "Description" in selected and description_seen:
            values["Description"] = ["\n".join(description)]
        # Preserve repeated source values and strings; do not silently infer
        # physical validity, convert units, or turn missing values into zero.
        return {"encoding": encoding, "fields": values,
                "missing_fields": [key for key, value in values.items() if not value],
                "warnings": ["Description block has no end marker."] if in_description else []}

    @staticmethod
    @log_call
    def read_project_metadata(content: str | bytes,
                              fields: Iterable[str] | None = None) -> dict:
        """Read project title, component references, current plan and unit marker.

        Args:
            content: A project text snapshot; no referenced files are opened.
            fields: Exact field names from ``PROJECT_FIELDS``; defaults to all.

        Returns:
            Encoding, selected fields as lists of source strings, and absent fields.
            Component references are opaque strings, never resolved as paths.

        Raises:
            TypeError: If content is neither text nor bytes.
            ValueError: If content contains NUL or a field is unsupported.
        """
        return RasText._metadata(content, fields, RasText.PROJECT_FIELDS, True)

    @staticmethod
    @log_call
    def read_plan_metadata(content: str | bytes,
                           fields: Iterable[str] | None = None) -> dict:
        """Read selected scalar plan settings and optional narrative description.

        Args:
            content: A plan text snapshot.
            fields: Exact field names from ``PLAN_FIELDS``; defaults to all.

        Returns:
            Encoding, selected fields as lists of source strings, and absent fields.
            Time strings retain the file's basis; timezone is not inferred.

        Raises:
            TypeError: If content is neither text nor bytes.
            ValueError: If content contains NUL or a field is unsupported.
        """
        return RasText._metadata(content, fields, RasText.PLAN_FIELDS, False)
