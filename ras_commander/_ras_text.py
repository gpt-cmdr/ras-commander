"""Internal serialization for line-oriented HEC-RAS model files."""

from io import BytesIO, StringIO
from pathlib import Path


def _normalize_ras_newlines(text: str | bytes) -> str | bytes:
    """Normalize newlines without decoding byte-preserving mutation payloads."""
    if isinstance(text, bytes):
        return (
            text.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
        )
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _write_ras_text(
    path: str | Path,
    text: str,
    *,
    encoding: str | None = None,
    errors: str | None = None,
) -> None:
    """Write model text with CRLF, preserving encoding and terminal-newline state.

    Universal-newline readers continue to accept LF, CRLF, and CR inputs.
    Normalize before translation so existing CRLF never becomes CRCRLF.
    """
    with Path(path).open("w", encoding=encoding, errors=errors, newline="") as stream:
        stream.write(_normalize_ras_newlines(text))


def _write_ras_xml(
    tree, path: str | Path, *, encoding="utf-8", xml_declaration=None
) -> None:
    """Preserve ElementTree serialization while enforcing model text newlines."""
    buffer = StringIO() if encoding == "unicode" else BytesIO()
    tree.write(buffer, encoding=encoding, xml_declaration=xml_declaration)
    content = buffer.getvalue()
    if isinstance(content, bytes):
        # A reversible byte mapping retains the serializer's exact encoding/BOM.
        _write_ras_text(path, content.decode("latin-1"), encoding="latin-1")
    else:
        _write_ras_text(path, content, encoding="utf-8", errors="xmlcharrefreplace")
