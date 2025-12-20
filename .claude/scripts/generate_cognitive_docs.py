#!/usr/bin/env python3
"""
Generate Cognitive Infrastructure Documentation

This script dynamically generates documentation for agents, skills, and commands
by aggregating content from the .claude directory structure.

Run this script before building documentation to ensure the cognitive
infrastructure pages are up-to-date.

Usage:
    python scripts/generate_cognitive_docs.py
"""

import re
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# GitHub repository base URL for linking to source files
GITHUB_REPO_URL = "https://github.com/gpt-cmdr/ras-commander/blob/main"


def github_link(path: str) -> str:
    """Generate a GitHub link for a file path."""
    # Ensure forward slashes for URL
    path_str = str(path).replace('\\', '/')
    return f"{GITHUB_REPO_URL}/{path_str}"


def extract_yaml_frontmatter(content: str) -> Tuple[Optional[dict], str]:
    """Extract YAML frontmatter and remaining content from markdown."""
    if not content.startswith('---'):
        return None, content

    # Find the closing ---
    lines = content.split('\n')
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            end_idx = i
            break

    if end_idx is None:
        return None, content

    yaml_content = '\n'.join(lines[1:end_idx])
    remaining = '\n'.join(lines[end_idx + 1:])

    try:
        frontmatter = yaml.safe_load(yaml_content)
        return frontmatter, remaining.strip()
    except yaml.YAMLError:
        return None, content


def get_agent_files(claude_dir: Path) -> List[Dict]:
    """Collect all agent definition files."""
    agents = []
    agents_dir = claude_dir / 'agents'

    if not agents_dir.exists():
        return agents

    # Look for SUBAGENT.md files in subdirectories
    for subagent_file in agents_dir.glob('**/SUBAGENT.md'):
        content = subagent_file.read_text(encoding='utf-8')
        frontmatter, body = extract_yaml_frontmatter(content)

        agent_name = subagent_file.parent.name
        agents.append({
            'name': frontmatter.get('name', agent_name) if frontmatter else agent_name,
            'path': subagent_file.relative_to(claude_dir.parent),
            'frontmatter': frontmatter or {},
            'body': body,
            'file': subagent_file
        })

    # Also look for top-level .md files (non-nested agents)
    for md_file in agents_dir.glob('*.md'):
        if md_file.name == 'README.md':
            continue

        content = md_file.read_text(encoding='utf-8')
        frontmatter, body = extract_yaml_frontmatter(content)

        agent_name = md_file.stem
        agents.append({
            'name': frontmatter.get('name', agent_name) if frontmatter else agent_name,
            'path': md_file.relative_to(claude_dir.parent),
            'frontmatter': frontmatter or {},
            'body': body,
            'file': md_file
        })

    return sorted(agents, key=lambda x: x['name'])


def get_skill_files(claude_dir: Path) -> List[Dict]:
    """Collect all skill definition files."""
    skills = []
    skills_dir = claude_dir / 'skills'

    if not skills_dir.exists():
        return skills

    for skill_file in skills_dir.glob('**/SKILL.md'):
        content = skill_file.read_text(encoding='utf-8')
        frontmatter, body = extract_yaml_frontmatter(content)

        skill_name = skill_file.parent.name
        skills.append({
            'name': frontmatter.get('name', skill_name) if frontmatter else skill_name,
            'path': skill_file.relative_to(claude_dir.parent),
            'frontmatter': frontmatter or {},
            'body': body,
            'file': skill_file
        })

    return sorted(skills, key=lambda x: x['name'])


def get_command_files(claude_dir: Path) -> List[Dict]:
    """Collect all command definition files."""
    commands = []
    commands_dir = claude_dir / 'commands'

    if not commands_dir.exists():
        return commands

    for cmd_file in commands_dir.glob('*.md'):
        content = cmd_file.read_text(encoding='utf-8')
        frontmatter, body = extract_yaml_frontmatter(content)

        cmd_name = cmd_file.stem
        commands.append({
            'name': cmd_name,
            'path': cmd_file.relative_to(claude_dir.parent),
            'frontmatter': frontmatter or {},
            'body': body,
            'file': cmd_file
        })

    return sorted(commands, key=lambda x: x['name'])


