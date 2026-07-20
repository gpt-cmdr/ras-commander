"""Shared fail-closed classification for software-assent dialogs.

This module intentionally contains no UI automation.  Callers may use the
returned diagnostic to terminate their own process tree, but must never click a
control on a matching dialog.
"""

from typing import Optional


TCU_DIALOG_TITLE = "Terms and Conditions for Use (TCU)"
TCU_BLOCKING_ERROR = (
    'HEC-RAS is blocked by the first-run "Terms and Conditions for Use (TCU)" '
    "dialog. Provision an already accepted, exact-version user state or have an "
    "authorized user review the terms interactively; ras-commander will not "
    "automate assent."
)

_LEGAL_ASSENT_MARKERS = (
    "terms and conditions for use",
    "terms and conditions of use",
    "terms of use",
    "license agreement",
    "licence agreement",
    "end user license agreement",
    "end-user license agreement",
    "eula",
)


def legal_dialog_blocking_reason(title: str = "", body: str = "") -> Optional[str]:
    """Return a fail-closed diagnostic for a legal-assent dialog, if any."""
    combined = " ".join(part.strip() for part in (title, body) if part).casefold()
    if any(marker in combined for marker in _LEGAL_ASSENT_MARKERS):
        return TCU_BLOCKING_ERROR
    return None
