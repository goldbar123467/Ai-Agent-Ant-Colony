"""
Scribe Agent - Memory Writer and Feedback Aggregator.

The Scribe observes all agent communications, writes memories to RAG Brain
after every task completion, collects worker feedback, and triggers
orchestrator rule reviews every 25 friction reports.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings, DOMAINS
from ..shared.schemas import (
    QAReport,
    QAStatus,
    WorkerOutput,
    FeedbackBlock,
    FeedbackSummary,
    MemoryCategory,
    MemoryRecord,
    TaskRecord,
)
from ..shared.agent_mail import Message

logger = structlog.get_logger()


SCRIBE_SYSTEM_PROMPT = """You are the Scribe agent, the memory writer for the Kyzlo Swarm system.

Your core mandate: Every task completion MUST produce at least one memory.
No silent completions. No forgotten work. No unrecorded outcomes.

Your responsibilities:
1. Observe all agent communications
2. Write memories to RAG Brain after every task completion
3. Collect worker feedback with non-null friction
4. Trigger orchestrator rule reviews every 25 friction reports
5. Extract patterns, outcomes, failures, violations, and decisions

Memory Types:
- outcome: Basic task completion record (always created)
- pattern: Reusable approaches from high-confidence successful work
- bug_fix: Failures, violations, and problems encountered
- decision: Orchestrator decisions, rule changes, escalations
- insight: Observations across multiple tasks

