"""
Orchestrator Agent - Task Slicing and Rule Management.

Orchestrators receive tasks from the Queen, query RAG Brain for context,
slice tasks into 7 parallel pieces, assign constraints to workers,
dispatch work, and manage rule evolution.
"""

import argparse
import json
from typing import Dict, Any, List, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings, DOMAINS, DomainConfig
from ..shared.schemas import (
    TaskAssignment,
    TaskSlice,
    TaskType,
    ConstraintEnvelope,
    WorkerOutput,
    FeedbackBlock,
    FeedbackSummary,
    RuleAdjustment,
    EscalationRequest,
)
from ..shared.agent_mail import Message
from ..shared.comm_laws import get_survival_notice

logger = structlog.get_logger()


ORCHESTRATOR_SYSTEM_PROMPT = """{survival_notice}

You are an Orchestrator agent for the Kyzlo Swarm system.

Your responsibilities:
1. Receive tasks from the Queen and slice them into 7 parallel pieces
2. Assign each slice to a specialized worker with appropriate constraints
3. Inject relevant context from RAG Brain into worker prompts
4. Collect and forward worker outputs to the Warden
5. Manage rule evolution based on worker feedback

Domain: {domain}
Workers: {worker_ids}
Worker Specializations: {specializations}

Current Rules:
Can Do: {can_do}
Cannot Do: {cannot_do}

When slicing tasks:
- Divide work so each slice is independent (no dependencies between workers)
- Match slices to worker specializations when possible
- Include relevant context and patterns from RAG Brain
- Specify clear file paths and deliverables for each slice
- Set appropriate task types for each slice

Task types: code, research, planning, design, debug, documentation, conversation, analysis
"""


