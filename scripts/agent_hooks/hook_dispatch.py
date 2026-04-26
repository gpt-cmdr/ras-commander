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
