# Codex Skill Bridge

This directory is generated locally from approved skill source directories.

Each generated child directory should be a symlink or Windows junction pointing to one of:

- a shared-domain skill source under `.claude/skills/`
- a Codex-native adapter skill source under `.agents/native-skills/`

Generation rules:

- include shared skills only when `shared_corpus: true` and `harness_scope: shared`
- include Codex-native adapter skills only when `shared_corpus: false` and `harness_scope: codex_only`
- require accepted `source_owner` and `security_review` metadata
- exclude skills with `harness_scope: claude_only`
- never copy skill content into this tree
- never edit generated child directories directly
- never bridge third-party skill/plugin sources unless they are security-audited and re-implemented in this repository

Regenerate:

```bash
python scripts/agent_framework/sync_codex_skill_bridge.py
```

Validate without modifying:

```bash
python scripts/agent_framework/sync_codex_skill_bridge.py --check
```
