"""Pydantic schemas for Kyzlo Swarm message types."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class TaskType(str, Enum):
    """Types of tasks workers can handle."""

    CODE = "code"
    RESEARCH = "research"
    PLANNING = "planning"
    DESIGN = "design"
    DEBUG = "debug"
    DOCUMENTATION = "documentation"
    CONVERSATION = "conversation"
    ANALYSIS = "analysis"


class FrictionType(str, Enum):
    """Types of friction workers can report."""

    RULE_TOO_STRICT = "rule_too_strict"
    RULE_UNCLEAR = "rule_unclear"
    MISSING_CONTEXT = "missing_context"
    WRONG_SLICE = "wrong_slice"
    DEPENDENCY_ISSUE = "dependency_issue"
    TOOLING_GAP = "tooling_gap"
    SCOPE_TOO_BIG = "scope_too_big"
    SCOPE_TOO_SMALL = "scope_too_small"
    AMBIGUOUS_REQUEST = "ambiguous_request"


class DeliverableType(str, Enum):
    """Types of worker output deliverables."""

    FILE = "file"
    TEXT = "text"
    LIST = "list"
    STRUCTURED = "structured"


class MemoryCategory(str, Enum):
    """Categories for RAG Brain memories."""

    DECISION = "decision"
    PATTERN = "pattern"
    BUG_FIX = "bug_fix"
    OUTCOME = "outcome"
    CODE_SNIPPET = "code_snippet"
    INSIGHT = "insight"
    DOCUMENTATION = "documentation"


class ValidationStatus(str, Enum):
    """Status of warden validation."""

    PASSED = "passed"
    FAILED = "failed"
    VIOLATION = "violation"


class QAStatus(str, Enum):
    """Status of QA assessment."""

    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class AgentRole(str, Enum):
    """Roles of agents in the swarm."""

    QUEEN = "queen"
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    WARDEN = "warden"
    SCRIBE = "scribe"
    QA_REPORTER = "qa_reporter"


class DomainType(str, Enum):
    """Domain specializations."""

    WEB_DESIGN = "web_design"
    AI_CODING = "ai_coding"
    QUANT_TRADING = "quant_trading"


# =============================================================================
# Core Message Schemas
# =============================================================================


class ConstraintEnvelope(BaseModel):
    """Defines what a worker can and cannot do."""

    can_do: List[str] = Field(default_factory=list)
    cannot_do: List[str] = Field(default_factory=list)


class TaskAssignment(BaseModel):
    """Message from Queen to Orchestrator."""

    task_id: UUID = Field(default_factory=uuid4)
    task: str = Field(..., description="The high-level task description")
    domain: str = Field(..., description="Target domain: web, ai, or quant")
    project: str = Field(..., description="Project identifier")
    priority: str = Field(default="normal", description="Task priority")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskSlice(BaseModel):
    """Message from Orchestrator to Worker."""

    task_id: UUID = Field(..., description="Parent task ID")
    slice_id: int = Field(..., description="Slice number (1-7)")
    worker_id: int = Field(..., description="Target worker ID")
    task_type: TaskType = Field(..., description="Type of task")
    description: str = Field(..., description="Slice-specific instructions")
    assigned_file: Optional[str] = Field(None, description="File path to create/modify")
    constraints: ConstraintEnvelope = Field(default_factory=ConstraintEnvelope)
    context: Dict[str, Any] = Field(default_factory=dict, description="RAG context and patterns")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Deliverable(BaseModel):
    """Worker output content."""

    type: DeliverableType
    file_path: Optional[str] = None
    content: str = ""
    items: Optional[List[str]] = None
    data: Optional[Dict[str, Any]] = None


class Metrics(BaseModel):
    """Worker execution metrics."""

    tokens_used: int = 0
    duration_ms: int = 0


class FeedbackBlock(BaseModel):
    """Mandatory feedback from every worker output."""

    # Friction reporting (optional, but null means no friction)
    friction: Optional[FrictionType] = None
    friction_detail: Optional[str] = None
    suggestion: Optional[str] = None
    blocked_by_rule: Optional[str] = None

    # Required scores (always present)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in output quality")
    task_fit: float = Field(..., ge=0.0, le=1.0, description="How well slice matched specialization")
    clarity: float = Field(..., ge=0.0, le=1.0, description="How clear the instructions were")
    context_quality: float = Field(..., ge=0.0, le=1.0, description="Quality of provided context")

    # Optional improvement suggestions
    would_change: Optional[str] = None


class WorkerOutput(BaseModel):
    """Complete output from a worker."""

    task_id: UUID
    worker_id: int
    slice_id: int
    task_type: TaskType
    deliverable: Deliverable
    metrics: Metrics
    feedback: FeedbackBlock  # MANDATORY - never omit
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Violation(BaseModel):
    """Rule violation detected by Warden."""

    worker_id: int
    slice_id: int
    rule: str
    description: str
    severity: str = "warning"  # warning, error, critical


class ValidationResult(BaseModel):
    """Result of Warden validation for one worker output."""

    task_id: UUID
    worker_id: int
    slice_id: int
    status: ValidationStatus
    violations: List[Violation] = Field(default_factory=list)
    notes: Optional[str] = None


class MergedResult(BaseModel):
    """Merged output from Warden after validating all 7 workers."""

    task_id: UUID
    domain: str
    worker_outputs: List[WorkerOutput]
    validation_results: List[ValidationResult]
    conflicts: List[str] = Field(default_factory=list)
    merged_files: Dict[str, str] = Field(default_factory=dict)
    total_violations: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QAReport(BaseModel):
    """Quality assessment report from QA Reporter."""

    task_id: UUID
    domain: str
    status: QAStatus
    test_results: Dict[str, Any] = Field(default_factory=dict)
    quality_score: float = Field(..., ge=0.0, le=1.0)
    issues: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Scribe Memory Schemas
# =============================================================================


class MemoryRecord(BaseModel):
    """Memory to be written to RAG Brain."""

    content: str
    category: MemoryCategory
    tags: List[str] = Field(default_factory=list)
    project: Optional[str] = None
    source: str = "agent"
    extra_data: Dict[str, Any] = Field(default_factory=dict)


class FeedbackSummary(BaseModel):
    """Summary of accumulated worker feedback for rule review."""

    feedback_count: int
    friction_counts: Dict[str, int] = Field(default_factory=dict)
    most_blocked_rules: List[str] = Field(default_factory=list)
    top_suggestions: List[str] = Field(default_factory=list)
    average_confidence: float = 0.0
    feedback_records: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Rule Evolution Schemas
# =============================================================================


class RuleAdjustment(BaseModel):
    """Proposed adjustment to a constraint rule."""

    adjustment_type: str  # relaxation, clarification, addition, removal
    old_rule: Optional[str] = None
    new_rule: Optional[str] = None
    rationale: str
    requires_escalation: bool = False


class EscalationRequest(BaseModel):
    """Escalation from Orchestrator to Queen."""

    domain: str
    rule_in_question: str
    feedback_summary: FeedbackSummary
    proposed_adjustment: RuleAdjustment
    orchestrator_recommendation: Optional[str] = None


class EscalationDecision(BaseModel):
    """Queen's decision on an escalation."""

    approved: bool
    modified_rule: Optional[str] = None
    explanation: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Task Record (Full lifecycle)
