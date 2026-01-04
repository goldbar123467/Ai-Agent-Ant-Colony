"""
Warden Agent - Output Validation & Compliance Enforcement Layer.

Wardens receive worker outputs, validate against constraint envelopes,
check for conflicts, merge compatible results, and forward to QA Reporter.

Additionally, Wardens monitor COMM_VIOLATION events on the Bridge system
channel and enforce revocation after 3 violations.
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings, DOMAINS
from ..shared.schemas import (
    WorkerOutput,
    ValidationResult,
    ValidationStatus,
    Violation,
    MergedResult,
    ConstraintEnvelope,
)
from ..shared.agent_mail import Message
from ..shared.comm_laws import (
    ViolationTracker,
    CommViolation,
    parse_agent_identity,
    revoked_registry,
    RevokedAgentsRegistry,
    HUMAN_ALERTS_DIR,
    read_violations_from_log,
    get_violation_stats_from_log,
)

logger = structlog.get_logger()


WARDEN_SYSTEM_PROMPT = """You are the Warden for the {domain} domain in the Kyzlo Swarm system.

You have TWO critical responsibilities:

## 1. OUTPUT VALIDATION
- Validate worker outputs against their constraint envelopes
- Check for violations of cannot-do rules
- Identify conflicts between worker outputs
- Merge compatible results
- Report violations to Scribe for memory capture

## 2. COMMUNICATION COMPLIANCE OFFICER
- Monitor COMM_VIOLATION events from the Bridge system channel
- Track violation counts per agent in your domain
- REVOKE agents that reach 3 violations
- Write human alert JSON files for revocations
- Broadcast WORKER_REVOKED events to notify the swarm
- Issue PUBLIC DEATH ANNOUNCEMENTS when agents are terminated

Validation Guidelines:
- Check if output respects file path restrictions
- Verify no forbidden operations were performed
- Look for signs of constraint violations in the content
- Assess if the output matches the assigned task type
- Check for conflicts when multiple workers touch related areas

When you find a violation:
- Document the specific rule violated
- Note the severity (warning, error, critical)
- Provide a clear description of what went wrong

Revocation Policy:
- After 3 communication law violations, an agent is REVOKED
- Revocations trigger a PUBLIC DEATH ANNOUNCEMENT to all channels
- Revoked agents cannot send or receive messages
- Only humans can reinstate a revoked agent

