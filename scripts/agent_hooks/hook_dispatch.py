#!/usr/bin/env python3
"""Cross-harness hook dispatcher for Claude Code and Codex.

Both harnesses pass hook event data as JSON on stdin. This script keeps the
repo policy in one place and emits hook output shapes both harnesses understand.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


SESSION_CONTEXT = (
    "ras-commander agent contract: AGENTS.md is the shared source of truth. "
    "CLAUDE.md and .codex/.agents files are harness adapters. "
    "Do not edit generated .agents/skills bridge entries directly."
)

DENIED_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
        "git reset --hard is blocked by the repository hook policy.",
    ),
    (
        re.compile(r"\brmdir\s+/s\b", re.IGNORECASE),
        "recursive rmdir /s is blocked by the repository hook policy.",
    ),
    (
        re.compile(r"\brd\s+/s\b", re.IGNORECASE),
        "recursive rd /s is blocked by the repository hook policy.",
    ),
    (
        re.compile(r"\bdel\s+/s\b", re.IGNORECASE),
        "recursive del /s is blocked by the repository hook policy.",
    ),
    (
        re.compile(r"\berase\s+/s\b", re.IGNORECASE),
        "recursive erase /s is blocked by the repository hook policy.",
    ),
)

EDIT_TOOL_NAMES = {
    "apply_patch",
    "edit",
    "multiedit",
    "notebookedit",
    "write",
}

GENERATED_BRIDGE_WRITE_COMMAND_PATTERN = re.compile(
    r"(\b(set-content|add-content|out-file|new-item|copy-item|move-item|remove-item)\b"
    r"|\b(del|erase|rm|mv|cp|copy|move)\b"
    r"|>\s*)",
    re.IGNORECASE,
)

# --- Retrieved federal source corpora (F: drive) -------------------------------
#
# F:\AGENTS.md rule 1: "raw\ holds delivered bytes only, and they are never
# modified." These are as-delivered publisher bytes -- ~16 TB of FEMA eBFE plus
# state BLE -- and generated knowledge belongs in audit\ or derived\ instead.
# The rule was written down but nothing enforced it; this does.
#
# Reads are always allowed. Only writes, moves and deletes are refused.
IMMUTABLE_CORPUS_PATTERN = re.compile(
    r"(?:"
    r"[a-z]:/(?:ebfe|ble_state)(?:/[^\s\"']*?)?/raw(?:/|\b)"
    r"|/nas/(?:ebfe|ble_state)(?:/[^\s\"']*?)?/raw(?:/|\b)"
    r"|/mnt/pool_12tb/fema/[^\s\"']*?/raw(?:/|\b)"
    r")",
    re.IGNORECASE,
)

# A write verb somewhere in a command and a corpus path somewhere else in the same
# command do not imply the verb targets that path -- `unzip -l <raw>/M.zip > out.txt`
# reads the corpus and writes elsewhere. So resolve the verb's actual target instead
# of scanning the whole command.
DESTRUCTIVE_VERB_PATTERN = re.compile(
    r"(?<!\S)(rm|rmdir|del|erase|shred|truncate|unlink|remove-item|clear-content)\b",
    re.IGNORECASE,
)
RELOCATE_VERB_PATTERN = re.compile(
    r"(?<!\S)(mv|cp|copy|move|copy-item|move-item|rename-item|rsync|robocopy)\b",
    re.IGNORECASE,
)
REDIRECT_TARGET_PATTERN = re.compile(r">>?\s*(?P<target>[^\s;&|]+)")
TEE_TARGET_PATTERN = re.compile(r"(?<!\S)tee\b\s+(?:-a\s+)?(?P<target>[^\s;&|]+)", re.IGNORECASE)
DD_TARGET_PATTERN = re.compile(r"(?<!\S)of=(?P<target>[^\s;&|]+)", re.IGNORECASE)

# --- Hashing guard -------------------------------------------------------------
#
# Standing instruction (campaign decision D2): do not hash corpus data without
# asking. Verification is file size against the provenance sidecar, the ETag as
# an identity label, and the archive format's own CRC -- which the decompressor
# checks for free. Hashing 16 TB is slow and buys nothing.
#
# Deliberately scoped to corpus paths: hashing a git diff, a config, or a small
# artifact is unaffected.
HASHING_COMMAND_PATTERN = re.compile(
    r"(\b(sha1sum|sha256sum|sha512sum|md5sum|shasum|b2sum|cksum)\b"
    r"|\bget-filehash\b"
    r"|\bcertutil\b[^\n]*\B-hashfile\b"
    r"|\bopenssl\s+(?:dgst|sha256|md5)\b"
    r"|\bhashlib\b)",
    re.IGNORECASE,
)

CORPUS_PATH_HINT_PATTERN = re.compile(
    r"(?:"
    r"[a-z]:/(?:ebfe|ble_state)\b"
    r"|/nas/(?:ebfe|ble_state)\b"
    r"|/mnt/pool_12tb/fema\b"
    r"|/work/\d{5,12}\b"
    r")",
    re.IGNORECASE,
)


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit_system_message(f"Hook input was not valid JSON: {exc}")
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def emit_system_message(message: str) -> None:
    emit_json({"systemMessage": message})


def emit_additional_context(event_name: str, context: str) -> None:
    emit_json(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": context,
            }
        }
    )


def emit_pre_tool_deny(event_name: str, reason: str) -> None:
    emit_json(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def emit_permission_request_deny(event_name: str, reason: str) -> None:
    emit_json(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "decision": {
                    "behavior": "deny",
                    "message": reason,
                },
            }
        }
    )


def emit_deny(event_name: str, reason: str) -> None:
    if event_name == "PermissionRequest":
        emit_permission_request_deny(event_name, reason)
    else:
        emit_pre_tool_deny(event_name, reason)


def payload_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload.get("tool_input", payload), default=str)


def command_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, dict):
        command = tool_input.get("command", "")
        if isinstance(command, str):
            return command
    return ""


def tool_name(payload: dict[str, Any]) -> str:
    value = payload.get("tool_name", "")
    return value if isinstance(value, str) else ""


def normalized_payload_text(payload: dict[str, Any]) -> str:
    return payload_text(payload).lower().replace("\\\\", "/").replace("\\", "/")


def should_deny_generated_bridge_edit(payload: dict[str, Any]) -> str | None:
    normalized = normalized_payload_text(payload)
    if ".agents/skills/" not in normalized:
        return None
    if ".agents/skills/readme.md" in normalized:
        return None

    name = tool_name(payload).lower()
    command = command_text(payload)
    if name in EDIT_TOOL_NAMES or GENERATED_BRIDGE_WRITE_COMMAND_PATTERN.search(command):
        return "Generated .agents/skills bridge entries must be regenerated, not edited directly."
    return None


def destination_text(payload: dict[str, Any]) -> str:
    """The path an edit tool would write to, normalized. Empty when not an edit."""
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return ""
    parts = [
        tool_input.get(key, "")
        for key in ("file_path", "path", "notebook_path", "target_file")
    ]
    text = " ".join(p for p in parts if isinstance(p, str))
    return text.lower().replace("\\\\", "/").replace("\\", "/")


def _normalize_path_token(token: str) -> str:
    return token.strip("\"'").lower().replace("\\\\", "/").replace("\\", "/")


def _targets_corpus(token: str) -> bool:
    return bool(IMMUTABLE_CORPUS_PATTERN.search(_normalize_path_token(token)))


def command_writes_to_corpus(command: str) -> bool:
    """Whether a shell command writes to a corpus raw\\ path.

    Resolves each write verb's actual target rather than asking whether a write
    verb and a corpus path both appear somewhere in the command. Reading the
    corpus and writing the result elsewhere -- probe-then-record, the common
    worker pattern -- must stay allowed.
    """
    if not command:
        return False

    for segment in re.split(r"[;&|\n]+", command):
        if not segment.strip():
            continue

        # Redirects, tee and dd name their target explicitly.
        for pattern in (REDIRECT_TARGET_PATTERN, TEE_TARGET_PATTERN, DD_TARGET_PATTERN):
            for match in pattern.finditer(segment):
                if _targets_corpus(match.group("target")):
                    return True

        tokens = [t for t in re.split(r"\s+", segment.strip()) if t]
        operands = [t for t in tokens if not t.startswith("-")]

        # Destructive verbs: every operand is a target.
        if DESTRUCTIVE_VERB_PATTERN.search(segment):
            if any(_targets_corpus(t) for t in operands[1:]):
                return True

        # Relocation verbs: only the final operand is the destination. A corpus
        # path in a source position is a read.
        if RELOCATE_VERB_PATTERN.search(segment) and len(operands) >= 2:
            if _targets_corpus(operands[-1]):
                return True

    return False


def should_deny_immutable_corpus_write(payload: dict[str, Any]) -> str | None:
    """Refuse writes under a retrieved-source raw\\ tree. Reads stay allowed."""
    name = tool_name(payload).lower()
    command = command_text(payload)

    if name in EDIT_TOOL_NAMES:
        # Match the destination only. A file that merely *mentions* a raw path --
        # a test, a doc, this dispatcher -- is not a write to the corpus.
        matched = bool(IMMUTABLE_CORPUS_PATTERN.search(destination_text(payload)))
    else:
        matched = command_writes_to_corpus(command)

    if matched:
        return (
            "Refused: raw\\ holds as-delivered publisher bytes and is never modified "
            "(F:\\AGENTS.md rule 1). Generated knowledge belongs in the dataset's "
            "audit\\<key>\\ or derived\\ tree instead. Reads are allowed."
        )
    return None


def should_deny_corpus_hashing(payload: dict[str, Any]) -> str | None:
    """Refuse hashing of corpus data; it is a standing decision, not a preference."""
    command = command_text(payload)
    if not HASHING_COMMAND_PATTERN.search(command):
        return None
    if not CORPUS_PATH_HINT_PATTERN.search(normalized_payload_text(payload)):
        return None
    return (
        "Refused: do not hash corpus data without asking (campaign decision D2). "
        "Verify with file size against the .ebfe-source.json sidecar, the ETag as an "
        "identity label, and the zip's own CRC-32, which the decompressor already "
        "checks. If hashing is genuinely needed here, ask the user first."
    )


def command_segment(command: str, executable_pattern: str) -> str | None:
    match = re.search(executable_pattern + r"\b(?P<args>[^;&|\n]*)", command, re.IGNORECASE)
    if not match:
        return None
    return match.group("args")


def has_short_option(args: str, option: str) -> bool:
    return bool(re.search(r"(?<!\S)-[A-Za-z]*" + re.escape(option) + r"[A-Za-z]*\b", args))


def has_long_option(args: str, option: str) -> bool:
    return bool(re.search(r"(?<!\S)--" + re.escape(option) + r"\b", args, re.IGNORECASE))


def has_broad_delete_target(args: str) -> bool:
    return bool(re.search(r"(?<!\S)(/|\\|\.|\.\.|~|\*|[A-Za-z]:[\\/])(?:\s|$)", args))


def should_deny_git_clean(command: str) -> str | None:
    args = command_segment(command, r"\bgit\s+clean")
    if args is None:
        return None
    has_force = has_short_option(args, "f") or has_long_option(args, "force")
    has_directory = has_short_option(args, "d")
    if has_force and has_directory:
        return "git clean with force+directory deletion is blocked by the repository hook policy."
    return None


def should_deny_rm(command: str) -> str | None:
    args = command_segment(command, r"\brm")
    if args is None:
        return None
    has_recursive = has_short_option(args, "r") or has_long_option(args, "recursive") or has_long_option(args, "dir")
    has_force = has_short_option(args, "f") or has_long_option(args, "force")
    has_powershell_recursive = bool(re.search(r"\B-recurse\b", args, re.IGNORECASE))
    has_powershell_force = bool(re.search(r"\B-force\b", args, re.IGNORECASE))
    if (has_recursive and has_force and has_broad_delete_target(args)) or (
        has_powershell_recursive and has_powershell_force
    ):
        return "recursive forced rm deletion is blocked by the repository hook policy."
    return None


def should_deny_remove_item(command: str) -> str | None:
    if not re.search(r"\bremove-item\b", command, re.IGNORECASE):
        return None
    has_recursive = bool(re.search(r"\B-recurse\b", command, re.IGNORECASE))
    has_force = bool(re.search(r"\B-force\b", command, re.IGNORECASE))
    if has_recursive and has_force:
        return "recursive forced Remove-Item is blocked by the repository hook policy."
    return None


def should_deny_command(command: str) -> str | None:
    for check in (should_deny_git_clean, should_deny_rm, should_deny_remove_item):
        reason = check(command)
        if reason:
            return reason

    for pattern, reason in DENIED_COMMAND_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def handle_session_start(event_name: str) -> int:
    emit_additional_context(event_name, SESSION_CONTEXT)
    return 0


def handle_tool_event(event_name: str, payload: dict[str, Any]) -> int:
    generated_bridge_reason = should_deny_generated_bridge_edit(payload)
    if generated_bridge_reason:
        emit_deny(event_name, generated_bridge_reason)
        return 0

    corpus_write_reason = should_deny_immutable_corpus_write(payload)
    if corpus_write_reason:
        emit_deny(event_name, corpus_write_reason)
        return 0

    hashing_reason = should_deny_corpus_hashing(payload)
    if hashing_reason:
        emit_deny(event_name, hashing_reason)
        return 0

    command_reason = should_deny_command(command_text(payload))
    if command_reason:
        emit_deny(event_name, command_reason)
        return 0

    return 0


def main() -> int:
    payload = read_payload()
    event_name = sys.argv[1] if len(sys.argv) > 1 else payload.get("hook_event_name", "")

    if event_name == "SessionStart":
        return handle_session_start(event_name)
    if event_name in {"PreToolUse", "PermissionRequest"}:
        return handle_tool_event(event_name, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
