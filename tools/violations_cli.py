#!/usr/bin/env python3
"""
Violations CLI - View communication law violations.

View and analyze blocked messages and rule violations in Agent Ant Colony.

Usage:
    python violations_cli.py                    # Show recent violations
    python violations_cli.py --stats            # Show violation statistics
    python violations_cli.py --sender Worker-5  # Filter by sender
    python violations_cli.py --limit 100        # Show more violations
    python violations_cli.py --tail             # Watch for new violations
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.shared.comm_laws import (
    read_violations_from_log,
    get_violation_stats_from_log,
    get_violations_report,
    VIOLATION_LOG_FILE,
)


def format_violation(v: dict) -> str:
    """Format a single violation for display."""
    ts = v.get("timestamp", "unknown")
    if isinstance(ts, str) and "T" in ts:
        ts = ts.replace("T", " ").split(".")[0]

    sender = v.get("sender_id", "?")
    sender_role = v.get("sender_role", "?")
    recipient = v.get("recipient_id", "?")
    recipient_role = v.get("recipient_role", "?")
    reason = v.get("reason", "Unknown reason")
    channel = v.get("channel")
    preview = v.get("message_preview", "")

    lines = [
        f"[{ts}] {sender} ({sender_role}) -> {recipient} ({recipient_role})",
        f"  Reason: {reason}",
    ]

    if channel:
        lines.append(f"  Channel: {channel}")

    if preview:
        lines.append(f"  Preview: {preview[:60]}...")

    return "\n".join(lines)


def show_violations(limit: int = 50, sender: str = None):
    """Show recent violations."""
    print(f"\n=== Communication Law Violations ===")
    print(f"Log file: {VIOLATION_LOG_FILE}")
    print()

    violations = read_violations_from_log(limit=limit, sender_filter=sender)

    if not violations:
        print("No violations found.")
        return

    print(f"Showing {len(violations)} violations:\n")

    for v in violations:
        print(format_violation(v))
        print()


def show_stats():
    """Show violation statistics."""
    print(f"\n=== Violation Statistics ===")
    print(f"Log file: {VIOLATION_LOG_FILE}")
    print()

    stats = get_violation_stats_from_log()

    if not stats.get("exists"):
        print("No violation log file found.")
        return

    print(f"Total violations: {stats.get('total_violations', 0)}")
    print(f"Unique senders: {stats.get('unique_senders', 0)}")
    print()

    # Top offenders
    offenders = stats.get("top_offenders", [])
    if offenders:
        print("Top Offenders:")
        for o in offenders[:10]:
            print(f"  - {o['sender']}: {o['count']} violations")
        print()

    # By sender role
    by_role = stats.get("violations_by_sender_role", {})
    if by_role:
        print("Violations by Sender Role:")
        for role, count in sorted(by_role.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {role}: {count}")
        print()

    # By blocked recipient role
    by_blocked = stats.get("violations_by_blocked_recipient_role", {})
    if by_blocked:
        print("Blocked Recipients by Role:")
        for role, count in sorted(by_blocked.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {role}: {count}")
        print()

    # Recent violations
    recent = stats.get("recent_violations", [])
    if recent:
        print("Most Recent Violations:")
        for v in recent[-3:]:
            print(f"  {format_violation(v)}")
            print()


def tail_violations(interval: float = 2.0):
    """Watch for new violations in real-time."""
    print(f"\n=== Watching for Violations ===")
    print(f"Log file: {VIOLATION_LOG_FILE}")
    print("Press Ctrl+C to stop.\n")

    last_count = 0

    try:
        while True:
            violations = read_violations_from_log(limit=1000)
            current_count = len(violations)

            if current_count > last_count:
                new_violations = violations[last_count:]
                for v in new_violations:
                    print(format_violation(v))
                    print()
                last_count = current_count

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")


def show_memory_report():
    """Show in-memory violation report (current session)."""
    print(f"\n=== In-Memory Violation Report ===")
    print("(Current session only)\n")

    report = get_violations_report()

    print(f"Total violations: {report.get('total_violations', 0)}")
    print(f"Unique offenders: {report.get('unique_offenders', 0)}")
    print()

    offenders = report.get("top_offenders", [])
    if offenders:
        print("Top Offenders:")
        for o in offenders:
            print(f"  - {o['agent_id']}: {o['count']} violations")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="View communication law violations in Agent Ant Colony"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show violation statistics",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Show in-memory report (current session only)",
    )
    parser.add_argument(
        "--tail",
        action="store_true",
        help="Watch for new violations in real-time",
    )
    parser.add_argument(
        "--sender",
        type=str,
        help="Filter violations by sender ID (e.g., Worker-5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of violations to show (default: 50)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval for --tail mode (default: 2.0 seconds)",
    )

    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.memory:
        show_memory_report()
    elif args.tail:
        tail_violations(args.interval)
    else:
        show_violations(limit=args.limit, sender=args.sender)


if __name__ == "__main__":
    main()