def categorize_agents(agents: List[Dict]) -> Dict[str, List[Dict]]:
    """Categorize agents by their type/model."""
    categories = {
        'Domain Specialists (Sonnet)': [],
        'Knowledge Management (Opus)': [],
        'Utility Agents (Sonnet)': [],
        'Review Agents (Haiku)': [],
        'Analysis Agents': [],
    }

    domain_keywords = ['hdf', 'geometry', 'usgs', 'remote', 'precipitation',
                       'quality', 'dss', 'win32com', 'api-consistency', 'ras-commander-api']
    utility_keywords = ['documentation', 'notebook-librarian', 'python-environment',
                        'git-operations', 'notebook-runner']
    review_keywords = ['auditor', 'anomaly', 'scanner', 'finder', 'guide', 'scout']
    knowledge_keywords = ['hierarchical-knowledge', 'memory-curator']

    for agent in agents:
        name = agent['name'].lower()
        model = agent['frontmatter'].get('model', 'sonnet')

        if any(kw in name for kw in knowledge_keywords):
            categories['Knowledge Management (Opus)'].append(agent)
        elif any(kw in name for kw in domain_keywords):
            categories['Domain Specialists (Sonnet)'].append(agent)
        elif any(kw in name for kw in utility_keywords):
            categories['Utility Agents (Sonnet)'].append(agent)
        elif any(kw in name for kw in review_keywords) or model == 'haiku':
            categories['Review Agents (Haiku)'].append(agent)
        else:
            categories['Analysis Agents'].append(agent)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def generate_agents_page(agents: List[Dict], output_path: Path):
    """Generate the agents documentation page."""
    categorized = categorize_agents(agents)

    content = f"""# Agents Reference

This page provides a comprehensive reference for all available agents in the ras-commander cognitive infrastructure.

!!! info "Auto-Generated"
    This page is automatically generated from `.claude/agents/` directory.
    Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Overview

ras-commander includes **{len(agents)} agents** organized into specialized categories:

| Category | Count | Description |
|----------|-------|-------------|
| Domain Specialists | {len(categorized.get('Domain Specialists (Sonnet)', []))} | HEC-RAS domain expertise |
| Knowledge Management | {len(categorized.get('Knowledge Management (Opus)', []))} | Hierarchical knowledge organization |
| Utility Agents | {len(categorized.get('Utility Agents (Sonnet)', []))} | Development and documentation |
| Review Agents | {len(categorized.get('Review Agents (Haiku)', []))} | Output validation and review |
| Analysis Agents | {len(categorized.get('Analysis Agents', []))} | Research and pattern extraction |

---

"""

    for category, cat_agents in categorized.items():
        content += f"## {category}\n\n"

        for agent in cat_agents:
            fm = agent['frontmatter']
            name = agent['name']
            description = fm.get('description', 'No description available.')
            if isinstance(description, str):
                # Clean up multi-line descriptions
                description = ' '.join(description.split())
                if len(description) > 300:
                    description = description[:297] + '...'

            model = fm.get('model', 'sonnet')
            tools = fm.get('tools', [])
            if isinstance(tools, list):
                tools_str = ', '.join(tools[:5])
                if len(tools) > 5:
                    tools_str += f', +{len(tools) - 5} more'
            else:
                tools_str = str(tools)

            working_dir = fm.get('working_directory', 'root')

            content += f"""### {name}

**Model**: `{model}` | **Working Directory**: `{working_dir}`

**Tools**: {tools_str}

{description}

:material-github: [View Source]({github_link(agent['path'])})

---

"""

    content += """
## Agent Invocation

### From Orchestrator

```python
from Task import Task

# Invoke domain specialist
result = Task(
    subagent_type="hdf-analyst",
    model="sonnet",  # Optional: override default model
    prompt="Analyze water surface elevations in project.p01.hdf"
)
```

### Model Override

```python
# Escalate to more capable model if needed
result = Task(
    subagent_type="notebook-output-auditor",
    model="opus",  # Override default haiku
    prompt="Perform deep analysis of notebook outputs"
)
```

## Creating New Agents

See [Contributing Guide](../development/contributing.md) for instructions on creating new agents.

### Agent Definition Template

```yaml
---
name: my-agent
model: sonnet
tools:
  - Read
  - Grep
  - Glob
working_directory: ras_commander/module
description: |
  Clear description of what this agent does.
  Include trigger keywords for discovery.
---

# Agent Title

## Primary Sources
[Point to authoritative documentation]

## Quick Reference
[Common tasks and patterns]

## When to Use
[Trigger phrases and use cases]
```
"""

    output_path.write_text(content, encoding='utf-8')
    print(f"Generated: {output_path}")


