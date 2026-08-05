"""Strict pre-submission validation for Olist dispute-resolution artifacts."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.agents.graph import investigate_case
from src.data_access import OlistDataStore, load_case_inputs


ISSUE_TO_CAUSE = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}
ISSUE_TO_ACTION = {
    "canceled_order_paid": "issue_full_refund",
    "unavailable_order_paid": "issue_full_refund",
    "late_delivery_seller": "refund_freight",
    "late_delivery_logistics": "refund_freight",
    "valid_split_payment": "explain_valid_split_payment",
    "unsupported_late_claim": "reject_late_refund",
}
REQUIRED_TOP_LEVEL = {
    "case_id", "assessment", "affected_entities", "root_cause_analysis",
    "evidence_ids", "financial_resolution", "resolution_actions",
}


def _decimal(value: Any, field: str, errors: list[str]) -> Decimal | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{field}: expected number")
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        errors.append(f"{field}: invalid number")
        return None
    if amount.as_tuple().exponent < -2:
        errors.append(f"{field}: must be rounded to at most 2 decimals")
    return amount


def _expect_keys(value: Any, keys: set[str], location: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{location}: expected object")
        return False
    missing = keys - value.keys()
    if missing:
        errors.append(f"{location}: missing keys {sorted(missing)}")
        return False
    return True


def _validate_evidence(
    evidence_ids: Any,
    order_id: str,
    context: Any,
    errors: list[str],
) -> None:
    if not isinstance(evidence_ids, list) or not all(isinstance(value, str) for value in evidence_ids):
        errors.append("evidence_ids: expected list of strings")
        return
    if len(evidence_ids) > 10:
        errors.append("evidence_ids: exceeds maximum 10")
    item_ids = {str(item["order_item_id"]) for item in context.items}
    payment_ids = {str(payment["payment_sequential"]) for payment in context.payments}
    seller_ids = {item["seller_id"] for item in context.items}
    policy_codes = set(ISSUE_TO_CAUSE.values())
    for evidence in evidence_ids:
        pieces = evidence.split(":")
        kind = pieces[0]
        if kind == "order" and len(pieces) == 2 and pieces[1] == order_id:
            continue
        if kind == "item" and len(pieces) == 3 and pieces[1] == order_id and pieces[2] in item_ids:
            continue
        if kind == "payment" and len(pieces) == 3 and pieces[1] == order_id and pieces[2] in payment_ids:
            continue
        if kind == "seller" and len(pieces) == 2 and pieces[1] in seller_ids:
            continue
        if kind == "policy" and len(pieces) == 2 and pieces[1] in policy_codes:
            continue
        errors.append(f"evidence_ids: invalid or non-source ID {evidence!r}")


def _validate_entities(entities: Any, order_id: str, context: Any, errors: list[str]) -> None:
    expected_keys = {"order_ids", "item_ids", "seller_ids", "payment_ids"}
    if not _expect_keys(entities, expected_keys, "affected_entities", errors):
        return
    valid_items = {f"{order_id}:{item['order_item_id']}" for item in context.items}
    valid_sellers = {item["seller_id"] for item in context.items}
    valid_payments = {f"{order_id}:{payment['payment_sequential']}" for payment in context.payments}
    allowed = {
        "order_ids": {order_id}, "item_ids": valid_items,
        "seller_ids": valid_sellers, "payment_ids": valid_payments,
    }
    for name, valid_ids in allowed.items():
        values = entities[name]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            errors.append(f"affected_entities.{name}: expected list of strings")
            continue
        if len(values) > 5:
            errors.append(f"affected_entities.{name}: exceeds maximum 5")
        if len(values) != len(set(values)):
            errors.append(f"affected_entities.{name}: duplicate IDs")
        invalid = set(values) - valid_ids
        if invalid:
            errors.append(f"affected_entities.{name}: IDs do not belong to claimed order: {sorted(invalid)}")


def _validate_output(result: dict[str, Any], case: dict[str, Any], state: dict[str, Any], errors: list[str]) -> None:
    case_id = case["case_id"]
    prefix = f"{case_id}: "
    local_errors: list[str] = []
    if set(result) != REQUIRED_TOP_LEVEL:
        local_errors.append("top-level keys do not match output schema")
    if result.get("case_id") != case_id:
        local_errors.append("case_id does not match input")
    context = state["context"]
    order_id = case["customer_request"]["claimed_order_id"]
    assessment = result.get("assessment")
    if _expect_keys(assessment, {"primary_issue", "case_status", "confidence"}, "assessment", local_errors):
        issue = assessment["primary_issue"]
        decision = state["policy_decision"]
        if issue not in ISSUE_TO_CAUSE:
            local_errors.append("assessment.primary_issue is not allowed")
        if issue != decision["primary_issue"]:
            local_errors.append("assessment.primary_issue does not match policy facts")
        if assessment["case_status"] not in {"action_required", "no_action"}:
            local_errors.append("assessment.case_status is invalid")
        if assessment["case_status"] != decision["case_status"]:
            local_errors.append("assessment.case_status does not match policy facts")
        if not isinstance(assessment["confidence"], (int, float)) or not 0 <= assessment["confidence"] <= 1:
            local_errors.append("assessment.confidence must be in [0, 1]")
    _validate_entities(result.get("affected_entities"), order_id, context, local_errors)
    root = result.get("root_cause_analysis")
    if _expect_keys(root, {"ranked_causes", "responsible_parties"}, "root_cause_analysis", local_errors):
        causes = root["ranked_causes"]
        parties = root["responsible_parties"]
        if not isinstance(causes, list) or len(causes) > 3 or causes != [{"cause_code": state["policy_decision"]["root_cause_code"], "rank": 1}]:
            local_errors.append("root_cause_analysis.ranked_causes does not match policy facts")
        if not isinstance(parties, list) or len(parties) > 3 or parties != state["policy_decision"]["responsible_parties"]:
            local_errors.append("root_cause_analysis.responsible_parties does not match policy facts")
    _validate_evidence(result.get("evidence_ids"), order_id, context, local_errors)
    financial = result.get("financial_resolution")
    if _expect_keys(financial, {"currency", "item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"}, "financial_resolution", local_errors):
        if financial["currency"] != "BRL":
            local_errors.append("financial_resolution.currency must be BRL")
        expected = state["financials"] | {"recommended_refund_brl": state["policy_decision"]["recommended_refund_brl"]}
        for field, target in expected.items():
            actual = _decimal(financial[field], f"financial_resolution.{field}", local_errors)
            if actual is not None and actual != target:
                local_errors.append(f"financial_resolution.{field} does not match source facts")
    actions = result.get("resolution_actions")
    if not isinstance(actions, list) or len(actions) > 5 or actions != state["policy_decision"]["resolution_actions"]:
        local_errors.append("resolution_actions does not match policy facts")
    if result.get("assessment", {}).get("case_status") == "action_required" and result.get("financial_resolution", {}).get("recommended_refund_brl", 0) <= 0:
        local_errors.append("action_required requires a positive refund")
    if result.get("assessment", {}).get("case_status") == "no_action" and result.get("financial_resolution", {}).get("recommended_refund_brl") != 0:
        local_errors.append("no_action requires a zero refund")
    errors.extend(prefix + message for message in local_errors)


def validate_submission(project_root: Path) -> list[str]:
    """Return all errors found in the generated submission artifacts."""
    errors: list[str] = []
    output_dir = project_root / "output"
    expected_names = {f"EC_{number:03}.json" for number in range(1, 51)}
    actual_names = {path.name for path in output_dir.glob("*.json")}
    if actual_names != expected_names:
        errors.append(f"output JSON names mismatch; missing={sorted(expected_names - actual_names)}, extra={sorted(actual_names - expected_names)}")
    unexpected_files = [path.name for path in output_dir.iterdir() if path.is_file() and path.name not in expected_names]
    if unexpected_files:
        errors.append(f"output contains non-submission files: {sorted(unexpected_files)}")
    store = OlistDataStore(project_root / "data")
    for case in load_case_inputs(project_root / "input"):
        output_path = output_dir / f"{case['case_id']}.json"
        if not output_path.is_file():
            continue
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{case['case_id']}: invalid JSON: {error.msg}")
            continue
        state = investigate_case(case, store)
        _validate_output(result, case, state, errors)
    _validate_trace(project_root / "trace.jsonl", errors)
    _validate_metadata(project_root / "metadata.json", errors)
    return errors


def _validate_trace(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append("trace.jsonl is missing")
        return
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            errors.append(f"trace.jsonl line {number}: invalid JSON")
    if len(events) != 300:
        errors.append(f"trace.jsonl: expected 300 handoffs, found {len(events)}")
    sequences: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.get("event_type") != "agent_handoff" or "handoff" not in event:
            errors.append("trace.jsonl: malformed handoff event")
            continue
        sequences[event.get("case_id", "")].append(event.get("sequence"))
    if set(sequences) != {f"EC_{number:03}" for number in range(1, 51)}:
        errors.append("trace.jsonl: case coverage mismatch")
    if any(sequence != [1, 2, 3, 4, 5, 6] for sequence in sequences.values()):
        errors.append("trace.jsonl: each case must have sequential handoffs 1..6")


def _validate_metadata(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append("metadata.json is missing")
        return
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        errors.append("metadata.json: invalid JSON")
        return
    required = {"model", "parameter_size", "framework", "runtime"}
    if set(metadata) != required:
        errors.append("metadata.json: required fields mismatch")
    if metadata.get("parameter_size") != "8B":
        errors.append("metadata.json: model must declare 8B parameter size")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_submission(root)
    if errors:
        print("Validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Validation passed: 50 outputs, source-backed evidence, financials, trace and metadata are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