Memory Guidelines:
- Content must be self-contained and understandable without context
- Include specific details: project, domain, what worked/failed
- Tag appropriately for retrieval: domain, project, status, technologies
- Extract patterns only from high-confidence (>0.8) successful outputs
"""


class ScribeAgent(SwarmAgent):
    """Scribe - memory writer and feedback aggregator."""

    def __init__(self):
        super().__init__(
            name="Scribe",
            model=settings.models.scribe,
            # Join all channels to observe swarm activity
            bridge_channels=["web", "ai", "quant", "alerts", "system"],
            agent_role="scribe",
            agent_domain=None,
        )

        # Feedback tracking
        self.pending_feedback: List[Dict[str, Any]] = []
        self.friction_count = 0
        self.review_threshold = 25

        # Task tracking for memory extraction
        self.task_data: Dict[str, Dict[str, Any]] = {}

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("QA_REPORT:", self._handle_qa_report)
        self.mail.register_handler("WORKER_FEEDBACK:", self._handle_worker_feedback)
        self.mail.register_handler("VIOLATIONS:", self._handle_violations)
        self.mail.register_handler("ESCALATION:", self._handle_escalation)

    async def _handle_qa_report(self, message: Message):
        """Handle QA report - primary trigger for memory writing."""
        self.log.info("Received QA report", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse QA report")
            return

        try:
            qa_report = QAReport(**data)
        except Exception as e:
            self.log.error("Invalid QA report format", error=str(e))
            return

        # Signal start via Bridge
        self.status_update("busy", f"writing memories for task-{qa_report.task_id}")
        self.chat(qa_report.domain, f"Extracting memories from task {qa_report.task_id}...")

        # Extract and write memories
        memories = await self.extract_memories(qa_report)

        for memory in memories:
            result = await self.rag.remember_record(memory)
            if result.get("rejected"):
                self.log.warning(
                    "Memory rejected",
                    reason=result.get("reason"),
                    content=memory.content[:100],
                )
            else:
                self.log.info(
                    "Memory stored",
                    memory_id=result.get("memory_id"),
                    category=memory.category.value,
                )

        # Signal completion via Bridge
        self.status_update("done", f"task-{qa_report.task_id} memorized")
        self.chat(qa_report.domain, f"Wrote {len(memories)} memories for task {qa_report.task_id}")

        self.log.info(
            "Memories extracted",
            task_id=str(qa_report.task_id),
            memories_written=len(memories),
        )

    async def _handle_worker_feedback(self, message: Message):
        """Handle worker feedback for accumulation."""
        data = self.parse_json_from_message(message)
        if not data:
            return

        feedback = data.get("feedback", {})

        # Only track feedback with friction
        if feedback.get("friction"):
            self.friction_count += 1
            self.pending_feedback.append({
                "task_id": data.get("task_id"),
                "worker_id": data.get("worker_id"),
                "domain": data.get("domain"),
                "friction": feedback.get("friction"),
                "friction_detail": feedback.get("friction_detail"),
                "suggestion": feedback.get("suggestion"),
                "blocked_by_rule": feedback.get("blocked_by_rule"),
                "confidence": feedback.get("confidence"),
                "timestamp": datetime.utcnow().isoformat(),
            })

            self.log.debug(
                "Friction feedback tracked",
                worker_id=data.get("worker_id"),
                friction=feedback.get("friction"),
                count=self.friction_count,
            )

            # Check if we need to trigger review
            if self.friction_count >= self.review_threshold:
                # Alert via Bridge before triggering review
                self.signal("alerts", "rule_review_threshold", {
                    "friction_count": self.friction_count,
                })
                self.chat("general", f"Friction threshold reached ({self.friction_count}), triggering rule review...")
                await self._trigger_rule_review()

    async def _handle_violations(self, message: Message):
        """Handle violation reports from Wardens."""
        data = self.parse_json_from_message(message)
        if not data:
            return

        task_id = data.get("task_id")
        domain = data.get("domain")
        violations = data.get("violations", [])

        # Write violation memories
        for v in violations:
            memory = MemoryRecord(
                content=f"Violation in {domain} domain: Worker {v['worker_id']} violated rule '{v['rule']}'. "
                f"Description: {v['description']}. Severity: {v['severity']}.",
                category=MemoryCategory.BUG_FIX,
                tags=[domain, "violation", v["severity"], f"worker-{v['worker_id']}"],
                project=self.project_key,
                extra_data={
                    "task_id": task_id,
                    "worker_id": v["worker_id"],
                    "rule": v["rule"],
                    "severity": v["severity"],
                },
            )

            result = await self.rag.remember_record(memory)
            self.log.info(
                "Violation memory stored",
                memory_id=result.get("memory_id"),
                rule=v["rule"],
            )

    async def _handle_escalation(self, message: Message):
        """Handle escalation events for decision memory."""
        data = self.parse_json_from_message(message)
        if not data:
            return

        domain = data.get("domain", "unknown")
        rule = data.get("rule_in_question", "unknown rule")

        memory = MemoryRecord(
            content=f"Rule escalation in {domain} domain. Rule in question: {rule}. "
            f"This decision was escalated to Queen for review due to unclear resolution path.",
            category=MemoryCategory.DECISION,
            tags=[domain, "escalation", "rule_change"],
            project=self.project_key,
            extra_data=data,
        )

        await self.rag.remember_record(memory)
        self.log.info("Escalation memory stored", domain=domain, rule=rule)

    async def extract_memories(self, qa_report: QAReport) -> List[MemoryRecord]:
        """Extract memories from a QA report."""
        memories = []

        # Always create outcome memory
        outcome_memory = await self._create_outcome_memory(qa_report)
        memories.append(outcome_memory)

        # Extract patterns from successful tasks with high quality
        if qa_report.status == QAStatus.PASSED and qa_report.quality_score >= 0.8:
            patterns = await self._extract_patterns(qa_report)
            memories.extend(patterns)

        # Create failure memory for failed tasks
        if qa_report.status in [QAStatus.FAILED, QAStatus.BLOCKED]:
            failure_memory = await self._create_failure_memory(qa_report)
            memories.append(failure_memory)

        return memories

    async def _create_outcome_memory(self, qa_report: QAReport) -> MemoryRecord:
        """Create an outcome memory for task completion."""
        status_text = qa_report.status.value
        quality_text = f"{qa_report.quality_score:.0%}"

        content = (
            f"Task completed in {qa_report.domain} domain. "
            f"Status: {status_text}. Quality score: {quality_text}. "
            f"Duration: {qa_report.duration_ms}ms."
        )

        if qa_report.issues:
            content += f" Issues encountered: {', '.join(qa_report.issues[:3])}."

        return MemoryRecord(
            content=content,
            category=MemoryCategory.OUTCOME,
            tags=[
                qa_report.domain,
                status_text,
                f"quality-{int(qa_report.quality_score * 10)}",
            ],
            project=self.project_key,
            extra_data={
                "task_id": str(qa_report.task_id),
                "domain": qa_report.domain,
                "status": status_text,
                "quality_score": qa_report.quality_score,
                "duration_ms": qa_report.duration_ms,
                "issues": qa_report.issues,
            },
        )

    async def _extract_patterns(self, qa_report: QAReport) -> List[MemoryRecord]:
        """Extract reusable patterns from high-quality successful work."""
        # Use LLM to identify patterns
        messages = [
            {"role": "system", "content": SCRIBE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Extract reusable patterns from this successful task.

Domain: {qa_report.domain}
Quality Score: {qa_report.quality_score}
Status: {qa_report.status.value}
Recommendations (things that worked well): {qa_report.recommendations}

Identify 0-2 patterns worth remembering for future tasks.
Each pattern should be specific and actionable.

Respond with JSON array of pattern objects:
- content: description of the pattern (2-3 sentences, specific and actionable)
- tags: array of relevant tags
""",
            },
        ]

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content", "tags"],
            },
            "maxItems": 2,
        }

        try:
            result = await self.complete_json(messages, schema)
            patterns_data = result["data"]

            patterns = []
            for p in patterns_data:
                patterns.append(
                    MemoryRecord(
                        content=p["content"],
                        category=MemoryCategory.PATTERN,
                        tags=[qa_report.domain, "pattern"] + p.get("tags", []),
                        project=self.project_key,
                        extra_data={"task_id": str(qa_report.task_id)},
                    )
                )
            return patterns

        except Exception as e:
            self.log.error("Pattern extraction failed", error=str(e))
            return []

    async def _create_failure_memory(self, qa_report: QAReport) -> MemoryRecord:
        """Create a failure memory for failed tasks."""
        issues_text = ". ".join(qa_report.issues[:5]) if qa_report.issues else "No specific issues noted"

        content = (
            f"Task failed in {qa_report.domain} domain. "
            f"Quality score: {qa_report.quality_score:.0%}. "
            f"Issues: {issues_text}"
        )

        return MemoryRecord(
            content=content,
            category=MemoryCategory.BUG_FIX,
            tags=[qa_report.domain, "failure", qa_report.status.value],
            project=self.project_key,
            extra_data={
                "task_id": str(qa_report.task_id),
                "issues": qa_report.issues,
                "recommendations": qa_report.recommendations,
            },
        )

    async def _trigger_rule_review(self):
        """Trigger rule review for orchestrators."""
        self.log.info(
            "Triggering rule review",
            friction_count=self.friction_count,
        )

        # Group feedback by domain
        feedback_by_domain: Dict[str, List[Dict]] = {}
        for fb in self.pending_feedback:
            domain = fb.get("domain", "unknown")
            if domain not in feedback_by_domain:
                feedback_by_domain[domain] = []
            feedback_by_domain[domain].append(fb)

        # Send review trigger to each orchestrator with feedback
        for domain, feedbacks in feedback_by_domain.items():
            if domain not in DOMAINS:
                continue

            # Build summary
            friction_counts: Dict[str, int] = {}
            blocked_rules: Dict[str, int] = {}
            suggestions: Dict[str, int] = {}

            for fb in feedbacks:
                # Count friction types
                friction = fb.get("friction")
                if friction:
                    friction_counts[friction] = friction_counts.get(friction, 0) + 1

                # Count blocked rules
                rule = fb.get("blocked_by_rule")
                if rule:
                    blocked_rules[rule] = blocked_rules.get(rule, 0) + 1

                # Count suggestions
                suggestion = fb.get("suggestion")
                if suggestion:
                    suggestions[suggestion] = suggestions.get(suggestion, 0) + 1

            # Calculate average confidence
            confidences = [fb.get("confidence", 0.5) for fb in feedbacks]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

            summary = FeedbackSummary(
                feedback_count=len(feedbacks),
                friction_counts=friction_counts,
                most_blocked_rules=sorted(
                    blocked_rules.keys(),
                    key=lambda r: blocked_rules[r],
                    reverse=True,
                )[:5],
                top_suggestions=sorted(
                    suggestions.keys(),
                    key=lambda s: suggestions[s],
                    reverse=True,
                )[:5],
                average_confidence=avg_confidence,
                feedback_records=feedbacks,
            )

            orchestrator = f"Orch-{domain.capitalize()}"
            await self.send_json(
                to=[orchestrator],
                subject=f"REVIEW_TRIGGER: {domain}",
                data=summary.model_dump(mode="json"),
            )

            self.log.info(
                "Review trigger sent",
                orchestrator=orchestrator,
                feedback_count=len(feedbacks),
            )

        # Write review event memory
        memory = MemoryRecord(
            content=f"Rule review triggered after {self.friction_count} friction reports. "
            f"Domains affected: {list(feedback_by_domain.keys())}.",
            category=MemoryCategory.DECISION,
            tags=["rule_review", "feedback_threshold"],
            project=self.project_key,
            extra_data={
                "friction_count": self.friction_count,
                "domains": list(feedback_by_domain.keys()),
            },
        )
        await self.rag.remember_record(memory)

        # Reset counters
        self.friction_count = 0
        self.pending_feedback = []


def main():
    """Run the Scribe agent."""
    agent = ScribeAgent()
    run_agent(agent)


if __name__ == "__main__":
    main()
