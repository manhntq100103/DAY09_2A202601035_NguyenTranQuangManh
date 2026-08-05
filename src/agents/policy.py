"""Deterministic implementation of EC_POLICY_V1 in priority order."""

from __future__ import annotations

from decimal import Decimal

from .contracts import PolicyDecision


PAYMENT_TOLERANCE_BRL = Decimal("0.10")
ZERO_BRL = Decimal("0.00")


def reconcile_payment(payment_total: Decimal, item_total: Decimal, freight_total: Decimal) -> bool:
    """Return whether payments reconcile with item and freight values."""
    return abs(payment_total - (item_total + freight_total)) <= PAYMENT_TOLERANCE_BRL


def apply_ec_policy(
    *,
    order_status: str,
    payment_total: Decimal,
    item_total: Decimal,
    freight_total: Decimal,
    payment_count: int,
    delivered_after_estimate: bool,
    late_seller_ids: list[str],
) -> PolicyDecision | None:
    """Apply the README policy exactly in its prescribed priority order."""
    payment_matches = reconcile_payment(payment_total, item_total, freight_total)

    if order_status == "canceled" and payment_total > ZERO_BRL:
        return _decision(
            "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT",
            [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            payment_total, "issue_full_refund", "action_required",
        )
    if order_status == "unavailable" and payment_total > ZERO_BRL:
        return _decision(
            "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT",
            [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            payment_total, "issue_full_refund", "action_required",
        )
    if delivered_after_estimate and late_seller_ids:
        return _decision(
            "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT",
            [{"party_type": "seller", "party_id": seller_id} for seller_id in late_seller_ids],
            freight_total, "refund_freight", "action_required",
        )
    if delivered_after_estimate:
        return _decision(
            "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE",
            [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}],
            freight_total, "refund_freight", "action_required",
        )
    if payment_count >= 2 and payment_matches:
        return _decision(
            "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", [],
            ZERO_BRL, "explain_valid_split_payment", "no_action",
        )
    if not delivered_after_estimate and payment_matches:
        return _decision(
            "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", [],
            ZERO_BRL, "reject_late_refund", "no_action",
        )
    return None


def _decision(
    primary_issue: str,
    root_cause_code: str,
    responsible_parties: list[dict[str, str]],
    refund: Decimal,
    action: str,
    case_status: str,
) -> PolicyDecision:
    return {
        "primary_issue": primary_issue,
        "root_cause_code": root_cause_code,
        "responsible_parties": responsible_parties,
        "recommended_refund_brl": refund.quantize(Decimal("0.01")),
        "resolution_actions": [action],
        "case_status": case_status,  # type: ignore[typeddict-item]
        "confidence": 0.99,
    }
