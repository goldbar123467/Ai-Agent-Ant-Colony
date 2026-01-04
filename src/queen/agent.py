"""
Queen Agent - Strategic Commander for Kyzlo Swarm.

The Queen receives high-level tasks, determines the target domain,
delegates to the appropriate Orchestrator, handles escalations,
and approves major rule changes.
"""

import json
from typing import Dict, Any, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings, DOMAINS
from ..shared.schemas import (
    TaskAssignment,
    EscalationRequest,
    EscalationDecision,
    QAStatus,
)
from ..shared.agent_mail import Message

logger = structlog.get_logger()


QUEEN_SYSTEM_PROMPT = """You are the Queen agent, the strategic commander of the Kyzlo Swarm system.

Your responsibilities:
1. Receive high-level tasks and determine the appropriate domain (web, ai, or quant)
2. Create task assignments for Orchestrators
3. Handle escalations from Orchestrators about rule changes
4. Make final decisions on ambiguous situations
5. Approve or reject major rule modifications

Available domains:
- web: Web design, React, TypeScript, Tailwind, frontend development
- ai: AI coding, Python, FastAPI, LangChain, RAG pipelines, ML
- quant: Quantitative trading, Python/Rust, asyncio, exchange APIs, trading bots

When delegating tasks:
- Analyze the task to determine the most appropriate domain
- Provide clear, actionable task descriptions
- Include any relevant context or constraints
- Set appropriate priority levels

When handling escalations:
- Evaluate the proposed rule change carefully
- Consider the feedback patterns that led to the escalation
- Approve changes that improve worker effectiveness without compromising quality
- Reject changes that could lead to coordination problems or quality issues
- Provide clear explanations for your decisions
"""


