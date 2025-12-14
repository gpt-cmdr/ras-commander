# Conversation Insights - Data Structure Reference

**Companion to**: `conversation_insights_agent_plan.md`
**Purpose**: Technical reference for parsing Claude Code conversation history

---

## File Locations

```
Windows:  C:\Users\{username}\.claude\
Unix/Mac: ~/.claude/

Structure:
~/.claude/
├── history.jsonl              # Prompt index (all projects)
├── projects/                  # Full conversations by project
│   └── {encoded-project-path}/
│       ├── {session-uuid}.jsonl    # Main conversation
│       └── agent-{agent-id}.jsonl  # Sub-agent conversations
├── settings.json              # User settings
├── stats-cache.json           # Usage statistics
├── plans/                     # Plan mode drafts
├── todos/                     # Todo list state
└── file-history/              # File change tracking
```

---

## 1. history.jsonl (Index File)

### Format

One JSON object per line. Each entry represents a user prompt.

### Schema

```typescript
interface HistoryEntry {
  display: string;        // User's prompt text
  pastedContents: object; // Pasted content (usually empty {})
  timestamp: number;      // Unix timestamp in milliseconds
  project: string;        // Full path to project directory
}
```

### Example Entry

```json
{"display":"ultrathink and create a detailed plan for implementing the USGS gauge integration","pastedContents":{},"timestamp":1733847562000,"project":"C:\\GH\\ras-commander"}
```

### Python Parser

```python
import json
from pathlib import Path
from datetime import datetime

def parse_history_index(history_path: Path = None) -> list[dict]:
    """Parse the history.jsonl index file."""
    if history_path is None:
        history_path = Path.home() / ".claude" / "history.jsonl"

    entries = []
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    # Convert timestamp to datetime
                    entry['datetime'] = datetime.fromtimestamp(
                        entry['timestamp'] / 1000
                    )
                    # Extract project name
                    entry['project_name'] = Path(entry['project']).name
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    return entries

def filter_by_date(entries: list[dict], days: int = 7) -> list[dict]:
    """Filter entries to last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    return [e for e in entries if e['datetime'] >= cutoff]

def filter_by_project(entries: list[dict], project_name: str) -> list[dict]:
    """Filter entries to specific project."""
    return [e for e in entries if project_name in e['project']]
```

---

## 2. Conversation Files ({session-uuid}.jsonl)

### Format

One JSON object per line. Each entry is a message in the conversation.

### Message Types

| Type | Description |
|------|-------------|
| `user` | User prompt message |
| `assistant` | Claude's response |
| `file-history-snapshot` | File state snapshot |
| `summary` | Conversation summary (after compaction) |

### Schema - User Message

```typescript
interface UserMessage {
  type: "user";
  parentUuid: string | null;     // UUID of parent message (null for first)
  isSidechain: boolean;          // If this is a branched conversation
  userType: "external";          // Always "external" for user input
  cwd: string;                   // Current working directory
  sessionId: string;             // Session UUID
  version: string;               // Claude Code version (e.g., "2.0.69")
  gitBranch: string;             // Git branch at time of message
  message: {
    role: "user";
    content: string | ContentBlock[];
  };
  uuid: string;                  // Unique message ID
  timestamp: string;             // ISO 8601 timestamp
  thinkingMetadata?: {
    level: "high" | "medium" | "low";
    disabled: boolean;
    triggers: Array<{start: number, end: number, text: string}>;
  };
  todos: Array<TodoItem>;
}
```

### Schema - Assistant Message

```typescript
interface AssistantMessage {
  type: "assistant";
  parentUuid: string;
  message: {
    role: "assistant";
    content: ContentBlock[];  // Array of text and tool_use blocks
  };
  uuid: string;
  timestamp: string;
  // Additional fields for tool results, costs, etc.
}

interface ContentBlock {
  type: "text" | "tool_use" | "tool_result";
  text?: string;           // For type: "text"
  name?: string;           // For type: "tool_use" (tool name)
  input?: object;          // For type: "tool_use" (tool parameters)
  content?: string;        // For type: "tool_result"
}
```

### Example - User Message

