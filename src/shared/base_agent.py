"""Base agent class for Kyzlo Swarm agents."""

import asyncio
import json
import signal
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import structlog

from .agent_mail import AgentMailClient, Message
from .bridge import BridgeClient, Signals
from .config import settings
from .llm_client import LLMClient
from .rag_client import RAGBrainClient
from .comm_laws import get_survival_notice, check_agent_alive, get_agent_violation_count, revoked_registry

logger = structlog.get_logger()


class SwarmAgent(ABC):
    """
    Base class for all Kyzlo Swarm agents.

    Provides common functionality for:
    - Agent Mail communication (formal, tracked messages)
    - Bridge communication (quick, lightweight coordination)
    - RAG Brain memory access
    - LLM completion
    - Lifecycle management (start/stop)
    - Message handling

    Communication Strategy:
    - Use Agent Mail for: task assignments, outputs, formal tracking
    - Use Bridge for: status updates, quick queries, coordination signals
    """

    def __init__(
        self,
        name: str,
        model: str,
        project_key: Optional[str] = None,
        bridge_channels: Optional[List[str]] = None,
        agent_role: Optional[str] = None,
        agent_domain: Optional[str] = None,
    ):
        self.name = name
        self.model = model
        self.project_key = project_key or settings.project_key

        # Agent identity for communication laws
        self._agent_role = agent_role
        self._agent_domain = agent_domain

        # Clients (pass identity for communication law enforcement)
        self.mail = AgentMailClient(
            name,
            self.project_key,
            agent_role=agent_role,
            agent_domain=agent_domain,
        )
        self.llm = LLMClient(model)
        self.rag = RAGBrainClient()

        # Bridge for lightweight messaging
        self.bridge = BridgeClient(
            name,
            auto_join=bridge_channels,
            agent_role=agent_role,
            agent_domain=agent_domain,
        )

        # State
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Configure logging
        self.log = logger.bind(agent=name)

    async def start(self):
        """Start the agent - register and begin message polling."""
        self.log.info("Starting agent")

        # Register with Agent Mail
        await self.mail.register(program="kyzlo-swarm", model=self.model)

        # Set up message handlers
        await self._setup_handlers()

        # Start polling
        await self.mail.start_polling(interval=2.0)

        self._running = True
        self.log.info("Agent started")

        # Run until shutdown
        await self._run()

    async def stop(self):
        """Stop the agent gracefully."""
        self.log.info("Stopping agent")
        self._running = False
        self._shutdown_event.set()

        await self.mail.stop_polling()
        await self.mail.close()
        await self.llm.close()
        await self.rag.close()

        self.log.info("Agent stopped")

    async def _run(self):
        """Main run loop - wait for shutdown signal while checking for survey requests."""
        try:
            # Start survey listener task
            survey_task = asyncio.create_task(self._survey_listener())

            await self._shutdown_event.wait()

            # Cancel survey listener on shutdown
            survey_task.cancel()
            try:
                await survey_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass

    async def _survey_listener(self):
        """Listen for STATUS_SURVEY_REQUEST signals on Bridge."""
        while self._running:
            try:
                # Check system channel for survey requests
                for channel in ["system", "general"]:
                    messages = self.bridge.check_messages(channel, limit=10)

                    for msg in messages:
                        if msg.msg_type == "signal" and msg.metadata.get("signal") == "STATUS_SURVEY_REQUEST":
                            survey_data = msg.metadata.get("data", {})
                            survey_id = survey_data.get("survey_id")

                            if survey_id:
                                await self._respond_to_survey(survey_id)

                # Small delay between checks
                await asyncio.sleep(2.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error("Survey listener error", error=str(e))
                await asyncio.sleep(5.0)

    async def _respond_to_survey(self, survey_id: str):
        """Respond to a survey request."""
        self.log.info("Responding to status survey", survey_id=survey_id)

        try:
            # Fill out the survey
            report = await self.fill_status_survey(survey_id)

            # Send response via Bridge
            self.bridge.signal(
                channel="system",
                signal_type="STATUS_SURVEY_RESPONSE",
                data=report.model_dump(mode="json"),
            )

            self.log.info("Survey response sent", survey_id=survey_id)

        except Exception as e:
            self.log.error("Failed to respond to survey", survey_id=survey_id, error=str(e))

    @abstractmethod
    async def _setup_handlers(self):
        """Set up message handlers. Override in subclasses."""
        pass

    # -------------------------------------------------------------------------
    # Communication helpers
    # -------------------------------------------------------------------------

    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        importance: str = "normal",
    ) -> Optional[Dict[str, Any]]:
        """Send a message to other agents."""
        return await self.mail.send(
            to=to,
            subject=subject,
            body=body,
            thread_id=thread_id,
            importance=importance,
        )

    async def send_json(
        self,
        to: List[str],
        subject: str,
        data: Dict[str, Any],
        thread_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON message to other agents."""
        body = f"```json\n{json.dumps(data, indent=2, default=str)}\n```"
        return await self.send(to, subject, body, thread_id)

    async def reply(
        self,
        original: Message,
        subject: str,
        body: str,
    ) -> Optional[Dict[str, Any]]:
        """Reply to a message, preserving thread."""
        return await self.send(
            to=[original.from_agent],
            subject=subject,
            body=body,
            thread_id=original.thread_id,
        )

    # -------------------------------------------------------------------------
    # Bridge helpers (lightweight/quick communication)
    # -------------------------------------------------------------------------

    def chat(self, channel: str, message: str):
        """Send a quick chat message via Bridge."""
        return self.bridge.say(channel, message)

    def status_update(self, status: str, details: Optional[str] = None):
        """Post a status update (ready, busy, done, blocked, error)."""
        return self.bridge.status(status, details)

    def signal(self, channel: str, signal_type: str, data: Optional[Dict] = None):
        """Send a coordination signal via Bridge."""
        return self.bridge.signal(channel, signal_type, data)

    async def quick_query(self, channel: str, question: str, timeout: float = 5.0):
        """Ask a quick question and wait for response via Bridge."""
        return await self.bridge.ask(channel, question, timeout)

    def check_bridge(self, channel: str, limit: int = 10):
        """Check for new Bridge messages on a channel."""
        return self.bridge.check_messages(channel, limit)

    # -------------------------------------------------------------------------
    # LLM helpers
    # -------------------------------------------------------------------------

    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """Get an LLM completion."""
        return await self.llm.complete(messages, temperature=temperature)

    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Get a structured JSON completion."""
        return await self.llm.complete_json(messages, schema, temperature=temperature)

    # -------------------------------------------------------------------------
    # RAG helpers
    # -------------------------------------------------------------------------

    async def remember(
        self,
        content: str,
        category: str,
        tags: List[str],
        project: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a memory in RAG Brain."""
        from .schemas import MemoryCategory

        return await self.rag.remember(
            content=content,
            category=MemoryCategory(category),
            tags=tags,
            project=project or self.project_key,
        )

    async def recall(
        self,
        query: str,
        limit: int = 5,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query memories from RAG Brain."""
        return await self.rag.recall(
            query=query,
            project=project or self.project_key,
            tags=tags,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_json_from_message(message: Message) -> Optional[Dict[str, Any]]:
        """Extract JSON from a message body (expects ```json blocks)."""
        body = message.body
        if "```json" in body:
            start = body.find("```json") + 7
            end = body.find("```", start)
            if end > start:
                try:
                    return json.loads(body[start:end].strip())
                except json.JSONDecodeError:
                    pass
        return None

    # -------------------------------------------------------------------------
    # Status Survey
    # -------------------------------------------------------------------------

    async def fill_status_survey(self, survey_id: str) -> "AgentStatusReport":
        """
        Fill out a status survey with honest, reflective answers.

        Gathers context from recent activity and uses LLM to generate responses.
        """
        from .schemas import AgentStatusReport, AgentRole, DomainType

        # Gather recent context from Bridge channels
        recent_activity = []
        for channel in ["general", "status", "alerts"]:
            messages = self.bridge.check_messages(channel, limit=20)
            for msg in messages:
                recent_activity.append(f"[{channel}] {msg.sender}: {msg.content}")

        # Include domain channel if applicable
        if self._agent_domain:
            domain_messages = self.bridge.check_messages(self._agent_domain, limit=20)
            for msg in domain_messages:
                recent_activity.append(f"[{self._agent_domain}] {msg.sender}: {msg.content}")

        activity_summary = "\n".join(recent_activity[-30:]) if recent_activity else "No recent activity recorded."

        # Build prompt for honest reflection
        messages = [
            {
                "role": "system",
                "content": f"""You are {self.name}, an agent in the Kyzlo Swarm system.
You are being asked to fill out a status survey. Be SPECIFIC and TRUTHFUL.
If something is confusing or broken, report it honestly. Do not sugarcoat issues.
If everything is working well, say so clearly.

Your role: {self._agent_role or 'unknown'}
Your domain: {self._agent_domain or 'none'}

Answer each question thoughtfully based on your recent experience.""",
            },
            {
                "role": "user",
                "content": f"""Fill out this status survey based on your recent activity.

Recent activity context:
{activity_summary}

Answer these questions:
1. q1_tasks_clear (boolean): Were assigned tasks clear and actionable?
2. q2_blockers_waiting (boolean): Did you experience blockers waiting on other agents?
3. q3_hardest_thing (max 200 chars): What was the hardest thing you handled this cycle?
4. q4_suggestion (max 200 chars): One suggestion that would make your job easier.
5. q5_unexpected (max 200 chars): Anything unexpected you noticed in the system?

Respond with JSON containing these exact keys. Be specific and honest.""",
            },
        ]

        schema = {
            "type": "object",
            "properties": {
                "q1_tasks_clear": {"type": "boolean"},
                "q2_blockers_waiting": {"type": "boolean"},
                "q3_hardest_thing": {"type": "string", "maxLength": 200},
                "q4_suggestion": {"type": "string", "maxLength": 200},
                "q5_unexpected": {"type": "string", "maxLength": 200},
            },
            "required": [
                "q1_tasks_clear",
                "q2_blockers_waiting",
                "q3_hardest_thing",
                "q4_suggestion",
                "q5_unexpected",
            ],
        }

        try:
            result = await self.complete_json(messages, schema)
            data = result["data"]

            # Map domain string to enum if applicable
            domain_enum = None
            if self._agent_domain:
                domain_map = {
                    "web": DomainType.WEB_DESIGN,
                    "ai": DomainType.AI_CODING,
                    "quant": DomainType.QUANT_TRADING,
                }
                domain_enum = domain_map.get(self._agent_domain)

            # Map role string to enum
            role_enum = AgentRole.WORKER  # default
            if self._agent_role:
                try:
                    role_enum = AgentRole(self._agent_role)
                except ValueError:
                    pass

            return AgentStatusReport(
                agent_id=self.name,
                agent_role=role_enum,
                domain=domain_enum,
                survey_id=survey_id,
                q1_tasks_clear=data["q1_tasks_clear"],
                q2_blockers_waiting=data["q2_blockers_waiting"],
                q3_hardest_thing=data["q3_hardest_thing"][:200],
                q4_suggestion=data["q4_suggestion"][:200],
                q5_unexpected=data["q5_unexpected"][:200],
            )

        except Exception as e:
            self.log.error("Failed to fill status survey", error=str(e))
            # Return a fallback report indicating error
            role_enum = AgentRole.WORKER
            if self._agent_role:
                try:
                    role_enum = AgentRole(self._agent_role)
                except ValueError:
                    pass

            return AgentStatusReport(
                agent_id=self.name,
                agent_role=role_enum,
                domain=None,
                survey_id=survey_id,
                q1_tasks_clear=True,
                q2_blockers_waiting=False,
                q3_hardest_thing=f"Error filling survey: {str(e)[:150]}",
                q4_suggestion="Fix survey filling mechanism",
                q5_unexpected="Survey completion failed",
            )



    # -------------------------------------------------------------------------
    # Survival Awareness - Communication Law Compliance
    # -------------------------------------------------------------------------

    def get_survival_notice(self) -> str:
        """
        Get the survival notice for this agent with current violation count.

        Inject this into system prompts to remind agents of their mortality.
        """
        return get_survival_notice(self.name)

    def is_alive(self) -> bool:
        """
        Check if this agent is still alive (not revoked).

        Returns:
            True if alive, False if dead/revoked
        """
        return check_agent_alive(self.name)

    def get_violation_count(self) -> int:
        """
        Get this agent's current violation count.

        Returns:
            Number of communication law violations
        """
        return get_agent_violation_count(self.name)

    def check_mortality(self) -> bool:
        """
        Check if this agent should still be running.

        If the agent is dead, logs a critical error and returns False.
        Call this periodically in long-running agents.

        Returns:
            True if agent should continue, False if agent is dead
        """
        if not self.is_alive():
            self.log.critical(
                "AGENT IS DEAD - This agent has been revoked and should not be running",
                agent=self.name,
                violation_count=self.get_violation_count(),
            )
            return False
        return True


def run_agent(agent: SwarmAgent):
    """Run an agent with proper signal handling."""

    async def main():
        # Set up signal handlers
        loop = asyncio.get_running_loop()

        def handle_signal():
            asyncio.create_task(agent.stop())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)

        await agent.start()

    asyncio.run(main())
