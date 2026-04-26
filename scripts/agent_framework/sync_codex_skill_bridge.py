#!/usr/bin/env python3
"""Create a local Codex skill bridge without copying skill content.

Shared skill sources currently live in .claude/skills. Codex-native adapter
skill sources live in .agents/native-skills. Codex discovers repo skills from
.agents/skills, so this script creates symlinks or Windows junctions for
approved shared-domain skills plus approved Codex-native adapter skills.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_SKILLS = REPO_ROOT / ".claude" / "skills"
CODEX_NATIVE_SKILLS = REPO_ROOT / ".agents" / "native-skills"
CODEX_SKILLS = REPO_ROOT / ".agents" / "skills"
ALLOWED_SOURCE_OWNERS = {"gpt-cmdr", "anthropic", "openai"}
APPROVED_SECURITY_REVIEWS = {
    "internal",
    "official-upstream",
    "audited-reimplemented",
}
CODEX_DESCRIPTION_MAX_CHARS = 1024


def frontmatter_lines(skill_file: Path) -> list[str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return []

    lines = text.splitlines()
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break

    if end_index is None:
        return []
    return lines[1:end_index]


def parse_frontmatter(skill_file: Path) -> dict[str, str | bool]:
    """Parse the simple top-level YAML fields this bridge cares about."""
    metadata: dict[str, str | bool] = {}
    for raw_line in frontmatter_lines(skill_file):
        if not raw_line or raw_line.startswith((" ", "\t", "-")):
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        value = value.strip()
        if value.lower() == "false":
            parsed_value: str | bool = False
        elif value.lower() == "true":
            parsed_value = True
        else:
            parsed_value = value.strip("\"'")
        metadata[key.strip()] = parsed_value
    return metadata


def frontmatter_description(skill_file: Path) -> str | None:
    lines = frontmatter_lines(skill_file)
    for index, raw_line in enumerate(lines):
        if not raw_line.startswith("description:"):
            continue
        value = raw_line.split(":", 1)[1].strip()
        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            block: list[str] = []
            for block_line in lines[index + 1 :]:
                if block_line.startswith((" ", "\t")) or block_line == "":
                    block.append(block_line.strip())
                    continue
                break
            return "\n".join(block)
        return value.strip("\"'")
    return None


def is_shared_skill(skill_dir: Path) -> bool:
    metadata = parse_frontmatter(skill_dir / "SKILL.md")
    if metadata.get("shared_corpus") is not True:
        return False
    if metadata.get("harness_scope") != "shared":
        return False
    source_owner = str(metadata.get("source_owner", "")).lower()
    if source_owner not in ALLOWED_SOURCE_OWNERS:
        return False
    security_review = str(metadata.get("security_review", "")).lower()
    if security_review not in APPROVED_SECURITY_REVIEWS:
        return False
    return True


def is_codex_native_skill(skill_dir: Path) -> bool:
    metadata = parse_frontmatter(skill_dir / "SKILL.md")
    if metadata.get("shared_corpus") is not False:
        return False
    if metadata.get("harness_scope") != "codex_only":
        return False
    source_owner = str(metadata.get("source_owner", "")).lower()
    if source_owner not in ALLOWED_SOURCE_OWNERS:
        return False
    security_review = str(metadata.get("security_review", "")).lower()
    if security_review not in APPROVED_SECURITY_REVIEWS:
        return False
    return True


def shared_skill_dirs() -> list[Path]:
    if not CLAUDE_SKILLS.exists():
        raise FileNotFoundError(f"Missing canonical skill directory: {CLAUDE_SKILLS}")
    return sorted(
        skill_dir
        for skill_dir in CLAUDE_SKILLS.iterdir()
        if skill_dir.is_dir()
        and (skill_dir / "SKILL.md").exists()
        and is_shared_skill(skill_dir)
    )


def codex_native_skill_dirs() -> list[Path]:
    if not CODEX_NATIVE_SKILLS.exists():
        return []
    return sorted(
        skill_dir
        for skill_dir in CODEX_NATIVE_SKILLS.iterdir()
        if skill_dir.is_dir()
        and (skill_dir / "SKILL.md").exists()
        and is_codex_native_skill(skill_dir)
    )


def expected_skill_dirs() -> dict[str, Path]:
    expected = {skill_dir.name: skill_dir for skill_dir in shared_skill_dirs()}
    for skill_dir in codex_native_skill_dirs():
        if skill_dir.name in expected:
            raise RuntimeError(f"Duplicate Codex bridge skill name: {skill_dir.name}")
        expected[skill_dir.name] = skill_dir
    return expected


def validate_codex_skill_metadata(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    description = frontmatter_description(skill_file)
    if description is None or not description.strip():
        errors.append(f"{skill_file} is missing a Codex-loadable description")
    elif len(description) > CODEX_DESCRIPTION_MAX_CHARS:
        errors.append(
            f"{skill_file} description is {len(description)} characters; "
            f"Codex limit is {CODEX_DESCRIPTION_MAX_CHARS}"
        )
    return errors


def resolves_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def existing_bridge_is_valid(link_path: Path, target_path: Path) -> bool:
    if not os.path.lexists(link_path):
        return False
    try:
        return link_path.resolve(strict=True) == target_path.resolve(strict=True)
    except FileNotFoundError:
        return False


def remove_bridge(link_path: Path) -> None:
    if link_path.is_symlink():
        link_path.unlink()
        return
    if link_path.is_dir() and (
        resolves_inside(link_path, CLAUDE_SKILLS)
        or resolves_inside(link_path, CODEX_NATIVE_SKILLS)
    ):
        # On Windows this removes the junction, not the target directory.
        os.rmdir(link_path)
        return
    raise RuntimeError(f"Refusing to remove non-bridge path: {link_path}")


def create_bridge(target_path: Path, link_path: Path) -> None:
    try:
        relative_target = os.path.relpath(target_path, link_path.parent)
        os.symlink(relative_target, link_path, target_is_directory=True)
        return
    except OSError:
        if platform.system() != "Windows":
            raise

    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or "mklink failed without output"
        raise RuntimeError(f"Failed to create junction {link_path}: {detail}")


def sync(check_only: bool = False) -> int:
    errors: list[str] = []
    actions: list[str] = []

    if CODEX_SKILLS.exists() and not CODEX_SKILLS.is_dir():
        errors.append(f"Codex skills path is not a directory: {CODEX_SKILLS}")
    elif not CODEX_SKILLS.exists():
        actions.append(f"create bridge directory {CODEX_SKILLS}")
        if not check_only:
            CODEX_SKILLS.mkdir(parents=True, exist_ok=True)

    expected = expected_skill_dirs()
    for target_path in expected.values():
        errors.extend(validate_codex_skill_metadata(target_path))

    if errors or (check_only and not CODEX_SKILLS.exists()):
        for action in actions:
            print(action)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    for child in sorted(CODEX_SKILLS.iterdir()):
        if child.name == "README.md":
            continue
        if child.name in expected:
            continue
        if child.is_symlink() and not child.exists():
            actions.append(f"remove stale broken bridge {child.name}")
            if not check_only:
                remove_bridge(child)
            continue
        if child.is_dir() and (
            resolves_inside(child, CLAUDE_SKILLS)
            or resolves_inside(child, CODEX_NATIVE_SKILLS)
        ):
            actions.append(f"remove stale bridge {child.name}")
            if not check_only:
                remove_bridge(child)
            continue
        errors.append(f"unexpected path in {CODEX_SKILLS}: {child}")

    for name, target_path in expected.items():
        link_path = CODEX_SKILLS / name
        if existing_bridge_is_valid(link_path, target_path):
            continue
        if os.path.lexists(link_path):
            if link_path.is_symlink() and not link_path.exists():
                actions.append(f"remove broken bridge {name}")
                if not check_only:
                    remove_bridge(link_path)
            else:
                errors.append(f"conflicting path exists for skill {name}: {link_path}")
                continue
            if check_only:
                continue
        actions.append(f"create bridge {name}")
        if not check_only:
            create_bridge(target_path, link_path)

    for action in actions:
        print(action)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if check_only and actions:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the bridge without creating or removing links.",
    )
    args = parser.parse_args()
    return sync(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