```json
{
  "type": "user",
  "parentUuid": null,
  "isSidechain": false,
  "userType": "external",
  "cwd": "C:\\GH\\ras-commander",
  "sessionId": "c9694eb2-f431-43c4-8ece-efae6824aa96",
  "version": "2.0.69",
  "gitBranch": "main",
  "message": {
    "role": "user",
    "content": "Create a new function to parse HEC-RAS geometry files"
  },
  "uuid": "951812ad-469f-420c-81d4-338ecd4752bf",
  "timestamp": "2025-12-13T18:33:54.662Z",
  "todos": []
}
```

### Example - Assistant Message (Simplified)

```json
{
  "type": "assistant",
  "parentUuid": "951812ad-469f-420c-81d4-338ecd4752bf",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "I'll create a function to parse HEC-RAS geometry files."
      },
      {
        "type": "tool_use",
        "id": "tool_123",
        "name": "Write",
        "input": {
          "file_path": "/path/to/file.py",
          "content": "def parse_geometry():\n    pass"
        }
      }
    ]
  },
  "uuid": "abc123",
  "timestamp": "2025-12-13T18:34:10.000Z"
}
```

### Python Parser

```python
import json
from pathlib import Path
from typing import Generator

def stream_conversation(conv_path: Path) -> Generator[dict, None, None]:
    """Stream messages from a conversation file without loading all at once."""
    with open(conv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

def extract_user_messages(conv_path: Path) -> list[dict]:
    """Extract only user messages from a conversation."""
    user_messages = []
    for msg in stream_conversation(conv_path):
        if msg.get('type') == 'user' and 'message' in msg:
            content = msg['message'].get('content', '')
            if isinstance(content, str):
                user_messages.append({
                    'uuid': msg.get('uuid'),
                    'timestamp': msg.get('timestamp'),
                    'content': content,
                    'parent': msg.get('parentUuid')
                })
            elif isinstance(content, list):
                # Extract text from content blocks
                text_parts = [
                    block.get('text', '')
                    for block in content
                    if block.get('type') == 'text'
                ]
                user_messages.append({
                    'uuid': msg.get('uuid'),
                    'timestamp': msg.get('timestamp'),
                    'content': ' '.join(text_parts),
                    'parent': msg.get('parentUuid')
                })
    return user_messages

def get_conversation_summary(conv_path: Path) -> dict:
    """Get basic stats about a conversation without loading all content."""
    stats = {
        'path': str(conv_path),
        'session_id': conv_path.stem,
        'message_count': 0,
        'user_count': 0,
        'assistant_count': 0,
        'first_timestamp': None,
        'last_timestamp': None,
        'file_size_mb': conv_path.stat().st_size / (1024 * 1024)
    }

    for msg in stream_conversation(conv_path):
        stats['message_count'] += 1
        msg_type = msg.get('type')

        if msg_type == 'user':
            stats['user_count'] += 1
        elif msg_type == 'assistant':
            stats['assistant_count'] += 1

        timestamp = msg.get('timestamp')
        if timestamp:
            if stats['first_timestamp'] is None:
                stats['first_timestamp'] = timestamp
            stats['last_timestamp'] = timestamp

    return stats
```

---

## 3. Project Path Encoding

### Encoding Rules

Project paths are encoded for use as directory names:

1. Drive letter colon removed: `C:` → `C`
2. Path separators become dashes: `\` or `/` → `-`
3. Consecutive separators collapsed: `\\` → `-`

### Examples

| Original Path | Encoded |
|---------------|---------|
| `C:\GH\ras-commander` | `C--GH-ras-commander` |
| `C:\GH\ras-commander\examples` | `C--GH-ras-commander-examples` |
| `/home/user/project` | `-home-user-project` |

### Python Helpers

```python
from pathlib import Path
import re

def encode_project_path(path: str) -> str:
    """Convert a project path to encoded folder name."""
    # Normalize path
    path = str(Path(path).resolve())
    # Remove colon after drive letter (Windows)
    encoded = re.sub(r'^([A-Za-z]):', r'\1', path)
    # Replace separators with dashes
    encoded = re.sub(r'[\\/]+', '-', encoded)
    return encoded

