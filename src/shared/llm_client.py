"""OpenRouter LLM client for Kyzlo Swarm agents."""

import json
import time
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings


class LLMClient:
    """Async client for OpenRouter API."""

    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.base_url = settings.openrouter.base_url
        self.api_key = settings.openrouter.api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://kyzlo.dev",
                    "X-Title": "Kyzlo Swarm",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Complete a chat conversation.

        Returns dict with:
            - content: str (the response text)
            - model: str (model used)
            - tokens_used: int (total tokens)
            - duration_ms: int (request duration)
        """
        client = await self._get_client()
        model = model or self.model

        if not model:
            raise ValueError("Model must be specified")

        start_time = time.time()

        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", model),
            "tokens_used": data.get("usage", {}).get("total_tokens", 0),
            "duration_ms": duration_ms,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def complete_json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Complete a conversation expecting JSON output.

        Appends JSON schema instructions to the system message.
        Parses and validates the response against the schema.

        Returns dict with:
            - data: dict (parsed JSON)
            - model: str
            - tokens_used: int
            - duration_ms: int
        """
        client = await self._get_client()
        model = model or self.model

        if not model:
            raise ValueError("Model must be specified")

        # Append schema instructions
        schema_instruction = f"""
You must respond with valid JSON matching this schema:
```json
{json.dumps(schema, indent=2)}
```
Respond ONLY with the JSON object, no markdown code fences or additional text.
"""

        enhanced_messages = messages.copy()
        if enhanced_messages and enhanced_messages[0]["role"] == "system":
            enhanced_messages[0]["content"] += "\n\n" + schema_instruction
        else:
            enhanced_messages.insert(0, {"role": "system", "content": schema_instruction})

        start_time = time.time()

        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": enhanced_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()

        duration_ms = int((time.time() - start_time) * 1000)

        content = data["choices"][0]["message"]["content"]

        # Clean up response - remove markdown code fences if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}\nContent: {content}")

        return {
            "data": parsed,
            "model": data.get("model", model),
            "tokens_used": data.get("usage", {}).get("total_tokens", 0),
            "duration_ms": duration_ms,
        }


# Pre-configured clients for each agent type
def get_queen_client() -> LLMClient:
    return LLMClient(model=settings.models.queen)


def get_orchestrator_client() -> LLMClient:
    return LLMClient(model=settings.models.orchestrator)


def get_worker_client() -> LLMClient:
    return LLMClient(model=settings.models.worker)


def get_warden_client() -> LLMClient:
    return LLMClient(model=settings.models.warden)


def get_scribe_client() -> LLMClient:
    return LLMClient(model=settings.models.scribe)


def get_qa_client() -> LLMClient:
    return LLMClient(model=settings.models.qa_reporter)
