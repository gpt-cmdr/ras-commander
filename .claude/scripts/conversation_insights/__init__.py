"""
Conversation Insights - Claude Code Conversation History Analysis

A recursive learning system that extracts insights from Claude Code conversation history.

Components:
- conversation_parser: Parse history.jsonl and conversation files
- pattern_analyzer: Find repetitive patterns and slash command candidates
- insight_extractor: Extract blockers, best practices, and design patterns
- report_generator: Generate markdown reports

Usage:
    from conversation_insights import ConversationHistory, InsightAnalyzer

    history = ConversationHistory()
    analyzer = InsightAnalyzer(history)
    report = analyzer.generate_report(days=7)
"""

from .conversation_parser import ConversationHistory, ConversationMessage
from .pattern_analyzer import PatternAnalyzer, SlashCommandCandidate
from .insight_extractor import InsightExtractor, Blocker, BestPractice, DesignPattern
from .report_generator import ReportGenerator

__version__ = "1.0.0"
__all__ = [
    "ConversationHistory",
    "ConversationMessage",
    "PatternAnalyzer",
    "SlashCommandCandidate",
    "InsightExtractor",
    "Blocker",
    "BestPractice",
    "DesignPattern",
    "ReportGenerator",
]
