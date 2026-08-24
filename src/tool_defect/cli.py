"""Unified command-line entry point."""

import argparse
import csv
import json
from pathlib import Path

from tool_defect.config import load_config
from tool_defect.data.manifest import build_manifest, write_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _data_check(args):
    manifest_path = args.manifest
    if manifest_path is None and args.data_root.resolve() == (PROJECT_ROOT / "data").resolve():
        manifest_path = PROJECT_ROOT / "data/manifests/curated_v1_retrain.csv"

    if manifest_path is not None and manifest_path.is_file():
        with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        required = {
            "sample_id",
            "image_path",
            "mask_path",
            "annotation_path",
            "label",
            "label_name",
            "split",
        }
        for row in rows:
            missing = required.difference(row)
            if missing:
                raise ValueError(
                    f"manifest is missing columns: {sorted(missing)}"
                )
            for field in ("image_path", "mask_path"):
                path = args.data_root / row[field]
                if not path.is_file():
                    raise ValueError(f"missing {field} for {row['sample_id']}: {path}")
            if row["annotation_path"]:
                path = args.data_root / row["annotation_path"]
                if not path.is_file():
                    raise ValueError(
                        f"missing annotation for {row['sample_id']}: {path}"
                    )
    else:
        generated_rows = build_manifest(
            args.data_root,
            validation_fraction=args.validation_fraction,
            test_fraction=args.test_fraction,
            seed=args.seed,
        )
        if args.manifest:
            write_manifest(generated_rows, args.manifest)
        rows = [vars(row) for row in generated_rows]

    qualified = sum(row["label_name"] == "qualified" for row in rows)
    unqualified = sum(row["label_name"] == "unqualified" for row in rows)
    annotations = sum(bool(row["annotation_path"]) for row in rows)

    print(f"qualified images: {qualified}")
    print(f"unqualified images: {unqualified}")
    print(f"masks: {len(rows)}")
    print(f"annotations: {annotations}")
    print(f"train samples: {sum(row['split'] == 'train' for row in rows)}")
    print(f"validation samples: {sum(row['split'] == 'validation' for row in rows)}")
    print(f"test samples: {sum(row['split'] == 'test' for row in rows)}")
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
        input_paths=args.input_paths,
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


