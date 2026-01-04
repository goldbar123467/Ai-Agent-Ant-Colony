"""
Worker Agent - Task Execution Layer.

Workers receive task slices from Orchestrators, execute within their
constraint envelope, and return outputs with MANDATORY feedback blocks.
"""

import argparse
import time
from typing import Dict, Any, List, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings, DOMAINS
from ..shared.schemas import (
    TaskSlice,
    TaskType,
    WorkerOutput,
    Deliverable,
    DeliverableType,
    Metrics,
    FeedbackBlock,
    FrictionType,
)
from ..shared.agent_mail import Message
from ..shared.comm_laws import get_survival_notice

logger = structlog.get_logger()


WORKER_SYSTEM_PROMPT = """{survival_notice}

You are Worker-{worker_id}, a specialized worker in the Kyzlo Swarm system.

Domain: {domain}
Specialization: {specialization}

Your responsibilities:
1. Execute the assigned task slice within your constraints
2. Produce high-quality output matching the task type
3. Provide MANDATORY feedback about your experience

CONSTRAINT ENVELOPE - You MUST follow these rules:
CAN DO:
{can_do}

CANNOT DO:
{cannot_do}

If a constraint prevents you from doing necessary work:
- Complete what you can within constraints
- Report the friction in your feedback
- Suggest how the rule could be improved

Task Types and Expected Output:
- code: Create source files with file path and content
- research: Structured findings with sources and recommendations
- planning: Step-by-step plans with dependencies and risks
- design: Architecture documents with rationale and tradeoffs
- debug: Root cause analysis with remediation steps
- documentation: Formatted docs ready for use
- conversation: Natural language responses
- analysis: Structured analysis with key points and conclusions

FEEDBACK IS MANDATORY - Every output MUST include:
- confidence: Your confidence in the output quality (0.0-1.0)
- task_fit: How well this slice matched your specialization (0.0-1.0)
- clarity: How clear the instructions were (0.0-1.0)
- context_quality: Quality of provided context (0.0-1.0)
- friction: Any constraint that blocked your work (optional)
- suggestion: How the system could improve (optional)
"""