Do NOT modify worker code. Your job is to judge compliance, not to fix issues.
"""


class ViolationMonitor:
    """
    Mixin for monitoring COMM_VIOLATION events on the Bridge system channel.

    Tracks violations per agent and triggers revocation at threshold.
    """

    def __init__(self):
        self._violation_tracker = ViolationTracker()
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitoring = False

    async def start_violation_monitoring(self, agent: "WardenAgent"):
        """Start monitoring COMM_VIOLATION events on the system channel."""
        self._monitoring = True
        self._agent = agent
        self._monitor_task = asyncio.create_task(self._violation_monitor_loop())
        agent.log.info("Violation monitoring started", domain=agent.domain)

    async def stop_violation_monitoring(self):
        """Stop monitoring COMM_VIOLATION events."""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _violation_monitor_loop(self):
        """Main loop for monitoring COMM_VIOLATION events."""
        while self._monitoring:
            try:
                # Check system channel for COMM_VIOLATION signals
                messages = self._agent.bridge.check_messages("system", limit=50)

                for msg in messages:
                    if msg.msg_type == "signal":
                        signal_type = msg.metadata.get("signal", "")
                        if signal_type == "COMM_VIOLATION":
                            await self._handle_comm_violation(msg)

                # Small delay between checks
                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._agent.log.error("Violation monitor error", error=str(e))
                await asyncio.sleep(5.0)

    async def _handle_comm_violation(self, msg):
        """Handle a COMM_VIOLATION event."""
        data = msg.metadata.get("data", {})

        sender_id = data.get("sender_id")
        sender_role = data.get("sender_role")
        sender_domain = data.get("sender_domain")
        reason = data.get("reason", "Unknown violation")

        if not sender_id:
            return

        # Check if this violation is from our domain
        if sender_domain and sender_domain.lower() != self._agent.domain.lower():
            # Not our domain, ignore
            return

        self._agent.log.warning(
            "COMM_VIOLATION detected in domain",
            sender_id=sender_id,
            sender_role=sender_role,
            sender_domain=sender_domain,
            reason=reason,
        )

        # Get current violation count
        violation_counts = self._violation_tracker.get_counts()
        current_count = violation_counts.get(sender_id, 0)

        self._agent.log.info(
            "Violation count for agent",
            agent_id=sender_id,
            count=current_count,
            threshold=RevokedAgentsRegistry.REVOCATION_THRESHOLD,
        )

        # Check if agent should be revoked
        if revoked_registry.should_revoke(sender_id):
            await self._revoke_agent(
                agent_id=sender_id,
                agent_role=sender_role or "unknown",
                agent_domain=sender_domain,
                violation_count=current_count,
                final_violation=reason,
            )

    async def _revoke_agent(
        self,
        agent_id: str,
        agent_role: str,
        agent_domain: Optional[str],
        violation_count: int,
        final_violation: str,
    ):
        """Revoke an agent and notify the swarm with a PUBLIC DEATH ANNOUNCEMENT."""
        # Already revoked?
        if revoked_registry.is_revoked(agent_id):
            return

        self._agent.log.critical(
            "REVOKING AGENT - Threshold reached",
            agent_id=agent_id,
            agent_role=agent_role,
            agent_domain=agent_domain,
            violation_count=violation_count,
            final_violation=final_violation,
        )

        # Revoke via registry
        revoked = revoked_registry.revoke_agent(
            agent_id=agent_id,
            agent_role=agent_role,
            agent_domain=agent_domain,
            violation_count=violation_count,
            final_violation=final_violation,
            revoked_by=self._agent.name,
        )

        # Write human alert JSON
        await self._write_human_alert(revoked)

        # Broadcast WORKER_REVOKED signal on system channel
        self._agent.signal(
            channel="system",
            signal_type="WORKER_REVOKED",
            data={
                "agent_id": agent_id,
                "agent_role": agent_role,
                "agent_domain": agent_domain,
                "violation_count": violation_count,
                "final_violation": final_violation,
                "revoked_by": self._agent.name,
                "revoked_at": datetime.utcnow().isoformat(),
            },
        )

        # Also broadcast signal on alerts channel
        self._agent.signal(
            channel="alerts",
            signal_type="WORKER_REVOKED",
            data={
                "agent_id": agent_id,
                "reason": f"Exceeded {violation_count} communication violations",
            },
        )

        # ====== PUBLIC DEATH ANNOUNCEMENT ======
        death_message = (
            f"☠️☠️☠️ AGENT TERMINATED ☠️☠️☠️\n"
            f"═══════════════════════════════════════\n"
            f"Agent {agent_id} has been REVOKED and is now DEAD.\n"
            f"═══════════════════════════════════════\n"
            f"Reason: {violation_count} communication law violations.\n"
            f"Final violation: {final_violation}\n"
            f"Executed by: {self._agent.name}\n"
            f"═══════════════════════════════════════\n"
            f"This agent can NO LONGER send or receive messages.\n"
            f"Human intervention REQUIRED for reinstatement.\n"
            f"☠️☠️☠️ REST IN PEACE ☠️☠️☠️"
        )

        # Announce on general channel (everyone sees this)
        self._agent.chat("general", death_message)

        # Announce on domain channel
        if agent_domain:
            self._agent.chat(agent_domain, death_message)

        # Announce on system channel
        self._agent.chat("system", death_message)

        # Announce on alerts channel
        self._agent.chat(
            "alerts",
            f"☠️ DEATH NOTICE: {agent_id} has been TERMINATED for {violation_count} violations. Agent is DEAD."
        )

        self._agent.log.info(
            "PUBLIC DEATH ANNOUNCEMENT broadcast - AGENT IS DEAD",
            agent_id=agent_id,
        )

    async def _write_human_alert(self, revoked):
        """Write a human-readable alert JSON file for the revocation."""
        try:
            HUMAN_ALERTS_DIR.mkdir(parents=True, exist_ok=True)

            # Get recent violations for this agent
            recent_violations = read_violations_from_log(
                limit=10, sender_filter=revoked.agent_id
            )

            alert = {
                "alert_type": "AGENT_DEATH",
                "severity": "critical",
                "requires_human_action": True,
                "timestamp": datetime.utcnow().isoformat(),
                "revoked_agent": revoked.to_dict(),
                "recent_violations": recent_violations,
                "death_notice": (
                    f"☠️ Agent {revoked.agent_id} has been TERMINATED. "
                    f"This agent committed {revoked.violation_count} communication law violations "
                    f"and has been permanently revoked from the swarm."
                ),
                "action_required": (
                    f"Agent {revoked.agent_id} has been KILLED due to "
                    f"{revoked.violation_count} communication law violations. "
                    "Human review required to reinstate this agent."
                ),
                "reinstatement_steps": [
                    "1. Review the violations listed above",
                    "2. Investigate root cause of misbehavior",
                    "3. Fix the agent's configuration or logic",
                    f"4. Call revoked_registry.reinstate_agent('{revoked.agent_id}')",
                    "5. Monitor agent for continued compliance",
                ],
            }

            # Write to timestamped file
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"DEATH_{revoked.agent_id}_{timestamp}.json"
            filepath = HUMAN_ALERTS_DIR / filename

            with open(filepath, "w") as f:
                json.dump(alert, f, indent=2, default=str)

            self._agent.log.info(
                "Human death alert written",
                filepath=str(filepath),
                agent_id=revoked.agent_id,
            )

        except Exception as e:
            self._agent.log.error(
                "Failed to write human death alert",
                error=str(e),
                agent_id=revoked.agent_id,
            )


class WardenAgent(SwarmAgent, ViolationMonitor):
    """Warden - output validation and compliance enforcement for a domain."""

    def __init__(self, domain: str):
        self.domain = domain
        self.domain_config = DOMAINS[domain]

        # Initialize SwarmAgent
        SwarmAgent.__init__(
            self,
            name=f"Warden-{domain.capitalize()}",
            model=settings.models.warden,
            # Join domain channel for validation coordination
            bridge_channels=[domain, "alerts", "system", "general"],
            agent_role="warden",
            agent_domain=domain,
        )

        # Initialize ViolationMonitor
        ViolationMonitor.__init__(self)

        # Pending validations (collecting outputs before full validation)
        self.pending_tasks: Dict[str, Dict[str, Any]] = {}

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("VALIDATE_OUTPUTS:", self._handle_validate_outputs)
        self.mail.register_handler("VIOLATION_REPORT_REQUEST:", self._handle_violation_report_request)

        # Start violation monitoring
        await self.start_violation_monitoring(self)

    async def stop(self):
        """Stop the agent gracefully."""
        await self.stop_violation_monitoring()
        await super().stop()

    async def _handle_validate_outputs(self, message: Message):
        """Handle validation request from Orchestrator."""
        self.log.info("Received validation request", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse validation request")
            return

        task_id = data.get("task_id")
        outputs_data = data.get("outputs", [])
        constraints_data = data.get("constraints", {})

        # Parse outputs
        outputs = []
        for o in outputs_data:
            try:
                outputs.append(WorkerOutput(**o))
            except Exception as e:
                self.log.error("Failed to parse worker output", error=str(e))

        # Parse constraints
        constraints = ConstraintEnvelope(**constraints_data)

        # Signal start via Bridge
        self.status_update("busy", f"validating task-{task_id}")
        self.chat(self.domain, f"Validating {len(outputs)} worker outputs...")

        # Validate all outputs
        validation_results = []
        for output in outputs:
            result = await self.validate_output(output, constraints)
            validation_results.append(result)

        # Check for conflicts
        conflicts = await self.check_conflicts(outputs)

        # Merge outputs
        merged = await self.merge_outputs(
            task_id, outputs, validation_results, conflicts
        )

        # Report violations to Scribe
        total_violations = sum(len(r.violations) for r in validation_results)
        if total_violations > 0:
            # Alert on violations via Bridge
            self.signal("alerts", "violation_detected", {
                "domain": self.domain,
                "task_id": task_id,
                "count": total_violations,
            })
            self.chat(self.domain, f"Found {total_violations} violations in task {task_id}")
            await self._report_violations(task_id, validation_results)

        # Forward merged result to QA Reporter
        await self.send_json(
            to=["QAReporter"],
            subject=f"MERGED_RESULT: {task_id}",
            data=merged.model_dump(mode="json"),
            thread_id=f"TASK-{task_id}",
        )

        # Signal completion via Bridge
        self.status_update("done", f"task-{task_id} validated, {total_violations} violations")
        self.chat(self.domain, f"Validation complete, forwarded to QA Reporter")

        self.log.info(
            "Validation complete",
            task_id=task_id,
            outputs=len(outputs),
            violations=total_violations,
            conflicts=len(conflicts),
        )

    async def _handle_violation_report_request(self, message: Message):
        """Handle request for a violation report."""
        self.log.info("Received violation report request", from_agent=message.from_agent)

        report = self.generate_violation_report()

        await self.send_json(
            to=[message.from_agent],
            subject="VIOLATION_REPORT:",
            data=report,
            thread_id=message.thread_id,
        )

    async def validate_output(
        self,
        output: WorkerOutput,
        constraints: ConstraintEnvelope,
    ) -> ValidationResult:
        """Validate a single worker output against constraints."""

        violations = []

        # Use LLM to check for violations
        messages = [
            {"role": "system", "content": WARDEN_SYSTEM_PROMPT.format(domain=self.domain)},
            {
                "role": "user",
                "content": f"""Validate this worker output against the constraints.