def _train_multitask_source(args):
    from tool_defect.training.train_multitask_source import (
        train_multitask_source,
    )

    run_dir = train_multitask_source(
        config_path=args.config,
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


def _compare_multitask_suite(args):
    from tool_defect.evaluation.compare_multitask_suite import (
        compare_multitask_suite,
    )

    result = compare_multitask_suite(
        config_path=args.config,
        manifest_path=args.manifest,
        baseline_model_dir=args.baseline,
        previous_model_dir=args.previous,
        source_model_dir=args.candidate,
        output_dir=args.output,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _ring_compare(args):
    from tool_defect.data.ring_geometry import (
        process_image_path,
        save_boundary_profiles,
        save_comparison_figure,
        save_pipeline_figure,
    )

    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    input_paths = [args.qualified, args.unqualified]
    labels = ["合格刀片", "不合格刀片"]
    results = [
        process_image_path(
            path,
            output_size=args.output_size,
            angle_samples=args.angle_samples,
        )
        for path in input_paths
    ]
    for path, label, result in zip(input_paths, labels, results):
        save_pipeline_figure(
            result,
            output_dir / f"{path.stem}_pipeline.png",
            title=f"{label}：{path.name}",
        )
        save_boundary_profiles(
            result,
            output_dir / f"{path.stem}_boundary_profiles.csv",
        )
    comparison_path = output_dir / "ring_comparison.png"
    save_comparison_figure(results, labels, comparison_path)
    print(comparison_path)
    return 0


def _polar_fit(args):
    from tool_defect.detection.polar_anomaly import fit_unlabeled_model

    _, report = fit_unlabeled_model(
        args.input_path,
        args.output,
        output_size=args.output_size,
        angle_samples=args.angle_samples,
        minimum_periods=args.minimum_periods,
        maximum_periods=args.maximum_periods,
        cache_dir=args.cache,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _polar_detect(args):
    from tool_defect.detection.polar_anomaly import run_detection

    report = run_detection(
        args.input_path,
        args.model,
        args.output,
        cache_dir=args.cache,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _polar_cache(args):
    from tool_defect.detection.polar_anomaly import iter_image_paths
    from tool_defect.detection.polar_cache import build_polar_cache

    report = build_polar_cache(
        args.input_path,
        args.output,
        iter_image_paths(args.input_path),
        output_size=args.output_size,
        angle_samples=args.angle_samples,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _ring_dataset(args):
    from tool_defect.data.ring_dataset import build_ring_dataset

    output = args.output
    if output is None:
        output = (
            PROJECT_ROOT
            / "data"
            / "processed"
            / args.mode.replace("-", "_")
        )

    def report_progress(index, total, sample_id, cache_state):
        if index == 1 or index % 10 == 0 or index == total:
            print(
                f"[{index}/{total}] {sample_id} "
                f"（极坐标缓存：{cache_state}）"
            )

    report = build_ring_dataset(
        source_data_root=args.data_root,
        source_manifest=args.manifest,
        output_root=output,
        mode=args.mode,
        cache_dir=args.cache,
        output_size=args.output_size,
        angle_samples=args.angle_samples,
        radial_samples=args.radial_samples,
        progress_callback=report_progress,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
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
    predict_parser.add_argument("--input", dest="input_paths", type=Path, nargs="+", required=True)
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

    source_train_parser = subparsers.add_parser(
        "train-multitask-source",
        help="train multitask.py with a fresh ImageNet-initialized backbone",
    )
    source_train_parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/train_multitask_source.json",
    )
    source_train_parser.add_argument("--output-root", type=Path)
    source_train_parser.add_argument("--run-id")
    source_train_parser.add_argument("--resume", type=Path)
    source_train_parser.add_argument("--smoke", action="store_true")
    source_train_parser.set_defaults(handler=_train_multitask_source)

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
        default=PROJECT_ROOT / "data/manifests/curated_v1_retrain.csv",
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

    suite_parser = subparsers.add_parser(
        "compare-multitask-suite",
        help="compare original, previous retraining, and source-trained artifacts",
    )
    suite_parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/train_multitask_source.json",
    )
    suite_parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data/manifests/curated_v1_retrain.csv",
    )
    suite_parser.add_argument(
        "--baseline",
        type=Path,
        default=PROJECT_ROOT / "artifacts/multitask",
    )
    suite_parser.add_argument("--previous", type=Path, required=True)
    suite_parser.add_argument("--candidate", type=Path, required=True)
    suite_parser.add_argument("--output", type=Path, required=True)
    suite_parser.add_argument("--bootstrap-samples", type=int, default=1000)
    suite_parser.add_argument("--seed", type=int, default=1)
    suite_parser.set_defaults(handler=_compare_multitask_suite)

    ring_parser = subparsers.add_parser(
        "ring-compare", help="定位、校正并展开合格与不合格刀片的环形区域"
    )
    ring_parser.add_argument(
        "--qualified",
        type=Path,
        default=PROJECT_ROOT / "data/images/Qualified/21-1.png",
    )
    ring_parser.add_argument(
        "--unqualified",
        type=Path,
        default=PROJECT_ROOT / "data/images/Unqualified/103.png",
    )
    ring_parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs/ring_comparison",
    )
    ring_parser.add_argument("--output-size", type=int, default=512)
    ring_parser.add_argument("--angle-samples", type=int, default=1440)
    ring_parser.set_defaults(handler=_ring_compare)

    polar_fit_parser = subparsers.add_parser(
        "polar-fit", help="从无标签圆形刀片图像标定极坐标异常检测器"
    )
    polar_fit_parser.add_argument(
        "--input",
        dest="input_path",
        type=Path,
        default=PROJECT_ROOT / "data/images",
    )
    polar_fit_parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/polar_anomaly",
    )
    polar_fit_parser.add_argument("--output-size", type=int, default=512)
    polar_fit_parser.add_argument("--angle-samples", type=int, default=1440)
    polar_fit_parser.add_argument("--minimum-periods", type=int, default=8)
    polar_fit_parser.add_argument("--maximum-periods", type=int, default=40)
    polar_fit_parser.add_argument(
        "--cache",
        type=Path,
        help="复用或自动更新指定目录中的极坐标预处理缓存",
    )
    polar_fit_parser.set_defaults(handler=_polar_fit)

    polar_detect_parser = subparsers.add_parser(
        "polar-detect", help="定位并评分极坐标展开图中的疑似缺陷"
    )
    polar_detect_parser.add_argument(
        "--input", dest="input_path", type=Path, required=True
    )
    polar_detect_parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT / "artifacts/polar_anomaly",
    )
    polar_detect_parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs/polar_detection",
    )
    polar_detect_parser.add_argument(
        "--cache",
        type=Path,
        help="复用或自动更新指定目录中的极坐标预处理缓存",
    )
    polar_detect_parser.set_defaults(handler=_polar_detect)

    polar_cache_parser = subparsers.add_parser(
        "polar-cache", help="生成或更新圆形刀片的极坐标预处理缓存"
    )
    polar_cache_parser.add_argument(
        "--input",
        dest="input_path",
        type=Path,
        default=PROJECT_ROOT / "data/images",
    )
    polar_cache_parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs/polar_cache",
    )
    polar_cache_parser.add_argument("--output-size", type=int, default=512)
    polar_cache_parser.add_argument("--angle-samples", type=int, default=1440)
    polar_cache_parser.set_defaults(handler=_polar_cache)

    ring_dataset_parser = subparsers.add_parser(
        "ring-dataset",
        help="生成自适应环形区域或边界归一化展开训练数据集",
    )
    ring_dataset_parser.add_argument(
        "--mode",
        choices=("adaptive-annular", "boundary-normalized"),
        required=True,
    )
    ring_dataset_parser.add_argument(
        "--data-root",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="源图像、掩膜所在的数据根目录",
    )
    ring_dataset_parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data/manifests/curated_v1_retrain.csv",
        help="源数据清单；原有训练、验证、测试划分会原样保留",
    )
    ring_dataset_parser.add_argument(
        "--output",
        type=Path,
        help="输出数据根目录；默认按模式写入 data/processed",
    )
    ring_dataset_parser.add_argument(
        "--cache",
        type=Path,
        default=PROJECT_ROOT / "outputs/polar_cache",
        help="复用或自动更新极坐标几何缓存",
    )
    ring_dataset_parser.add_argument("--output-size", type=int, default=512)
    ring_dataset_parser.add_argument("--angle-samples", type=int, default=1440)
    ring_dataset_parser.add_argument(
        "--radial-samples",
        type=int,
        help="展开图固定径向采样数，仅用于 boundary-normalized",
    )
    ring_dataset_parser.set_defaults(handler=_ring_dataset)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
