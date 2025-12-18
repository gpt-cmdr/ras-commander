"""
conversation_parser.py

Core utilities for parsing Claude Code conversation history files.
Handles both the history.jsonl index and full conversation JSONL files.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional, List, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    """Types of messages in conversation files."""
    USER = "user"
    ASSISTANT = "assistant"
    FILE_SNAPSHOT = "file-history-snapshot"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


@dataclass
class ConversationMessage:
    """Represents a single message in a conversation."""
    uuid: str
    message_type: MessageType
    timestamp: Optional[datetime]
    content: str
    parent_uuid: Optional[str] = None
    session_id: Optional[str] = None
    git_branch: Optional[str] = None
    cwd: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ConversationMessage":
        """Create a ConversationMessage from raw JSON data."""
        msg_type_str = data.get("type", "unknown")
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            msg_type = MessageType.UNKNOWN

        # Parse timestamp
        timestamp = None
        ts_raw = data.get("timestamp")
        if ts_raw:
            if isinstance(ts_raw, str):
                try:
                    if ts_raw.endswith("Z"):
                        ts_raw = ts_raw[:-1] + "+00:00"
                    timestamp = datetime.fromisoformat(ts_raw)
                except ValueError:
                    pass
            elif isinstance(ts_raw, (int, float)):
                timestamp = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)

        # Extract content
        content = ""
        tool_calls = []
        message_data = data.get("message", {})
        raw_content = message_data.get("content", "")

        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            text_parts = []
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                            "id": block.get("id")
                        })
            content = "\n".join(text_parts)

        return cls(
            uuid=data.get("uuid", ""),
            message_type=msg_type,
            timestamp=timestamp,
            content=content,
            parent_uuid=data.get("parentUuid"),
            session_id=data.get("sessionId"),
            git_branch=data.get("gitBranch"),
            cwd=data.get("cwd"),
            tool_calls=tool_calls,
            raw_data=data
        )


@dataclass
class HistoryEntry:
    """Represents an entry from history.jsonl (prompt index)."""
    display: str
    timestamp: datetime
    project: str
    project_name: str
    pasted_contents: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "HistoryEntry":
        """Create a HistoryEntry from raw JSON data."""
        ts = data.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        project = data.get("project", "")
        project_name = Path(project).name if project else ""

        return cls(
            display=data.get("display", ""),
            timestamp=timestamp,
            project=project,
            project_name=project_name,
            pasted_contents=data.get("pastedContents", {})
        )


@dataclass
class ConversationSession:
    """Metadata about a conversation session."""
    session_id: str
    file_path: Path
    file_size_mb: float
    message_count: int
    user_message_count: int
    assistant_message_count: int
    first_timestamp: Optional[datetime]
    last_timestamp: Optional[datetime]
    first_prompt: Optional[str]
    git_branch: Optional[str] = None
    is_agent: bool = False


class ConversationHistory:
    """
    Main class for accessing Claude Code conversation history.

    Provides methods to:
    - Parse the history.jsonl index file
    - Access full conversation files
    - Stream large conversations without loading entirely
    - Filter by date, project, and other criteria
    """

    def __init__(self, claude_dir: Optional[Path] = None):
        """
        Initialize ConversationHistory.

        Args:
            claude_dir: Path to .claude directory. Defaults to ~/.claude
        """
        self.claude_dir = claude_dir or (Path.home() / ".claude")
        self.history_file = self.claude_dir / "history.jsonl"
        self.projects_dir = self.claude_dir / "projects"

    def get_all_prompts(
        self,
        days: Optional[int] = None,
        project_filter: Optional[str] = None
    ) -> List[HistoryEntry]:
        """
        Get all user prompts from history index.

        Args:
            days: Only include prompts from last N days
            project_filter: Only include prompts from projects containing this string

        Returns:
            List of HistoryEntry objects, newest first
        """
        if not self.history_file.exists():
            return []

        prompts = []
        cutoff = None
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with open(self.history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = HistoryEntry.from_json(data)

                    # Apply date filter
                    if cutoff and entry.timestamp < cutoff:
                        continue

                    # Apply project filter
                    if project_filter and project_filter.lower() not in entry.project.lower():
                        continue

                    prompts.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

        # Sort by timestamp descending (newest first)
        prompts.sort(key=lambda x: x.timestamp, reverse=True)
        return prompts

    def get_projects(self) -> List[str]:
        """Get list of all project directory names."""
        if not self.projects_dir.exists():
            return []
        return sorted([d.name for d in self.projects_dir.iterdir() if d.is_dir()])

    def get_project_path(self, project_name: str) -> Optional[Path]:
        """Get the full path to a project's conversation directory."""
        project_dir = self.projects_dir / project_name
        return project_dir if project_dir.exists() else None

    def get_project_sessions(
        self,
        project_name: str,
        include_agents: bool = False,
        days: Optional[int] = None
    ) -> List[ConversationSession]:
        """
        Get all conversation sessions for a project.

        Args:
            project_name: Encoded project name (e.g., "C--GH-ras-commander")
            include_agents: Whether to include agent sub-conversations
            days: Only include sessions from last N days

        Returns:
            List of ConversationSession objects, newest first
        """
        project_dir = self.projects_dir / project_name
        if not project_dir.exists():
            return []

        cutoff = None
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        sessions = []
        for jsonl_file in project_dir.glob("*.jsonl"):
            is_agent = jsonl_file.name.startswith("agent-")
            if is_agent and not include_agents:
                continue

            session = self._get_session_metadata(jsonl_file, is_agent)

            # Apply date filter
            if cutoff and session.last_timestamp and session.last_timestamp < cutoff:
                continue

            sessions.append(session)

        # Sort by last timestamp descending
        sessions.sort(
            key=lambda x: x.last_timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
        return sessions

    def _get_session_metadata(self, file_path: Path, is_agent: bool = False) -> ConversationSession:
        """Extract metadata from a conversation file without loading all content."""
        stats = {
            "message_count": 0,
            "user_count": 0,
            "assistant_count": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "first_prompt": None,
            "git_branch": None
        }

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        stats["message_count"] += 1

                        msg_type = data.get("type")
                        if msg_type == "user":
                            stats["user_count"] += 1
                        elif msg_type == "assistant":
                            stats["assistant_count"] += 1

                        # Track timestamps
                        ts_raw = data.get("timestamp")
                        if ts_raw:
                            if isinstance(ts_raw, str):
                                try:
                                    if ts_raw.endswith("Z"):
                                        ts_raw = ts_raw[:-1] + "+00:00"
                                    ts = datetime.fromisoformat(ts_raw)
                                except ValueError:
                                    ts = None
                            elif isinstance(ts_raw, (int, float)):
                                ts = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)
                            else:
                                ts = None

                            if ts:
                                if stats["first_timestamp"] is None:
                                    stats["first_timestamp"] = ts
                                stats["last_timestamp"] = ts

                        # Get first user prompt and git branch
                        if stats["first_prompt"] is None and msg_type == "user":
                            message_data = data.get("message", {})
                            content = message_data.get("content", "")
                            if isinstance(content, str):
                                stats["first_prompt"] = content[:200]
                            elif isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        stats["first_prompt"] = block.get("text", "")[:200]
                                        break

                        if stats["git_branch"] is None:
                            stats["git_branch"] = data.get("gitBranch")

                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return ConversationSession(
            session_id=file_path.stem,
            file_path=file_path,
            file_size_mb=file_path.stat().st_size / (1024 * 1024),
            message_count=stats["message_count"],
            user_message_count=stats["user_count"],
            assistant_message_count=stats["assistant_count"],
            first_timestamp=stats["first_timestamp"],
            last_timestamp=stats["last_timestamp"],
            first_prompt=stats["first_prompt"],
            git_branch=stats["git_branch"],
            is_agent=is_agent
        )

    def stream_messages(
        self,
        session_path: Path,
        message_types: Optional[List[MessageType]] = None
    ) -> Generator[ConversationMessage, None, None]:
        """
        Stream messages from a conversation file.

        Args:
            session_path: Path to the .jsonl conversation file
            message_types: Only yield messages of these types (None = all)

        Yields:
            ConversationMessage objects
        """
        if not session_path.exists():
            return

        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    msg = ConversationMessage.from_json(data)

                    if message_types is None or msg.message_type in message_types:
                        yield msg
                except json.JSONDecodeError:
                    continue

    def get_user_messages(self, session_path: Path) -> List[ConversationMessage]:
        """Get all user messages from a conversation."""
        return list(self.stream_messages(session_path, [MessageType.USER]))

    def get_conversation_content(
        self,
        session_path: Path,
        user_only: bool = False,
        max_messages: Optional[int] = None
    ) -> str:
        """
        Get conversation content as formatted text.

        Args:
            session_path: Path to conversation file
            user_only: Only include user messages
            max_messages: Maximum number of messages to include

        Returns:
            Formatted conversation text
        """
        message_types = [MessageType.USER] if user_only else [MessageType.USER, MessageType.ASSISTANT]

        lines = []
        count = 0

        for msg in self.stream_messages(session_path, message_types):
            if max_messages and count >= max_messages:
                break

            role = "USER" if msg.message_type == MessageType.USER else "ASSISTANT"
            timestamp = msg.timestamp.strftime("%Y-%m-%d %H:%M") if msg.timestamp else "?"

            lines.append(f"[{timestamp}] {role}:")
            lines.append(msg.content[:2000] if len(msg.content) > 2000 else msg.content)
            lines.append("")

            count += 1

        return "\n".join(lines)

    def search_prompts(
        self,
        pattern: str,
        days: Optional[int] = None,
        case_sensitive: bool = False
    ) -> List[HistoryEntry]:
        """
        Search prompts by regex pattern.

        Args:
            pattern: Regex pattern to search for
            days: Only search last N days
            case_sensitive: Whether search is case-sensitive

        Returns:
            List of matching HistoryEntry objects
        """
        prompts = self.get_all_prompts(days=days)
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            regex = re.compile(pattern, flags)
        except re.error:
            return []

        return [p for p in prompts if regex.search(p.display)]

    def get_prompt_frequency(
        self,
        days: Optional[int] = None,
        min_length: int = 3,
        top_n: int = 50
    ) -> List[tuple]:
        """
        Get frequency of n-grams in prompts.

        Args:
            days: Only analyze last N days
            min_length: Minimum n-gram length (words)
            top_n: Return top N most frequent

        Returns:
            List of (phrase, count) tuples
        """
        from collections import Counter

        prompts = self.get_all_prompts(days=days)
        ngram_counts = Counter()

        for entry in prompts:
            words = entry.display.lower().split()
            # Generate n-grams of various sizes
            for n in range(min_length, min(len(words) + 1, 8)):
                for i in range(len(words) - n + 1):
                    ngram = " ".join(words[i:i+n])
                    # Filter out very short or very common phrases
                    if len(ngram) > 10 and not ngram.startswith("the "):
                        ngram_counts[ngram] += 1

        # Filter to phrases that appear multiple times
        frequent = [(phrase, count) for phrase, count in ngram_counts.items() if count >= 2]
        frequent.sort(key=lambda x: (-x[1], x[0]))

        return frequent[:top_n]


def encode_project_path(path: str) -> str:
    """Convert a project path to encoded folder name."""
    path = str(Path(path).resolve())
    # Remove colon after drive letter (Windows)
    encoded = re.sub(r"^([A-Za-z]):", r"\1", path)
    # Replace separators with dashes
    encoded = re.sub(r"[\\/]+", "-", encoded)
    return encoded


def decode_project_path(encoded: str) -> str:
    """Attempt to decode folder name back to path (approximate)."""
    # Add colon back to Windows drive letter
    if len(encoded) >= 2 and encoded[0].isalpha() and encoded[1] == "-":
        decoded = encoded[0] + ":" + encoded[1:]
    else:
        decoded = encoded
    return decoded


# Convenience functions
def get_recent_prompts(days: int = 7) -> List[HistoryEntry]:
    """Quick access to recent prompts."""
    return ConversationHistory().get_all_prompts(days=days)


def get_project_conversations(project_name: str, days: int = 7) -> List[ConversationSession]:
    """Quick access to project conversations."""
    return ConversationHistory().get_project_sessions(project_name, days=days)
