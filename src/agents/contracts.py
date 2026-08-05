"""Shared handoff contract for the LangGraph dispute workflow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypedDict


AgentName = Literal[
    "coordinator",
    "order_seller",
    "payment",
    "delivery",
    "policy",
    "verifier",
]


class AgentHandoff(TypedDict):
    """A verified, auditable data handoff between two agents."""

    from_agent: AgentName
    to_agent: AgentName | None
    scope: str
    facts: dict[str, Any]
    financials: dict[str, Decimal]
    evidence_ids: list[str]
    warnings: list[str]
    status: Literal["completed", "blocked"]


class PolicyDecision(TypedDict):
    primary_issue: str
    root_cause_code: str
    responsible_parties: list[dict[str, str]]
    recommended_refund_brl: Decimal
    resolution_actions: list[str]
    case_status: Literal["action_required", "no_action"]
    confidence: float


def isoformat_or_none(value: datetime | None) -> str | None:
    """Make date facts readable in a handoff without changing their timezone."""
    return value.isoformat(sep=" ") if value else None