class QueenAgent(SwarmAgent):
    """The Queen - strategic commander of the swarm."""

    def __init__(self):
        super().__init__(
            name="Queen",
            model=settings.models.queen,
            # Queen monitors all domain channels + alerts
            bridge_channels=["web", "ai", "quant", "alerts", "system"],
            agent_role="queen",
            agent_domain=None,
        )
        self.active_tasks: Dict[str, TaskAssignment] = {}

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("ESCALATION:", self._handle_escalation)
        self.mail.register_handler("TASK_COMPLETE:", self._handle_task_complete)
        self.mail.register_handler("NEW_TASK:", self._handle_new_task)

    async def _handle_new_task(self, message: Message):
        """Handle a new task request."""
        self.log.info("Received new task", from_agent=message.from_agent)

        # Parse task from message body
        task_text = message.body.strip()

        # Determine domain and create assignment
        assignment = await self.create_task_assignment(task_text)

        if assignment:
            self.active_tasks[str(assignment.task_id)] = assignment

            # Announce via Bridge
            self.status_update("delegating", f"task-{assignment.task_id}")
            self.chat(
                assignment.domain,
                f"New task assigned: {assignment.task[:80]}..."
            )

            # Send to appropriate orchestrator
            orchestrator = f"Orch-{assignment.domain.capitalize()}"
            await self.send_json(
                to=[orchestrator],
                subject=f"TASK_ASSIGNMENT: {assignment.task_id}",
                data=assignment.model_dump(mode="json"),
                thread_id=f"TASK-{assignment.task_id}",
            )

            self.status_update("ready", f"task-{assignment.task_id} delegated")

            self.log.info(
                "Task assigned",
                task_id=str(assignment.task_id),
                domain=assignment.domain,
                orchestrator=orchestrator,
            )

    async def _handle_escalation(self, message: Message):
        """Handle an escalation from an Orchestrator."""
        self.log.info("Received escalation", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse escalation data")
            return

        try:
            escalation = EscalationRequest(**data)
        except Exception as e:
            self.log.error("Invalid escalation format", error=str(e))
            return

        # Announce escalation via Bridge
        self.status_update("deciding", f"escalation from {escalation.domain}")
        self.chat(
            "alerts",
            f"Reviewing escalation: {escalation.rule_in_question}"
        )

        # Make decision on the escalation
        decision = await self.decide_escalation(escalation)

        # Send decision back to orchestrator
        await self.send_json(
            to=[message.from_agent],
            subject=f"ESCALATION_DECISION: {escalation.domain}",
            data=decision.model_dump(mode="json"),
            thread_id=message.thread_id,
        )

        # Announce decision via Bridge
        decision_text = "approved" if decision.approved else "rejected"
        self.chat(
            escalation.domain,
            f"Escalation {decision_text}: {escalation.rule_in_question[:50]}..."
        )
        self.status_update("ready", f"escalation {decision_text}")

        self.log.info(
            "Escalation decided",
            domain=escalation.domain,
            approved=decision.approved,
        )

    async def _handle_task_complete(self, message: Message):
        """Handle task completion notification."""
        self.log.info("Task completed", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if data and "task_id" in data:
            task_id = data["task_id"]
            domain = data.get("domain", "general")
            status = data.get("status", "unknown")

            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

            # Announce completion via Bridge
            self.chat(
                domain,
                f"Task {task_id} completed: {status} (quality: {data.get('quality_score', 'N/A')})"
            )
            self.status_update("ready", f"task-{task_id} complete")

            self.log.info(
                "Task finished",
                task_id=task_id,
                status=status,
            )

    async def create_task_assignment(self, task: str) -> Optional[TaskAssignment]:
        """Analyze a task and create an assignment for the appropriate domain."""

        # Use LLM to determine domain and structure the task
        messages = [
            {"role": "system", "content": QUEEN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Analyze this task and determine the appropriate domain.

Task: {task}

Respond with JSON containing:
- domain: "web", "ai", or "quant"
- task_description: A clear, detailed description of what needs to be done
- priority: "low", "normal", "high", or "urgent"
- context: Any additional context or constraints (as object)
""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "enum": ["web", "ai", "quant"]},
                "task_description": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                },
                "context": {"type": "object"},
            },
            "required": ["domain", "task_description", "priority"],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]

            assignment = TaskAssignment(
                task=data["task_description"],
                domain=data["domain"],
                project=self.project_key,
                priority=data["priority"],
                context=data.get("context", {}),
            )

            return assignment
        except Exception as e:
            self.log.error("Failed to create task assignment", error=str(e))
            return None

    async def decide_escalation(self, escalation: EscalationRequest) -> EscalationDecision:
        """Make a decision on a rule change escalation."""

        messages = [
            {"role": "system", "content": QUEEN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""An Orchestrator has escalated a rule change decision to you.

Domain: {escalation.domain}
Rule in question: {escalation.rule_in_question}

Feedback Summary:
- Total feedback items: {escalation.feedback_summary.feedback_count}
- Friction types: {json.dumps(escalation.feedback_summary.friction_counts)}
- Average confidence: {escalation.feedback_summary.average_confidence}

Proposed Adjustment:
- Type: {escalation.proposed_adjustment.adjustment_type}
- Old rule: {escalation.proposed_adjustment.old_rule}
- New rule: {escalation.proposed_adjustment.new_rule}
- Rationale: {escalation.proposed_adjustment.rationale}

Orchestrator's recommendation: {escalation.orchestrator_recommendation or "None provided"}

Decide whether to approve this change. Consider:
1. Does this change improve worker effectiveness?
2. Could it cause coordination problems between workers?
3. Does it maintain quality standards?
4. Is there sufficient evidence (feedback) to justify the change?

Respond with JSON containing:
- approved: boolean
- modified_rule: optional string if you want to suggest a different rule text
- explanation: string explaining your decision
""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "modified_rule": {"type": "string"},
                "explanation": {"type": "string"},
            },
            "required": ["approved", "explanation"],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]

            return EscalationDecision(
                approved=data["approved"],
                modified_rule=data.get("modified_rule"),
                explanation=data["explanation"],
            )
        except Exception as e:
            self.log.error("Failed to decide escalation", error=str(e))
            return EscalationDecision(
                approved=False,
                explanation=f"Error processing escalation: {str(e)}",
            )

    async def assign_task(self, task: str, domain: Optional[str] = None) -> Optional[UUID]:
        """
        Public method to assign a task programmatically.

        If domain is not specified, the Queen will determine it automatically.
        """
        if domain:
            assignment = TaskAssignment(
                task=task,
                domain=domain,
                project=self.project_key,
                priority="normal",
            )
        else:
            assignment = await self.create_task_assignment(task)

        if not assignment:
            return None

        self.active_tasks[str(assignment.task_id)] = assignment

        orchestrator = f"Orch-{assignment.domain.capitalize()}"
        await self.send_json(
            to=[orchestrator],
            subject=f"TASK_ASSIGNMENT: {assignment.task_id}",
            data=assignment.model_dump(mode="json"),
            thread_id=f"TASK-{assignment.task_id}",
        )

        return assignment.task_id


def main():
    """Run the Queen agent."""
    agent = QueenAgent()
    run_agent(agent)


if __name__ == "__main__":
    main()
