"""Step-1 readiness check for the Olist data and case inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_access import DatasetError, OlistDataStore, load_case_inputs  # noqa: E402


def main() -> int:
    store = OlistDataStore(ROOT / "data")
    report = {"datasets": store.schema_report()}
    try:
        cases = load_case_inputs(ROOT / "input")
        report["inputs"] = {"status": "ready", "count": len(cases)}
    except DatasetError as error:
        report["inputs"] = {"status": "not_ready", "message": str(error)}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
