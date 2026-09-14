#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
用法：
  bash tools/run_four_experiments.sh [选项]

选项：
  --run-id ID       实验批次编号，默认 four_YYYYMMDD_HHMMSS
  --gpu ID          使用的服务器显卡编号，默认 0
  --output-root DIR 权重输出根目录，默认 artifacts/four_group/<run-id>
  --result-root DIR 测试结果目录，默认 outputs/four_group/<run-id>
  --preflight-only  只做检查，不训练、不测试
  -h, --help        显示帮助
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_TF="$SCRIPT_DIR/run_tf.sh"

RUN_ID="four_$(date +%Y%m%d_%H%M%S)"
GPU_ID="0"
OUTPUT_ROOT=""
RESULT_ROOT=""
PREFLIGHT_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      [[ $# -ge 2 ]] || { echo "--run-id 缺少参数" >&2; exit 2; }
      RUN_ID="$2"
      shift 2
      ;;
    --gpu)
      [[ $# -ge 2 ]] || { echo "--gpu 缺少参数" >&2; exit 2; }
      GPU_ID="$2"
      shift 2
      ;;
    --output-root)
      [[ $# -ge 2 ]] || { echo "--output-root 缺少参数" >&2; exit 2; }
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --result-root)
      [[ $# -ge 2 ]] || { echo "--result-root 缺少参数" >&2; exit 2; }
      RESULT_ROOT="$2"
      shift 2
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$RUN_ID" == */* || "$RUN_ID" == *"\\"* || -z "$RUN_ID" ]]; then
  echo "--run-id 只能是单个目录名：$RUN_ID" >&2
  exit 2
fi
if ! [[ "$GPU_ID" =~ ^[0-9]+$ ]]; then
  echo "--gpu 必须是非负整数：$GPU_ID" >&2
  exit 2
fi

make_absolute() {
  local value="$1"
  if [[ "$value" = /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$PROJECT_ROOT" "$value"
  fi
}

if [[ -z "$OUTPUT_ROOT" ]]; then
  OUTPUT_ROOT="$PROJECT_ROOT/artifacts/four_group/$RUN_ID"
else
  OUTPUT_ROOT="$(make_absolute "$OUTPUT_ROOT")"
fi
if [[ -z "$RESULT_ROOT" ]]; then
  RESULT_ROOT="$PROJECT_ROOT/outputs/four_group/$RUN_ID"
else
  RESULT_ROOT="$(make_absolute "$RESULT_ROOT")"
fi

CONFIG_A_WHOLE="$PROJECT_ROOT/configs/multitask_boundary_normalized.json"
CONFIG_A_PATCH="$PROJECT_ROOT/configs/multitask_boundary_normalized_8patch.json"
CONFIG_B_WHOLE="$PROJECT_ROOT/configs/train_multitask_source_boundary_normalized.json"
CONFIG_B_PATCH="$PROJECT_ROOT/configs/train_multitask_source_boundary_normalized_8patch.json"
PARENT_DATA="$PROJECT_ROOT/data/processed/boundary_normalized"
IMAGENET_WEIGHTS="$PROJECT_ROOT/artifacts/pretrained/xception/xception_weights_tf_dim_ordering_tf_kernels_notop.h5"

A_WHOLE="$OUTPUT_ROOT/A_boundary_normalized"
A_PATCH="$OUTPUT_ROOT/A_boundary_normalized_8patch"
B_WHOLE="$OUTPUT_ROOT/B_boundary_normalized"
B_PATCH="$OUTPUT_ROOT/B_boundary_normalized_8patch"

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "缺少文件：$path" >&2
    exit 1
  fi
}

require_directory() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    echo "缺少目录：$path" >&2
    exit 1
  fi
}

echo "开始预检查"
require_file "$RUN_TF"
require_file "$SCRIPT_DIR/gpu_preflight.py"
require_file "$CONFIG_A_WHOLE"
require_file "$CONFIG_A_PATCH"
require_file "$CONFIG_B_WHOLE"
require_file "$CONFIG_B_PATCH"
require_file "$IMAGENET_WEIGHTS"
require_directory "$PARENT_DATA"
require_file "$PARENT_DATA/manifests/dataset.csv"
require_file "$PARENT_DATA/manifests/provenance.csv"
require_directory "$PROJECT_ROOT/data/processed/boundary_normalized_8patch"
require_file "$PROJECT_ROOT/data/processed/boundary_normalized_8patch/manifests/dataset.csv"
require_file "$PROJECT_ROOT/data/processed/boundary_normalized_8patch/manifests/provenance.csv"

"$RUN_TF" - "$PROJECT_ROOT" "$CONFIG_B_WHOLE" "$CONFIG_B_PATCH" <<'PY'
import csv
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
config_paths = [Path(sys.argv[2]), Path(sys.argv[3])]

def load_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))

whole_config = json.loads(config_paths[0].read_text(encoding="utf-8"))
patch_config = json.loads(config_paths[1].read_text(encoding="utf-8"))
whole_data = (project_root / whole_config["paths"]["data"]).resolve()
patch_data = (project_root / patch_config["paths"]["data"]).resolve()
whole_rows = load_rows(project_root / whole_config["paths"]["manifest"])
patch_rows = load_rows(project_root / patch_config["paths"]["manifest"])
whole_test = [row for row in whole_rows if row["split"] == "test"]
patch_test = [row for row in patch_rows if row["split"] == "test"]
provenance_path = patch_data / "manifests" / "provenance.csv"
provenance_test = [
    row for row in load_rows(provenance_path) if row["split"] == "test"
]
parent_ids = {row["parent_sample_id"] for row in provenance_test}
whole_ids = {row["sample_id"] for row in whole_test}
if parent_ids != whole_ids:
    raise SystemExit(
        "完整图与八分块测试父图集合不一致："
        f"完整图缺少 {sorted(parent_ids - whole_ids)[:3]}，"
        f"八分块缺少 {sorted(whole_ids - parent_ids)[:3]}"
    )
if not whole_test or not patch_test or not parent_ids:
    raise SystemExit("测试清单为空，无法执行对照实验")
print(
    "数据预检查通过："
    f"完整图 train/validation/test={sum(r['split']=='train' for r in whole_rows)}/"
    f"{sum(r['split']=='validation' for r in whole_rows)}/{len(whole_test)}；"
    f"八分块 train/validation/test={sum(r['split']=='train' for r in patch_rows)}/"
    f"{sum(r['split']=='validation' for r in patch_rows)}/{len(patch_test)}；"
    f"测试父图={len(parent_ids)}"
)
PY

echo "检查 GPU 和 CuDNN"
CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" "$SCRIPT_DIR/gpu_preflight.py"

for directory in "$A_WHOLE" "$A_PATCH" "$B_WHOLE" "$B_PATCH" "$RESULT_ROOT"; do
  if [[ -e "$directory" ]]; then
    echo "目标目录已存在，为避免覆盖已有实验而停止：$directory" >&2
    exit 1
  fi
done

if [[ "$PREFLIGHT_ONLY" == "1" ]]; then
  echo "预检查完成，未启动训练和测试。"
  exit 0
fi

mkdir -p "$OUTPUT_ROOT/logs"

run_logged() {
  local name="$1"
  shift
  local log_path="$OUTPUT_ROOT/logs/${name}.log"
  echo
  echo "========== 开始：$name =========="
  echo "日志：$log_path"
  {
    echo "开始时间：$(date --iso-8601=seconds)"
    echo "命令：$*"
    "$@"
    echo "结束时间：$(date --iso-8601=seconds)"
  } 2>&1 | tee "$log_path"
  echo "========== 完成：$name =========="
}

verify_artifact() {
  local name="$1"
  local directory="$2"
  local required=(
    model.json
    weights_best_classification.h5
    weights_last.h5
    weights.h5
    weight_selection.json
  )
  for file in "${required[@]}"; do
    require_file "$directory/$file"
  done
  echo "${name} 权重检查通过：$directory"
}

echo "实验批次：$RUN_ID"
echo "权重目录：$OUTPUT_ROOT"
echo "测试目录：$RESULT_ROOT"
echo "使用显卡：$GPU_ID"

run_logged "A_boundary_normalized" \
  env CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" -m tool_defect.cli train \
  --task multitask \
  --config "$CONFIG_A_WHOLE" \
  --backbone-weights none \
  --output "$A_WHOLE"
verify_artifact "甲组完整图" "$A_WHOLE"

run_logged "A_boundary_normalized_8patch" \
  env CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" -m tool_defect.cli train \
  --task multitask \
  --config "$CONFIG_A_PATCH" \
  --backbone-weights none \
  --output "$A_PATCH"
verify_artifact "甲组八分块" "$A_PATCH"

run_logged "B_boundary_normalized" \
  env CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" -m tool_defect.cli train-multitask-source \
  --config "$CONFIG_B_WHOLE" \
  --output-root "$OUTPUT_ROOT" \
  --run-id "$(basename "$B_WHOLE")"
verify_artifact "乙组完整图" "$B_WHOLE"

run_logged "B_boundary_normalized_8patch" \
  env CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" -m tool_defect.cli train-multitask-source \
  --config "$CONFIG_B_PATCH" \
  --output-root "$OUTPUT_ROOT" \
  --run-id "$(basename "$B_PATCH")"
verify_artifact "乙组八分块" "$B_PATCH"

mkdir -p "$RESULT_ROOT"
run_logged "parent_level_test" \
  env CUDA_VISIBLE_DEVICES="$GPU_ID" "$RUN_TF" -m tool_defect.cli compare-four-multitask \
  --whole-config "$CONFIG_B_WHOLE" \
  --whole-a "$A_WHOLE" \
  --whole-b "$B_WHOLE" \
  --patch-config "$CONFIG_B_PATCH" \
  --patch-a "$A_PATCH" \
  --patch-b "$B_PATCH" \
  --patch-parent-data "$PARENT_DATA" \
  --split test \
  --threshold 0.5 \
  --output "$RESULT_ROOT"

require_file "$RESULT_ROOT/four_group_metrics.json"
require_file "$RESULT_ROOT/FOUR_GROUP_REPORT.md"
echo
echo "四组训练和父图级测试全部完成。"
echo "权重目录：$OUTPUT_ROOT"
echo "测试结果：$RESULT_ROOT"
echo "对比报告：$RESULT_ROOT/FOUR_GROUP_REPORT.md"