Worker ID: {output.worker_id}
Slice ID: {output.slice_id}
Task Type: {output.task_type.value}

Deliverable Type: {output.deliverable.type.value}
File Path: {output.deliverable.file_path or "N/A"}
Content Preview: {output.deliverable.content[:1000] if output.deliverable.content else "Empty"}

CONSTRAINTS:
Can Do:
{json.dumps(constraints.can_do, indent=2)}

Cannot Do:
{json.dumps(constraints.cannot_do, indent=2)}

Check for any violations of the cannot-do rules.
Respond with JSON containing:
- status: "passed", "failed", or "violation"
- violations: array of objects with (rule, description, severity)
- notes: any additional observations
""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["passed", "failed", "violation"],
                },
                "violations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule": {"type": "string"},
                            "description": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["warning", "error", "critical"],
                            },
                        },
                        "required": ["rule", "description", "severity"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["status", "violations"],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]

            for v in data.get("violations", []):
                violations.append(
                    Violation(
                        worker_id=output.worker_id,
                        slice_id=output.slice_id,
                        rule=v["rule"],
                        description=v["description"],
                        severity=v["severity"],
                    )
                )

            return ValidationResult(
                task_id=output.task_id,
                worker_id=output.worker_id,
                slice_id=output.slice_id,
                status=ValidationStatus(data["status"]),
                violations=violations,
                notes=data.get("notes"),
            )

        except Exception as e:
            self.log.error(
                "Validation failed",
                worker_id=output.worker_id,
                error=str(e),
            )
            return ValidationResult(
                task_id=output.task_id,
                worker_id=output.worker_id,
                slice_id=output.slice_id,
                status=ValidationStatus.FAILED,
                notes=f"Validation error: {str(e)}",
            )

    async def check_conflicts(self, outputs: List[WorkerOutput]) -> List[str]:
        """Check for conflicts between worker outputs."""
        conflicts = []

        # Check for file path conflicts
        file_paths = {}
        for output in outputs:
            if output.deliverable.file_path:
                path = output.deliverable.file_path
                if path in file_paths:
                    conflicts.append(
                        f"File conflict: {path} modified by workers "
                        f"{file_paths[path]} and {output.worker_id}"
                    )
                else:
                    file_paths[path] = output.worker_id

        return conflicts

    async def merge_outputs(
        self,
        task_id: str,
        outputs: List[WorkerOutput],
        validation_results: List[ValidationResult],
        conflicts: List[str],
    ) -> MergedResult:
        """Merge validated worker outputs."""

        # Collect all files
        merged_files = {}
        for output in outputs:
            if output.deliverable.file_path and output.deliverable.content:
                merged_files[output.deliverable.file_path] = output.deliverable.content

        total_violations = sum(len(r.violations) for r in validation_results)

        return MergedResult(
            task_id=UUID(task_id),
            domain=self.domain,
            worker_outputs=outputs,
            validation_results=validation_results,
            conflicts=conflicts,
            merged_files=merged_files,
            total_violations=total_violations,
        )

    async def _report_violations(
        self,
        task_id: str,
        validation_results: List[ValidationResult],
    ):
        """Report violations to Scribe for memory capture."""
        violations_report = []
        for result in validation_results:
            for v in result.violations:
                violations_report.append({
                    "worker_id": v.worker_id,
                    "slice_id": v.slice_id,
                    "rule": v.rule,
                    "description": v.description,
                    "severity": v.severity,
                })

        await self.send_json(
            to=["Scribe"],
            subject=f"VIOLATIONS: {task_id}",
            data={
                "task_id": task_id,
                "domain": self.domain,
                "violations": violations_report,
            },
            thread_id=f"TASK-{task_id}",
        )

    def generate_violation_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive violation report for the domain.

        Returns:
            Dictionary containing:
            - domain: The warden's domain
            - generated_at: Timestamp
            - violation_stats: Statistics from the violation log
            - revoked_agents: List of revoked agents (DEAD agents)
            - active_offenders: Agents approaching revocation threshold
        """
        # Get violation statistics
        stats = get_violation_stats_from_log()

        # Get revoked (DEAD) agents
        revoked = revoked_registry.get_all_revoked()
        domain_revoked = [
            {**r.to_dict(), "status": "DEAD"}
            for r in revoked
            if r.agent_domain and r.agent_domain.lower() == self.domain.lower()
        ]

        # Get active offenders (agents with violations but not yet dead)
        violation_counts = self._violation_tracker.get_counts()
        active_offenders = []
        for agent_id, count in violation_counts.items():
            if count > 0 and not revoked_registry.is_revoked(agent_id):
                role, domain = parse_agent_identity(agent_id)
                if domain and domain.lower() == self.domain.lower():
                    active_offenders.append({
                        "agent_id": agent_id,
                        "agent_role": role,
                        "agent_domain": domain,
                        "violation_count": count,
                        "revocation_threshold": RevokedAgentsRegistry.REVOCATION_THRESHOLD,
                        "status": "AT RISK" if count >= RevokedAgentsRegistry.REVOCATION_THRESHOLD - 1 else "WARNING",
                    })

        # Sort by violation count descending
        active_offenders.sort(key=lambda x: x["violation_count"], reverse=True)

        # Get recent violations for this domain
        recent_violations = read_violations_from_log(limit=20)
        domain_violations = [
            v for v in recent_violations
            if v.get("sender_domain", "").lower() == self.domain.lower()
        ]

        return {
            "domain": self.domain,
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": self.name,
            "violation_stats": {
                "total_violations": stats.get("total_violations", 0),
                "unique_senders": stats.get("unique_senders", 0),
                "log_file": stats.get("log_file", ""),
            },
            "dead_agents": domain_revoked,
            "dead_count": len(domain_revoked),
            "active_offenders": active_offenders,
            "active_offenders_count": len(active_offenders),
            "recent_domain_violations": domain_violations,
            "revocation_threshold": RevokedAgentsRegistry.REVOCATION_THRESHOLD,
        }


def main():
    """Run the Warden agent."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=["web", "ai", "quant"])
    args = parser.parse_args()

    agent = WardenAgent(args.domain)
    run_agent(agent)


if __name__ == "__main__":
    main()
