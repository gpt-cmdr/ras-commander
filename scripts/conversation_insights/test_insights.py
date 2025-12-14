#!/usr/bin/env python3
"""
test_insights.py

Test script for the Conversation Insights system.
Run from repository root: python scripts/conversation_insights/test_insights.py
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from conversation_parser import ConversationHistory, HistoryEntry, encode_project_path
from pattern_analyzer import PatternAnalyzer
from insight_extractor import InsightExtractor
from report_generator import ReportGenerator


def test_conversation_history():
    """Test ConversationHistory class."""
    print("=" * 60)
    print("Testing ConversationHistory")
    print("=" * 60)

    history = ConversationHistory()

    # Test history file exists
    print(f"\nHistory file: {history.history_file}")
    print(f"Exists: {history.history_file.exists()}")

    if not history.history_file.exists():
        print("ERROR: History file not found!")
        return False

    # Get all prompts
    all_prompts = history.get_all_prompts()
    print(f"\nTotal prompts: {len(all_prompts)}")

    # Get recent prompts
    recent = history.get_all_prompts(days=7)
    print(f"Prompts (last 7 days): {len(recent)}")

    # Show sample
    if recent:
        print(f"\nMost recent prompt:")
        print(f"  Time: {recent[0].timestamp}")
        print(f"  Project: {recent[0].project_name}")
        print(f"  Display: {recent[0].display[:100]}...")

    # Get projects
    projects = history.get_projects()
    print(f"\nProjects found: {len(projects)}")
    for proj in projects[:5]:
        print(f"  - {proj}")
    if len(projects) > 5:
        print(f"  ... and {len(projects) - 5} more")

    return True


def test_pattern_analyzer():
    """Test PatternAnalyzer class."""
    print("\n" + "=" * 60)
    print("Testing PatternAnalyzer")
    print("=" * 60)

    history = ConversationHistory()
    analyzer = PatternAnalyzer(history)

    # Find slash command candidates
    candidates = analyzer.find_slash_command_candidates(days=30)
    print(f"\nSlash command candidates found: {len(candidates)}")

    for candidate in candidates[:5]:
        print(f"\n  {candidate.command_name} ({candidate.frequency} uses)")
        print(f"    Priority: {candidate.priority}")
        print(f"    Category: {candidate.category}")
        print(f"    Implementation: {candidate.suggested_implementation[:60]}...")

    # Analyze project activity
    prompts = history.get_all_prompts(days=30)
    activity = analyzer.analyze_project_activity(prompts)
    print(f"\nProject activity (last 30 days):")
    for proj in activity[:5]:
        print(f"  - {proj.project_name}: {proj.prompt_count} prompts")

    # Word frequency
    word_freq = analyzer.analyze_word_frequency(prompts)
    print(f"\nTop words:")
    for word, count in word_freq[:10]:
        print(f"  - {word}: {count}")

    return True


def test_insight_extractor():
    """Test InsightExtractor class."""
    print("\n" + "=" * 60)
    print("Testing InsightExtractor")
    print("=" * 60)

    history = ConversationHistory()
    extractor = InsightExtractor(history)

    # Find the ras-commander project
    projects = history.get_projects()
    ras_project = None
    for proj in projects:
        if "ras-commander" in proj.lower() and "example" not in proj.lower():
            ras_project = proj
            break

    if not ras_project:
        print("ras-commander project not found in history")
        return False

    print(f"\nAnalyzing project: {ras_project}")

    # Extract insights
    insights = extractor.extract_all_insights(ras_project, days=30, max_sessions=10)

    print(f"\nSessions analyzed: {insights.get('sessions_analyzed', 0)}")
    print(f"Messages analyzed: {insights.get('total_messages_analyzed', 0)}")
    print(f"Blockers found: {len(insights.get('blockers', []))}")
    print(f"Best practices: {len(insights.get('best_practices', []))}")
    print(f"Design patterns: {len(insights.get('design_patterns', []))}")
    print(f"Anti-patterns: {len(insights.get('anti_patterns', []))}")

    # Show sample blocker
    blockers = insights.get('blockers', [])
    if blockers:
        b = blockers[0]
        print(f"\nSample blocker:")
        print(f"  Category: {b.get('category', 'unknown')}")
        print(f"  Problem: {b.get('problem', '')[:100]}...")

    return True


def test_report_generator():
    """Test ReportGenerator class."""
    print("\n" + "=" * 60)
    print("Testing ReportGenerator")
    print("=" * 60)

    generator = ReportGenerator()

    # Generate quick report
    print("\nGenerating quick report...")
    quick_report = generator.generate_quick_report(days=7)
    print(f"Quick report length: {len(quick_report)} characters")
    print("\n--- Quick Report Preview ---")
    print(quick_report[:1000])
    print("...")

    return True


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("CONVERSATION INSIGHTS TEST SUITE")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}

    try:
        results['history'] = test_conversation_history()
    except Exception as e:
        print(f"ERROR in test_conversation_history: {e}")
        results['history'] = False

    try:
        results['patterns'] = test_pattern_analyzer()
    except Exception as e:
        print(f"ERROR in test_pattern_analyzer: {e}")
        results['patterns'] = False

    try:
        results['insights'] = test_insight_extractor()
    except Exception as e:
        print(f"ERROR in test_insight_extractor: {e}")
        results['insights'] = False

    try:
        results['reports'] = test_report_generator()
    except Exception as e:
        print(f"ERROR in test_report_generator: {e}")
        results['reports'] = False

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + ("ALL TESTS PASSED!" if all_passed else "SOME TESTS FAILED!"))

    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