def generate_skills_page(skills: List[Dict], output_path: Path):
    """Generate the skills documentation page."""

    content = f"""# Skills Reference

This page provides a comprehensive reference for all available skills in the ras-commander cognitive infrastructure.

!!! info "Auto-Generated"
    This page is automatically generated from `.claude/skills/` directory.
    Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Overview

ras-commander includes **{len(skills)} skills** that provide guided workflows for common HEC-RAS automation tasks.

Skills are **lightweight navigators** that:

- Point to primary documentation sources
- Provide copy-paste ready code examples
- Include trigger keywords for auto-discovery
- Cross-reference example notebooks

---

## Available Skills

"""

    for skill in skills:
        fm = skill['frontmatter']
        name = skill['name']
        description = fm.get('description', 'No description available.')
        if isinstance(description, str):
            description = ' '.join(description.split())
            if len(description) > 400:
                description = description[:397] + '...'

        allowed_tools = fm.get('allowed-tools', [])
        if isinstance(allowed_tools, list):
            tools_str = ', '.join(allowed_tools)
        else:
            tools_str = str(allowed_tools) if allowed_tools else 'Default'

        content += f"""### {name}

**Tools**: {tools_str}

{description}

:material-github: [View Source]({github_link(skill['path'])})

---

"""

    content += """
## Using Skills

### Automatic Discovery

Skills are automatically invoked based on trigger phrases in your prompts:

| Phrase | Skill |
|--------|-------|
| "Execute HEC-RAS plan" | `executing-hecras-plans` |
| "Extract HDF results" | `extracting-hecras-results` |
| "Parse geometry file" | `parsing-hecras-geometry` |
| "Integrate USGS data" | `integrating-usgs-gauges` |
| "Repair geometry issues" | `repairing-geometry-issues` |

### Manual Invocation

```python
# Skills provide workflow guidance
# Follow the patterns in the skill's SKILL.md file

# Example: Executing HEC-RAS Plans
from ras_commander import init_ras_project, RasCmdr

init_ras_project(r"C:\\Models\\MyProject", "6.6")
RasCmdr.compute_plan("01", num_cores=4)
```

## Creating New Skills

See [Contributing Guide](../development/contributing.md) for instructions on creating new skills.

### Skill Definition Template

```yaml
---
name: my-skill
description: |
  Clear description with trigger keywords.
  Include: what, when, common phrases.
allowed-tools:
  - Read
  - Grep
  - Glob
---

# Skill Title

## Primary Sources
[Point to CLAUDE.md, AGENTS.md, notebooks]

## Quick Reference
[Copy-paste code examples]

## Common Patterns
[Workflow steps with references]
```

## Design Philosophy

Skills follow the **Lightweight Navigator Pattern**:

1. **200-400 lines maximum** - Keep focused
2. **Point to primary sources** - Don't duplicate
3. **Include critical warnings** - Surface important info
4. **Provide examples** - Copy-paste ready code
5. **Cross-reference notebooks** - Show working demos
"""

    output_path.write_text(content, encoding='utf-8')
    print(f"Generated: {output_path}")