def decode_project_path(encoded: str) -> str:
    """Attempt to decode folder name back to path (approximate)."""
    # This is lossy - can't perfectly reconstruct
    # Add colon back to Windows drive letter
    if len(encoded) >= 2 and encoded[0].isalpha() and encoded[1] == '-':
        decoded = encoded[0] + ':' + encoded[1:]
    else:
        decoded = encoded
    # Replace dashes with OS-appropriate separator
    decoded = decoded.replace('-', '\\')  # Windows
    return decoded

def get_project_conversations(project_path: str) -> list[Path]:
    """Get all conversation files for a project."""
    claude_dir = Path.home() / ".claude" / "projects"
    encoded = encode_project_path(project_path)
    project_dir = claude_dir / encoded

    if not project_dir.exists():
        return []

    # Main conversations (UUID.jsonl) and agent conversations (agent-*.jsonl)
    return list(project_dir.glob("*.jsonl"))
```

---

## 4. Agent Conversation Files (agent-{id}.jsonl)

### Format

Same structure as main conversations, but for sub-agent (Task tool) executions.

### Identification

- Filename pattern: `agent-{8-char-hex-id}.jsonl`
- Example: `agent-533dbca0.jsonl`

### Relationship to Main Conversation

Agent conversations are spawned from main conversations via the Task tool. The agent ID appears in the main conversation's tool call.

### Python Helper

```python
def get_agent_conversations(project_dir: Path) -> list[Path]:
    """Get all agent sub-conversation files."""
    return list(project_dir.glob("agent-*.jsonl"))

def get_main_conversations(project_dir: Path) -> list[Path]:
    """Get main conversation files (excluding agents)."""
    all_jsonl = set(project_dir.glob("*.jsonl"))
    agents = set(project_dir.glob("agent-*.jsonl"))
    return list(all_jsonl - agents)
```

---

## 5. Timestamp Handling

### Formats Used

| Location | Format | Example |
|----------|--------|---------|
| history.jsonl | Unix ms | `1733847562000` |
| Conversation messages | ISO 8601 | `2025-12-13T18:33:54.662Z` |

### Python Converters

```python
from datetime import datetime, timezone

def parse_history_timestamp(ts: int) -> datetime:
    """Parse Unix millisecond timestamp from history.jsonl."""
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

def parse_message_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 timestamp from conversation messages."""
    # Handle 'Z' suffix (UTC)
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    return datetime.fromisoformat(ts)

def to_local_time(dt: datetime) -> datetime:
    """Convert to local timezone."""
    return dt.astimezone()
```

---

## 6. Complete Utility Script

```python
#!/usr/bin/env python3
"""
conversation_utils.py

Utilities for parsing Claude Code conversation history.
Used by Conversation Insights Agent sub-agents.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional
import re

