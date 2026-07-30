#!/usr/bin/env python3
"""只读复核 P0 冻结数据、资产清单与现场安全默认值。"""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.baseline.decision_checks import validate_files
from tools.baseline.hardcoded_scan import scan_hardcoded_site_parameters
from tools.baseline.inventory import build_inventory, verify_lock


LOCK_PATH = ROOT / "tests/fixtures/baseline/baseline-lock.json"


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    first = build_inventory(ROOT)
    second = build_inventory(ROOT)

    errors: list[str] = []
    if first != second:
        errors.append("连续两次资产扫描结果不一致")
    errors.extend(verify_lock(first, lock))
    errors.extend(validate_files(ROOT))
    errors.extend(
        f"未登记现场硬编码：{finding}"
        for finding in scan_hardcoded_site_parameters(ROOT)
    )

    result = {
        "status": "PASSED" if not errors else "FAILED",
        "stable_inventory_sha256": first["stable_inventory_sha256"],
        "raw_image_count": first["asset_groups"]["raw_images"]["file_count"],
        "retraining_sample_count": first["dataset_facts"]["retraining"]["row_count"],
        "audit_test_sample_count": first["dataset_facts"]["retraining_audit"][
            "test_samples"
        ],
        "expected_blocker_count": len(first["blockers"]),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