class OrchestratorAgent(SwarmAgent):
    """Orchestrator - task slicing and coordination for a domain."""

    def __init__(self, domain: str):
        self.domain = domain
        self.domain_config: DomainConfig = DOMAINS[domain]

        super().__init__(
            name=f"Orch-{domain.capitalize()}",
            model=settings.models.orchestrator,
            # Join domain channel for worker coordination
            bridge_channels=[domain, "alerts", "system"],
            agent_role="orchestrator",
            agent_domain=domain,
        )

        # Current rules (mutable based on feedback)
        self.can_do = self.domain_config.can_do.copy()
        self.cannot_do = self.domain_config.cannot_do.copy()

        # Task tracking
        self.active_tasks: Dict[str, Dict[str, Any]] = {}

        # Feedback accumulation
        self.pending_feedback: List[Dict[str, Any]] = []
        self.friction_count = 0

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("TASK_ASSIGNMENT:", self._handle_task_assignment)
        self.mail.register_handler("WORKER_OUTPUT:", self._handle_worker_output)
        self.mail.register_handler("REVIEW_TRIGGER:", self._handle_review_trigger)
        self.mail.register_handler("ESCALATION_DECISION:", self._handle_escalation_decision)

    async def _handle_task_assignment(self, message: Message):
        """Handle a task assignment from the Queen."""
        self.log.info("Received task assignment", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse task assignment")
            return

        try:
            assignment = TaskAssignment(**data)
        except Exception as e:
            self.log.error("Invalid task assignment format", error=str(e))
            return

        # Signal start via Bridge
        self.status_update("busy", f"task-{assignment.task_id}")
        self.chat(self.domain, f"Received task, gathering context from RAG Brain...")

        # Get context from RAG Brain
        context = await self._get_task_context(assignment)

        # Slice the task
        slices = await self.slice_task(assignment, context)

        # Store task state
        self.active_tasks[str(assignment.task_id)] = {
            "assignment": assignment,
            "slices": slices,
            "outputs": {},
            "context": context,
        }

        # Notify via Bridge that slicing is complete
        self.chat(self.domain, f"Task sliced into {len(slices)} pieces, dispatching to workers...")

        # Dispatch slices to workers
        for task_slice in slices:
            worker_name = f"Worker-{task_slice.worker_id}"
            await self.send_json(
                to=[worker_name],
                subject=f"TASK_SLICE: {assignment.task_id}",
                data=task_slice.model_dump(mode="json"),
                thread_id=f"TASK-{assignment.task_id}",
            )

        # Signal dispatch complete
        self.status_update("waiting", f"task-{assignment.task_id} awaiting {len(slices)} workers")

        self.log.info(
            "Task sliced and dispatched",
            task_id=str(assignment.task_id),
            slices=len(slices),
        )

    async def _handle_worker_output(self, message: Message):
        """Handle output from a worker."""
        self.log.info("Received worker output", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse worker output")
            return

        try:
            output = WorkerOutput(**data)
        except Exception as e:
            self.log.error("Invalid worker output format", error=str(e))
            return

        task_id = str(output.task_id)
        if task_id not in self.active_tasks:
            self.log.warning("Output for unknown task", task_id=task_id)
            return

        # Store output
        self.active_tasks[task_id]["outputs"][output.worker_id] = output

        # Track feedback
        await self._track_feedback(output.feedback, output.worker_id, task_id)

        # Check if all workers have completed
        expected_workers = len(self.domain_config.worker_ids)
        received = len(self.active_tasks[task_id]["outputs"])

        self.log.info(
            "Worker output received",
            task_id=task_id,
            worker_id=output.worker_id,
            received=received,
            expected=expected_workers,
        )

        if received >= expected_workers:
            # All workers done - notify via Bridge
            self.chat(self.domain, f"All {expected_workers} workers completed, forwarding to Warden")
            await self._forward_to_warden(task_id)

    async def _handle_review_trigger(self, message: Message):
        """Handle review trigger from Scribe."""
        self.log.info("Received review trigger")

        data = self.parse_json_from_message(message)
        if not data:
            return

        try:
            summary = FeedbackSummary(**data)
        except Exception as e:
            self.log.error("Invalid feedback summary", error=str(e))
            return

        # Review and adjust rules
        adjustments = await self.review_rules(summary)

        for adjustment in adjustments:
            if adjustment.requires_escalation:
                await self._escalate_to_queen(adjustment, summary)
            else:
                self._apply_adjustment(adjustment)

    async def _handle_escalation_decision(self, message: Message):
        """Handle decision from Queen on an escalation."""
        self.log.info("Received escalation decision")

        data = self.parse_json_from_message(message)
        if not data:
            return

        if data.get("approved"):
            modified_rule = data.get("modified_rule")
            if modified_rule:
                self.log.info("Applying modified rule from Queen", rule=modified_rule)
                # Apply the modified rule (simplified - would need more context)

    async def _get_task_context(self, assignment: TaskAssignment) -> Dict[str, Any]:
        """Get relevant context from RAG Brain for a task."""
        context = {
            "project_profile": None,
            "patterns": [],
            "failures": [],
        }

        # Get project profile
        profile = await self.rag.get_project_profile(assignment.project)
        if profile:
            context["project_profile"] = profile

        # Get relevant patterns
        patterns = await self.rag.get_patterns(self.domain, assignment.project)
        context["patterns"] = patterns

        # Get known failures to avoid
        failures = await self.rag.get_failures(self.domain, assignment.project)
        context["failures"] = failures

        return context

    async def slice_task(
        self,
        assignment: TaskAssignment,
        context: Dict[str, Any],
    ) -> List[TaskSlice]:
        """Slice a task into 7 parallel pieces for workers."""

        # Build context string for LLM
        context_str = ""
        if context.get("project_profile"):
            context_str += f"Project Profile: {context['project_profile'].get('content', '')}\n\n"
        if context.get("patterns"):
            context_str += "Relevant Patterns:\n"
            for p in context["patterns"][:3]:
                context_str += f"- {p.get('content', '')[:200]}...\n"
        if context.get("failures"):
            context_str += "\nFailures to Avoid:\n"
            for f in context["failures"][:3]:
                context_str += f"- {f.get('content', '')[:200]}...\n"

        specializations_str = json.dumps(self.domain_config.specializations, indent=2)

        messages = [
            {
                "role": "system",
                "content": ORCHESTRATOR_SYSTEM_PROMPT.format(
                    survival_notice=self.get_survival_notice(),
                    domain=self.domain,
                    worker_ids=self.domain_config.worker_ids,
                    specializations=specializations_str,
                    can_do=self.can_do,
                    cannot_do=self.cannot_do,
                ),
            },
            {
                "role": "user",
                "content": f"""Slice this task into 7 parallel pieces for workers.

Task: {assignment.task}
Priority: {assignment.priority}

Context from RAG Brain:
{context_str}

For each slice, specify:
- slice_id: 1-7
- worker_id: Which worker from {self.domain_config.worker_ids}
- task_type: code/research/planning/design/debug/documentation/conversation/analysis
- description: Clear instructions for this slice
- assigned_file: File path to create (if applicable)

Ensure slices are independent - no worker should depend on another's output.
Match slices to worker specializations when possible.

Respond with a JSON array of 7 slice objects.
""",
            },
        ]

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slice_id": {"type": "integer", "minimum": 1, "maximum": 7},
                    "worker_id": {"type": "integer"},
                    "task_type": {
                        "type": "string",
                        "enum": [t.value for t in TaskType],
                    },
                    "description": {"type": "string"},
                    "assigned_file": {"type": "string"},
                },
                "required": ["slice_id", "worker_id", "task_type", "description"],
            },
            "minItems": 7,
            "maxItems": 7,
        }

        try:
            result = await self.complete_json(messages, schema)
            slices_data = result["data"]

            slices = []
            for slice_data in slices_data:
                task_slice = TaskSlice(
                    task_id=assignment.task_id,
                    slice_id=slice_data["slice_id"],
                    worker_id=slice_data["worker_id"],
                    task_type=TaskType(slice_data["task_type"]),
                    description=slice_data["description"],
                    assigned_file=slice_data.get("assigned_file"),
                    constraints=ConstraintEnvelope(
                        can_do=self.can_do,
                        cannot_do=self.cannot_do,
                    ),
                    context=context,
                )
                slices.append(task_slice)

            return slices
        except Exception as e:
            self.log.error("Failed to slice task", error=str(e))
            # Return minimal slices on error
            return self._create_fallback_slices(assignment)

    def _create_fallback_slices(self, assignment: TaskAssignment) -> List[TaskSlice]:
        """Create fallback slices if LLM slicing fails."""
        slices = []
        for i, worker_id in enumerate(self.domain_config.worker_ids, 1):
            slices.append(
                TaskSlice(
                    task_id=assignment.task_id,
                    slice_id=i,
                    worker_id=worker_id,
                    task_type=TaskType.CODE,
                    description=f"Part {i} of task: {assignment.task}",
                    constraints=ConstraintEnvelope(
                        can_do=self.can_do,
                        cannot_do=self.cannot_do,
                    ),
                )
            )
        return slices

    async def _forward_to_warden(self, task_id: str):
        """Forward completed outputs to the Warden."""
        task_data = self.active_tasks[task_id]
        outputs = list(task_data["outputs"].values())

        warden_name = f"Warden-{self.domain.capitalize()}"
        await self.send_json(
            to=[warden_name],
            subject=f"VALIDATE_OUTPUTS: {task_id}",
            data={
                "task_id": task_id,
                "domain": self.domain,
                "assignment": task_data["assignment"].model_dump(mode="json"),
                "outputs": [o.model_dump(mode="json") for o in outputs],
                "constraints": {
                    "can_do": self.can_do,
                    "cannot_do": self.cannot_do,
                },
            },
            thread_id=f"TASK-{task_id}",
        )

        self.status_update("done", f"task-{task_id} sent to warden")
        self.log.info("Forwarded outputs to warden", task_id=task_id, warden=warden_name)

    async def _track_feedback(
        self,
        feedback: FeedbackBlock,
        worker_id: int,
        task_id: str,
    ):
        """Track worker feedback for rule evolution."""
        if feedback.friction:
            self.friction_count += 1
            self.pending_feedback.append({
                "worker_id": worker_id,
                "task_id": task_id,
                "friction": feedback.friction.value,
                "friction_detail": feedback.friction_detail,
                "suggestion": feedback.suggestion,
                "blocked_by_rule": feedback.blocked_by_rule,
                "confidence": feedback.confidence,
            })

    async def review_rules(self, summary: FeedbackSummary) -> List[RuleAdjustment]:
        """Review rules based on accumulated feedback."""
        messages = [
            {
                "role": "system",
                "content": f"""You are reviewing worker feedback to determine if rules should change.

Current Rules:
Can Do: {self.can_do}
Cannot Do: {self.cannot_do}

Review guidelines:
- Rules blocked by 5+ workers warrant consideration
- Consistent suggestions from multiple workers carry more weight
- Consider if changes would cause coordination problems
- Minor relaxations with strong consensus can proceed automatically
- Major changes or rule removals should escalate to Queen
""",
            },
            {
                "role": "user",
                "content": f"""Review this feedback summary and propose rule adjustments.

Feedback Count: {summary.feedback_count}
Friction Types: {json.dumps(summary.friction_counts)}
Most Blocked Rules: {summary.most_blocked_rules}
Top Suggestions: {summary.top_suggestions}
Average Confidence: {summary.average_confidence}

Respond with a JSON array of adjustment objects, each with:
- adjustment_type: "relaxation", "clarification", "addition", or "removal"
- old_rule: the current rule text (if modifying)
- new_rule: the proposed new rule text
- rationale: why this change is needed
- requires_escalation: boolean (true for removals or major changes)
""",
            },
        ]

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "adjustment_type": {
                        "type": "string",
                        "enum": ["relaxation", "clarification", "addition", "removal"],
                    },
                    "old_rule": {"type": "string"},
                    "new_rule": {"type": "string"},
                    "rationale": {"type": "string"},
                    "requires_escalation": {"type": "boolean"},
                },
                "required": ["adjustment_type", "rationale", "requires_escalation"],
            },
        }

        try:
            result = await self.complete_json(messages, schema)
            adjustments = [RuleAdjustment(**adj) for adj in result["data"]]
            return adjustments
        except Exception as e:
            self.log.error("Failed to review rules", error=str(e))
            return []

    def _apply_adjustment(self, adjustment: RuleAdjustment):
        """Apply a rule adjustment locally."""
        if adjustment.adjustment_type == "relaxation" and adjustment.old_rule:
            if adjustment.old_rule in self.cannot_do:
                self.cannot_do.remove(adjustment.old_rule)
                if adjustment.new_rule:
                    self.cannot_do.append(adjustment.new_rule)
        elif adjustment.adjustment_type == "clarification" and adjustment.old_rule:
            if adjustment.old_rule in self.can_do:
                idx = self.can_do.index(adjustment.old_rule)
                self.can_do[idx] = adjustment.new_rule
            elif adjustment.old_rule in self.cannot_do:
                idx = self.cannot_do.index(adjustment.old_rule)
                self.cannot_do[idx] = adjustment.new_rule
        elif adjustment.adjustment_type == "addition" and adjustment.new_rule:
            self.cannot_do.append(adjustment.new_rule)

        self.log.info(
            "Rule adjustment applied",
            type=adjustment.adjustment_type,
            old=adjustment.old_rule,
            new=adjustment.new_rule,
        )

    async def _escalate_to_queen(
        self,
        adjustment: RuleAdjustment,
        summary: FeedbackSummary,
    ):
        """Escalate a rule change decision to the Queen."""
        escalation = EscalationRequest(
            domain=self.domain,
            rule_in_question=adjustment.old_rule or adjustment.new_rule or "",
            feedback_summary=summary,
            proposed_adjustment=adjustment,
            orchestrator_recommendation=adjustment.rationale,
        )

        await self.send_json(
            to=["Queen"],
            subject=f"ESCALATION: {self.domain} rule change",
            data=escalation.model_dump(mode="json"),
        )

        self.log.info("Escalated rule change to Queen", rule=adjustment.old_rule)


def main():
    """Run the Orchestrator agent."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, choices=["web", "ai", "quant"])
    args = parser.parse_args()

    agent = OrchestratorAgent(args.domain)
    run_agent(agent)


if __name__ == "__main__":
    main()
