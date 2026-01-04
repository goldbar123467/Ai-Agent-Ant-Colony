"""Configuration settings for Kyzlo Swarm agents."""

from typing import Dict, List
from pydantic import Field
from pydantic_settings import BaseSettings


class OpenRouterSettings(BaseSettings):
    """OpenRouter API configuration."""

    api_key: str = Field(alias="OPENROUTER_API_KEY")
    base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class ModelSettings(BaseSettings):
    """Model IDs for each agent type."""

    queen: str = Field(default="anthropic/claude-sonnet-4", alias="QUEEN_MODEL")
    orchestrator: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="ORCHESTRATOR_MODEL")
    worker: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="WORKER_MODEL")
    warden: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="WARDEN_MODEL")
    scribe: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="SCRIBE_MODEL")
    qa_reporter: str = Field(default="anthropic/claude-sonnet-4", alias="QA_REPORTER_MODEL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class AgentMailSettings(BaseSettings):
    """Agent Mail server configuration."""

    url: str = Field(default="http://localhost:8766", alias="AGENT_MAIL_URL")
    token: str = Field(alias="AGENT_MAIL_TOKEN")

    class Config:
        env_file = ".env"
        extra = "ignore"


class RAGBrainSettings(BaseSettings):
    """RAG Brain server configuration."""

    url: str = Field(default="http://localhost:8000", alias="RAG_BRAIN_URL")

    class Config:
        env_file = ".env"
        extra = "ignore"


class DomainConfig:
    """Configuration for a swarm domain."""

    def __init__(
        self,
        name: str,
        worker_ids: List[int],
        can_do: List[str],
        cannot_do: List[str],
        specializations: Dict[int, str],
    ):
        self.name = name
        self.worker_ids = worker_ids
        self.can_do = can_do
        self.cannot_do = cannot_do
        self.specializations = specializations


# Web Design Domain Configuration
WEB_DOMAIN = DomainConfig(
    name="web",
    worker_ids=[1, 2, 3, 4, 5, 6, 7],
    can_do=[
        "create assigned file",
        "import from designated modules",
        "use Tailwind classes",
        "use shadcn components",
        "use React hooks",
        "define TypeScript types",
    ],
    cannot_do=[
        "modify files outside assignment",
        "create routes",
        "fetch data directly",
        "modify global state",
        "install packages",
        "use inline styles",
    ],
    specializations={
        1: "layout and shell structure",
        2: "navigation and header components",
        3: "core components (cards, tables)",
        4: "form components (inputs, modals)",
        5: "charts and data visualization",
        6: "styles and theme tokens",
        7: "types, utilities, and hooks",
    },
)

# AI Coding Domain Configuration
AI_DOMAIN = DomainConfig(
    name="ai",
    worker_ids=[8, 9, 10, 11, 12, 13, 14],
    can_do=[
        "create assigned file",
        "import from project packages",
        "define Pydantic models",
        "use async patterns",
        "call configured LLM clients",
        "access vector stores",
    ],
    cannot_do=[
        "modify files outside assignment",
        "hardcode API keys",
        "make external calls in module body",
        "create database migrations",
        "modify configuration files",
    ],
    specializations={
        8: "data loaders and chunking",
        9: "embeddings and vector operations",
        10: "retrieval and reranking",
        11: "LLM clients and prompts",
        12: "pipeline orchestration",
        13: "API routes and handlers",
        14: "types, schemas, and tests",
    },
)

# Quantitative Domain Configuration
QUANT_DOMAIN = DomainConfig(
    name="quant",
    worker_ids=[15, 16, 17, 18, 19, 20, 21],
    can_do=[
        "create assigned file",
        "import from project libraries",
        "define dataclasses",
        "use async websocket patterns",
        "access configured exchange clients",
        "use numpy and pandas",
    ],
    cannot_do=[
        "modify files outside assignment",
        "hardcode private keys",
        "execute real trades in module body",
        "modify configuration files",
        "bypass risk checks",
        "disable logging",
    ],
    specializations={
        15: "data feeds and websockets",
        16: "indicators and signals",
        17: "position sizing and risk",
        18: "order execution",
        19: "portfolio state tracking",
        20: "backtesting harnesses",
        21: "types, config, and utilities",
    },
)

# Domain lookup
DOMAINS = {
    "web": WEB_DOMAIN,
    "ai": AI_DOMAIN,
    "quant": QUANT_DOMAIN,
}


class Settings(BaseSettings):
    """Main settings aggregator."""

    project_key: str = Field(default="/home/ubuntu/kyzlo-swarm", alias="PROJECT_KEY")

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def openrouter(self) -> OpenRouterSettings:
        return OpenRouterSettings()

    @property
    def models(self) -> ModelSettings:
        return ModelSettings()

    @property
    def agent_mail(self) -> AgentMailSettings:
        return AgentMailSettings()

    @property
    def rag_brain(self) -> RAGBrainSettings:
        return RAGBrainSettings()


# Global settings instance
settings = Settings()
