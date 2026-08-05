"""Step-2 LangGraph topology and explicit agent handoffs.

This graph establishes orchestration only. Data retrieval, policy decisions and
output generation deliberately belong to later plan steps.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


AgentName = Literal[
    "coordinator",
    "order_seller",
    "payment",
    "delivery",
    "policy",
    "verifier",
]


class Handoff(TypedDict):
    """An auditable transfer from one graph node to the next."""

    from_agent: AgentName
    to_agent: AgentName | None
    scope: str
    status: Literal["pending_implementation"]


class DisputeState(TypedDict, total=False):
    """Shared state contract; detailed facts will be added in plan step 3."""

    case_id: str
    claimed_order_id: str
    handoffs: list[Handoff]
    current_agent: AgentName
    model: Any


def _handoff(
    state: DisputeState,
    from_agent: AgentName,
    to_agent: AgentName | None,
    scope: str,
) -> DisputeState:
    prior = state.get("handoffs", [])
    return {
        "current_agent": from_agent,
        "handoffs": [
            *prior,
            {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "scope": scope,
                "status": "pending_implementation",
            },
        ],
    }


def coordinator_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "coordinator", "order_seller", "delegate verified order investigation")


def order_seller_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "order_seller", "payment", "handoff order, item, seller and shipping-limit facts")


def payment_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "payment", "delivery", "handoff payment reconciliation facts")


def delivery_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "delivery", "policy", "handoff delivery-versus-estimate facts")


def policy_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "policy", "verifier", "handoff proposed resolution for validation")


def verifier_node(state: DisputeState) -> DisputeState:
    return _handoff(state, "verifier", None, "validate schema, evidence and financial consistency")


def build_dispute_graph() -> Any:
    """Compile the six-agent workflow required by the project architecture."""
    builder = StateGraph(DisputeState)
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("order_seller", order_seller_node)
    builder.add_node("payment", payment_node)
    builder.add_node("delivery", delivery_node)
    builder.add_node("policy", policy_node)
    builder.add_node("verifier", verifier_node)
    builder.add_edge(START, "coordinator")
    builder.add_edge("coordinator", "order_seller")
    builder.add_edge("order_seller", "payment")
    builder.add_edge("payment", "delivery")
    builder.add_edge("delivery", "policy")
    builder.add_edge("policy", "verifier")
    builder.add_edge("verifier", END)
    return builder.compile()
