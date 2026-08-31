#!/usr/bin/env python3
"""服务器端五类多任务模型检查、训练、评估和检测图生成入口。"""

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tool_defect.evaluation.multitask_suite import (  # noqa: E402
    DEFAULT_GPUS,
    DEFAULT_SPLIT,
    run_suite,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="检查并维护五类数据集对应的多任务模型套件。"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，默认是当前脚本所在项目。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="结果根目录，默认是 outputs/multitask_suite。",
    )
    parser.add_argument(
        "--gpus",
        default=','.join(str(gpu) for gpu in DEFAULT_GPUS),
        help="缺失模型的显卡编号，逗号分隔；默认使用五张 2080 Ti。",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="并行训练任务数，默认不超过显卡数量。",
    )
    parser.add_argument(
        "--split",
        choices=("validation", "test"),
        default=DEFAULT_SPLIT,
        help="评估划分，正式公平比较默认使用 test。",
    )
    parser.add_argument(
        "--seg-threshold",
        type=float,
        default=0.5,
        help="分割缺陷概率阈值，默认 0.5。",
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        default=None,
        help="训练子进程使用的 Python；默认继承当前环境。",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="只执行预检查并生成 run_plan.json，不训练、不加载模型。",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    output_root = args.output_root
    if output_root is None:
        output_root = project_root / "outputs" / "multitask_suite"
    elif not output_root.is_absolute():
        output_root = project_root / output_root
    result = run_suite(
        project_root,
        output_root=output_root,
        gpus=args.gpus,
        split=args.split,
        simulate=args.simulate,
        python_executable=args.python_executable,
        max_workers=args.max_workers,
        threshold=args.seg_threshold,
    )
    plan = result["plan"]
    print(f"项目：{plan['project_root']}")
    print(f"结果：{plan['output_root']}")
    for entry in plan["datasets"]:
        status = "已存在" if not entry["train_required"] else "需要训练"
        gpu = entry.get("planned_gpu", "-")
        print(f"{entry['name']}（{entry['dataset_id']}）：{status}，计划显卡 {gpu}")
    if args.simulate:
        print("模拟运行完成，未启动训练或模型推理。")
    else:
        print("五套模型训练、父图级评估和检测图生成完成。")
        print(f"汇总指标：{Path(plan['output_root']) / 'suite_metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
