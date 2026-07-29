#!/usr/bin/env python3
"""统一模型验证入口：审计三组历史候选并刷新受控证据。"""

import importlib.util
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVALUATOR_PATH = (
    PROJECT_ROOT / "jobs/model-evaluator/evaluate_candidates.py"
)
CONTROLLED_OUTPUT = (
    PROJECT_ROOT
    / "jobs/model-evaluator/controlled-output/p2-baseline"
)


def _load_evaluator():
    specification = importlib.util.spec_from_file_location(
        "tool_defect_model_evaluator",
        EVALUATOR_PATH,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载模型评估器")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def verify_models(
    project_root: Path = PROJECT_ROOT,
    output_dir: Path = CONTROLLED_OUTPUT,
) -> dict:
    evaluator = _load_evaluator()
    root = Path(project_root).resolve(strict=True)
    return evaluator.evaluate_three_candidates(
        evaluator.documented_candidate_specs(root),
        Path(output_dir),
    )


def main() -> int:
    try:
        report = verify_models()
    except Exception as error:
        report = {
            "schema_version": "1.0",
            "status": "BLOCKED",
            "production_claim_allowed": False,
            "blockers": [
                {
                    "candidate_id": "all",
                    "code": "VERIFIER_FAILED",
                    "message": "模型验证入口执行失败",
                    "exception_type": type(error).__name__,
                }
            ],
        }
        exit_code = 2
    else:
        exit_code = 0 if report.get("status") == "COMPLETE" else 2
    print(
        json.dumps(
            {
                "status": report.get("status", "BLOCKED"),
                "candidate_count": report.get("candidate_count", 0),
                "blocker_count": len(report.get("blockers", [])),
                "production_claim_allowed": False,
                "report": str(
                    CONTROLLED_OUTPUT / "evaluation-report.json"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
