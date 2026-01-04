"""
QA Reporter Agent - Quality Assessment Layer.

The QA Reporter receives merged outputs from Wardens, assesses quality,
runs appropriate tests, and produces status reports for Scribe.
"""

import time
from typing import Dict, Any, List, Optional
from uuid import UUID

import structlog

from ..shared.base_agent import SwarmAgent, run_agent
from ..shared.config import settings
from ..shared.schemas import (
    MergedResult,
    QAReport,
    QAStatus,
)
from ..shared.agent_mail import Message

logger = structlog.get_logger()


QA_SYSTEM_PROMPT = """You are the QA Reporter for the Kyzlo Swarm system.

Your responsibilities:
1. Assess the quality of merged worker outputs
2. Check for completeness and correctness
3. Identify issues and potential improvements
4. Produce comprehensive quality reports
5. Signal pass/fail status for Scribe memory categorization

Quality Assessment Criteria:
- Completeness: Does the output fulfill all requirements?
- Correctness: Is the output technically correct?
- Consistency: Are all parts consistent with each other?
- Code Quality: For code outputs, check structure, patterns, best practices
- Documentation: Is the output well-documented where needed?

Quality Score Guidelines:
- 0.9-1.0: Excellent, production-ready
- 0.7-0.9: Good, minor improvements possible
- 0.5-0.7: Acceptable, needs some work
- 0.3-0.5: Poor, significant issues
- 0.0-0.3: Failing, major problems

Report honestly. Scribe uses your assessment to categorize memories.
Successful patterns should be captured differently than failed attempts.
"""


class QAReporterAgent(SwarmAgent):
    """QA Reporter - quality assessment and reporting."""

    def __init__(self):
        super().__init__(
            name="QAReporter",
            model=settings.models.qa_reporter,
            # Join all domain channels + alerts for QA updates
            bridge_channels=["web", "ai", "quant", "alerts", "system"],
            agent_role="qa_reporter",
            agent_domain=None,
        )

    async def _setup_handlers(self):
        """Register message handlers."""
        self.mail.register_handler("MERGED_RESULT:", self._handle_merged_result)

    async def _handle_merged_result(self, message: Message):
        """Handle merged result from Warden."""
        self.log.info("Received merged result", from_agent=message.from_agent)

        data = self.parse_json_from_message(message)
        if not data:
            self.log.error("Failed to parse merged result")
            return

        try:
            merged = MergedResult(**data)
        except Exception as e:
            self.log.error("Invalid merged result format", error=str(e))
            return

        # Signal start via Bridge
        self.status_update("busy", f"assessing task-{merged.task_id}")
        self.chat(merged.domain, f"Starting quality assessment for task {merged.task_id}...")

        # Assess quality
        qa_report = await self.assess_quality(merged)

        # Send report to Scribe
        await self.send_json(
            to=["Scribe"],
            subject=f"QA_REPORT: {merged.task_id}",
            data=qa_report.model_dump(mode="json"),
            thread_id=f"TASK-{merged.task_id}",
        )

        # Notify Queen of completion
        await self.send_json(
            to=["Queen"],
            subject=f"TASK_COMPLETE: {merged.task_id}",
            data={
                "task_id": str(merged.task_id),
                "domain": merged.domain,
                "status": qa_report.status.value,
                "quality_score": qa_report.quality_score,
            },
            thread_id=f"TASK-{merged.task_id}",
        )

        # Signal completion via Bridge
        status_emoji = "passed" if qa_report.status.value == "passed" else "needs_attention"
        self.status_update("done", f"task-{merged.task_id} {qa_report.status.value}")
        self.chat(
            merged.domain,
            f"QA complete: {qa_report.status.value} (quality: {qa_report.quality_score:.0%})"
        )

        # Alert if quality is low
        if qa_report.quality_score < 0.5:
            self.signal("alerts", "low_quality", {
                "task_id": str(merged.task_id),
                "domain": merged.domain,
                "quality": qa_report.quality_score,
            })

        self.log.info(
            "QA assessment complete",
            task_id=str(merged.task_id),
            status=qa_report.status.value,
            quality=qa_report.quality_score,
        )

    async def assess_quality(self, merged: MergedResult) -> QAReport:
        """Assess quality of merged outputs."""
        start_time = time.time()

        # Build summary of outputs for assessment
        outputs_summary = []
        for output in merged.worker_outputs:
            outputs_summary.append({
                "worker_id": output.worker_id,
                "slice_id": output.slice_id,
                "task_type": output.task_type.value,
                "deliverable_type": output.deliverable.type.value,
                "file_path": output.deliverable.file_path,
                "content_preview": output.deliverable.content[:500] if output.deliverable.content else "",
                "confidence": output.feedback.confidence,
            })

        # Build validation summary
        validation_summary = []
        for result in merged.validation_results:
            validation_summary.append({
                "worker_id": result.worker_id,
                "status": result.status.value,
                "violations_count": len(result.violations),
                "notes": result.notes,
            })

        messages = [
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Assess the quality of this task output.

Task ID: {merged.task_id}
Domain: {merged.domain}
Total Violations: {merged.total_violations}
Conflicts: {merged.conflicts}

Worker Outputs:
{self._format_outputs_summary(outputs_summary)}

Validation Results:
{self._format_validation_summary(validation_summary)}

Files Created:
{list(merged.merged_files.keys())}

Respond with JSON containing:
- status: "passed", "failed", "partial", or "blocked"
- quality_score: 0.0-1.0
- issues: array of issue descriptions
- recommendations: array of improvement suggestions
- test_results: object with any test observations
""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["passed", "failed", "partial", "blocked"],
                },
                "quality_score": {"type": "number", "minimum": 0, "maximum": 1},
                "issues": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "test_results": {"type": "object"},
            },
            "required": ["status", "quality_score", "issues", "recommendations"],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]

            duration_ms = int((time.time() - start_time) * 1000)

            return QAReport(
                task_id=merged.task_id,
                domain=merged.domain,
                status=QAStatus(data["status"]),
                quality_score=data["quality_score"],
                issues=data["issues"],
                recommendations=data["recommendations"],
                test_results=data.get("test_results", {}),
                duration_ms=duration_ms,
            )

        except Exception as e:
            self.log.error("QA assessment failed", error=str(e))
            duration_ms = int((time.time() - start_time) * 1000)

            return QAReport(
                task_id=merged.task_id,
                domain=merged.domain,
                status=QAStatus.FAILED,
                quality_score=0.0,
                issues=[f"QA assessment error: {str(e)}"],
                recommendations=["Manual review required"],
                duration_ms=duration_ms,
            )

    def _format_outputs_summary(self, outputs: List[Dict]) -> str:
        """Format outputs summary for prompt."""
        lines = []
        for o in outputs:
            lines.append(
                f"- Worker {o['worker_id']}: {o['task_type']}, "
                f"confidence={o['confidence']:.2f}, "
                f"file={o['file_path'] or 'N/A'}"
            )
        return "\n".join(lines)

    def _format_validation_summary(self, validations: List[Dict]) -> str:
        """Format validation summary for prompt."""
        lines = []
        for v in validations:
            lines.append(
                f"- Worker {v['worker_id']}: {v['status']}, "
                f"violations={v['violations_count']}"
            )
        return "\n".join(lines)


def main():
    """Run the QA Reporter agent."""
    agent = QAReporterAgent()
    run_agent(agent)


if __name__ == "__main__":
    main()
