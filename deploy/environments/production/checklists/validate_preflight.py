#!/usr/bin/env python3
"""聚合起飞前结构化执行记录，不直接执行清单中的任意 Shell。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.preflight import validate_preflight_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checklist",
        type=Path,
        default=REPO_ROOT / "deploy/environments/production/checklists/pre-flight.json",
    )
    parser.add_argument("--results", type=Path)
    args = parser.parse_args(argv)
    return validate_preflight_results(
        repo_root=REPO_ROOT,
        checklist_path=args.checklist,
        results_path=args.results,
    ).emit()


if __name__ == "__main__":
    raise SystemExit(main())