# =============================================================================


class TaskRecord(BaseModel):
    """Complete record of a task for Scribe memory extraction."""

    task_id: UUID
    domain: str
    project: str
    task_description: str
    status: QAStatus
    worker_outputs: List[WorkerOutput]
    validation_results: List[ValidationResult]
    qa_report: Optional[QAReport] = None
    total_tokens: int = 0
    total_duration_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# =============================================================================
# Status Survey Schemas
# =============================================================================


class AgentStatusReport(BaseModel):
    """Status survey response from an agent."""

    # Agent metadata
    agent_id: str = Field(..., description="Unique identifier for the agent")
    agent_role: AgentRole = Field(..., description="Role of the agent in the swarm")
    domain: Optional[DomainType] = Field(None, description="Domain specialization if applicable")
    survey_id: str = Field(..., description="ID of the survey this response belongs to")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Yes/No questions
    q1_tasks_clear: bool = Field(
        ..., description="Were assigned tasks clear and actionable?"
    )
    q2_blockers_waiting: bool = Field(
        ..., description="Did you experience blockers waiting on other agents?"
    )

    # Text answers (max 200 chars each)
    q3_hardest_thing: str = Field(
        ...,
        max_length=200,
        description="What was the hardest thing you handled this cycle?"
    )
    q4_suggestion: str = Field(
        ...,
        max_length=200,
        description="One suggestion that would make your job easier"
    )
    q5_unexpected: str = Field(
        ...,
        max_length=200,
        description="Anything unexpected you noticed in the system?"
    )
