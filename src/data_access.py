"""Normalized, read-only access to Olist CSV data.

This module deliberately uses only the Python standard library.  It keeps all
identifiers as strings, monetary values as ``Decimal`` and timestamps as naive
``datetime`` values exactly as represented in the source CSV (no timezone
conversion).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


DATA_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

TIMESTAMP_COLUMNS = {
    "orders": {
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    },
    "items": {"shipping_limit_date"},
    "reviews": {"review_creation_date", "review_answer_timestamp"},
}

DECIMAL_COLUMNS = {
    "items": {"price", "freight_value"},
    "payments": {"payment_value"},
    "geolocation": {"geolocation_lat", "geolocation_lng"},
}

INTEGER_COLUMNS = {
    "items": {"order_item_id"},
    "payments": {"payment_sequential", "payment_installments"},
    "reviews": {"review_score"},
    "products": {
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    },
}

REQUIRED_CASE_KEYS = {"case_id", "opened_at", "customer_request", "policy_version"}
REQUIRED_REQUEST_KEYS = {"language", "message", "claimed_order_id"}


class DatasetError(ValueError):
    """Raised when source data does not meet the project contract."""


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise DatasetError(f"Invalid CSV timestamp: {value!r}") from error


def _parse_decimal(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise DatasetError(f"Invalid decimal value: {value!r}") from error


def _parse_integer(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise DatasetError(f"Invalid integer value: {value!r}") from error


def _read_csv(path: Path, dataset_name: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetError(f"Missing required dataset file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows: list[dict[str, Any]] = []
        for raw_row in csv.DictReader(csv_file):
            row: dict[str, Any] = dict(raw_row)
            for column in TIMESTAMP_COLUMNS.get(dataset_name, set()):
                row[column] = _parse_timestamp(row.get(column, ""))
            for column in DECIMAL_COLUMNS.get(dataset_name, set()):
                row[column] = _parse_decimal(row.get(column, ""))
            for column in INTEGER_COLUMNS.get(dataset_name, set()):
                row[column] = _parse_integer(row.get(column, ""))
            rows.append(row)
    return rows


def validate_case_payload(payload: dict[str, Any], source: str = "case") -> None:
    """Validate the input shape that later agents will consume."""
    missing = REQUIRED_CASE_KEYS - payload.keys()
    if missing:
        raise DatasetError(f"{source}: missing required keys: {sorted(missing)}")
    if not isinstance(payload["customer_request"], dict):
        raise DatasetError(f"{source}: customer_request must be an object")
    request_missing = REQUIRED_REQUEST_KEYS - payload["customer_request"].keys()
    if request_missing:
        raise DatasetError(f"{source}: customer_request missing keys: {sorted(request_missing)}")
    if not isinstance(payload["customer_request"]["claimed_order_id"], str) or not payload["customer_request"]["claimed_order_id"]:
        raise DatasetError(f"{source}: claimed_order_id must be a non-empty string")


def load_case_inputs(input_dir: Path) -> list[dict[str, Any]]:
    """Load and validate EC_*.json files in deterministic filename order."""
    case_files = sorted(input_dir.glob("EC_*.json"))
    if len(case_files) != 50:
        raise DatasetError(f"Expected 50 case files in {input_dir}, found {len(case_files)}")
    cases = []
    for path in case_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise DatasetError(f"{path}: invalid JSON") from error
        validate_case_payload(payload, str(path))
        cases.append(payload)
    return cases


@dataclass(frozen=True)
class OrderContext:
    """All records joined to one order while preserving one-to-many rows."""

    order: dict[str, Any]
    customer: dict[str, Any] | None
    items: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    sellers: dict[str, dict[str, Any]]
    products: dict[str, dict[str, Any]]


class OlistDataStore:
    """Loads Olist data once and exposes safe, indexed order lookups."""

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.tables = {
            name: _read_csv(self.data_dir / filename, name)
            for name, filename in DATA_FILES.items()
        }
        self.orders_by_id = _unique_index(self.tables["orders"], "order_id", "orders")
        self.customers_by_id = _unique_index(self.tables["customers"], "customer_id", "customers")
        self.sellers_by_id = _unique_index(self.tables["sellers"], "seller_id", "sellers")
        self.products_by_id = _unique_index(self.tables["products"], "product_id", "products")
        self.items_by_order = _group_index(self.tables["items"], "order_id")
        self.payments_by_order = _group_index(self.tables["payments"], "order_id")
        self.reviews_by_order = _group_index(self.tables["reviews"], "order_id")

    def order_context(self, order_id: str) -> OrderContext | None:
        """Return normalized records for one order, or ``None`` if absent."""
        order = self.orders_by_id.get(order_id)
        if order is None:
            return None
        items = list(self.items_by_order.get(order_id, []))
        return OrderContext(
            order=order,
            customer=self.customers_by_id.get(order["customer_id"]),
            items=items,
            payments=list(self.payments_by_order.get(order_id, [])),
            reviews=list(self.reviews_by_order.get(order_id, [])),
            sellers={item["seller_id"]: self.sellers_by_id[item["seller_id"]] for item in items if item["seller_id"] in self.sellers_by_id},
            products={item["product_id"]: self.products_by_id[item["product_id"]] for item in items if item["product_id"] in self.products_by_id},
        )

    def schema_report(self) -> dict[str, Any]:
        """Return a compact, serializable inventory of loaded tables."""
        return {
            name: {
                "rows": len(rows),
                "columns": list(rows[0].keys()) if rows else [],
            }
            for name, rows in self.tables.items()
        }


def _unique_index(rows: Iterable[dict[str, Any]], key: str, name: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not value:
            raise DatasetError(f"{name}: blank {key}")
        if value in index:
            raise DatasetError(f"{name}: duplicate {key}: {value}")
        index[value] = row
    return index


def _group_index(rows: Iterable[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if not value:
            raise DatasetError(f"Blank {key} in grouped table")
        index[value].append(row)
    return dict(index)
