"""
insight_extractor.py

Extracts insights from conversation content including:
- Blockers and their resolutions
- Best practices
- Design patterns and anti-patterns
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from pathlib import Path
from datetime import datetime

try:
    from .conversation_parser import (
        ConversationHistory,
        ConversationSession,
        ConversationMessage,
        MessageType
    )
except ImportError:
    from conversation_parser import (
        ConversationHistory,
        ConversationSession,
        ConversationMessage,
        MessageType
    )


@dataclass
class Blocker:
    """Represents a blocking issue and its resolution."""
    category: str
    problem: str
    root_cause: Optional[str]
    solution: str
    prevention: Optional[str]
    frequency: int
    session_ids: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "category": self.category,
            "problem": self.problem,
            "root_cause": self.root_cause,
            "solution": self.solution,
            "prevention": self.prevention,
            "frequency": self.frequency,
            "session_ids": self.session_ids[:5],
            "keywords": self.keywords
        }


@dataclass
class BestPractice:
    """Represents a best practice extracted from conversations."""
    category: str
    practice: str
    rationale: str
    implementation: Optional[str]
    session_ids: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "category": self.category,
            "practice": self.practice,
            "rationale": self.rationale,
            "implementation": self.implementation,
            "session_ids": self.session_ids[:3],
            "evidence": self.evidence[:3]
        }


@dataclass
class DesignPattern:
    """Represents a design pattern or anti-pattern."""
    name: str
    pattern_type: str  # "pattern" or "anti-pattern"
    category: str  # "code", "workflow", "documentation", "testing"
    description: str
    examples: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)  # For patterns
    problems: List[str] = field(default_factory=list)  # For anti-patterns
    alternative: Optional[str] = None  # For anti-patterns
    session_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        result = {
            "name": self.name,
            "type": self.pattern_type,
            "category": self.category,
            "description": self.description,
            "examples": self.examples[:3],
            "session_ids": self.session_ids[:3]
        }
        if self.pattern_type == "pattern":
            result["benefits"] = self.benefits
        else:
            result["problems"] = self.problems
            result["alternative"] = self.alternative
        return result


class InsightExtractor:
    """
    Extracts insights from conversation content.

    Uses keyword matching and pattern recognition to identify:
    - Blocking issues and resolutions
    - Best practices that were established
    - Design patterns and anti-patterns discussed
    """

    # Keywords indicating problems/blockers
    PROBLEM_KEYWORDS = [
        "doesn't work", "not working", "failed", "error", "bug",
        "issue", "problem", "broken", "crash", "exception",
        "wrong", "incorrect", "unexpected", "confused", "stuck",
        "can't", "cannot", "unable", "impossible", "blocked"
    ]

    # Keywords indicating solutions
    SOLUTION_KEYWORDS = [
        "fixed", "solved", "solution", "works now", "working now",
        "the fix", "resolved", "figured out", "found the issue",
        "the answer", "turns out", "the trick", "workaround",
        "finally", "success", "got it working"
    ]

    # Keywords indicating best practices
    BEST_PRACTICE_KEYWORDS = [
        "best practice", "should always", "always use", "never use",
        "recommended", "prefer", "important to", "make sure to",
        "don't forget", "remember to", "key is to", "the pattern is"
    ]

    # Keywords indicating patterns
    PATTERN_KEYWORDS = [
        "pattern", "approach", "strategy", "method", "technique",
        "way to", "how to", "standard", "convention", "practice"
    ]

    # Keywords indicating anti-patterns
    ANTI_PATTERN_KEYWORDS = [
        "don't do", "avoid", "wrong way", "bad practice", "anti-pattern",
        "mistake", "pitfall", "gotcha", "trap", "common error"
    ]

    # Category mapping based on keywords
    CATEGORY_KEYWORDS = {
        "remote_execution": ["remote", "psexec", "ssh", "worker", "session_id"],
        "hdf_files": ["hdf", "h5py", "results", "extraction"],
        "geometry": ["geometry", "cross section", "mesh", "2d area"],
        "documentation": ["documentation", "readme", "mkdocs", "notebook"],
        "testing": ["test", "pytest", "example", "validation"],
        "git": ["git", "commit", "branch", "merge", "push"],
        "imports": ["import", "module", "package", "dependency"],
        "paths": ["path", "file", "directory", "folder"],
        "execution": ["execute", "run", "compute", "plan"]
    }

    def __init__(self, history: Optional[ConversationHistory] = None):
        """Initialize InsightExtractor."""
        self.history = history or ConversationHistory()

    def extract_all_insights(
        self,
        project_name: str,
        days: Optional[int] = None,
        max_sessions: int = 50
    ) -> Dict:
        """
        Extract all insights from a project's conversations.

        Args:
            project_name: Encoded project name
            days: Only analyze last N days
            max_sessions: Maximum number of sessions to analyze

        Returns:
            Dictionary containing all extracted insights
        """
        sessions = self.history.get_project_sessions(
            project_name,
            include_agents=False,
            days=days
        )[:max_sessions]

        all_blockers = []
        all_practices = []
        all_patterns = []

        for session in sessions:
            # Extract from user messages (faster, captures intent)
            user_messages = self.history.get_user_messages(session.file_path)

            blockers = self._extract_blockers_from_messages(
                user_messages, session.session_id
            )
            all_blockers.extend(blockers)

            practices = self._extract_practices_from_messages(
                user_messages, session.session_id
            )
            all_practices.extend(practices)

            patterns = self._extract_patterns_from_messages(
                user_messages, session.session_id
            )
            all_patterns.extend(patterns)

        # Deduplicate and merge similar insights
        blockers = self._merge_similar_blockers(all_blockers)
        practices = self._merge_similar_practices(all_practices)
        patterns = self._merge_similar_patterns(all_patterns)

        return {
            "blockers": [b.to_dict() for b in blockers],
            "best_practices": [p.to_dict() for p in practices],
            "design_patterns": [p.to_dict() for p in patterns if p.pattern_type == "pattern"],
            "anti_patterns": [p.to_dict() for p in patterns if p.pattern_type == "anti-pattern"],
            "sessions_analyzed": len(sessions),
            "total_messages_analyzed": sum(s.user_message_count for s in sessions)
        }

    def _extract_blockers_from_messages(
        self,
        messages: List[ConversationMessage],
        session_id: str
    ) -> List[Blocker]:
        """Extract blockers from a list of messages."""
        blockers = []

        for i, msg in enumerate(messages):
            content = msg.content.lower()

            # Check for problem indicators
            has_problem = any(kw in content for kw in self.PROBLEM_KEYWORDS)
            if not has_problem:
                continue

            # Try to find solution in subsequent messages
            solution = None
            for j in range(i + 1, min(i + 10, len(messages))):
                later_content = messages[j].content.lower()
                if any(kw in later_content for kw in self.SOLUTION_KEYWORDS):
                    solution = messages[j].content[:300]
                    break

            if solution:
                category = self._categorize_content(msg.content)
                blockers.append(Blocker(
                    category=category,
                    problem=msg.content[:300],
                    root_cause=None,
                    solution=solution,
                    prevention=None,
                    frequency=1,
                    session_ids=[session_id],
                    keywords=self._extract_keywords(msg.content)
                ))

        return blockers

    def _extract_practices_from_messages(
        self,
        messages: List[ConversationMessage],
        session_id: str
    ) -> List[BestPractice]:
        """Extract best practices from messages."""
        practices = []

        for msg in messages:
            content = msg.content.lower()

            # Check for best practice indicators
            if not any(kw in content for kw in self.BEST_PRACTICE_KEYWORDS):
                continue

            category = self._categorize_content(msg.content)

            # Extract the practice statement
            practice_text = msg.content[:400]
            for kw in self.BEST_PRACTICE_KEYWORDS:
                if kw in content:
                    # Try to extract text after the keyword
                    idx = content.find(kw)
                    if idx != -1:
                        practice_text = msg.content[idx:idx + 200]
                        break

            practices.append(BestPractice(
                category=category,
                practice=practice_text,
                rationale="Extracted from conversation",
                implementation=None,
                session_ids=[session_id],
                evidence=[msg.content[:200]]
            ))

        return practices

    def _extract_patterns_from_messages(
        self,
        messages: List[ConversationMessage],
        session_id: str
    ) -> List[DesignPattern]:
        """Extract design patterns and anti-patterns from messages."""
        patterns = []

        for msg in messages:
            content = msg.content.lower()

            # Check for anti-pattern indicators
            is_anti = any(kw in content for kw in self.ANTI_PATTERN_KEYWORDS)

            # Check for pattern indicators
            is_pattern = any(kw in content for kw in self.PATTERN_KEYWORDS)

            if not (is_anti or is_pattern):
                continue

            category = self._categorize_content(msg.content)
            pattern_type = "anti-pattern" if is_anti else "pattern"

            # Try to extract pattern name
            name = self._extract_pattern_name(msg.content)

            patterns.append(DesignPattern(
                name=name,
                pattern_type=pattern_type,
                category=category,
                description=msg.content[:300],
                examples=[msg.content[:150]],
                benefits=[] if is_anti else ["Mentioned as good practice"],
                problems=["Mentioned as issue to avoid"] if is_anti else [],
                alternative=None,
                session_ids=[session_id]
            ))

        return patterns

    def _categorize_content(self, content: str) -> str:
        """Categorize content based on keywords."""
        content_lower = content.lower()

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in content_lower for kw in keywords):
                return category

        return "general"

    def _extract_keywords(self, content: str) -> List[str]:
        """Extract relevant keywords from content."""
        # Find technical terms (CamelCase, snake_case, etc.)
        camel = re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b", content)
        snake = re.findall(r"\b[a-z]+_[a-z_]+\b", content)

        keywords = list(set(camel + snake))
        return keywords[:10]

    def _extract_pattern_name(self, content: str) -> str:
        """Try to extract a pattern name from content."""
        # Look for quoted names
        quoted = re.findall(r'"([^"]+)"', content)
        if quoted:
            return quoted[0][:50]

        # Look for capitalized phrases
        caps = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", content)
        if caps:
            return caps[0]

        # Default: first few words
        words = content.split()[:5]
        return " ".join(words)

    def _merge_similar_blockers(self, blockers: List[Blocker]) -> List[Blocker]:
        """Merge similar blockers based on keywords."""
        if not blockers:
            return []

        merged = []
        used = set()

        for i, b1 in enumerate(blockers):
            if i in used:
                continue

            # Find similar blockers
            similar_ids = [b1.session_ids[0]] if b1.session_ids else []
            frequency = b1.frequency

            for j, b2 in enumerate(blockers[i + 1:], i + 1):
                if j in used:
                    continue

                # Check similarity based on category and keywords
                if b1.category == b2.category:
                    keyword_overlap = set(b1.keywords) & set(b2.keywords)
                    if keyword_overlap or self._text_similarity(b1.problem, b2.problem) > 0.5:
                        used.add(j)
                        similar_ids.extend(b2.session_ids)
                        frequency += b2.frequency

            merged.append(Blocker(
                category=b1.category,
                problem=b1.problem,
                root_cause=b1.root_cause,
                solution=b1.solution,
                prevention=b1.prevention,
                frequency=frequency,
                session_ids=list(set(similar_ids)),
                keywords=list(set(b1.keywords))
            ))

        # Sort by frequency
        merged.sort(key=lambda x: -x.frequency)
        return merged[:20]

    def _merge_similar_practices(self, practices: List[BestPractice]) -> List[BestPractice]:
        """Merge similar best practices."""
        if not practices:
            return []

        merged = []
        used = set()

        for i, p1 in enumerate(practices):
            if i in used:
                continue

            similar_ids = list(p1.session_ids)

            for j, p2 in enumerate(practices[i + 1:], i + 1):
                if j in used:
                    continue

                if p1.category == p2.category:
                    if self._text_similarity(p1.practice, p2.practice) > 0.4:
                        used.add(j)
                        similar_ids.extend(p2.session_ids)

            merged.append(BestPractice(
                category=p1.category,
                practice=p1.practice,
                rationale=p1.rationale,
                implementation=p1.implementation,
                session_ids=list(set(similar_ids)),
                evidence=p1.evidence
            ))

        return merged[:15]

    def _merge_similar_patterns(self, patterns: List[DesignPattern]) -> List[DesignPattern]:
        """Merge similar patterns."""
        if not patterns:
            return []

        merged = []
        used = set()

        for i, p1 in enumerate(patterns):
            if i in used:
                continue

            similar_ids = list(p1.session_ids)
            examples = list(p1.examples)

            for j, p2 in enumerate(patterns[i + 1:], i + 1):
                if j in used:
                    continue

                if p1.pattern_type == p2.pattern_type and p1.category == p2.category:
                    if self._text_similarity(p1.name, p2.name) > 0.3:
                        used.add(j)
                        similar_ids.extend(p2.session_ids)
                        examples.extend(p2.examples)

            merged.append(DesignPattern(
                name=p1.name,
                pattern_type=p1.pattern_type,
                category=p1.category,
                description=p1.description,
                examples=list(set(examples))[:5],
                benefits=p1.benefits,
                problems=p1.problems,
                alternative=p1.alternative,
                session_ids=list(set(similar_ids))
            ))

        return merged[:20]

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity (Jaccard)."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def search_conversations_for_topic(
        self,
        project_name: str,
        topic: str,
        days: Optional[int] = None
    ) -> List[Dict]:
        """
        Search conversations for a specific topic.

        Args:
            project_name: Encoded project name
            topic: Topic/keyword to search for
            days: Only search last N days

        Returns:
            List of matching conversation summaries
        """
        sessions = self.history.get_project_sessions(
            project_name,
            include_agents=False,
            days=days
        )

        matches = []
        topic_lower = topic.lower()

        for session in sessions:
            # Check first prompt for quick filtering
            if session.first_prompt and topic_lower in session.first_prompt.lower():
                matches.append({
                    "session_id": session.session_id,
                    "first_prompt": session.first_prompt,
                    "timestamp": session.first_timestamp.isoformat() if session.first_timestamp else None,
                    "message_count": session.message_count,
                    "match_in": "first_prompt"
                })
                continue

            # Search through user messages
            for msg in self.history.get_user_messages(session.file_path):
                if topic_lower in msg.content.lower():
                    matches.append({
                        "session_id": session.session_id,
                        "first_prompt": session.first_prompt,
                        "timestamp": session.first_timestamp.isoformat() if session.first_timestamp else None,
                        "message_count": session.message_count,
                        "match_in": "user_message",
                        "matched_content": msg.content[:200]
                    })
                    break

        return matches

    def get_conversation_summary(
        self,
        session_path: Path,
        max_length: int = 500
    ) -> str:
        """
        Generate a brief summary of a conversation.

        Args:
            session_path: Path to conversation file
            max_length: Maximum summary length

        Returns:
            Brief summary string
        """
        user_messages = self.history.get_user_messages(session_path)

        if not user_messages:
            return "Empty conversation"

        # Get key messages
        first_msg = user_messages[0].content[:200] if user_messages else ""
        last_msg = user_messages[-1].content[:200] if len(user_messages) > 1 else ""

        # Extract topics
        all_content = " ".join(m.content for m in user_messages[:10])
        keywords = self._extract_keywords(all_content)

        summary_parts = [
            f"Started with: {first_msg}",
        ]

        if keywords:
            summary_parts.append(f"Keywords: {', '.join(keywords[:5])}")

        if last_msg and last_msg != first_msg:
            summary_parts.append(f"Ended with: {last_msg}")

        summary = " | ".join(summary_parts)
        return summary[:max_length]
