#!/usr/bin/env python3
"""生成确定性的 P0 资产清单。

该工具只读取仓库。它不会恢复 Git LFS 权重、创建输出目录或修改任何
数据、模型和缓存。所有记录均以仓库相对路径排序，目录摘要由
``相对路径 + 文件字节数 + 文件 SHA-256`` 的规范 JSON 计算。
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
from importlib import metadata as package_metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Iterable


SCHEMA_VERSION = "1.0.0"
SCANNER_VERSION = "1.0.0"
BASELINE_GIT_REVISION = "97c88cbdcee18129ad0011008d6e49a8f700e145"

BASELINE_TEST_FILES = (
    "tests/test_cli.py",
    "tests/test_compare_multitask.py",
    "tests/test_config.py",
    "tests/test_datasets.py",
    "tests/test_inference.py",
    "tests/test_manifest.py",
    "tests/test_mask_conversion.py",
    "tests/test_metrics.py",
    "tests/test_model_builders.py",
    "tests/test_model_loading.py",
    "tests/test_polar_anomaly.py",
    "tests/test_preprocess.py",
    "tests/test_retrain_manifest.py",
    "tests/test_retrain_multitask.py",
    "tests/test_ring_dataset.py",
    "tests/test_ring_geometry.py",
    "tests/test_training_objectives.py",
    "tests/test_training_sequence.py",
    "tests/test_visualize.py",
    "tests/test_workflows.py",
)

BASELINE_CONFIG_FILES = (
    "configs/default.json",
    "configs/multitask_adaptive_annular.json",
    "configs/multitask_boundary_normalized.json",
    "configs/retrain_multitask.json",
    "configs/retrain_multitask_resume_20260727.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-app.txt",
    "setup.cfg",
)

ROOT_ENTRY_FILES = (
    "predict.bat",
    "predict.ps1",
    "run_ring_batch.py",
)

DESIGN_DOCUMENT_FILES = (
    "Docs/README.md",
    "Docs/01-核心设计原则.md",
    "Docs/02-完整检测业务流程.md",
    "Docs/03-算法与预处理通用接口设计.md",
    "Docs/04-人工复核系统.md",
    "Docs/05-数据库设计.md",
    "Docs/06-接口设计.md",
    "Docs/07-图片存储方案.md",
    "Docs/08-增量训练闭环.md",
    "Docs/09-前端功能规划.md",
    "Docs/10-异常处理.md",
    "Docs/11-日志与监控.md",
    "Docs/12-安全权限与角色.md",
    "Docs/13-推荐项目代码结构.md",
    "Docs/14-技术选型.md",
    "Docs/15-系统分阶段构建与智能体任务计划.md",
)

EXPECTED_MODEL_FILES = (
    {
        "path": "artifacts/classification/model.json",
        "kind": "分类模型结构",
        "expected_sha256": None,
    },
    {
        "path": "artifacts/classification/weights.h5",
        "kind": "分类模型权重",
        "expected_sha256": None,
    },
    {
        "path": "artifacts/multitask/model.json",
        "kind": "历史双任务模型结构",
        "expected_sha256":
            "377a1cece0dc45bd15407356ec2b624ac25072a9a91ddebaec5c51a508005f50",
    },
    {
        "path": "artifacts/multitask/weights.h5",
        "kind": "历史双任务模型权重",
        "expected_sha256": None,
    },
    {
        "path": "outputs/training/multitask/model.json",
        "kind": "原图双任务候选结构",
        "expected_sha256":
            "63870f093b42ae0b51617cf0dd83465c122b49222e7e8e80db4f6c855b77d4b3",
    },
    {
        "path": "outputs/training/multitask/weights.h5",
        "kind": "原图双任务候选权重",
        "expected_sha256":
            "5613d2eb4dabcc691e114fd921f5bb8f6d9d5a5a561bd8232dd58f1ece248f7a",
    },
    {
        "path": "outputs/training/multitask_adaptive_annular/model.json",
        "kind": "自适应环形双任务候选结构",
        "expected_sha256":
            "63870f093b42ae0b51617cf0dd83465c122b49222e7e8e80db4f6c855b77d4b3",
    },
    {
        "path": "outputs/training/multitask_adaptive_annular/weights.h5",
        "kind": "自适应环形双任务候选权重",
        "expected_sha256":
            "35f64b4a9545afe8564a69e9b9ba8d4dc305729f51977c495ab033f95e96a98e",
    },
    {
        "path": "outputs/training/multitask_boundary_normalized/model.json",
        "kind": "边界归一化双任务候选结构",
        "expected_sha256":
            "63870f093b42ae0b51617cf0dd83465c122b49222e7e8e80db4f6c855b77d4b3",
    },
    {
        "path": "outputs/training/multitask_boundary_normalized/weights.h5",
        "kind": "边界归一化双任务候选权重",
        "expected_sha256":
            "162526a04bc4972faff9fff13f77b37e4a3509884d33aa188303ae5b855ca545",
    },
    {
        "path": "artifacts/polar_anomaly/polar_anomaly.json",
        "kind": "极坐标异常模型",
        "expected_sha256": None,
    },
)

HISTORICAL_WEIGHT_PATHS = (
    "artifacts/classification/weights.h5",
    "artifacts/multitask/weights.h5",
)

PACKAGE_NAMES = (
    "tensorflow",
    "keras",
    "opencv-python",
    "Pillow",
    "scikit-image",
    "numpy",
    "pandas",
    "scikit-learn",
    "matplotlib",
    "seaborn",
    "tqdm",
)

IGNORED_NAMES = {
    ".DS_Store",
    "__pycache__",
    ".pytest_cache",
}


@dataclass(frozen=True)
class FileRecord:
    path: str
    size_bytes: int
    sha256: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_NAMES for part in path.parts) or path.suffix == ".pyc"


def _expand_paths(root: Path, relative_paths: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for relative in relative_paths:
        candidate = root / relative
        if candidate.is_file():
            paths.append(candidate)
        elif candidate.is_dir():
            paths.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file() and not _is_ignored(path.relative_to(root))
            )
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def file_records(root: Path, relative_paths: Iterable[str]) -> list[FileRecord]:
    records = []
    for path in _expand_paths(root, relative_paths):
        records.append(
            FileRecord(
                path=path.relative_to(root).as_posix(),
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
    return records


def git_snapshot_file_records(
    root: Path,
    relative_paths: Iterable[str],
    revision: str = BASELINE_GIT_REVISION,
) -> list[FileRecord]:
    """从冻结提交读取文件，不受后续阶段工作树改动影响。"""

    result = _git(
        "ls-tree",
        "-r",
        "-l",
        "-z",
        revision,
        "--",
        *relative_paths,
        root=root,
        check=True,
    )
    records = []
    for raw_entry in result.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        parts = metadata.decode("ascii").split()
        if len(parts) != 4 or parts[1] != "blob":
            continue
        object_id = parts[2]
        payload = _git(
            "cat-file",
            "blob",
            object_id,
            root=root,
            check=True,
        ).stdout
        relative_path = raw_path.decode("utf-8")
        records.append(
            FileRecord(
                path=relative_path,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    return sorted(records, key=lambda item: item.path)


def summarize_records(records: list[FileRecord], include_records: bool) -> dict[str, Any]:
    serialized = [asdict(record) for record in records]
    result: dict[str, Any] = {
        "file_count": len(records),
        "total_bytes": sum(record.size_bytes for record in records),
        "aggregate_sha256": canonical_sha256(serialized),
    }
    if include_records:
        result["records"] = serialized
    return result


def _worktree_asset_group_specs() -> dict[str, tuple[str, ...]]:
    return {
        "design_documents": DESIGN_DOCUMENT_FILES,
        "raw_images": ("data/images",),
        "raw_masks": ("data/masks",),
        "labelme_annotations": ("data/annotations/labelme_json",),
        "dataset_manifests": (
            "data/manifests/dataset.csv",
            "data/manifests/retrain.csv",
            "data/manifests/retrain_audit.json",
        ),
        "adaptive_annular_dataset": ("data/processed/adaptive_annular",),
        "boundary_normalized_dataset": ("data/processed/boundary_normalized",),
        "current_model_artifacts": ("artifacts",),
    }


def _git_asset_group_specs() -> dict[str, tuple[str, ...]]:
    return {
        "current_source_code": ("src", "app/legacy", *ROOT_ENTRY_FILES),
        "current_configuration": BASELINE_CONFIG_FILES,
        "current_tests": BASELINE_TEST_FILES,
    }


def build_asset_groups(root: Path, include_records: bool = False) -> dict[str, Any]:
    groups = {
        name: summarize_records(file_records(root, paths), include_records)
        for name, paths in sorted(_worktree_asset_group_specs().items())
    }
    groups.update(
        {
            name: summarize_records(
                git_snapshot_file_records(root, paths),
                include_records,
            )
            for name, paths in sorted(_git_asset_group_specs().items())
        }
    )
    return dict(sorted(groups.items()))


def _exact_case_exists(root: Path, relative_path: str) -> bool:
    current = root
    for part in Path(relative_path).parts:
        if not current.is_dir():
            return False
        names = {entry.name for entry in current.iterdir()}
        if part not in names:
            return False
        current = current / part
    return current.is_file()


def _manifest_facts(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    split_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    sample_ids: list[str] = []
    image_case_mismatches = 0
    mask_case_mismatches = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        split = row["split"].strip()
        label_name = row["label_name"].strip()
        split_counts[split] = split_counts.get(split, 0) + 1
        class_counts[label_name] = class_counts.get(label_name, 0) + 1
        sample_ids.append(row["sample_id"])
        if not _exact_case_exists(root / "data", row["image_path"]):
            image_case_mismatches += 1
        if not _exact_case_exists(root / "data", row["mask_path"]):
            mask_case_mismatches += 1
    return {
        "path": relative_path,
        "sha256": sha256_file(path),
        "row_count": len(rows),
        "split_counts": dict(sorted(split_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "duplicate_sample_id_count": len(sample_ids) - len(set(sample_ids)),
        "image_exact_case_mismatch_count": image_case_mismatches,
        "mask_exact_case_mismatch_count": mask_case_mismatches,
    }


def build_dataset_facts(root: Path) -> dict[str, Any]:
    audit_path = root / "data/manifests/retrain_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    return {
        "original": _manifest_facts(root, "data/manifests/dataset.csv"),
        "retraining": _manifest_facts(root, "data/manifests/retrain.csv"),
        "retraining_audit": {
            "path": "data/manifests/retrain_audit.json",
            "sha256": sha256_file(audit_path),
            "source_samples": audit.get("source_samples"),
            "final_samples": audit.get("final_samples"),
            "test_samples": audit.get("split_counts", {}).get("test"),
            "excluded_conflicting": audit.get("excluded_conflicting"),
            "deduplicated_exact": audit.get("deduplicated_exact"),
            "cross_split_duplicate_hashes": audit.get(
                "cross_split_duplicate_hashes"
            ),
        },
    }


def _keras_signature(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    config = payload.get("config", {})
    layers = config.get("layers", [])
    layer_by_name = {
        layer.get("name"): layer
        for layer in layers
        if isinstance(layer, dict) and layer.get("name")
    }
    inputs = []
    for value in config.get("input_layers", []):
        name = value[0] if isinstance(value, list) and value else str(value)
        layer_config = layer_by_name.get(name, {}).get("config", {})
        inputs.append(
            {
                "name": name,
                "shape": layer_config.get("batch_input_shape")
                or layer_config.get("batch_shape"),
            }
        )
    outputs = []
    for value in config.get("output_layers", []):
        name = value[0] if isinstance(value, list) and value else str(value)
        layer = layer_by_name.get(name, {})
        layer_config = layer.get("config", {})
        outputs.append(
            {
                "name": name,
                "layer_type": layer.get("class_name"),
                "units": layer_config.get("units"),
                "filters": layer_config.get("filters"),
            }
        )
    return {
        "keras_version": payload.get("keras_version"),
        "backend": payload.get("backend"),
        "inputs": inputs,
        "outputs": outputs,
    }


def build_model_facts(root: Path) -> dict[str, Any]:
    files = []
    for expected in EXPECTED_MODEL_FILES:
        relative_path = expected["path"]
        path = root / relative_path
        present = path.is_file()
        actual_sha256 = sha256_file(path) if present else None
        expected_sha256 = expected["expected_sha256"]
        files.append(
            {
                **expected,
                "present": present,
                "size_bytes": path.stat().st_size if present else None,
                "actual_sha256": actual_sha256,
                "hash_matches_expected": (
                    actual_sha256 == expected_sha256
                    if expected_sha256 is not None and present
                    else None
                ),
                "signature": (
                    _keras_signature(path)
                    if relative_path.endswith("model.json")
                    else None
                ),
            }
        )
    polar_path = root / "artifacts/polar_anomaly/polar_anomaly.json"
    polar_version = None
    if polar_path.is_file():
        polar_version = json.loads(polar_path.read_text(encoding="utf-8")).get(
            "version"
        )
    code_path = root / "src/tool_defect/detection/polar_anomaly.py"
    required_version = None
    if code_path.is_file():
        match = re.search(
            r"^MODEL_VERSION\s*=\s*(\d+)\s*$",
            code_path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        required_version = int(match.group(1)) if match else None
    return {
        "files": files,
        "polar_model_version": polar_version,
        "polar_required_version": required_version,
        "polar_version_compatible": (
            polar_version == required_version
            if polar_version is not None and required_version is not None
            else False
        ),
    }


def _git(*args: str, root: Path, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _historical_blob_oid(root: Path, relative_path: str) -> str | None:
    result = _git(
        "rev-list",
        "--objects",
        "--all",
        "--",
        relative_path,
        root=root,
        check=False,
    )
    if result.returncode != 0:
        return None
    suffix = f" {relative_path}"
    candidates = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        if line.endswith(suffix):
            candidates.append(line.split(" ", 1)[0])
    return sorted(set(candidates))[0] if candidates else None


def _parse_lfs_pointer(payload: bytes) -> dict[str, Any] | None:
    text = payload.decode("utf-8", errors="replace")
    oid_match = re.search(r"^oid sha256:([0-9a-f]{64})$", text, re.MULTILINE)
    size_match = re.search(r"^size (\d+)$", text, re.MULTILINE)
    if not oid_match or not size_match:
        return None
    return {
        "lfs_oid_sha256": oid_match.group(1),
        "lfs_size_bytes": int(size_match.group(1)),
    }


def build_historical_weight_evidence(root: Path) -> list[dict[str, Any]]:
    evidence = []
    for relative_path in HISTORICAL_WEIGHT_PATHS:
        blob_oid = _historical_blob_oid(root, relative_path)
        record: dict[str, Any] = {
            "path": relative_path,
            "git_blob_oid": blob_oid,
            "git_blob_type": None,
            "git_blob_size_bytes": None,
            "git_blob_sha256": None,
            "lfs_oid_sha256": None,
            "lfs_size_bytes": None,
            "lfs_cached_object_present": False,
            "lfs_cached_object_hash_matches": None,
            "lfs_cached_object_size_matches": None,
            "worktree_restored": (root / relative_path).is_file(),
        }
        if blob_oid:
            type_result = _git(
                "cat-file", "-t", blob_oid, root=root, check=False
            )
            size_result = _git(
                "cat-file", "-s", blob_oid, root=root, check=False
            )
            payload_result = _git(
                "cat-file", "blob", blob_oid, root=root, check=False
            )
            if (
                type_result.returncode == 0
                and size_result.returncode == 0
                and payload_result.returncode == 0
            ):
                payload = payload_result.stdout
                record["git_blob_type"] = type_result.stdout.decode().strip()
                record["git_blob_size_bytes"] = int(
                    size_result.stdout.decode().strip()
                )
                record["git_blob_sha256"] = hashlib.sha256(payload).hexdigest()
                pointer = _parse_lfs_pointer(payload)
                if pointer:
                    record.update(pointer)
                    oid = pointer["lfs_oid_sha256"]
                    cached = (
                        root
                        / ".git/lfs/objects"
                        / oid[:2]
                        / oid[2:4]
                        / oid
                    )
                    if cached.is_file():
                        record["lfs_cached_object_present"] = True
                        record["lfs_cached_object_hash_matches"] = (
                            sha256_file(cached) == oid
                        )
                        record["lfs_cached_object_size_matches"] = (
                            cached.stat().st_size == pointer["lfs_size_bytes"]
                        )
        evidence.append(record)
    return evidence


def _declared_package_versions(root: Path) -> dict[str, str]:
    declared: dict[str, str] = {}
    path = root / "requirements.txt"
    if not path.is_file():
        return declared
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-r ")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if match:
            declared[match.group(1)] = match.group(2)
    return dict(sorted(declared.items(), key=lambda item: item[0].lower()))


def build_environment_facts(root: Path) -> dict[str, Any]:
    packages = {}
    for name in PACKAGE_NAMES:
        try:
            packages[name] = package_metadata.version(name)
        except package_metadata.PackageNotFoundError:
            packages[name] = "未安装"
    declared = _declared_package_versions(root)
    installed_casefold = {
        name.casefold(): version for name, version in packages.items()
    }
    version_drift = []
    for name, expected in declared.items():
        actual = installed_casefold.get(name.casefold(), "未安装")
        if actual != expected:
            version_drift.append(
                {
                    "package": name,
                    "declared": expected,
                    "installed": actual,
                }
            )
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "machine": platform.machine(),
        "packages": packages,
        "declared_packages": declared,
        "version_drift": version_drift,
    }


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    if isinstance(value, str):
        return value.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", value))
    return False


def build_blockers(
    root: Path,
    groups: dict[str, Any],
    datasets: dict[str, Any],
    models: dict[str, Any],
    environment: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []

    def add(
        code: str,
        summary: str,
        evidence: list[str],
        latest_gate: str,
        safe_behavior: str,
    ) -> None:
        blockers.append(
            {
                "code": code,
                "severity": "阻断",
                "summary": summary,
                "evidence": evidence,
                "latest_gate": latest_gate,
                "safe_behavior": safe_behavior,
            }
        )

    model_by_path = {item["path"]: item for item in models["files"]}
    missing_worktree_weights = [
        path
        for path in HISTORICAL_WEIGHT_PATHS
        if not model_by_path[path]["present"]
    ]
    if missing_worktree_weights:
        add(
            "P0-ASSET-HISTORICAL-WEIGHTS-MISSING",
            "历史分类与双任务权重未出现在工作树",
            missing_worktree_weights,
            "G2",
            "相关推理、评估和模型加载保持失败，不得生成占位权重或自动 PASS。",
        )

    missing_training = [
        item["path"]
        for item in models["files"]
        if item["path"].startswith("outputs/training/") and not item["present"]
    ]
    if missing_training:
        add(
            "P0-ASSET-THREE-TRAINING-MODELS-MISSING",
            "文档所列三组双任务训练产物均缺失",
            missing_training,
            "G2",
            "不得登记、混配或声称这些候选模型可加载。",
        )

    if groups["labelme_annotations"]["file_count"] == 0:
        add(
            "P0-ASSET-LABELME-ANNOTATIONS-MISSING",
            "README 声称的 82 份 Labelme 标注当前为 0",
            ["data/annotations/labelme_json"],
            "G6",
            "掩膜可用于当前基线，但不得声称 Labelme 来源完整。",
        )

    if not models["polar_version_compatible"]:
        add(
            "P0-ASSET-POLAR-MODEL-INCOMPATIBLE",
            "极坐标模型版本与代码要求不兼容",
            [
                f"model={models['polar_model_version']}",
                f"required={models['polar_required_version']}",
            ],
            "G6",
            "拒绝登记和加载旧模型，重新缓存并标定前不得部署。",
        )

    case_mismatches = (
        datasets["original"]["image_exact_case_mismatch_count"]
        + datasets["retraining"]["image_exact_case_mismatch_count"]
        + datasets["original"]["mask_exact_case_mismatch_count"]
        + datasets["retraining"]["mask_exact_case_mismatch_count"]
    )
    if case_mismatches:
        add(
            "P0-ASSET-PATH-CASE-MISMATCH",
            "数据清单路径大小写与磁盘目录不完全一致",
            [
                "data/images/Qualified 与清单 images/qualified",
                "data/images/Unqualified 与清单 images/unqualified",
                f"mismatch_count={case_mismatches}",
            ],
            "G1",
            "大小写敏感环境不得在未校验路径时启动训练或评估。",
        )

    absolute_reports = []
    for relative in (
        "data/processed/adaptive_annular/generation_report.json",
        "data/processed/boundary_normalized/generation_report.json",
    ):
        path = root / relative
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if _contains_absolute_path(payload):
                absolute_reports.append(relative)
    if absolute_reports:
        add(
            "P0-ASSET-NONPORTABLE-GENERATION-REPORT",
            "处理数据报告含个人机器绝对路径",
            absolute_reports,
            "G1",
            "报告仅作历史证据，不能作为跨环境生成入口。",
        )

    if environment["version_drift"]:
        add(
            "P0-ENVIRONMENT-DEPENDENCY-DRIFT",
            "当前虚拟环境与锁定依赖版本不一致",
            [
                (
                    f"{item['package']}: declared={item['declared']}, "
                    f"installed={item['installed']}"
                )
                for item in environment["version_drift"]
            ],
            "G1",
            "环境漂移不得作为可重复构建证据；重新锁定或重建前保留失败状态。",
        )

    add(
        "P0-TEST-FROZEN-BASELINE-FAILED",
        "冻结测试结果为 62 项中 1 个失败、9 个错误",
        [
            "命令：PYTHONDONTWRITEBYTECODE=1 .venv/bin/python "
            "-m unittest discover -s tests",
            "9 个错误由缺失权重触发；1 个失败为 POSIX 下 D:/ 路径识别问题。",
        ],
        "G1",
        "失败基线必须显式保留；技术失败不得转换为 PASS。",
    )

    add(
        "P0-ASSET-MODEL-PROVENANCE-INCOMPLETE",
        "现有模型缺少完整训练历史、配置副本和环境来源",
        [
            "artifacts/classification",
            "artifacts/multitask",
            "Docs/08-增量训练闭环.md#2.2",
        ],
        "G6",
        "目录名和研究指标不能用于生产发布，模型仅可作为待核验历史资产。",
    )
    return sorted(blockers, key=lambda item: item["code"])


def _load_frozen_test_baseline(root: Path) -> dict[str, Any] | None:
    path = root / "tests/fixtures/baseline/test-baseline.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_inventory(root: Path, include_records: bool = False) -> dict[str, Any]:
    root = root.resolve()
    groups = build_asset_groups(root, include_records=include_records)
    datasets = build_dataset_facts(root)
    models = build_model_facts(root)
    historical = build_historical_weight_evidence(root)
    environment = build_environment_facts(root)
    blockers = build_blockers(root, groups, datasets, models, environment)
    stable_payload = {
        "source_revision": BASELINE_GIT_REVISION,
        "asset_groups": {
            name: {
                key: value
                for key, value in group.items()
                if key != "records"
            }
            for name, group in groups.items()
        },
        "dataset_facts": datasets,
        "model_facts": models,
        "historical_weight_evidence": [
            {
                key: value
                for key, value in item.items()
                if not key.startswith("lfs_cached_")
            }
            for item in historical
        ],
        "environment": {
            "python_version": environment["python_version"],
            "python_implementation": environment["python_implementation"],
            "packages": environment["packages"],
            "declared_packages": environment["declared_packages"],
            "version_drift": environment["version_drift"],
        },
        "blocker_codes": [item["code"] for item in blockers],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scanner_version": SCANNER_VERSION,
        "source_revision": BASELINE_GIT_REVISION,
        "asset_groups": groups,
        "dataset_facts": datasets,
        "model_facts": models,
        "historical_weight_evidence": historical,
        "environment": environment,
        "frozen_test_baseline": _load_frozen_test_baseline(root),
        "blockers": blockers,
        "stable_inventory_sha256": canonical_sha256(stable_payload),
    }


def _stable_group_summaries(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            key: value
            for key, value in group.items()
            if key != "records"
        }
        for name, group in inventory["asset_groups"].items()
    }


def verify_lock(inventory: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if inventory["source_revision"] != lock.get("source_revision"):
        errors.append("来源提交与冻结清单不一致")
    actual_groups = _stable_group_summaries(inventory)
    if actual_groups != lock.get("asset_groups"):
        errors.append("资产组数量、字节数或聚合 SHA-256 与冻结清单不一致")

    expected_datasets = lock.get("dataset_facts")
    if inventory["dataset_facts"] != expected_datasets:
        errors.append("180/172/34 数据事实或清单 SHA-256 与冻结清单不一致")

    critical_files = {
        item["path"]: {
            "present": item["present"],
            "size_bytes": item["size_bytes"],
            "actual_sha256": item["actual_sha256"],
            "expected_sha256": item["expected_sha256"],
            "hash_matches_expected": item["hash_matches_expected"],
        }
        for item in inventory["model_facts"]["files"]
    }
    if critical_files != lock.get("critical_model_files"):
        errors.append("模型文件存在性、大小或 SHA-256 与冻结清单不一致")

    historical = [
        {
            key: value
            for key, value in item.items()
            if key
            in {
                "path",
                "git_blob_oid",
                "git_blob_type",
                "git_blob_size_bytes",
                "git_blob_sha256",
                "lfs_oid_sha256",
                "lfs_size_bytes",
                "worktree_restored",
            }
        }
        for item in inventory["historical_weight_evidence"]
    ]
    if historical != lock.get("historical_weight_evidence"):
        errors.append("历史权重 Git/LFS 指针证据与冻结清单不一致")

    blocker_codes = [item["code"] for item in inventory["blockers"]]
    if blocker_codes != lock.get("expected_blocker_codes"):
        errors.append("阻断项集合与冻结失败清单不一致")

    frozen_environment = {
        key: inventory["environment"][key]
        for key in (
            "python_version",
            "python_implementation",
            "packages",
            "declared_packages",
            "version_drift",
        )
    }
    if frozen_environment != lock.get("environment"):
        errors.append("Python 与依赖环境和冻结环境报告不一致")

    if inventory["stable_inventory_sha256"] != lock.get(
        "stable_inventory_sha256"
    ):
        errors.append("稳定资产清单总摘要不一致")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
        help="仓库根目录，默认从脚本位置解析。",
    )
    parser.add_argument(
        "--include-records",
        action="store_true",
        help="在输出中包含每个文件的相对路径、字节数和 SHA-256。",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="验证指定的冻结清单；只读，不改写清单。",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="输出紧凑 JSON。",
    )
    args = parser.parse_args(argv)

    inventory = build_inventory(
        args.repo_root,
        include_records=args.include_records,
    )
    if args.verify:
        lock = json.loads(args.verify.read_text(encoding="utf-8"))
        errors = verify_lock(inventory, lock)
        result = {
            "verified": not errors,
            "errors": errors,
            "stable_inventory_sha256": inventory["stable_inventory_sha256"],
        }
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                indent=None if args.compact else 2,
            )
        )
        return 0 if not errors else 1

    print(
        json.dumps(
            inventory,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
