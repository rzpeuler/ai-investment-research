"""Pure conversational-control contracts (not persisted business models)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Mapping, Optional


ChatState = Literal["clarification", "ready", "executing", "executed", "failed"]
ResolutionStatus = Literal["resolved", "clarification", "failure", "omitted"]


@dataclass(frozen=True)
class ChatRequest:
    message: str
    selected_scenario: Optional[str] = "AUTO"
    llm_enabled: bool = True
    research_live: bool = False
    session_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    message: str = ""
    entity: Optional[str] = None
    symbol: Optional[str] = None
    company_entity_id: Optional[str] = None
    security_entity_id: Optional[str] = None
    company_name: Optional[str] = None
    industry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemporalResult:
    status: ResolutionStatus
    message: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    as_of: Optional[str] = None


@dataclass(frozen=True)
class IndustryResult:
    status: ResolutionStatus
    message: str = ""
    industry_id: Optional[str] = None
    industry_name: Optional[str] = None


@dataclass(frozen=True)
class ChatResult:
    state: ChatState
    message: str
    scenario: Optional[str] = None
    public_draft: Optional[Dict[str, Any]] = None
    minimal_request: Optional[Dict[str, Any]] = None
    research_result: Optional[Dict[str, Any]] = None
    reference_now: Optional[str] = None
    llm_calls: int = 0
