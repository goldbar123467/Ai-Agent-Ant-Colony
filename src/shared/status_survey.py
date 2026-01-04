"""
Status Survey System for Kyzlo Swarm.

Triggers pulse surveys across all agents, collects responses,
and generates summary analysis.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from .bridge import Bridge, BridgeClient, BridgeMessage
from .llm_client import LLMClient
from .schemas import AgentStatusReport, AgentRole

logger = structlog.get_logger()


class StatusSurveySystem:
    """
    Orchestrates status surveys across the swarm.

    Broadcasts survey requests via Bridge, collects responses,
    saves raw data, and generates summary analysis.
    """

    def __init__(
        self,
        bridge_client: Optional[BridgeClient] = None,
        llm_client: Optional[LLMClient] = None,
        reports_dir: str = "/data/status_reports",
    ):
        self.bridge = bridge_client or BridgeClient("SurveySystem", auto_join=["system"])
        self.llm = llm_client or LLMClient("thudm/glm-4")
        self.reports_dir = Path(reports_dir)
        self.log = logger.bind(component="StatusSurveySystem")

        # Create reports directory if it doesn't exist
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    async def trigger_survey(
        self,
        response_window: float = 30.0,
        expected_agents: int = 30,
    ) -> Dict[str, Any]:
        """
        Trigger a status survey across all agents.

        Args:
            response_window: Seconds to wait for responses
            expected_agents: Expected number of agent responses

        Returns:
            Summary analysis of survey responses
        """
        # Generate survey ID from timestamp
        survey_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.log.info("Triggering status survey", survey_id=survey_id)

        # Broadcast survey request via Bridge system channel
        self.bridge.signal(
            channel="system",
            signal_type="STATUS_SURVEY_REQUEST",
            data={
                "survey_id": survey_id,
                "response_window_seconds": response_window,
                "requested_at": datetime.utcnow().isoformat(),
            },
        )

        # Also broadcast to all domain channels for wider reach
        for channel in ["general", "web", "ai", "quant", "alerts"]:
            self.bridge.signal(
                channel=channel,
                signal_type="STATUS_SURVEY_REQUEST",
                data={
                    "survey_id": survey_id,
                    "response_window_seconds": response_window,
                },
            )

        self.log.info(
            "Survey request broadcast",
            survey_id=survey_id,
            response_window=response_window,
        )

        # Collect responses with timeout
        responses = await self._collect_responses(
            survey_id=survey_id,
            timeout=response_window,
            expected_count=expected_agents,
        )

        # Save raw responses to file
        report_path = self.reports_dir / f"survey_{survey_id}.json"
        raw_data = {
            "survey_id": survey_id,
            "triggered_at": datetime.utcnow().isoformat(),
            "response_window_seconds": response_window,
            "expected_agents": expected_agents,
            "responses_received": len(responses),
            "responses": [r.model_dump(mode="json") for r in responses],
        }

        with open(report_path, "w") as f:
            json.dump(raw_data, f, indent=2, default=str)

        self.log.info(
            "Survey responses saved",
            survey_id=survey_id,
            responses=len(responses),
            path=str(report_path),
        )

        # Generate and return summary analysis
        summary = self.analyze_responses(responses)
        summary["survey_id"] = survey_id
        summary["report_path"] = str(report_path)

        return summary

    async def _collect_responses(
        self,
        survey_id: str,
        timeout: float,
        expected_count: int,
    ) -> List[AgentStatusReport]:
        """
        Collect survey responses from Bridge.

        Listens for STATUS_SURVEY_RESPONSE signals on the system channel.
        """
        responses: List[AgentStatusReport] = []
        start_time = asyncio.get_event_loop().time()
        seen_agents = set()

        self.log.info("Collecting survey responses", timeout=timeout)

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                break

            if len(responses) >= expected_count:
                self.log.info("All expected responses received")
                break

            # Check for responses on system channel
            messages = self.bridge.check_messages("system", limit=50)

            for msg in messages:
                if msg.msg_type == "signal" and msg.metadata.get("signal") == "STATUS_SURVEY_RESPONSE":
                    response_data = msg.metadata.get("data", {})

                    # Skip if not for this survey
                    if response_data.get("survey_id") != survey_id:
                        continue

                    # Skip if already seen this agent
                    agent_id = response_data.get("agent_id")
                    if agent_id in seen_agents:
                        continue

                    seen_agents.add(agent_id)

                    try:
                        report = AgentStatusReport(**response_data)
                        responses.append(report)
                        self.log.debug(
                            "Received survey response",
                            agent_id=agent_id,
                            count=len(responses),
                        )
                    except Exception as e:
                        self.log.warning(
                            "Invalid survey response",
                            agent_id=agent_id,
                            error=str(e),
                        )

            # Small delay to avoid busy-waiting
            await asyncio.sleep(0.5)

        self.log.info(
            "Response collection complete",
            responses=len(responses),
            expected=expected_count,
        )

        return responses

    def analyze_responses(
        self,
        responses: List[AgentStatusReport],
    ) -> Dict[str, Any]:
        """
        Analyze survey responses and generate summary.

        Returns:
            Summary dictionary with quantitative rollups and qualitative groupings.
        """
        if not responses:
            return {
                "response_count": 0,
                "response_rate": 0.0,
                "tasks_clear_percentage": 0.0,
                "blockers_percentage": 0.0,
                "by_role": {},
            }

        total = len(responses)

        # Quantitative rollups
        tasks_clear_count = sum(1 for r in responses if r.q1_tasks_clear)
        blockers_count = sum(1 for r in responses if r.q2_blockers_waiting)

        # Group by role
        by_role: Dict[str, Dict[str, Any]] = {}

        for response in responses:
            role = response.agent_role.value

            if role not in by_role:
                by_role[role] = {
                    "count": 0,
                    "tasks_clear": 0,
                    "had_blockers": 0,
                    "hardest_things": [],
                    "suggestions": [],
                    "observations": [],
                }

            by_role[role]["count"] += 1
            if response.q1_tasks_clear:
                by_role[role]["tasks_clear"] += 1
            if response.q2_blockers_waiting:
                by_role[role]["had_blockers"] += 1

            by_role[role]["hardest_things"].append({
                "agent_id": response.agent_id,
                "text": response.q3_hardest_thing,
            })
            by_role[role]["suggestions"].append({
                "agent_id": response.agent_id,
                "text": response.q4_suggestion,
            })
            by_role[role]["observations"].append({
                "agent_id": response.agent_id,
                "text": response.q5_unexpected,
            })

        return {
            "response_count": total,
            "response_rate": total / 30.0,  # Assuming 30 agents
            "tasks_clear_percentage": (tasks_clear_count / total) * 100 if total > 0 else 0.0,
            "blockers_percentage": (blockers_count / total) * 100 if total > 0 else 0.0,
            "by_role": by_role,
        }

    async def get_past_surveys(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get list of past survey reports.

        Returns:
            List of survey metadata sorted by date (newest first)
        """
        surveys = []

        for report_file in sorted(self.reports_dir.glob("survey_*.json"), reverse=True):
            try:
                with open(report_file) as f:
                    data = json.load(f)
                    surveys.append({
                        "survey_id": data.get("survey_id"),
                        "triggered_at": data.get("triggered_at"),
                        "responses_received": data.get("responses_received", 0),
                        "path": str(report_file),
                    })
            except Exception as e:
                self.log.warning("Failed to read survey file", path=str(report_file), error=str(e))

            if len(surveys) >= limit:
                break

        return surveys

    async def load_survey(self, survey_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a specific survey by ID.

        Returns:
            Full survey data or None if not found
        """
        report_path = self.reports_dir / f"survey_{survey_id}.json"

        if not report_path.exists():
            return None

        try:
            with open(report_path) as f:
                return json.load(f)
        except Exception as e:
            self.log.error("Failed to load survey", survey_id=survey_id, error=str(e))
            return None
