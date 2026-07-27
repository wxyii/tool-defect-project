"""Unified command-line entry point."""

import argparse
import json
from pathlib import Path

from tool_defect.config import load_config
from tool_defect.data.manifest import build_manifest, write_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _data_check(args):
    rows = build_manifest(
        args.data_root,
        validation_fraction=args.validation_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    qualified = sum(row.label_name == "qualified" for row in rows)
    unqualified = sum(row.label_name == "unqualified" for row in rows)
    annotations = sum(bool(row.annotation_path) for row in rows)
    if args.manifest:
        write_manifest(rows, args.manifest)

    print(f"qualified images: {qualified}")
    print(f"unqualified images: {unqualified}")
    print(f"masks: {len(rows)}")
    print(f"annotations: {annotations}")
    print(f"train samples: {sum(row.split == 'train' for row in rows)}")
    print(f"validation samples: {sum(row.split == 'validation' for row in rows)}")
    print(f"test samples: {sum(row.split == 'test' for row in rows)}")
    return 0


def _predict(args):
    from tool_defect.inference.predict import predict

    config = load_config(args.config)
    model_key = (
        "classification_model"
        if args.task == "classification"
        else "multitask_model"
    )
    model_dir = args.model_dir or config.path(model_key)
    output_dir = args.output or config.path("outputs")
    result = predict(
        task=args.task,
        input_path=args.input_path,
        output_dir=output_dir,
        model_dir=model_dir,
    )
    print(result)
    return 0


def _train(args):
    from tool_defect.training.train import train

    keyword_arguments = {
        "task": args.task,
        "config_path": args.config,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "max_samples": args.max_samples,
        "output_dir": args.output,
    }
    if args.backbone_weights is not None:
        keyword_arguments["backbone_weights"] = args.backbone_weights
    history = train(**keyword_arguments)
    print(json.dumps(history, ensure_ascii=False))
    return 0


def _retrain_multitask(args):
    from tool_defect.training.retrain_multitask import retrain_multitask

    run_dir = retrain_multitask(
        config_path=args.config,
        init_model_dir=args.init_model_dir,
        output_root=args.output_root,
        run_id=args.run_id,
        smoke=args.smoke,
        resume=args.resume,
    )
    print(run_dir)
    return 0


def _evaluate(args):
    from tool_defect.evaluation.evaluate import evaluate

    metrics = evaluate(
        task=args.task,
        config_path=args.config,
        max_samples=args.max_samples,
        model_dir=args.model_dir,
        split=args.split,
        output_dir=args.output,
        full_metrics=args.full_metrics,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def _compare_multitask(args):
    from tool_defect.evaluation.compare_multitask import (
        compare_multitask_models,
    )

    result = compare_multitask_models(
        config_path=args.config,
        manifest_path=args.manifest,
        baseline_model_dir=args.baseline,
        candidate_model_dir=args.candidate,
        output_dir=args.output,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    data_check = subparsers.add_parser(
        "data-check", help="validate image, mask, and annotation pairing"
    )
    data_check.add_argument(
        "--data-root", type=Path, default=PROJECT_ROOT / "data"
    )
    data_check.add_argument("--manifest", type=Path)
    data_check.add_argument("--validation-fraction", type=float, default=0.2)
    data_check.add_argument("--test-fraction", type=float, default=0.2)
    data_check.add_argument("--seed", type=int, default=1)
    data_check.set_defaults(handler=_data_check)

    predict_parser = subparsers.add_parser(
        "predict", help="run existing JSON/H5 artifacts"
    )
    predict_parser.add_argument(
        "--task", choices=("classification", "multitask"), required=True
    )
    predict_parser.add_argument("--input", dest="input_path", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path)
    predict_parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/default.json"
    )
    predict_parser.add_argument("--model-dir", type=Path)
    predict_parser.set_defaults(handler=_predict)

    train_parser = subparsers.add_parser(
        "train", help="train one of the retained source models"
    )
    train_parser.add_argument(
        "--task", choices=("classification", "multitask"), required=True
    )
    train_parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/default.json"
    )
    train_parser.add_argument("--epochs", type=int)
    train_parser.add_argument("--batch-size", type=int)
    train_parser.add_argument("--max-samples", type=int)
    train_parser.add_argument(
        "--backbone-weights",
        help="use 'none', 'imagenet' (classifier), or a local weights path",
    )
    train_parser.add_argument("--output", type=Path)
    train_parser.set_defaults(handler=_train)

    retrain_parser = subparsers.add_parser(
        "retrain-multitask",
        help="warm-start the supplied multitask artifact in two stages",
    )
    retrain_parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/retrain_multitask.json",
    )
    retrain_parser.add_argument("--init-model-dir", type=Path)
    retrain_parser.add_argument("--output-root", type=Path)
    retrain_parser.add_argument("--run-id")
    retrain_parser.add_argument("--resume", type=Path)
    retrain_parser.add_argument("--smoke", action="store_true")
    retrain_parser.set_defaults(handler=_retrain_multitask)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate an existing artifact on the validation split"
    )
    evaluate_parser.add_argument(
        "--task", choices=("classification", "multitask"), required=True
    )
    evaluate_parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/default.json"
    )
    evaluate_parser.add_argument("--max-samples", type=int)
    evaluate_parser.add_argument("--model-dir", type=Path)
    evaluate_parser.add_argument(
        "--split",
        choices=("train", "validation", "test"),
        default="validation",
    )
    evaluate_parser.add_argument("--output", type=Path)
    evaluate_parser.add_argument("--full-metrics", action="store_true")
    evaluate_parser.set_defaults(handler=_evaluate)

    compare_parser = subparsers.add_parser(
        "compare-multitask",
        help="compare original and retrained multitask artifacts on one test split",
    )
    compare_parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/retrain_multitask.json",
    )
    compare_parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data/manifests/retrain.csv",
    )
    compare_parser.add_argument(
        "--baseline",
        type=Path,
        default=PROJECT_ROOT / "artifacts/multitask",
    )
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.add_argument("--bootstrap-samples", type=int, default=1000)
    compare_parser.add_argument("--seed", type=int, default=1)
    compare_parser.set_defaults(handler=_compare_multitask)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
