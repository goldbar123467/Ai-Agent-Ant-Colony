#!/usr/bin/env python3
"""
Survey CLI - Command line tool to trigger status surveys.

Usage:
    python survey_cli.py

This script triggers a pulse survey across all agents in the swarm,
collects responses, and displays a summary.
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.shared.status_survey import StatusSurveySystem


def format_percentage(value: float) -> str:
    """Format a percentage value."""
    return f"{value:.1f}%"


def print_role_observations(by_role: Dict[str, Any], limit_per_role: int = 2) -> None:
    """Print notable observations grouped by role."""
    print("\nNotable Observations by Role:")
    print("-" * 40)

    for role, data in sorted(by_role.items()):
        observations = data.get("observations", [])
        if not observations:
            continue

        print(f"\n  {role.upper()} ({data['count']} responses):")

        # Show first N observations
        for obs in observations[:limit_per_role]:
            agent_id = obs.get("agent_id", "unknown")
            text = obs.get("text", "").strip()
            if text:
                # Truncate long observations
                if len(text) > 100:
                    text = text[:97] + "..."
                print(f"    - [{agent_id}] {text}")


def print_role_suggestions(by_role: Dict[str, Any], limit_per_role: int = 2) -> None:
    """Print suggestions grouped by role."""
    print("\nTop Suggestions by Role:")
    print("-" * 40)

    for role, data in sorted(by_role.items()):
        suggestions = data.get("suggestions", [])
        if not suggestions:
            continue

        print(f"\n  {role.upper()}:")

        for sug in suggestions[:limit_per_role]:
            agent_id = sug.get("agent_id", "unknown")
            text = sug.get("text", "").strip()
            if text:
                if len(text) > 100:
                    text = text[:97] + "..."
                print(f"    - [{agent_id}] {text}")


async def run_survey() -> None:
    """Run the survey and display results."""
    print("=" * 60)
    print("  Agent Ant Colony Status Survey")
    print("=" * 60)
    print()

    # Initialize survey system
    survey_system = StatusSurveySystem()

    print("Triggering survey across all agents...")
    print("(Waiting 30 seconds for responses)")
    print()

    # Trigger survey
    try:
        summary = await survey_system.trigger_survey(
            response_window=30.0,
            expected_agents=30,
        )
    except Exception as e:
        print(f"Error triggering survey: {e}")
        return

    # Display results
    print()
    print("=" * 60)
    print("  Survey Results")
    print("=" * 60)
    print()

    print(f"Survey ID:        {summary.get('survey_id', 'N/A')}")
    print(f"Response Rate:    {format_percentage(summary.get('response_rate', 0) * 100)}")
    print(f"Responses:        {summary.get('response_count', 0)} / 30 agents")
    print()

    print("Quantitative Summary:")
    print("-" * 40)
    print(f"  Tasks Clear:    {format_percentage(summary.get('tasks_clear_percentage', 0))}")
    print(f"  Had Blockers:   {format_percentage(summary.get('blockers_percentage', 0))}")
    print()

    # Print role breakdown
    by_role = summary.get("by_role", {})

    if by_role:
        print("Response Breakdown by Role:")
        print("-" * 40)
        for role, data in sorted(by_role.items()):
            count = data.get("count", 0)
            clear = data.get("tasks_clear", 0)
            blockers = data.get("had_blockers", 0)
            clear_pct = (clear / count * 100) if count > 0 else 0
            blocker_pct = (blockers / count * 100) if count > 0 else 0
            print(f"  {role:15} {count:3} responses | Clear: {clear_pct:5.1f}% | Blockers: {blocker_pct:5.1f}%")

        # Print observations (limit 2 per role)
        print_role_observations(by_role, limit_per_role=2)

        # Print suggestions (limit 2 per role)
        print_role_suggestions(by_role, limit_per_role=2)

    print()
    print("-" * 40)
    print(f"Report saved to: {summary.get('report_path', 'N/A')}")
    print()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(run_survey())
    except KeyboardInterrupt:
        print("\nSurvey cancelled.")
        sys.exit(1)


if __name__ == "__main__":
    main()
