#!/usr/bin/env python3
"""
Demo script for Agent Ant Colony.

This script demonstrates how to send a task to the swarm and observe the results.
Run this after starting the colony with: make start
"""

import asyncio
import json
from src.shared.agent_mail import AgentMailClient
from src.shared.config import settings


async def send_demo_task():
    """Send a demo task to the Queen."""

    # Create a client to communicate with the swarm
    client = AgentMailClient("DemoClient", settings.project_key)

    try:
        # Register with Agent Mail
        await client.register(program="demo", model="human")
        print("Registered with Agent Mail")

        # Send a task to the Queen
        task = """Create a simple React dashboard component with:
        1. A header with the title "Dashboard"
        2. Three stat cards showing placeholder metrics
        3. A responsive grid layout using Tailwind
        4. TypeScript types for the props
        """

        result = await client.send(
            to=["Queen"],
            subject="NEW_TASK: Create Dashboard Component",
            body=task,
            thread_id="DEMO-001",
            importance="normal",
        )

        print(f"Task sent to Queen: {result}")
        print("\nThe swarm will now:")
        print("1. Queen determines this is a 'web' domain task")
        print("2. Queen sends to Orch-Web")
        print("3. Orch-Web slices into 7 parallel pieces")
        print("4. Workers 1-7 execute their slices")
        print("5. Warden-Web validates outputs")
        print("6. QA Reporter assesses quality")
        print("7. Scribe writes memories to RAG Brain")
        print("\nMonitor the Agent Mail inbox for updates.")

        # Poll for responses
        print("\nWaiting for responses...")
        for i in range(30):  # Wait up to 60 seconds
            await asyncio.sleep(2)
            messages = await client.fetch_messages()
            for msg in messages:
                print(f"\n[{msg.from_agent}] {msg.subject}")
                if msg.body:
                    print(f"  {msg.body[:200]}...")

    finally:
        await client.close()


if __name__ == "__main__":
    print("Agent Ant Colony Demo")
    print("=====================")
    print(f"Agent Mail: {settings.agent_mail.url}")
    print(f"RAG Brain: {settings.rag_brain.url}")
    print()

    asyncio.run(send_demo_task())
