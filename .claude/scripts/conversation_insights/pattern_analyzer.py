"""
pattern_analyzer.py

Analyzes conversation history for repetitive patterns and slash command candidates.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path

try:
    from .conversation_parser import ConversationHistory, HistoryEntry
except ImportError:
    from conversation_parser import ConversationHistory, HistoryEntry


@dataclass
class SlashCommandCandidate:
    """A potential slash command based on repetitive user patterns."""
    command_name: str
    trigger_phrases: List[str]
    frequency: int
    example_uses: List[str]
    suggested_implementation: str
    priority: str  # "high", "medium", "low"
    category: str  # "workflow", "tool", "query", "action"

    def to_dict(self) -> Dict:
        return {
            "command_name": self.command_name,
            "trigger_phrases": self.trigger_phrases,
            "frequency": self.frequency,
            "example_uses": self.example_uses[:5],
            "suggested_implementation": self.suggested_implementation,
            "priority": self.priority,
            "category": self.category
        }


@dataclass
class ProjectActivity:
    """Activity statistics for a project."""
    project_name: str
    encoded_name: str
    prompt_count: int
    first_activity: str
    last_activity: str
    top_topics: List[str] = field(default_factory=list)


class PatternAnalyzer:
    """
    Analyzes conversation patterns to identify:
    - Repetitive commands (slash command candidates)
    - Common workflows
    - Frequently used phrases
    - Project activity distribution
    """

    # Known command patterns to look for
    KNOWN_PATTERNS = {
        "ultrathink": {
            "regex": r"\bultrathink\b",
            "command": "/ultrathink",
            "implementation": "Enable extended thinking mode with high-level analysis",
            "category": "workflow"
        },
        "deep_research": {
            "regex": r"\bdeep\s*research\b",
            "command": "/deep-research",
            "implementation": "Enable comprehensive research mode with multiple sources",
            "category": "workflow"
        },
        "run_build": {
            "regex": r"\b(run|execute)\s+(the\s+)?build\b",
            "command": "/build",
            "implementation": "Execute project build command (npm build, python setup.py, etc.)",
            "category": "action"
        },
        "run_tests": {
            "regex": r"\b(run|execute)\s+(the\s+)?(tests?|test\s*suite)\b",
            "command": "/test",
            "implementation": "Execute project test command (pytest, npm test, etc.)",
            "category": "action"
        },
        "commit": {
            "regex": r"\b(commit|create\s+a?\s*commit)\b.*changes?",
            "command": "/commit",
            "implementation": "Git commit workflow with message generation",
            "category": "action"
        },
        "plan_mode": {
            "regex": r"\b(enter\s+)?plan\s*mode\b",
            "command": "/plan",
            "implementation": "Enter planning mode for implementation design",
            "category": "workflow"
        },
        "brainstorm": {
            "regex": r"\bbrainstorm\b",
            "command": "/brainstorm",
            "implementation": "Creative ideation mode with multiple options",
            "category": "workflow"
        },
        "summarize": {
            "regex": r"\b(summarize|summary\s+of)\b",
            "command": "/summarize",
            "implementation": "Create concise summary of code/conversation",
            "category": "query"
        },
        "review": {
            "regex": r"\breview\s+(the\s+)?(code|changes|pr)\b",
            "command": "/review",
            "implementation": "Code review with suggestions",
            "category": "action"
        },
        "explain": {
            "regex": r"\bexplain\s+(this|the|how)\b",
            "command": "/explain",
            "implementation": "Detailed explanation of code or concept",
            "category": "query"
        },
        "fix": {
            "regex": r"\bfix\s+(this|the|all)\s*(error|bug|issue)s?\b",
            "command": "/fix",
            "implementation": "Identify and fix errors in code",
            "category": "action"
        },
        "refactor": {
            "regex": r"\brefactor\b",
            "command": "/refactor",
            "implementation": "Improve code structure without changing behavior",
            "category": "action"
        },
        "document": {
            "regex": r"\b(add|write|create)\s+(documentation|docstrings?|docs)\b",
            "command": "/document",
            "implementation": "Generate documentation for code",
            "category": "action"
        }
    }

    def __init__(self, history: Optional[ConversationHistory] = None):
        """
        Initialize PatternAnalyzer.

        Args:
            history: ConversationHistory instance (creates new if None)
        """
        self.history = history or ConversationHistory()

    def analyze_patterns(
        self,
        days: Optional[int] = None,
        project_filter: Optional[str] = None
    ) -> Dict:
        """
        Perform comprehensive pattern analysis.

        Args:
            days: Only analyze last N days
            project_filter: Only analyze specific project

        Returns:
            Dictionary with analysis results
        """
        prompts = self.history.get_all_prompts(days=days, project_filter=project_filter)

        return {
            "total_prompts": len(prompts),
            "time_range": self._get_time_range(prompts),
            "slash_command_candidates": self.find_slash_command_candidates(prompts),
            "project_activity": self.analyze_project_activity(prompts),
            "word_frequency": self.analyze_word_frequency(prompts),
            "action_verbs": self.analyze_action_verbs(prompts),
            "common_phrases": self.find_common_phrases(prompts)
        }

    def find_slash_command_candidates(
        self,
        prompts: Optional[List[HistoryEntry]] = None,
        days: Optional[int] = None,
        min_frequency: int = 3
    ) -> List[SlashCommandCandidate]:
        """
        Find repetitive patterns that could become slash commands.

        Args:
            prompts: List of prompts to analyze (fetches if None)
            days: Only analyze last N days
            min_frequency: Minimum occurrences to be considered

        Returns:
            List of SlashCommandCandidate objects, sorted by priority
        """
        if prompts is None:
            prompts = self.history.get_all_prompts(days=days)

        candidates = []

        # Check known patterns
        for pattern_name, pattern_info in self.KNOWN_PATTERNS.items():
            regex = re.compile(pattern_info["regex"], re.IGNORECASE)
            matches = []

            for entry in prompts:
                if regex.search(entry.display):
                    matches.append(entry.display[:150])

            if len(matches) >= min_frequency:
                priority = "high" if len(matches) >= 10 else "medium" if len(matches) >= 5 else "low"
                candidates.append(SlashCommandCandidate(
                    command_name=pattern_info["command"],
                    trigger_phrases=[pattern_info["regex"]],
                    frequency=len(matches),
                    example_uses=matches[:5],
                    suggested_implementation=pattern_info["implementation"],
                    priority=priority,
                    category=pattern_info["category"]
                ))

        # Find additional patterns through n-gram analysis
        additional = self._find_ngram_patterns(prompts, min_frequency)
        candidates.extend(additional)

        # Sort by frequency descending
        candidates.sort(key=lambda x: (-self._priority_score(x.priority), -x.frequency))

        return candidates

    def _find_ngram_patterns(
        self,
        prompts: List[HistoryEntry],
        min_frequency: int
    ) -> List[SlashCommandCandidate]:
        """Find command-like patterns through n-gram analysis."""
        # Action verbs that often start commands
        action_verbs = {
            "create", "add", "remove", "delete", "update", "modify",
            "show", "list", "find", "search", "get", "fetch",
            "run", "execute", "start", "stop", "restart",
            "check", "verify", "validate", "test",
            "generate", "build", "deploy", "install"
        }

        # Count phrases starting with action verbs
        phrase_counts = Counter()
        phrase_examples = defaultdict(list)

        for entry in prompts:
            words = entry.display.lower().split()
            if not words:
                continue

            # Look for action verb at start or after common prefixes
            start_idx = 0
            if words[0] in {"please", "can", "could", "would", "help"}:
                start_idx = 1
            if len(words) > start_idx + 1 and words[start_idx] in {"you", "me"}:
                start_idx += 1

            if start_idx < len(words) and words[start_idx] in action_verbs:
                # Extract phrase (2-4 words starting with action verb)
                for length in range(2, min(5, len(words) - start_idx + 1)):
                    phrase = " ".join(words[start_idx:start_idx + length])
                    if len(phrase) > 5:  # Minimum meaningful length
                        phrase_counts[phrase] += 1
                        if len(phrase_examples[phrase]) < 5:
                            phrase_examples[phrase].append(entry.display[:150])

        # Convert frequent phrases to candidates
        candidates = []
        seen_commands = set()

        for phrase, count in phrase_counts.most_common(20):
            if count < min_frequency:
                continue

            # Generate command name from phrase
            words = phrase.split()
            if len(words) >= 2:
                cmd_name = "/" + "-".join(words[:2])
            else:
                cmd_name = "/" + words[0]

            # Skip if similar command already exists
            if cmd_name in seen_commands:
                continue
            seen_commands.add(cmd_name)

            # Skip known patterns (already handled)
            if any(re.search(p["regex"], phrase, re.IGNORECASE)
                   for p in self.KNOWN_PATTERNS.values()):
                continue

            priority = "high" if count >= 10 else "medium" if count >= 5 else "low"
            candidates.append(SlashCommandCandidate(
                command_name=cmd_name,
                trigger_phrases=[phrase],
                frequency=count,
                example_uses=phrase_examples[phrase],
                suggested_implementation=f"Automate: {phrase}",
                priority=priority,
                category="action"
            ))

        return candidates

    def _priority_score(self, priority: str) -> int:
        """Convert priority to numeric score."""
        return {"high": 3, "medium": 2, "low": 1}.get(priority, 0)

    def analyze_project_activity(
        self,
        prompts: Optional[List[HistoryEntry]] = None,
        days: Optional[int] = None
    ) -> List[ProjectActivity]:
        """
        Analyze activity distribution across projects.

        Args:
            prompts: List of prompts to analyze
            days: Only analyze last N days

        Returns:
            List of ProjectActivity objects, sorted by activity
        """
        if prompts is None:
            prompts = self.history.get_all_prompts(days=days)

        project_data = defaultdict(lambda: {
            "prompts": [],
            "first": None,
            "last": None
        })

        for entry in prompts:
            proj_name = entry.project_name
            project_data[proj_name]["prompts"].append(entry)

            ts = entry.timestamp
            if project_data[proj_name]["first"] is None or ts < project_data[proj_name]["first"]:
                project_data[proj_name]["first"] = ts
            if project_data[proj_name]["last"] is None or ts > project_data[proj_name]["last"]:
                project_data[proj_name]["last"] = ts

        activities = []
        for proj_name, data in project_data.items():
            if not proj_name:
                continue

            # Extract top topics (first words of prompts)
            topics = Counter()
            for entry in data["prompts"]:
                words = entry.display.split()[:3]
                if words:
                    topics[" ".join(words)] += 1

            try:
                from .conversation_parser import encode_project_path
            except ImportError:
                from conversation_parser import encode_project_path

            activities.append(ProjectActivity(
                project_name=proj_name,
                encoded_name=encode_project_path(data["prompts"][0].project) if data["prompts"] else "",
                prompt_count=len(data["prompts"]),
                first_activity=data["first"].strftime("%Y-%m-%d") if data["first"] else "",
                last_activity=data["last"].strftime("%Y-%m-%d") if data["last"] else "",
                top_topics=[t[0] for t in topics.most_common(3)]
            ))

        activities.sort(key=lambda x: -x.prompt_count)
        return activities

    def analyze_word_frequency(
        self,
        prompts: Optional[List[HistoryEntry]] = None,
        days: Optional[int] = None,
        top_n: int = 50
    ) -> List[Tuple[str, int]]:
        """
        Analyze word frequency in prompts.

        Args:
            prompts: List of prompts to analyze
            days: Only analyze last N days
            top_n: Return top N words

        Returns:
            List of (word, count) tuples
        """
        if prompts is None:
            prompts = self.history.get_all_prompts(days=days)

        # Common words to ignore
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
            "be", "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "shall", "can", "need",
            "it", "its", "this", "that", "these", "those", "i", "you", "he",
            "she", "we", "they", "me", "him", "her", "us", "them", "my", "your",
            "his", "our", "their", "what", "which", "who", "whom", "when",
            "where", "why", "how", "all", "each", "every", "both", "few",
            "more", "most", "other", "some", "such", "no", "not", "only",
            "same", "so", "than", "too", "very", "just", "also", "now", "here",
            "there", "then", "if", "else", "let", "please", "help", "want"
        }

        word_counts = Counter()
        for entry in prompts:
            words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", entry.display.lower())
            for word in words:
                if word not in stop_words and len(word) > 2:
                    word_counts[word] += 1

        return word_counts.most_common(top_n)

    def analyze_action_verbs(
        self,
        prompts: Optional[List[HistoryEntry]] = None,
        days: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Analyze action verbs used in prompts.

        Args:
            prompts: List of prompts to analyze
            days: Only analyze last N days

        Returns:
            Dictionary of verb -> count
        """
        if prompts is None:
            prompts = self.history.get_all_prompts(days=days)

        action_verbs = {
            "create", "add", "remove", "delete", "update", "modify", "change",
            "show", "list", "find", "search", "get", "fetch", "read", "write",
            "run", "execute", "start", "stop", "restart", "deploy",
            "check", "verify", "validate", "test", "debug", "fix",
            "generate", "build", "compile", "install", "configure",
            "explain", "describe", "summarize", "analyze", "review",
            "implement", "refactor", "optimize", "improve", "enhance",
            "commit", "push", "pull", "merge", "branch"
        }

        verb_counts = Counter()
        for entry in prompts:
            words = entry.display.lower().split()
            for word in words:
                # Strip punctuation
                word = re.sub(r"[^\w]", "", word)
                if word in action_verbs:
                    verb_counts[word] += 1

        return dict(verb_counts.most_common())

    def find_common_phrases(
        self,
        prompts: Optional[List[HistoryEntry]] = None,
        days: Optional[int] = None,
        min_length: int = 3,
        max_length: int = 6,
        min_frequency: int = 3,
        top_n: int = 30
    ) -> List[Tuple[str, int]]:
        """
        Find common multi-word phrases.

        Args:
            prompts: List of prompts to analyze
            days: Only analyze last N days
            min_length: Minimum words in phrase
            max_length: Maximum words in phrase
            min_frequency: Minimum occurrences
            top_n: Return top N phrases

        Returns:
            List of (phrase, count) tuples
        """
        if prompts is None:
            prompts = self.history.get_all_prompts(days=days)

        phrase_counts = Counter()

        for entry in prompts:
            words = entry.display.lower().split()

            for n in range(min_length, min(max_length + 1, len(words) + 1)):
                for i in range(len(words) - n + 1):
                    phrase = " ".join(words[i:i + n])
                    # Filter criteria
                    if len(phrase) >= 10:  # Minimum character length
                        phrase_counts[phrase] += 1

        # Filter by minimum frequency
        frequent = [(p, c) for p, c in phrase_counts.items() if c >= min_frequency]
        frequent.sort(key=lambda x: (-x[1], x[0]))

        return frequent[:top_n]

    def _get_time_range(self, prompts: List[HistoryEntry]) -> Dict[str, str]:
        """Get the time range covered by prompts."""
        if not prompts:
            return {"start": "", "end": ""}

        timestamps = [p.timestamp for p in prompts if p.timestamp]
        if not timestamps:
            return {"start": "", "end": ""}

        return {
            "start": min(timestamps).strftime("%Y-%m-%d"),
            "end": max(timestamps).strftime("%Y-%m-%d")
        }

    def generate_quick_report(
        self,
        days: int = 7,
        project_filter: Optional[str] = None
    ) -> str:
        """
        Generate a quick text report of patterns.

        Args:
            days: Number of days to analyze
            project_filter: Optional project filter

        Returns:
            Formatted text report
        """
        analysis = self.analyze_patterns(days=days, project_filter=project_filter)

        lines = [
            f"# Pattern Analysis Report",
            f"",
            f"**Period**: Last {days} days",
            f"**Total Prompts**: {analysis['total_prompts']}",
            f"**Time Range**: {analysis['time_range']['start']} to {analysis['time_range']['end']}",
            f"",
            f"## Slash Command Candidates",
            f""
        ]

        for candidate in analysis["slash_command_candidates"][:10]:
            lines.append(f"- **{candidate.command_name}** ({candidate.frequency} uses) - {candidate.priority} priority")
            lines.append(f"  - {candidate.suggested_implementation}")

        lines.extend([
            f"",
            f"## Project Activity",
            f""
        ])

        for activity in analysis["project_activity"][:5]:
            lines.append(f"- **{activity.project_name}**: {activity.prompt_count} prompts")

        lines.extend([
            f"",
            f"## Top Action Verbs",
            f""
        ])

        verb_items = list(analysis["action_verbs"].items())[:10]
        for verb, count in verb_items:
            lines.append(f"- {verb}: {count}")

        return "\n".join(lines)
