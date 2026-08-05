"""LangGraph workflow that hands verified Olist facts to EC_POLICY_V1."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.data_access import DatasetError, OlistDataStore, OrderContext, validate_case_payload

from .contracts import AgentHandoff, AgentName, PolicyDecision, isoformat_or_none
from .policy import apply_ec_policy, reconcile_payment


class DisputeState(TypedDict, total=False):
    """State exchanged by agents; only source-derived facts enter policy."""

    case: dict[str, Any]
    case_id: str
    claimed_order_id: str
    data_store: OlistDataStore
    context: OrderContext
    handoffs: list[AgentHandoff]
    order_facts: dict[str, Any]
    payment_facts: dict[str, Any]
    delivery_facts: dict[str, Any]
    financials: dict[str, Decimal]
    policy_decision: PolicyDecision
    warnings: list[str]
    current_agent: AgentName


def create_initial_state(case: dict[str, Any], data_store: OlistDataStore) -> DisputeState:
    """Validate an input case before it enters the graph."""
    validate_case_payload(case)
    return {
        "case": case,
        "case_id": case["case_id"],
        "claimed_order_id": case["customer_request"]["claimed_order_id"],
        "data_store": data_store,
        "handoffs": [],
        "warnings": [],
    }


def _append_handoff(
    state: DisputeState,
    *,
    from_agent: AgentName,
    to_agent: AgentName | None,
    scope: str,
    facts: dict[str, Any] | None = None,
    financials: dict[str, Decimal] | None = None,
    evidence_ids: list[str] | None = None,
    warnings: list[str] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    handoff: AgentHandoff = {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "scope": scope,
        "facts": facts or {},
        "financials": financials or {},
        "evidence_ids": evidence_ids or [],
        "warnings": warnings or [],
        "status": status,  # type: ignore[typeddict-item]
    }
    return {"current_agent": from_agent, "handoffs": [*state.get("handoffs", []), handoff]}


def coordinator_node(state: DisputeState) -> dict[str, Any]:
    order_id = state["claimed_order_id"]
    context = state["data_store"].order_context(order_id)
    if context is None:
        warning = f"claimed_order_id not found in orders.csv: {order_id}"
        return {
            **_append_handoff(
                state, from_agent="coordinator", to_agent=None,
                scope="retrieve claimed order", warnings=[warning], status="blocked",
            ),
            "warnings": [*state.get("warnings", []), warning],
        }
    return {
        **_append_handoff(
            state, from_agent="coordinator", to_agent="order_seller",
            scope="retrieve claimed order", facts={"order_id": order_id},
            evidence_ids=[f"order:{order_id}"],
        ),
        "context": context,
    }


def order_seller_node(state: DisputeState) -> dict[str, Any]:
    if "context" not in state:
        return _append_handoff(state, from_agent="order_seller", to_agent=None, scope="inspect order and seller", status="blocked")
    context = state["context"]
    order_id = context.order["order_id"]
    carrier_date = context.order["order_delivered_carrier_date"]
    late_seller_ids = sorted({
        item["seller_id"] for item in context.items
        if carrier_date and item["shipping_limit_date"] and carrier_date > item["shipping_limit_date"]
    })
    facts = {
        "order_id": order_id,
        "order_status": context.order["order_status"],
        "customer_id": context.order["customer_id"],
        "item_ids": [f"{order_id}:{item['order_item_id']}" for item in context.items],
        "seller_ids": sorted({item["seller_id"] for item in context.items}),
        "carrier_received_at": isoformat_or_none(carrier_date),
        "late_seller_ids": late_seller_ids,
    }
    evidence = [f"order:{order_id}"]
    evidence.extend(f"item:{order_id}:{item['order_item_id']}" for item in context.items)
    evidence.extend(f"seller:{seller_id}" for seller_id in facts["seller_ids"])
    return {
        **_append_handoff(state, from_agent="order_seller", to_agent="payment", scope="inspect order, items and sellers", facts=facts, evidence_ids=evidence),
        "order_facts": facts,
    }


def payment_node(state: DisputeState) -> dict[str, Any]:
    if "context" not in state:
        return _append_handoff(state, from_agent="payment", to_agent=None, scope="reconcile payment", status="blocked")
    context = state["context"]
    order_id = context.order["order_id"]
    item_total = sum(((item["price"] or Decimal("0")) for item in context.items), Decimal("0"))
    freight_total = sum(((item["freight_value"] or Decimal("0")) for item in context.items), Decimal("0"))
    payment_total = sum(((payment["payment_value"] or Decimal("0")) for payment in context.payments), Decimal("0"))
    financials = {
        "item_total_brl": item_total.quantize(Decimal("0.01")),
        "freight_total_brl": freight_total.quantize(Decimal("0.01")),
        "payment_total_brl": payment_total.quantize(Decimal("0.01")),
    }
    facts = {
        "payment_count": len(context.payments),
        "payment_ids": [f"{order_id}:{payment['payment_sequential']}" for payment in context.payments],
        "payment_matches_order_total": reconcile_payment(payment_total, item_total, freight_total),
    }
    evidence = [f"payment:{order_id}:{payment['payment_sequential']}" for payment in context.payments]
    return {
        **_append_handoff(state, from_agent="payment", to_agent="delivery", scope="reconcile item, freight and payment totals", facts=facts, financials=financials, evidence_ids=evidence),
        "payment_facts": facts,
        "financials": financials,
    }


def delivery_node(state: DisputeState) -> dict[str, Any]:
    if "context" not in state:
        return _append_handoff(state, from_agent="delivery", to_agent=None, scope="inspect delivery timing", status="blocked")
    order = state["context"].order
    delivered_at = order["order_delivered_customer_date"]
    estimated_at = order["order_estimated_delivery_date"]
    delivered_after_estimate = bool(delivered_at and estimated_at and delivered_at > estimated_at)
    facts = {
        "delivered_at": isoformat_or_none(delivered_at),
        "estimated_delivery_at": isoformat_or_none(estimated_at),
        "delivered_after_estimate": delivered_after_estimate,
    }
    return {
        **_append_handoff(state, from_agent="delivery", to_agent="policy", scope="compare actual and estimated delivery", facts=facts, evidence_ids=[f"order:{order['order_id']}"]),
        "delivery_facts": facts,
    }


def policy_node(state: DisputeState) -> dict[str, Any]:
    required = {"context", "order_facts", "payment_facts", "delivery_facts", "financials"}
    missing = sorted(required - state.keys())
    if missing:
        warning = f"policy cannot run; missing verified facts: {', '.join(missing)}"
        return {
            **_append_handoff(state, from_agent="policy", to_agent=None, scope="apply EC_POLICY_V1", warnings=[warning], status="blocked"),
            "warnings": [*state.get("warnings", []), warning],
        }
    financials = state["financials"]
    decision = apply_ec_policy(
        order_status=state["order_facts"]["order_status"],
        payment_total=financials["payment_total_brl"],
        item_total=financials["item_total_brl"],
        freight_total=financials["freight_total_brl"],
        payment_count=state["payment_facts"]["payment_count"],
        delivered_after_estimate=state["delivery_facts"]["delivered_after_estimate"],
        late_seller_ids=state["order_facts"]["late_seller_ids"],
    )
    if decision is None:
        warning = "No EC_POLICY_V1 rule matches the verified facts"
        return {
            **_append_handoff(state, from_agent="policy", to_agent=None, scope="apply EC_POLICY_V1", warnings=[warning], status="blocked"),
            "warnings": [*state.get("warnings", []), warning],
        }
    return {
        **_append_handoff(
            state, from_agent="policy", to_agent="verifier", scope="apply EC_POLICY_V1",
            facts={"primary_issue": decision["primary_issue"], "root_cause_code": decision["root_cause_code"]},
            financials={"recommended_refund_brl": decision["recommended_refund_brl"]},
            evidence_ids=[f"policy:{decision['root_cause_code']}"],
        ),
        "policy_decision": decision,
    }


def verifier_node(state: DisputeState) -> dict[str, Any]:
    """Step 3 verifies that policy only receives source-derived facts.

    Full output-schema and evidence-set validation is deliberately implemented
    in plan step 5.
    """
    if "policy_decision" not in state:
        return _append_handoff(state, from_agent="verifier", to_agent=None, scope="verify policy handoff", status="blocked")
    decision = state["policy_decision"]
    return _append_handoff(
        state, from_agent="verifier", to_agent=None, scope="verify policy handoff",
        facts={"primary_issue": decision["primary_issue"], "case_status": decision["case_status"]},
        financials={"recommended_refund_brl": decision["recommended_refund_brl"]},
        evidence_ids=[f"policy:{decision['root_cause_code']}"],
    )


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


def investigate_case(case: dict[str, Any], data_store: OlistDataStore) -> DisputeState:
    """Run a single case through facts collection and deterministic policy."""
    return build_dispute_graph().invoke(create_initial_state(case, data_store))
