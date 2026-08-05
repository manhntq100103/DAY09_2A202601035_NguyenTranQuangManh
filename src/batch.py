"""Batch execution, output construction and trace generation for all cases."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.agents.graph import investigate_case
from src.agents.llm import get_groq_model_config
from src.data_access import OlistDataStore, load_case_inputs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
TRACE_PATH = PROJECT_ROOT / "trace.jsonl"
METADATA_PATH = PROJECT_ROOT / "metadata.json"


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _limited(values: list[str], maximum: int = 5) -> list[str]:
    return values[:maximum]


def _build_evidence(state: dict[str, Any]) -> list[str]:
    """Return at most ten direct, valid evidence IDs with policy evidence kept."""
    order_id = state["claimed_order_id"]
    order_facts = state["order_facts"]
    payment_facts = state["payment_facts"]
    decision = state["policy_decision"]
    candidates = [
        f"order:{order_id}",
        *(f"item:{item_id}" for item_id in _limited(order_facts["item_ids"], 3)),
        *(f"payment:{payment_id}" for payment_id in _limited(payment_facts["payment_ids"], 3)),
        *(f"seller:{seller_id}" for seller_id in _limited(order_facts["seller_ids"], 2)),
        f"policy:{decision['root_cause_code']}",
    ]
    seen: set[str] = set()
    return [value for value in candidates if not (value in seen or seen.add(value))][:10]


def state_to_output(state: dict[str, Any]) -> dict[str, Any]:
    """Transform a completed graph state into the required output schema."""
    if "policy_decision" not in state:
        raise RuntimeError(f"{state['case_id']}: graph did not produce a policy decision")
    decision = state["policy_decision"]
    order_facts = state["order_facts"]
    payment_facts = state["payment_facts"]
    financials = state["financials"]
    order_id = state["claimed_order_id"]
    return {
        "case_id": state["case_id"],
        "assessment": {
            "primary_issue": decision["primary_issue"],
            "case_status": decision["case_status"],
            "confidence": decision["confidence"],
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": _limited(order_facts["item_ids"]),
            "seller_ids": _limited(order_facts["seller_ids"]),
            "payment_ids": _limited(payment_facts["payment_ids"]),
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": decision["root_cause_code"], "rank": 1}],
            "responsible_parties": decision["responsible_parties"][:3],
        },
        "evidence_ids": _build_evidence(state),
        "financial_resolution": {
            "currency": "BRL",
            "item_total_brl": _money(financials["item_total_brl"]),
            "freight_total_brl": _money(financials["freight_total_brl"]),
            "payment_total_brl": _money(financials["payment_total_brl"]),
            "recommended_refund_brl": _money(decision["recommended_refund_brl"]),
        },
        "resolution_actions": decision["resolution_actions"][:5],
    }


def _json_default(value: Any) -> str:
    if isinstance(value, (Decimal, datetime)):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _write_trace(states: list[dict[str, Any]]) -> None:
    """Replace trace with the handoffs from this batch run; never append."""
    lines: list[str] = []
    for state in states:
        for sequence, handoff in enumerate(state["handoffs"], start=1):
            event = {
                "run_at": datetime.now(timezone.utc).isoformat(),
                "case_id": state["case_id"],
                "sequence": sequence,
                "event_type": "agent_handoff",
                "handoff": handoff,
            }
            lines.append(json.dumps(event, ensure_ascii=False, default=_json_default))
    TRACE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_metadata() -> None:
    model_name, specification = get_groq_model_config()
    metadata = {
        "model": model_name,
        "parameter_size": specification["parameter_size"],
        "framework": "LangGraph + LangChain Groq",
        "runtime": f"Python {platform.python_version()} on {platform.system()} {platform.release()}",
    }
    METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_batch() -> list[dict[str, Any]]:
    """Run every official input and generate output, trace and metadata artifacts."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    store = OlistDataStore(PROJECT_ROOT / "data")
    cases = load_case_inputs(PROJECT_ROOT / "input")
    states = [investigate_case(case, store) for case in cases]
    outputs = [state_to_output(state) for state in states]
    for result in outputs:
        output_path = OUTPUT_DIR / f"{result['case_id']}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_trace(states)
    _write_metadata()
    return outputs


def main() -> int:
    outputs = run_batch()
    print(f"Generated {len(outputs)} output files in {OUTPUT_DIR}")
    print(f"Wrote trace: {TRACE_PATH}")
    print(f"Wrote metadata: {METADATA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
