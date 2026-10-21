"""Native encodings shared by breakline validation and HDF synchronization."""


def _protection_radius_flag(value) -> int:
    """Map native text Boolean encodings -1/0/1 to the HDF flag 1/0/1.

    Protection radius is an enabled flag, not an unsigned wraparound value
    or an unspecified-control sentinel. Reject other values before casting.
    """
    if value not in (-1, 0, 1):
        raise ValueError("Protection Radius must be -1, 0, or 1")
    return int(value != 0)
