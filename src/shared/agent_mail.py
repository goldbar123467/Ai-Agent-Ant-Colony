"""Agent Mail client for Kyzlo Swarm inter-agent communication."""

import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

import httpx
import structlog

from .config import settings
from .comm_laws import (
    validate_and_log,
    identity_resolver,
    parse_agent_identity,
)

logger = structlog.get_logger()


class Message:
    """Represents an Agent Mail message."""

    def __init__(self, data: Dict[str, Any]):
        self.id: int = data.get("id", 0)
        self.thread_id: Optional[str] = data.get("thread_id")
        self.from_agent: str = data.get("from", "")
        self.to_agents: List[str] = data.get("to", [])
        self.subject: str = data.get("subject", "")
        self.body: str = data.get("body_md", "")
        self.importance: str = data.get("importance", "normal")
        self.ack_required: bool = data.get("ack_required", False)
        self.created_at: str = data.get("created", "")
        self.raw = data

    def __repr__(self) -> str:
        return f"Message(id={self.id}, from={self.from_agent}, subject={self.subject[:30]}...)"


MessageHandler = Callable[[Message], None]


class AgentMailClient:
    """Client for Agent Mail MCP server."""

    def __init__(
        self,
        agent_name: str,
        project_key: Optional[str] = None,
        agent_role: Optional[str] = None,
        agent_domain: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.project_key = project_key or settings.project_key
        self.base_url = settings.agent_mail.url
        self.token = settings.agent_mail.token
        self._client: Optional[httpx.AsyncClient] = None
        self._handlers: Dict[str, List[MessageHandler]] = {}
        self._polling = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_fetch: Optional[str] = None

        # Agent identity for communication law enforcement
        if agent_role and agent_domain is not None:
            self._agent_role = agent_role
            self._agent_domain = agent_domain
            identity_resolver.register(agent_name, agent_role, agent_domain)
        else:
            # Auto-detect from agent name
            self._agent_role, self._agent_domain = parse_agent_identity(agent_name)
            identity_resolver.register(agent_name, self._agent_role, self._agent_domain)

        self._enforce_laws = True  # Can be disabled for testing

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        await self.stop_polling()
        if self._client:
            await self._client.aclose()
            self._client = None

    async def register(self, program: str = "kyzlo-swarm", model: str = "deepseek") -> bool:
        """Register this agent with Agent Mail."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/register",
                json={
                    "agent_name": self.agent_name,
                    "project": self.project_key,
                },
            )
            response.raise_for_status()
            result = response.json()
            logger.info("Agent registered", agent=self.agent_name, result=result)
            return True
        except Exception as e:
            logger.error("Failed to register agent", agent=self.agent_name, error=str(e))
            return False

    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        importance: str = "normal",
        ack_required: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Send a message to one or more agents."""
        # Validate communication law for each recipient
        if self._enforce_laws:
            blocked_recipients = []
            for recipient in to:
                recipient_role, recipient_domain = identity_resolver.resolve(recipient)

                allowed, reason = validate_and_log(
                    sender_id=self.agent_name,
                    sender_role=self._agent_role,
                    sender_domain=self._agent_domain,
                    recipient_id=recipient,
                    recipient_role=recipient_role,
                    recipient_domain=recipient_domain,
                    message_preview=f"[{subject}] {body[:50]}",
                )

                if not allowed:
                    logger.warning(
                        "Message blocked by communication law",
                        sender=self.agent_name,
                        recipient=recipient,
                        reason=reason,
                    )
                    blocked_recipients.append(recipient)

            # Remove blocked recipients
            allowed_recipients = [r for r in to if r not in blocked_recipients]

            if not allowed_recipients:
                logger.warning(
                    "All recipients blocked by communication law",
                    sender=self.agent_name,
                    recipients=to,
                )
                return {"blocked": True, "reason": "All recipients blocked by communication law"}

            to = allowed_recipients

        try:
            client = await self._get_client()
            # Send to each recipient (Agent Mail only supports single recipient)
            results = []
            for recipient in to:
                response = await client.post(
                    "/send",
                    json={
                        "from_agent": self.agent_name,
                        "to_agent": recipient,
                        "project": self.project_key,
                        "message_type": subject,
                        "payload": {
                            "body": body,
                            "thread_id": thread_id,
                            "importance": importance,
                            "ack_required": ack_required,
                        },
                    },
                )
                response.raise_for_status()
                results.append(response.json())
            logger.debug("Message sent", to=to, subject=subject)
            return results[0] if results else None
        except Exception as e:
            logger.error("Failed to send message", to=to, subject=subject, error=str(e))
            return None

    def disable_law_enforcement(self):
        """Disable communication law enforcement (for testing)."""
        self._enforce_laws = False

    def enable_law_enforcement(self):
        """Enable communication law enforcement."""
        self._enforce_laws = True

    async def broadcast(
        self,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        exclude: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Broadcast a message to all agents in the project."""
        # Note: Agent Mail doesn't have native broadcast, so this is a placeholder
        # In practice, we'd need to get the agent list and send to each
        logger.warning("Broadcast not fully implemented - use send with explicit recipients")
        return []

    async def fetch_messages(
        self,
        limit: int = 20,
        include_bodies: bool = True,
        since_ts: Optional[str] = None,
    ) -> List[Message]:
        """Fetch messages from inbox."""
        try:
            client = await self._get_client()
            params = {
                "project": self.project_key,
                "agent_name": self.agent_name,
                "limit": limit,
            }

            response = await client.get("/messages", params=params)
            response.raise_for_status()
            result = response.json()

            messages = []
            if isinstance(result, list):
                for msg_data in result:
                    # Adapt Agent Mail format to our Message format
                    adapted = {
                        "id": msg_data.get("id", 0),
                        "from": msg_data.get("from_agent", ""),
                        "to": [msg_data.get("to_agent", "")],
                        "subject": msg_data.get("message_type", ""),
                        "body_md": msg_data.get("payload", {}).get("body", ""),
                        "thread_id": msg_data.get("payload", {}).get("thread_id"),
                        "importance": msg_data.get("payload", {}).get("importance", "normal"),
                        "created": msg_data.get("created_at", ""),
                    }
                    messages.append(Message(adapted))
            elif isinstance(result, dict) and "messages" in result:
                for msg_data in result["messages"]:
                    adapted = {
                        "id": msg_data.get("id", 0),
                        "from": msg_data.get("from_agent", ""),
                        "to": [msg_data.get("to_agent", "")],
                        "subject": msg_data.get("message_type", ""),
                        "body_md": msg_data.get("payload", {}).get("body", ""),
                        "thread_id": msg_data.get("payload", {}).get("thread_id"),
                        "importance": msg_data.get("payload", {}).get("importance", "normal"),
                        "created": msg_data.get("created_at", ""),
                    }
                    messages.append(Message(adapted))

            if messages:
                self._last_fetch = datetime.utcnow().isoformat() + "Z"

            return messages
        except Exception as e:
            logger.error("Failed to fetch messages", error=str(e))
            return []

    async def mark_read(self, message_id: int) -> bool:
        """Mark a message as read (no-op - Agent Mail tracks reads automatically)."""
        return True

    async def acknowledge(self, message_id: int) -> bool:
        """Acknowledge a message (no-op - not implemented in Agent Mail API)."""
        return True

    def register_handler(self, message_type: str, handler: MessageHandler):
        """Register a handler for a specific message type (matched by subject prefix)."""
        if message_type not in self._handlers:
            self._handlers[message_type] = []
        self._handlers[message_type].append(handler)

    def on_message(self, message_type: str):
        """Decorator for registering message handlers."""
        def decorator(func: MessageHandler) -> MessageHandler:
            self.register_handler(message_type, func)
            return func
        return decorator

    async def _dispatch_message(self, message: Message):
        """Dispatch a message to registered handlers."""
        for msg_type, handlers in self._handlers.items():
            if message.subject.startswith(msg_type):
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(message)
                        else:
                            handler(message)
                    except Exception as e:
                        logger.error(
                            "Handler error",
                            handler=handler.__name__,
                            message_id=message.id,
                            error=str(e),
                        )

    async def start_polling(self, interval: float = 2.0):
        """Start polling for messages in the background."""
        if self._polling:
            return

        self._polling = True

        async def poll_loop():
            while self._polling:
                try:
                    messages = await self.fetch_messages()
                    for message in messages:
                        await self._dispatch_message(message)
                        await self.mark_read(message.id)
                except Exception as e:
                    logger.error("Polling error", error=str(e))

                await asyncio.sleep(interval)

        self._poll_task = asyncio.create_task(poll_loop())
        logger.info("Started polling", agent=self.agent_name, interval=interval)

    async def stop_polling(self):
        """Stop polling for messages."""
        self._polling = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("Stopped polling", agent=self.agent_name)
