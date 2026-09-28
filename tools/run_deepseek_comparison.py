#!/usr/bin/env python3
"""批量调用 DeepSeek 视觉模型，并与现有算法父图结果统一对比。

示例：
  python tools/run_deepseek_comparison.py \
    --input data/images/Unqualified \
    --output outputs/deepseek_validation \
    --baseline-predictions outputs/current_baseline/predictions.csv
"""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.deepseek.batch import run_batch  # noqa: E402
from tool_defect.deepseek.client import DeepSeekVisionClient  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True, help="图片或图片目录")
    parser.add_argument("--output", type=Path, required=True, help="结果输出目录")
    parser.add_argument("--labels-csv", type=Path, help="可选真值 CSV：image_path,label")
    parser.add_argument(
        "--baseline-predictions",
        type=Path,
        help="可选现有算法 predictions.csv；建议使用父图级结果",
    )
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--detail", choices=("low", "high", "original", "auto"), default="original")
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="disabled")
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"))
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser


def main():
    args = build_parser().parse_args()
    client = DeepSeekVisionClient(
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        max_retries=args.max_retries,
    )
    summary = run_batch(
        client=client,
        input_paths=args.input,
        output_dir=args.output,
        labels_csv=args.labels_csv,
        baseline_predictions=args.baseline_predictions,
        detail=args.detail,
        max_tokens=args.max_tokens,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
