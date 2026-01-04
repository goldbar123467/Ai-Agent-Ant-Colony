"""RAG Brain client for Kyzlo Swarm memory operations."""

from typing import Any, Dict, List, Optional

import httpx
import structlog

from .config import settings
from .schemas import MemoryCategory, MemoryRecord

logger = structlog.get_logger()


class RAGBrainClient:
    """Client for RAG Brain MCP server."""

    def __init__(self):
        self.base_url = settings.rag_brain.url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a RAG Brain MCP tool via REST endpoint."""
        client = await self._get_client()

        # Use the REST API endpoint
        if tool_name == "remember":
            response = await client.post("/remember", json=arguments)
        elif tool_name == "recall":
            response = await client.post("/recall", json=arguments)
        elif tool_name == "feedback":
            response = await client.post("/feedback", json=arguments)
        elif tool_name == "stats":
            response = await client.get("/stats", params=arguments)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        response.raise_for_status()
        return response.json()

    async def remember(
        self,
        content: str,
        category: MemoryCategory,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        source: str = "agent",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Store a memory in RAG Brain.

        Returns dict with:
            - rejected: bool
            - memory_id: str (if accepted)
            - quality_score: float
            - tier: str
            - reason: str (if rejected)
        """
        try:
            result = await self._call_tool(
                "remember",
                {
                    "content": content,
                    "category": category.value,
                    "tags": tags or [],
                    "project": project,
                    "source": source,
                    "metadata": metadata or {},
                },
            )
            logger.debug(
                "Memory stored",
                memory_id=result.get("memory_id"),
                quality=result.get("quality_score"),
            )
            return result
        except Exception as e:
            logger.error("Failed to store memory", error=str(e))
            return {"rejected": True, "reason": str(e)}

    async def remember_record(self, record: MemoryRecord) -> Dict[str, Any]:
        """Store a MemoryRecord in RAG Brain."""
        return await self.remember(
            content=record.content,
            category=record.category,
            tags=record.tags,
            project=record.project,
            source=record.source,
            metadata=record.extra_data,
        )

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Query memories from RAG Brain.

        Returns list of memories with:
            - id: str
            - content: str
            - category: str
            - tags: list
            - predicted_quality: float
            - usefulness_score: float
            - similarity: float
            - composite_score: float
        """
        try:
            result = await self._call_tool(
                "recall",
                {
                    "query": query,
                    "project": project,
                    "tags": tags,
                    "limit": limit,
                },
            )

            # Handle different response formats
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "memories" in result:
                return result["memories"]
            else:
                return []
        except Exception as e:
            logger.error("Failed to recall memories", query=query, error=str(e))
            return []

    async def feedback(
        self,
        memory_id: str,
        helpful: bool,
        context: Optional[str] = None,
    ) -> bool:
        """
        Provide feedback on a memory's usefulness.

        Returns True if feedback was recorded successfully.
        """
        try:
            await self._call_tool(
                "feedback",
                {
                    "memory_id": memory_id,
                    "helpful": helpful,
                    "context": context,
                },
            )
            logger.debug("Feedback recorded", memory_id=memory_id, helpful=helpful)
            return True
        except Exception as e:
            logger.error("Failed to record feedback", memory_id=memory_id, error=str(e))
            return False

    async def get_stats(self, project: Optional[str] = None) -> Dict[str, Any]:
        """Get RAG Brain statistics."""
        try:
            return await self._call_tool("stats", {"project": project} if project else {})
        except Exception as e:
            logger.error("Failed to get stats", error=str(e))
            return {}

    async def get_project_profile(self, project: str) -> Optional[Dict[str, Any]]:
        """Get project profile from RAG Brain."""
        memories = await self.recall(
            query=f"project profile for {project}",
            project=project,
            tags=["project_profile"],
            limit=1,
        )
        return memories[0] if memories else None

    async def get_patterns(
        self,
        domain: str,
        project: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get relevant patterns for a domain."""
        return await self.recall(
            query=f"{domain} patterns and best practices",
            project=project,
            tags=[domain, "pattern"],
            limit=limit,
        )

    async def get_failures(
        self,
        domain: str,
        project: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Get known failures to avoid for a domain."""
        return await self.recall(
            query=f"{domain} failures and problems to avoid",
            project=project,
            tags=[domain, "bug_fix"],
            limit=limit,
        )


# Global client instance
rag_client = RAGBrainClient()
