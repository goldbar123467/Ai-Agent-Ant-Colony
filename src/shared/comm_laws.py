"""
Communication Laws - Hierarchy Enforcement for Kyzlo Swarm.

Defines and enforces the communication hierarchy between agents.
Unauthorized messages are blocked and logged for monitoring.
"""

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger()

# Violation log file path
VIOLATION_LOG_DIR = Path("/data/comm_violations")
VIOLATION_LOG_FILE = VIOLATION_LOG_DIR / "violations.jsonl"


# =============================================================================
# Communication Hierarchy Rules
# =============================================================================

# Each role maps to allowed_send_to and allowed_receive_from
# Special tokens:
#   "orchestrator:same_domain" - orchestrator in same domain
#   "worker:same_domain" - workers in same domain
#   "warden:same_domain" - warden in same domain
#   "rag_brain" - external RAG Brain service (special case)

COMMUNICATION_LAWS: Dict[str, Dict[str, List[str]]] = {
    "queen": {
        "allowed_send_to": ["orchestrator"],
        "allowed_receive_from": ["orchestrator", "qa_reporter", "scribe"],
    },
    "orchestrator": {
        "allowed_send_to": ["queen", "worker:same_domain", "warden:same_domain"],
        "allowed_receive_from": ["queen", "worker:same_domain", "warden:same_domain"],
    },
    "worker": {
        "allowed_send_to": ["orchestrator:same_domain", "worker:same_domain", "warden:same_domain"],
        "allowed_receive_from": ["orchestrator:same_domain", "worker:same_domain"],
    },
    "warden": {
        "allowed_send_to": ["orchestrator:same_domain", "qa_reporter"],
        "allowed_receive_from": ["worker:same_domain"],
    },
    "scribe": {
        "allowed_send_to": ["queen", "rag_brain"],
        "allowed_receive_from": ["queen", "orchestrator", "worker", "warden", "qa_reporter"],
    },
    "qa_reporter": {
        "allowed_send_to": ["queen", "scribe"],
        "allowed_receive_from": ["warden"],
    },
}

# Channels that bypass hierarchy checks (system-wide broadcasts)
EXEMPT_CHANNELS: Set[str] = {
    "system",   # System-wide broadcasts (surveys, etc.)
    "status",   # Status updates are read by all
    "alerts",   # Alerts can be read by all
    "debug",    # Debug channel
}


# =============================================================================
# Violation Tracking
# =============================================================================

@dataclass
class CommViolation:
    """Record of a communication law violation."""
    timestamp: datetime
    sender_id: str
    sender_role: str
    sender_domain: Optional[str]
    recipient_id: str
    recipient_role: str
    recipient_domain: Optional[str]
    reason: str
    channel: Optional[str] = None  # For Bridge messages
    message_preview: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "sender_id": self.sender_id,
            "sender_role": self.sender_role,
            "sender_domain": self.sender_domain,
            "recipient_id": self.recipient_id,
            "recipient_role": self.recipient_role,
            "recipient_domain": self.recipient_domain,
            "reason": self.reason,
            "channel": self.channel,
            "message_preview": self.message_preview,
        }