def generate_commands_page(commands: List[Dict], output_path: Path):
    """Generate the commands documentation page."""

    content = f"""# Commands Reference

This page provides a comprehensive reference for all available slash commands in the ras-commander cognitive infrastructure.

!!! info "Auto-Generated"
    This page is automatically generated from `.claude/commands/` directory.
    Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Overview

ras-commander includes **{len(commands)} custom commands** for multi-session task coordination and agent management.

Commands enable:

- **Task coordination** across multiple conversation sessions
- **Knowledge extraction** at session boundaries
- **File lifecycle management** with non-destructive cleanup
- **Git worktree workflows** for isolated feature development

---

## Available Commands

"""

    # Categorize commands
    task_cmds = []
    git_cmds = []
    other_cmds = []

    for cmd in commands:
        name = cmd['name']
        if 'task' in name:
            task_cmds.append(cmd)
        elif 'git' in name or 'worktree' in name:
            git_cmds.append(cmd)
        else:
            other_cmds.append(cmd)

    if task_cmds:
        content += "### Task Management Commands\n\n"
        for cmd in task_cmds:
            # Extract first paragraph as description
            body_lines = cmd['body'].split('\n\n')
            first_para = body_lines[0] if body_lines else 'No description.'
            first_para = ' '.join(first_para.split())
            if len(first_para) > 300:
                first_para = first_para[:297] + '...'

            content += f"""#### /{cmd['name']}

{first_para}

:material-github: [View Source]({github_link(cmd['path'])})

---

"""

    if git_cmds:
        content += "### Git Workflow Commands\n\n"
        for cmd in git_cmds:
            body_lines = cmd['body'].split('\n\n')
            first_para = body_lines[0] if body_lines else 'No description.'
            first_para = ' '.join(first_para.split())
            if len(first_para) > 300:
                first_para = first_para[:297] + '...'

            content += f"""#### /{cmd['name']}

{first_para}

:material-github: [View Source]({github_link(cmd['path'])})

---

"""

    if other_cmds:
        content += "### Other Commands\n\n"
        for cmd in other_cmds:
            body_lines = cmd['body'].split('\n\n')
            first_para = body_lines[0] if body_lines else 'No description.'
            first_para = ' '.join(first_para.split())
            if len(first_para) > 300:
                first_para = first_para[:297] + '...'

            content += f"""#### /{cmd['name']}

{first_para}

:material-github: [View Source]({github_link(cmd['path'])})

---

"""

    content += """
## Command Usage

### Invoking Commands

Commands are invoked with a forward slash prefix:

```bash
# End-of-session knowledge extraction
/agent-taskclose

# Update task progress
/agent-taskupdate

# Clean up stale files
/agent-cleanfiles

# Create git worktree for feature
/agents-start-gitworktree my-feature
```

### Multi-Session Workflow

Commands integrate with the `agent_tasks/.agent/` memory system:

```
Session Start
    ↓
Read STATE.md, PROGRESS.md, BACKLOG.md
    ↓
Work on tasks
    ↓
/agent-taskupdate (if session continues)
    ↓
/agent-taskclose (end of session)
    ↓
Knowledge extracted, state persisted
```

### Memory System Files

| File | Purpose |
|------|---------|
| `STATE.md` | Current task state snapshot |
| `PROGRESS.md` | Session history log |
| `BACKLOG.md` | Remaining work items |
| `NEXT_TASKS.md` | Immediate priorities |

## Creating New Commands

Commands are markdown files in `.claude/commands/` that expand into prompts:

```markdown
<!-- .claude/commands/my-command.md -->

Perform the following steps:

1. First step description
2. Second step with details
3. Final verification

## Context Files
- agent_tasks/.agent/STATE.md
- .claude/outputs/recent-analysis.md
```

When invoked as `/my-command`, the file contents become the prompt.
"""

    output_path.write_text(content, encoding='utf-8')
    print(f"Generated: {output_path}")


def main():
    """Main entry point for documentation generation."""
    # Find repository root (where .claude directory is)
    # Script is at .claude/scripts/generate_cognitive_docs.py
    # So repo_root is two levels up
    script_dir = Path(__file__).parent  # .claude/scripts/
    repo_root = script_dir.parent.parent  # repo root

    claude_dir = repo_root / '.claude'
    docs_dir = repo_root / 'docs' / 'cognitive-infrastructure'

    if not claude_dir.exists():
        print(f"Error: .claude directory not found at {claude_dir}")
        return 1

    # Ensure output directory exists
    docs_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating cognitive infrastructure documentation...")
    print(f"Source: {claude_dir}")
    print(f"Output: {docs_dir}")
    print()

    # Collect all source files
    agents = get_agent_files(claude_dir)
    skills = get_skill_files(claude_dir)
    commands = get_command_files(claude_dir)

    print(f"Found {len(agents)} agents")
    print(f"Found {len(skills)} skills")
    print(f"Found {len(commands)} commands")
    print()

    # Generate documentation pages
    generate_agents_page(agents, docs_dir / 'agents.md')
    generate_skills_page(skills, docs_dir / 'skills.md')
    generate_commands_page(commands, docs_dir / 'commands.md')

    print()
    print("Documentation generation complete!")
    return 0


if __name__ == '__main__':
    exit(main())