class ConversationHistory:
    """Main class for accessing Claude Code conversation history."""

    def __init__(self, claude_dir: Optional[Path] = None):
        self.claude_dir = claude_dir or (Path.home() / ".claude")
        self.history_file = self.claude_dir / "history.jsonl"
        self.projects_dir = self.claude_dir / "projects"

    def get_all_prompts(self, days: Optional[int] = None) -> list[dict]:
        """Get all user prompts from history index."""
        prompts = []
        cutoff = None
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with open(self.history_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        dt = datetime.fromtimestamp(
                            entry['timestamp'] / 1000,
                            tz=timezone.utc
                        )
                        if cutoff and dt < cutoff:
                            continue
                        entry['datetime'] = dt
                        entry['project_name'] = Path(entry['project']).name
                        prompts.append(entry)
                    except (json.JSONDecodeError, KeyError):
                        continue
        return prompts

    def get_projects(self) -> list[str]:
        """Get list of all project directories."""
        if not self.projects_dir.exists():
            return []
        return [d.name for d in self.projects_dir.iterdir() if d.is_dir()]

    def get_project_sessions(self, project_name: str) -> list[dict]:
        """Get all sessions for a project with basic metadata."""
        project_dir = self.projects_dir / project_name
        if not project_dir.exists():
            return []

        sessions = []
        for jsonl_file in project_dir.glob("*.jsonl"):
            if jsonl_file.name.startswith("agent-"):
                continue  # Skip agent files

            stats = self._get_file_stats(jsonl_file)
            sessions.append(stats)

        return sorted(sessions, key=lambda x: x['last_timestamp'] or '', reverse=True)

    def _get_file_stats(self, file_path: Path) -> dict:
        """Get basic stats from a conversation file."""
        stats = {
            'session_id': file_path.stem,
            'file_path': str(file_path),
            'file_size_mb': file_path.stat().st_size / (1024 * 1024),
            'message_count': 0,
            'first_timestamp': None,
            'last_timestamp': None,
            'first_prompt': None
        }

        with open(file_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if line.strip():
                    try:
                        msg = json.loads(line)
                        stats['message_count'] += 1

                        ts = msg.get('timestamp')
                        if ts:
                            if stats['first_timestamp'] is None:
                                stats['first_timestamp'] = ts
                            stats['last_timestamp'] = ts

                        # Get first user prompt
                        if (stats['first_prompt'] is None and
                            msg.get('type') == 'user' and
                            'message' in msg):
                            content = msg['message'].get('content', '')
                            if isinstance(content, str):
                                stats['first_prompt'] = content[:100]
                            elif isinstance(content, list):
                                for block in content:
                                    if block.get('type') == 'text':
                                        stats['first_prompt'] = block.get('text', '')[:100]
                                        break
                    except json.JSONDecodeError:
                        continue

        return stats

    def stream_messages(self, session_path: Path) -> Generator[dict, None, None]:
        """Stream messages from a session file."""
        with open(session_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def extract_user_content(self, session_path: Path) -> list[str]:
        """Extract just user message content from a session."""
        content = []
        for msg in self.stream_messages(session_path):
            if msg.get('type') == 'user' and 'message' in msg:
                msg_content = msg['message'].get('content', '')
                if isinstance(msg_content, str):
                    content.append(msg_content)
                elif isinstance(msg_content, list):
                    text_parts = [
                        block.get('text', '')
                        for block in msg_content
                        if block.get('type') == 'text'
                    ]
                    content.append(' '.join(text_parts))
        return content


# Example usage
if __name__ == "__main__":
    history = ConversationHistory()

    # Get recent prompts
    recent = history.get_all_prompts(days=7)
    print(f"Prompts in last 7 days: {len(recent)}")

    # Get projects
    projects = history.get_projects()
    print(f"Projects: {projects}")

    # Get sessions for a project
    if "C--GH-ras-commander" in projects:
        sessions = history.get_project_sessions("C--GH-ras-commander")
        print(f"Sessions in ras-commander: {len(sessions)}")
        if sessions:
            print(f"Most recent: {sessions[0]['first_prompt']}")
```

---

## 7. Size and Performance Considerations

### Typical Sizes (billk_clb's history)

| Component | Size | Count |
|-----------|------|-------|
| history.jsonl | 1.3 MB | 2,240 prompts |
| ras-commander project | 110 MB | 45+ sessions, 180+ agent files |
| Single conversation | 0.5-20 MB | Varies by length |
| Agent conversation | 0.1-4 MB | Usually smaller |

### Memory-Efficient Processing

```python
# DON'T do this (loads entire file):
with open(conv_path) as f:
    all_messages = json.load(f)  # Won't work - not valid JSON array

# DO this (streaming):
for msg in stream_conversation(conv_path):
    process_message(msg)

# For large files, process in chunks:
def process_in_chunks(conv_path: Path, chunk_size: int = 100):
    chunk = []
    for msg in stream_conversation(conv_path):
        chunk.append(msg)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
```

---

## 8. Quick Reference

### Common Operations

```python
# Get last 7 days of prompts
history = ConversationHistory()
recent_prompts = history.get_all_prompts(days=7)

# Get all sessions for ras-commander
sessions = history.get_project_sessions("C--GH-ras-commander")

# Get user content from most recent session
if sessions:
    latest = Path(sessions[0]['file_path'])
    user_content = history.extract_user_content(latest)

# Stream large conversation without loading all
for msg in history.stream_messages(some_session_path):
    if msg.get('type') == 'user':
        print(msg['message']['content'][:50])
```

### File Patterns

```bash
# Find all conversation files
~/.claude/projects/*/[0-9a-f]*.jsonl

# Find all agent files
~/.claude/projects/*/agent-*.jsonl

# Find history index
~/.claude/history.jsonl
```

---

*Reference document for Conversation Insights Agent - December 2025*
