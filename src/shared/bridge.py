"""
Bridge - Lightweight Real-time Messaging for Kyzlo Swarm.

Bridge is the "team chat" layer - fast, lightweight coordination between agents.
Use Bridge for:
- Quick status updates
- Rapid back-and-forth during task execution
- Coordination signals (ready, blocked, done)
- Lightweight queries that don't need formal tracking

Use Agent Mail for:
- Formal task assignments
- Outputs that need audit trails
- Messages requiring acknowledgment
- Cross-session persistence

Bridge saves tokens by avoiding full Agent Mail overhead for routine coordination.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import structlog

from .comm_laws import (
    validate_and_log,
    identity_resolver,
    parse_agent_identity,
    EXEMPT_CHANNELS,
)

logger = structlog.get_logger()


@dataclass
class BridgeMessage:
    """Lightweight message for Bridge communication."""
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    channel: str = ""  # Channel/room name
    sender: str = ""
    content: str = ""
    msg_type: str = "chat"  # chat, status, signal, query, response
    reply_to: Optional[str] = None  # ID of message being replied to
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "channel": self.channel,
            "sender": self.sender,
            "content": self.content,
            "msg_type": self.msg_type,
            "reply_to": self.reply_to,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


# Message handler type
BridgeHandler = Callable[[BridgeMessage], None]


class BridgeChannel:
    """A channel/room in Bridge for focused communication."""

    def __init__(self, name: str, max_history: int = 100):
        self.name = name
        self.subscribers: Set[str] = set()
        self.history: List[BridgeMessage] = []
        self.max_history = max_history
        self._handlers: Dict[str, List[BridgeHandler]] = {}

    def subscribe(self, agent_name: str, handler: Optional[BridgeHandler] = None):
        """Subscribe an agent to this channel."""
        self.subscribers.add(agent_name)
        if handler:
            if agent_name not in self._handlers:
                self._handlers[agent_name] = []
            self._handlers[agent_name].append(handler)

    def unsubscribe(self, agent_name: str):
        """Unsubscribe an agent from this channel."""
        self.subscribers.discard(agent_name)
        self._handlers.pop(agent_name, None)

    def post(self, message: BridgeMessage) -> BridgeMessage:
        """Post a message to this channel."""
        message.channel = self.name
        self.history.append(message)

        # Trim history if needed
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Notify handlers
        for agent_name, handlers in self._handlers.items():
            if agent_name != message.sender:  # Don't echo to sender
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            asyncio.create_task(handler(message))
                        else:
                            handler(message)
                    except Exception as e:
                        logger.error("Bridge handler error", error=str(e))

        return message

    def get_recent(self, limit: int = 10, since: Optional[float] = None) -> List[BridgeMessage]:
        """Get recent messages, optionally since a timestamp."""
        if since:
            messages = [m for m in self.history if m.timestamp > since]
        else:
            messages = self.history

        return messages[-limit:]


class Bridge:
    """
    Lightweight messaging hub for rapid agent coordination.

    Singleton pattern - all agents share the same Bridge instance.
    """

    _instance: Optional["Bridge"] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.channels: Dict[str, BridgeChannel] = {}
        self._agent_channels: Dict[str, Set[str]] = {}  # agent -> channels
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._initialized = True

        # Create default channels
        self._create_default_channels()

        logger.info("Bridge initialized")

    def _create_default_channels(self):
        """Create standard channels for swarm coordination."""
        default_channels = [
            "general",       # General coordination
            "status",        # Status updates (ready, busy, done)
            "system",        # System-wide broadcasts (surveys, etc.)
            "web",           # Web domain coordination
            "ai",            # AI domain coordination
            "quant",         # Quant domain coordination
            "alerts",        # Urgent notifications
            "debug",         # Debug/troubleshooting
        ]
        for name in default_channels:
            self.get_or_create_channel(name)

    def get_or_create_channel(self, name: str) -> BridgeChannel:
        """Get existing channel or create new one."""
        if name not in self.channels:
            self.channels[name] = BridgeChannel(name)
        return self.channels[name]

    def join(self, agent_name: str, channel: str, handler: Optional[BridgeHandler] = None):
        """Join an agent to a channel."""
        ch = self.get_or_create_channel(channel)
        ch.subscribe(agent_name, handler)

        if agent_name not in self._agent_channels:
            self._agent_channels[agent_name] = set()
        self._agent_channels[agent_name].add(channel)

        logger.debug("Agent joined channel", agent=agent_name, channel=channel)

    def leave(self, agent_name: str, channel: str):
        """Remove an agent from a channel."""
        if channel in self.channels:
            self.channels[channel].unsubscribe(agent_name)

        if agent_name in self._agent_channels:
            self._agent_channels[agent_name].discard(channel)

    def post(
        self,
        channel: str,
        sender: str,
        content: str,
        msg_type: str = "chat",
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BridgeMessage:
        """Post a message to a channel."""
        ch = self.get_or_create_channel(channel)

        message = BridgeMessage(
            channel=channel,
            sender=sender,
            content=content,
            msg_type=msg_type,
            reply_to=reply_to,
            metadata=metadata or {},
        )

        return ch.post(message)

    def status(self, sender: str, status: str, details: Optional[str] = None):
        """Post a status update to the status channel."""
        content = status
        if details:
            content = f"{status}: {details}"

        return self.post(
            channel="status",
            sender=sender,
            content=content,
            msg_type="status",
            metadata={"status": status},
        )

    def signal(self, sender: str, channel: str, signal_type: str, data: Optional[Dict] = None):
        """Send a coordination signal."""
        return self.post(
            channel=channel,
            sender=sender,
            content=signal_type,
            msg_type="signal",
            metadata={"signal": signal_type, "data": data or {}},
        )

    async def query(
        self,
        channel: str,
        sender: str,
        question: str,
        timeout: float = 5.0,
    ) -> Optional[BridgeMessage]:
        """
        Send a query and wait for a response.

        Returns the first response or None on timeout.
        """
        msg = self.post(
            channel=channel,
            sender=sender,
            content=question,
            msg_type="query",
        )

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending_responses[msg.id] = future

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_responses.pop(msg.id, None)

    def respond(self, sender: str, to_message_id: str, content: str, channel: str):
        """Respond to a query."""
        msg = self.post(
            channel=channel,
            sender=sender,
            content=content,
            msg_type="response",
            reply_to=to_message_id,
        )

        # Resolve pending future if exists
        if to_message_id in self._pending_responses:
            self._pending_responses[to_message_id].set_result(msg)

        return msg

    def get_history(
        self,
        channel: str,
        limit: int = 20,
        since: Optional[float] = None,
    ) -> List[BridgeMessage]:
        """Get message history from a channel."""
        if channel not in self.channels:
            return []
        return self.channels[channel].get_recent(limit, since)

    def broadcast(self, sender: str, content: str, channels: Optional[List[str]] = None):
        """Broadcast a message to multiple channels."""
        target_channels = channels or ["general", "status"]
        messages = []
        for ch in target_channels:
            msg = self.post(ch, sender, content, msg_type="broadcast")
            messages.append(msg)
        return messages


class BridgeClient:
    """
    Client interface for agents to use Bridge.

    Provides a simple API for agents to send/receive Bridge messages.
    """

    def __init__(
        self,
        agent_name: str,
        auto_join: Optional[List[str]] = None,
        agent_role: Optional[str] = None,
        agent_domain: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.bridge = Bridge()
        self._handlers: Dict[str, BridgeHandler] = {}
        self._last_check: Dict[str, float] = {}

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

        # Auto-join channels
        default_channels = ["general", "status"]
        if auto_join:
            default_channels.extend(auto_join)

        for channel in set(default_channels):
            self.join(channel)

    def join(self, channel: str, handler: Optional[BridgeHandler] = None):
        """Join a channel."""
        self.bridge.join(self.agent_name, channel, handler)
        self._last_check[channel] = time.time()

    def leave(self, channel: str):
        """Leave a channel."""
        self.bridge.leave(self.agent_name, channel)
        self._last_check.pop(channel, None)

    def say(self, channel: str, content: str, **metadata) -> BridgeMessage:
        """Send a chat message to a channel."""
        return self.bridge.post(
            channel=channel,
            sender=self.agent_name,
            content=content,
            msg_type="chat",
            metadata=metadata,
        )

    def status(self, status: str, details: Optional[str] = None) -> BridgeMessage:
        """Post a status update."""
        return self.bridge.status(self.agent_name, status, details)

    def signal(self, channel: str, signal_type: str, data: Optional[Dict] = None) -> BridgeMessage:
        """Send a coordination signal."""
        return self.bridge.signal(self.agent_name, channel, signal_type, data)

    async def ask(self, channel: str, question: str, timeout: float = 5.0) -> Optional[BridgeMessage]:
        """Ask a question and wait for response."""
        return await self.bridge.query(channel, self.agent_name, question, timeout)

    def reply(self, to_message: BridgeMessage, content: str) -> Optional[BridgeMessage]:
        """Reply to a message."""
        # Validate communication with the original sender
        if self._enforce_laws and to_message.channel not in EXEMPT_CHANNELS:
            recipient_role, recipient_domain = identity_resolver.resolve(to_message.sender)

            allowed, reason = validate_and_log(
                sender_id=self.agent_name,
                sender_role=self._agent_role,
                sender_domain=self._agent_domain,
                recipient_id=to_message.sender,
                recipient_role=recipient_role,
                recipient_domain=recipient_domain,
                channel=to_message.channel,
                message_preview=content[:50],
            )

            if not allowed:
                logger.warning(
                    "Bridge reply blocked by communication law",
                    sender=self.agent_name,
                    recipient=to_message.sender,
                    channel=to_message.channel,
                    reason=reason,
                )
                return None

        return self.bridge.respond(
            self.agent_name,
            to_message.id,
            content,
            to_message.channel,
        )

    def disable_law_enforcement(self):
        """Disable communication law enforcement (for testing)."""
        self._enforce_laws = False

    def enable_law_enforcement(self):
        """Enable communication law enforcement."""
        self._enforce_laws = True

    def check_messages(self, channel: str, limit: int = 10) -> List[BridgeMessage]:
        """Check for new messages since last check."""
        since = self._last_check.get(channel, 0)
        messages = self.bridge.get_history(channel, limit, since)
        self._last_check[channel] = time.time()

        # Filter out own messages
        return [m for m in messages if m.sender != self.agent_name]

    def broadcast(self, content: str, channels: Optional[List[str]] = None) -> List[BridgeMessage]:
        """Broadcast to multiple channels."""
        return self.bridge.broadcast(self.agent_name, content, channels)


# Convenience signals
class Signals:
    """Standard signal types for coordination."""

    READY = "ready"           # Agent is ready
    BUSY = "busy"             # Agent is working
    DONE = "done"             # Task complete
    BLOCKED = "blocked"       # Waiting on something
    ERROR = "error"           # Error occurred
    NEED_HELP = "need_help"   # Requesting assistance
    HANDOFF = "handoff"       # Handing off to another agent
    ACK = "ack"               # Acknowledgment
    SYNC = "sync"             # Sync request
    PING = "ping"             # Heartbeat
    PONG = "pong"             # Heartbeat response