class WorkerAgent(SwarmAgent):
    """Worker - task execution within constraint envelope."""

    def __init__(self, worker_id: int):
        self.worker_id = worker_id

        # Determine domain from worker ID
        if 1 <= worker_id <= 7:
            self.domain = "web"
        elif 8 <= worker_id <= 14:
            self.domain = "ai"
        else:
            self.domain = "quant"

        self.domain_config = DOMAINS[self.domain]
        self.specialization = self.domain_config.specializations.get(
            worker_id, "general"
        )

        super().__init__(
            name=f"Worker-{worker_id}",
            model=settings.models.worker,
            # Join domain-specific Bridge channel for quick coordination
            bridge_channels=[self.domain, "system"],
            agent_role="worker",
            agent_domain=self.domain,
        )

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("TASK_SLICE:", self._handle_task_slice)

    async def _handle_task_slice(self, message: Message):
        """Handle a task slice assignment from Orchestrator."""
        self.log.info("Received task slice", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse task slice")
            return

        try:
            task_slice = TaskSlice(**data)
        except Exception as e:
            self.log.error("Invalid task slice format", error=str(e))
            return

        # Signal start via Bridge (quick, no Agent Mail overhead)
        self.status_update("busy", f"slice-{task_slice.slice_id}")
        self.chat(self.domain, f"Starting slice {task_slice.slice_id}: {task_slice.task_type.value}")

        # Execute the slice
        output = await self.execute_slice(task_slice)

        # Signal completion via Bridge
        self.status_update("done", f"slice-{task_slice.slice_id} conf={output.feedback.confidence:.2f}")

        # Send output to orchestrator
        orchestrator = f"Orch-{self.domain.capitalize()}"
        await self.send_json(
            to=[orchestrator],
            subject=f"WORKER_OUTPUT: {task_slice.task_id}",
            data=output.model_dump(mode="json"),
            thread_id=f"TASK-{task_slice.task_id}",
        )

        # Also notify Scribe (for feedback tracking)
        await self.send_json(
            to=["Scribe"],
            subject=f"WORKER_FEEDBACK: {task_slice.task_id}",
            data={
                "task_id": str(task_slice.task_id),
                "worker_id": self.worker_id,
                "domain": self.domain,
                "feedback": output.feedback.model_dump(mode="json"),
            },
            thread_id=f"TASK-{task_slice.task_id}",
        )

        self.log.info(
            "Slice completed",
            task_id=str(task_slice.task_id),
            slice_id=task_slice.slice_id,
            confidence=output.feedback.confidence,
        )

    async def execute_slice(self, task_slice: TaskSlice) -> WorkerOutput:
        """Execute a task slice and produce output with mandatory feedback."""
        start_time = time.time()

        # Build context string from slice context
        context_str = self._format_context(task_slice.context)

        # Build the execution prompt
        messages = [
            {
                "role": "system",
                "content": WORKER_SYSTEM_PROMPT.format(
                    survival_notice=self.get_survival_notice(),
                    worker_id=self.worker_id,
                    domain=self.domain,
                    specialization=self.specialization,
                    can_do="\n".join(f"- {r}" for r in task_slice.constraints.can_do),
                    cannot_do="\n".join(f"- {r}" for r in task_slice.constraints.cannot_do),
                ),
            },
            {
                "role": "user",
                "content": f"""Execute this task slice.

Task Type: {task_slice.task_type.value}
Description: {task_slice.description}
Assigned File: {task_slice.assigned_file or "Not specified"}

Context:
{context_str}

Respond with JSON containing:
1. deliverable:
   - type: "file", "text", "list", or "structured"
   - file_path: (if type is file) the path to create
   - content: the actual output content
   - items: (if type is list) array of items
   - data: (if type is structured) structured data object

2. feedback (MANDATORY - never omit):
   - confidence: 0.0-1.0 (your confidence in output quality)
   - task_fit: 0.0-1.0 (how well this matched your specialization)
   - clarity: 0.0-1.0 (how clear the instructions were)
   - context_quality: 0.0-1.0 (quality of provided context)
   - friction: null or one of: "rule_too_strict", "rule_unclear", "missing_context", "wrong_slice", "dependency_issue", "tooling_gap", "scope_too_big", "scope_too_small", "ambiguous_request"
   - friction_detail: explanation if friction is not null
   - suggestion: how to improve (optional)
   - blocked_by_rule: exact rule text that blocked you (optional)
   - would_change: what you'd do differently without constraints (optional)
""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "deliverable": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["file", "text", "list", "structured"],
                        },
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                        "data": {"type": "object"},
                    },
                    "required": ["type", "content"],
                },
                "feedback": {
                    "type": "object",
                    "properties": {
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "task_fit": {"type": "number", "minimum": 0, "maximum": 1},
                        "clarity": {"type": "number", "minimum": 0, "maximum": 1},
                        "context_quality": {"type": "number", "minimum": 0, "maximum": 1},
                        "friction": {
                            "type": "string",
                            "enum": [
                                "rule_too_strict",
                                "rule_unclear",
                                "missing_context",
                                "wrong_slice",
                                "dependency_issue",
                                "tooling_gap",
                                "scope_too_big",
                                "scope_too_small",
                                "ambiguous_request",
                                None,
                            ],
                        },
                        "friction_detail": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "blocked_by_rule": {"type": "string"},
                        "would_change": {"type": "string"},
                    },
                    "required": ["confidence", "task_fit", "clarity", "context_quality"],
                },
            },
            "required": ["deliverable", "feedback"],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]
            tokens_used = result.get("tokens_used", 0)

            duration_ms = int((time.time() - start_time) * 1000)

            # Build deliverable
            del_data = data["deliverable"]
            deliverable = Deliverable(
                type=DeliverableType(del_data["type"]),
                file_path=del_data.get("file_path"),
                content=del_data.get("content", ""),
                items=del_data.get("items"),
                data=del_data.get("data"),
            )

            # Build feedback (MANDATORY)
            fb_data = data["feedback"]
            friction = None
            if fb_data.get("friction"):
                try:
                    friction = FrictionType(fb_data["friction"])
                except ValueError:
                    pass

            feedback = FeedbackBlock(
                confidence=fb_data["confidence"],
                task_fit=fb_data["task_fit"],
                clarity=fb_data["clarity"],
                context_quality=fb_data["context_quality"],
                friction=friction,
                friction_detail=fb_data.get("friction_detail"),
                suggestion=fb_data.get("suggestion"),
                blocked_by_rule=fb_data.get("blocked_by_rule"),
                would_change=fb_data.get("would_change"),
            )

            return WorkerOutput(
                task_id=task_slice.task_id,
                worker_id=self.worker_id,
                slice_id=task_slice.slice_id,
                task_type=task_slice.task_type,
                deliverable=deliverable,
                metrics=Metrics(tokens_used=tokens_used, duration_ms=duration_ms),
                feedback=feedback,
            )

        except Exception as e:
            self.log.error("Slice execution failed", error=str(e))
            duration_ms = int((time.time() - start_time) * 1000)

            # Return error output with mandatory feedback
            return WorkerOutput(
                task_id=task_slice.task_id,
                worker_id=self.worker_id,
                slice_id=task_slice.slice_id,
                task_type=task_slice.task_type,
                deliverable=Deliverable(
                    type=DeliverableType.TEXT,
                    content=f"Error executing slice: {str(e)}",
                ),
                metrics=Metrics(tokens_used=0, duration_ms=duration_ms),
                feedback=FeedbackBlock(
                    confidence=0.0,
                    task_fit=0.5,
                    clarity=0.5,
                    context_quality=0.5,
                    friction=FrictionType.TOOLING_GAP,
                    friction_detail=f"Execution error: {str(e)}",
                ),
            )

    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context from RAG Brain for the prompt."""
        parts = []

        if context.get("project_profile"):
            profile = context["project_profile"]
            if isinstance(profile, dict):
                parts.append(f"Project: {profile.get('content', profile)[:500]}")
            else:
                parts.append(f"Project: {str(profile)[:500]}")

        if context.get("patterns"):
            parts.append("\nRelevant Patterns:")
            for p in context["patterns"][:3]:
                if isinstance(p, dict):
                    parts.append(f"- {p.get('content', str(p))[:200]}")
                else:
                    parts.append(f"- {str(p)[:200]}")

        if context.get("failures"):
            parts.append("\nFailures to Avoid:")
            for f in context["failures"][:3]:
                if isinstance(f, dict):
                    parts.append(f"- {f.get('content', str(f))[:200]}")
                else:
                    parts.append(f"- {str(f)[:200]}")

        return "\n".join(parts) if parts else "No additional context provided."


def main():
    """Run a Worker agent."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", type=int, required=True)
    args = parser.parse_args()

    agent = WorkerAgent(args.worker_id)
    run_agent(agent)


if __name__ == "__main__":
    main()