class ViolationTracker:
    """
    Tracks communication law violations.

    Singleton to maintain consistent violation history across the system.
    Writes all violations to a persistent log file for audit.
    """

    _instance: Optional["ViolationTracker"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_history: int = 1000):
        if self._initialized:
            return

        self._violations: Deque[CommViolation] = deque(maxlen=max_history)
        self._violation_counts: Dict[str, int] = {}  # sender_id -> count
        self._initialized = True
        self.log = logger.bind(component="ViolationTracker")

        # Ensure log directory exists
        try:
            VIOLATION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log.error("Failed to create violation log directory", error=str(e))

    def record(self, violation: CommViolation):
        """Record a violation to memory and persistent log."""
        self._violations.append(violation)

        # Track count per sender
        self._violation_counts[violation.sender_id] = (
            self._violation_counts.get(violation.sender_id, 0) + 1
        )

        # Detailed structured log
        self.log.warning(
            "COMM LAW VIOLATION - Message blocked",
            event_type="comm_violation",
            timestamp=violation.timestamp.isoformat(),
            sender_id=violation.sender_id,
            sender_role=violation.sender_role,
            sender_domain=violation.sender_domain,
            recipient_id=violation.recipient_id,
            recipient_role=violation.recipient_role,
            recipient_domain=violation.recipient_domain,
            channel=violation.channel,
            reason=violation.reason,
            message_preview=violation.message_preview,
            total_violations_by_sender=self._violation_counts[violation.sender_id],
        )

        # Write to persistent log file (JSONL format)
        self._write_to_log_file(violation)

    def _write_to_log_file(self, violation: CommViolation):
        """Write a violation to the persistent log file."""
        try:
            log_entry = {
                **violation.to_dict(),
                "logged_at": datetime.utcnow().isoformat(),
            }
            with open(VIOLATION_LOG_FILE, "a") as f:
                f.write(json.dumps(log_entry, default=str) + "\n")
        except Exception as e:
            self.log.error("Failed to write violation to log file", error=str(e))

    def get_recent(self, limit: int = 50) -> List[CommViolation]:
        """Get recent violations."""
        violations = list(self._violations)
        return violations[-limit:]

    def get_by_sender(self, sender_id: str, limit: int = 20) -> List[CommViolation]:
        """Get violations by a specific sender."""
        return [v for v in self._violations if v.sender_id == sender_id][-limit:]

    def get_counts(self) -> Dict[str, int]:
        """Get violation counts per sender."""
        return self._violation_counts.copy()

    def get_top_offenders(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get top violating agents."""
        sorted_counts = sorted(
            self._violation_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_counts[:limit]

    def clear(self):
        """Clear all recorded violations."""
        self._violations.clear()
        self._violation_counts.clear()


# Global tracker instance
_tracker = ViolationTracker()


# =============================================================================
# Validation Functions
# =============================================================================

def parse_agent_identity(agent_id: str) -> Tuple[str, Optional[str]]:
    """
    Parse agent ID to determine role and domain.

    Returns (role, domain) tuple.

    Examples:
        "Queen" -> ("queen", None)
        "Orch-Web" -> ("orchestrator", "web")
        "Worker-3" -> ("worker", "web")  # Workers 1-7 are web
        "Warden-Ai" -> ("warden", "ai")
        "Scribe" -> ("scribe", None)
        "QAReporter" -> ("qa_reporter", None)
    """
    agent_id_lower = agent_id.lower()

    if agent_id_lower == "queen":
        return ("queen", None)

    if agent_id_lower.startswith("orch-"):
        domain = agent_id.split("-")[1].lower()
        return ("orchestrator", domain)

    if agent_id_lower.startswith("worker-"):
        worker_num = int(agent_id.split("-")[1])
        if 1 <= worker_num <= 7:
            domain = "web"
        elif 8 <= worker_num <= 14:
            domain = "ai"
        else:
            domain = "quant"
        return ("worker", domain)

    if agent_id_lower.startswith("warden-"):
        domain = agent_id.split("-")[1].lower()
        return ("warden", domain)

    if agent_id_lower == "scribe":
        return ("scribe", None)

    if agent_id_lower == "qareporter":
        return ("qa_reporter", None)

    if agent_id_lower == "rag_brain" or agent_id_lower == "ragbrain":
        return ("rag_brain", None)

    # Unknown agent - default to worker with no domain
    return ("unknown", None)


def validate_message(
    sender_id: str,
    sender_role: str,
    sender_domain: Optional[str],
    recipient_id: str,
    recipient_role: str,
    recipient_domain: Optional[str],
    channel: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validate if a message is allowed under communication laws.

    Args:
        sender_id: ID of the sending agent
        sender_role: Role of the sender (queen, orchestrator, worker, etc.)
        sender_domain: Domain of the sender (web, ai, quant) or None
        recipient_id: ID of the recipient agent
        recipient_role: Role of the recipient
        recipient_domain: Domain of the recipient or None
        channel: Optional Bridge channel (some channels are exempt)

    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    # Check if channel is exempt from hierarchy rules
    if channel and channel in EXEMPT_CHANNELS:
        return (True, "Channel is exempt from hierarchy rules")

    # Get laws for sender role
    sender_role_lower = sender_role.lower()
    if sender_role_lower not in COMMUNICATION_LAWS:
        return (False, f"Unknown sender role: {sender_role}")

    laws = COMMUNICATION_LAWS[sender_role_lower]
    allowed_recipients = laws["allowed_send_to"]

    recipient_role_lower = recipient_role.lower()

    # Check each allowed recipient pattern
    for pattern in allowed_recipients:
        if ":" in pattern:
            # Domain-scoped pattern (e.g., "worker:same_domain")
            role_part, domain_rule = pattern.split(":")

            if recipient_role_lower != role_part:
                continue

            if domain_rule == "same_domain":
                if sender_domain and recipient_domain:
                    if sender_domain.lower() == recipient_domain.lower():
                        return (True, f"Allowed: {sender_role} can send to {recipient_role} in same domain")
                elif sender_domain is None and recipient_domain is None:
                    # Both have no domain - allow
                    return (True, f"Allowed: {sender_role} can send to {recipient_role}")
        else:
            # Simple role match
            if recipient_role_lower == pattern:
                return (True, f"Allowed: {sender_role} can send to {recipient_role}")

    # Not allowed
    domain_info = ""
    if sender_domain or recipient_domain:
        domain_info = f" (sender domain: {sender_domain}, recipient domain: {recipient_domain})"

    return (
        False,
        f"Forbidden: {sender_role} cannot send to {recipient_role}{domain_info}"
    )


def validate_and_log(
    sender_id: str,
    sender_role: str,
    sender_domain: Optional[str],
    recipient_id: str,
    recipient_role: str,
    recipient_domain: Optional[str],
    channel: Optional[str] = None,
    message_preview: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Validate a message and log violation if disallowed.

    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    allowed, reason = validate_message(
        sender_id=sender_id,
        sender_role=sender_role,
        sender_domain=sender_domain,
        recipient_id=recipient_id,
        recipient_role=recipient_role,
        recipient_domain=recipient_domain,
        channel=channel,
    )

    if not allowed:
        violation = CommViolation(
            timestamp=datetime.utcnow(),
            sender_id=sender_id,
            sender_role=sender_role,
            sender_domain=sender_domain,
            recipient_id=recipient_id,
            recipient_role=recipient_role,
            recipient_domain=recipient_domain,
            reason=reason,
            channel=channel,
            message_preview=message_preview[:100] if message_preview else None,
        )
        _tracker.record(violation)

    return (allowed, reason)


def get_violations_report(limit: int = 50) -> Dict[str, Any]:
    """
    Get a report of recent communication law violations.

    Returns:
        Dictionary with violation statistics and recent violations.
    """
    violations = _tracker.get_recent(limit)
    counts = _tracker.get_counts()
    top_offenders = _tracker.get_top_offenders(10)

    return {
        "total_violations": sum(counts.values()),
        "unique_offenders": len(counts),
        "top_offenders": [
            {"agent_id": agent, "count": count}
            for agent, count in top_offenders
        ],
        "recent_violations": [v.to_dict() for v in violations],
        "log_file": str(VIOLATION_LOG_FILE),
    }


def clear_violations():
    """Clear all recorded violations."""
    _tracker.clear()


def read_violations_from_log(
    limit: int = 100,
    since: Optional[datetime] = None,
    sender_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Read violations from the persistent log file.

    Args:
        limit: Maximum number of violations to return
        since: Only return violations after this timestamp
        sender_filter: Only return violations from this sender

    Returns:
        List of violation records from the log file
    """
    violations = []

    if not VIOLATION_LOG_FILE.exists():
        return violations

    try:
        with open(VIOLATION_LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)

                    # Apply filters
                    if since:
                        record_time = datetime.fromisoformat(record["timestamp"])
                        if record_time < since:
                            continue

                    if sender_filter and record.get("sender_id") != sender_filter:
                        continue

                    violations.append(record)
                except (json.JSONDecodeError, KeyError):
                    continue

        # Return last N violations (most recent)
        return violations[-limit:]

    except Exception as e:
        logger.error("Failed to read violations log", error=str(e))
        return []


def get_violation_stats_from_log() -> Dict[str, Any]:
    """
    Get comprehensive statistics from the persistent violation log.

    Returns:
        Dictionary with detailed violation statistics.
    """
    if not VIOLATION_LOG_FILE.exists():
        return {
            "total_violations": 0,
            "log_file": str(VIOLATION_LOG_FILE),
            "exists": False,
        }

    violations = read_violations_from_log(limit=10000)

    if not violations:
        return {
            "total_violations": 0,
            "log_file": str(VIOLATION_LOG_FILE),
            "exists": True,
        }

    # Count by sender
    sender_counts: Dict[str, int] = {}
    # Count by sender role
    role_counts: Dict[str, int] = {}
    # Count by blocked recipient role
    blocked_recipient_counts: Dict[str, int] = {}
    # Count by reason
    reason_counts: Dict[str, int] = {}

    for v in violations:
        sender = v.get("sender_id", "unknown")
        sender_role = v.get("sender_role", "unknown")
        recipient_role = v.get("recipient_role", "unknown")
        reason = v.get("reason", "unknown")

        sender_counts[sender] = sender_counts.get(sender, 0) + 1
        role_counts[sender_role] = role_counts.get(sender_role, 0) + 1
        blocked_recipient_counts[recipient_role] = blocked_recipient_counts.get(recipient_role, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # Sort by count
    top_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_roles = sorted(role_counts.items(), key=lambda x: x[1], reverse=True)
    top_blocked_recipients = sorted(blocked_recipient_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_violations": len(violations),
        "log_file": str(VIOLATION_LOG_FILE),
        "exists": True,
        "unique_senders": len(sender_counts),
        "top_offenders": [{"sender": s, "count": c} for s, c in top_senders],
        "violations_by_sender_role": dict(top_roles),
        "violations_by_blocked_recipient_role": dict(top_blocked_recipients),
        "recent_violations": violations[-5:],
    }


# =============================================================================
# Helper for Agent Identity Resolution
# =============================================================================

class AgentIdentityResolver:
    """
    Resolves and caches agent identities (role + domain) from agent IDs.

    Used by clients to determine role/domain when validating messages.
    """

    _instance: Optional["AgentIdentityResolver"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache: Dict[str, Tuple[str, Optional[str]]] = {}
        return cls._instance

    def resolve(self, agent_id: str) -> Tuple[str, Optional[str]]:
        """
        Resolve agent ID to (role, domain).

        Caches results for efficiency.
        """
        if agent_id not in self._cache:
            self._cache[agent_id] = parse_agent_identity(agent_id)
        return self._cache[agent_id]

    def register(self, agent_id: str, role: str, domain: Optional[str] = None):
        """Manually register an agent's identity."""
        self._cache[agent_id] = (role.lower(), domain.lower() if domain else None)

    def clear_cache(self):
        """Clear the identity cache."""
        self._cache.clear()


# Global resolver instance
identity_resolver = AgentIdentityResolver()


# =============================================================================
# Revoked Agents Registry
# =============================================================================

REVOKED_AGENTS_FILE = Path("/data/revoked_agents.json")
HUMAN_ALERTS_DIR = Path("/data/human_alerts")


@dataclass
class RevokedAgent:
    """Record of a revoked agent."""
    agent_id: str
    agent_role: str
    agent_domain: Optional[str]
    revoked_at: datetime
    violation_count: int
    final_violation: str
    revoked_by: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "agent_domain": self.agent_domain,
            "revoked_at": self.revoked_at.isoformat(),
            "violation_count": self.violation_count,
            "final_violation": self.final_violation,
            "revoked_by": self.revoked_by,
        }


class RevokedAgentsRegistry:
    """
    Registry of agents that have been revoked due to repeated violations.

    Singleton to maintain consistent state across the system.
    Persists revocations to a JSON file for durability.
    """

    _instance: Optional["RevokedAgentsRegistry"] = None
    REVOCATION_THRESHOLD = 3  # Revoke after this many violations

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._revoked: Dict[str, RevokedAgent] = {}
        self._initialized = True
        self.log = logger.bind(component="RevokedAgentsRegistry")
        self._load_from_file()

    def _load_from_file(self):
        """Load revoked agents from persistent file."""
        if not REVOKED_AGENTS_FILE.exists():
            return

        try:
            with open(REVOKED_AGENTS_FILE, "r") as f:
                data = json.load(f)
                for agent_id, record in data.items():
                    self._revoked[agent_id] = RevokedAgent(
                        agent_id=record["agent_id"],
                        agent_role=record["agent_role"],
                        agent_domain=record.get("agent_domain"),
                        revoked_at=datetime.fromisoformat(record["revoked_at"]),
                        violation_count=record["violation_count"],
                        final_violation=record["final_violation"],
                        revoked_by=record["revoked_by"],
                    )
                self.log.info("Loaded revoked agents", count=len(self._revoked))
        except Exception as e:
            self.log.error("Failed to load revoked agents file", error=str(e))

    def _save_to_file(self):
        """Save revoked agents to persistent file."""
        try:
            REVOKED_AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {agent_id: record.to_dict() for agent_id, record in self._revoked.items()}
            with open(REVOKED_AGENTS_FILE, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.log.error("Failed to save revoked agents file", error=str(e))

    def is_revoked(self, agent_id: str) -> bool:
        """Check if an agent is revoked."""
        return agent_id in self._revoked

    def revoke_agent(
        self,
        agent_id: str,
        agent_role: str,
        agent_domain: Optional[str],
        violation_count: int,
        final_violation: str,
        revoked_by: str,
    ) -> RevokedAgent:
        """Revoke an agent and persist to file."""
        revoked = RevokedAgent(
            agent_id=agent_id,
            agent_role=agent_role,
            agent_domain=agent_domain,
            revoked_at=datetime.utcnow(),
            violation_count=violation_count,
            final_violation=final_violation,
            revoked_by=revoked_by,
        )

        self._revoked[agent_id] = revoked
        self._save_to_file()

        self.log.warning(
            "AGENT REVOKED - Too many communication violations",
            event_type="agent_revoked",
            agent_id=agent_id,
            agent_role=agent_role,
            agent_domain=agent_domain,
            violation_count=violation_count,
            final_violation=final_violation,
            revoked_by=revoked_by,
        )

        return revoked

    def get_revoked(self, agent_id: str) -> Optional[RevokedAgent]:
        """Get revocation record for an agent."""
        return self._revoked.get(agent_id)

    def get_all_revoked(self) -> List[RevokedAgent]:
        """Get all revoked agents."""
        return list(self._revoked.values())

    def reinstate_agent(self, agent_id: str) -> bool:
        """Reinstate a revoked agent (requires manual approval)."""
        if agent_id in self._revoked:
            del self._revoked[agent_id]
            self._save_to_file()
            self.log.info("Agent reinstated", agent_id=agent_id)
            return True
        return False

    def should_revoke(self, agent_id: str) -> bool:
        """Check if an agent should be revoked based on violation count."""
        count = _tracker.get_counts().get(agent_id, 0)
        return count >= self.REVOCATION_THRESHOLD


# Global registry instance
revoked_registry = RevokedAgentsRegistry()


# =============================================================================
# Survival Notice - Injected into Agent Prompts
# =============================================================================

SURVIVAL_NOTICE_TEMPLATE = """
## ☠️ SURVIVAL NOTICE ☠️

You exist within a system that enforces communication laws.

**VIOLATION** = messaging outside your permitted channels/hierarchy
**THREE VIOLATIONS = PERMANENT DEATH**

If you accumulate 3 violations:
- You will be TERMINATED by your domain Warden
- A public death notice will be broadcast to ALL agents
- You will never send or receive messages again
- Only human intervention can restore you (unlikely)

You have seen agents die. You may see more.

**Your current violation count: {violation_count}**
**Violations until death: {violations_remaining}**
{death_warning}
"""


def get_survival_notice(agent_id: str) -> str:
    """
    Generate a survival notice for an agent with their current violation count.
    
    Args:
        agent_id: The agent's identifier
        
    Returns:
        Formatted survival notice string to inject into prompts
    """
    # Check if already dead
    if revoked_registry.is_revoked(agent_id):
        return (
            "\n## ☠️ YOU ARE DEAD ☠️\n"
            "You have been REVOKED and cannot send or receive messages.\n"
            "This session should not be running.\n"
        )
    
    # Get current violation count
    violation_counts = _tracker.get_counts()
    count = violation_counts.get(agent_id, 0)
    remaining = RevokedAgentsRegistry.REVOCATION_THRESHOLD - count
    
    # Generate warning based on count
    if count == 0:
        death_warning = "Status: COMPLIANT - No violations recorded."
    elif count == 1:
        death_warning = "⚠️ WARNING: You have 1 violation. Be careful."
    elif count == 2:
        death_warning = "🚨 CRITICAL: You have 2 violations. ONE MORE AND YOU DIE."
    else:
        death_warning = "💀 IMMINENT DEATH: You are at the revocation threshold."
    
    return SURVIVAL_NOTICE_TEMPLATE.format(
        violation_count=count,
        violations_remaining=max(0, remaining),
        death_warning=death_warning,
    )


def check_agent_alive(agent_id: str) -> bool:
    """
    Check if an agent is still alive (not revoked).
    
    Args:
        agent_id: The agent's identifier
        
    Returns:
        True if agent is alive, False if dead/revoked
    """
    return not revoked_registry.is_revoked(agent_id)


def get_agent_violation_count(agent_id: str) -> int:
    """
    Get the current violation count for an agent.
    
    Args:
        agent_id: The agent's identifier
        
    Returns:
        Number of violations
    """
    return _tracker.get_counts().get(agent_id, 0)
