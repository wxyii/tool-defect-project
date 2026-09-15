#!/usr/bin/env bash
set -Eeuo pipefail

# 使用恢复后的旧训练逻辑，重新训练边界归一化整图和八分块两组实验。
# 训练和父图级测试由 tools/run_multitask_suite.py 完成；本脚本只负责
# 备份、调度、结果归档，不修改旧训练代码。

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PYTHON="/data2/dataset/cgp/miniconda3/envs/tf_311/bin/python"
RUN_ID="two_boundary_$(date +%Y%m%d_%H%M%S)"
GPUS="0,1"
PYTHON_EXECUTABLE="$DEFAULT_PYTHON"

usage() {
    cat <<'EOF'
用法：
  bash tools/run_two_boundary_experiments.sh [选项]

选项：
  --run-id ID       本次实验编号，只允许字母、数字、下划线、短横线和点
  --gpus A,B        两张显卡编号，默认 0,1
  --python PATH     Python 可执行文件，默认服务器 tf_311 环境
  -h, --help        显示帮助
EOF
}

while (($#)); do
    case "$1" in
        --run-id)
            [[ $# -ge 2 ]] || { echo "--run-id 缺少参数" >&2; exit 2; }
            RUN_ID="$2"
            shift 2
            ;;
        --gpus)
            [[ $# -ge 2 ]] || { echo "--gpus 缺少参数" >&2; exit 2; }
            GPUS="$2"
            shift 2
            ;;
        --python)
            [[ $# -ge 2 ]] || { echo "--python 缺少参数" >&2; exit 2; }
            PYTHON_EXECUTABLE="$2"
            shift 2
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

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "run-id 含有不允许的字符：$RUN_ID" >&2
    exit 2
fi

IFS=',' read -r GPU_A GPU_B GPU_EXTRA <<< "$GPUS"
if [[ -n "${GPU_EXTRA:-}" || -z "${GPU_A:-}" || -z "${GPU_B:-}" ]]; then
    echo "本脚本必须指定恰好两张显卡，例如 --gpus 0,1" >&2
    exit 2
fi
if [[ ! "$GPU_A" =~ ^[0-9]+$ || ! "$GPU_B" =~ ^[0-9]+$ ]]; then
    echo "显卡编号必须是非负整数：$GPUS" >&2
    exit 2
fi
if [[ "$GPU_A" == "$GPU_B" ]]; then
    echo "两组实验必须使用不同显卡：$GPUS" >&2
    exit 2
fi

RUN_ROOT="$PROJECT_ROOT/outputs/multitask_two/$RUN_ID"
BACKUP_ROOT="$RUN_ROOT/original_artifacts"

if [[ -e "$RUN_ROOT" ]]; then
    echo "结果目录已存在，为避免覆盖原实验，停止：$RUN_ROOT" >&2
    exit 1
fi
if [[ ! -x "$PYTHON_EXECUTABLE" ]]; then
    echo "Python 不存在或不可执行：$PYTHON_EXECUTABLE" >&2
    exit 1
fi

# TensorFlow 2.13 需要 cuDNN 8.6；服务器系统路径中的 cuDNN 8.0.1
# 会被优先加载，因此让 tf_311 环境自带的 NVIDIA 库优先。
PYTHON_SITE_PACKAGES="$($PYTHON_EXECUTABLE -c 'import site; print(site.getsitepackages()[0])')"
CUDA_LIBRARY_PATHS=()
for package in cudnn cublas cuda_runtime cufft curand cusolver cusparse nvjitlink; do
    library_path="$PYTHON_SITE_PACKAGES/nvidia/$package/lib"
    if [[ -d "$library_path" ]]; then
        CUDA_LIBRARY_PATHS+=("$library_path")
    fi
done
if ((${#CUDA_LIBRARY_PATHS[@]})); then
    CUDA_LIBRARY_PATHS_TEXT="$(IFS=:; echo "${CUDA_LIBRARY_PATHS[*]}")"
    export LD_LIBRARY_PATH="$CUDA_LIBRARY_PATHS_TEXT${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

declare -a DATASET_IDS=(boundary_normalized boundary_normalized_8patch)
declare -a CONFIGS=(
    "$PROJECT_ROOT/configs/multitask_boundary_normalized.json"
    "$PROJECT_ROOT/configs/multitask_boundary_normalized_8patch.json"
)
declare -a ARTIFACTS=(
    "$PROJECT_ROOT/artifacts/multitask_suite/boundary_normalized"
    "$PROJECT_ROOT/artifacts/multitask_suite/boundary_normalized_8patch"
)

for config in "${CONFIGS[@]}"; do
    [[ -f "$config" ]] || { echo "配置不存在：$config" >&2; exit 1; }
done
[[ -f "$PROJECT_ROOT/tools/run_multitask_suite.py" ]] || {
    echo "五组实验入口不存在：$PROJECT_ROOT/tools/run_multitask_suite.py" >&2
    exit 1
}

mkdir -p "$BACKUP_ROOT"
printf '实验编号：%s\n显卡：%s\n训练逻辑：恢复后的 9 月 1 日五组实验逻辑\n' \
    "$RUN_ID" "$GPUS" > "$RUN_ROOT/run_info.txt"

restore_if_needed() {
    local status=$?
    if ((status != 0)); then
        for index in 0 1; do
            local artifact="${ARTIFACTS[$index]}"
            local backup="$BACKUP_ROOT/${DATASET_IDS[$index]}"
            local failed="$RUN_ROOT/failed_artifacts/${DATASET_IDS[$index]}"
            if [[ -e "$artifact" && ! -f "$artifact/model.json" || \
                -e "$artifact" && ! -f "$artifact/weights.h5" ]]; then
                mkdir -p "$(dirname "$failed")"
                mv -- "$artifact" "$failed"
            fi
            if [[ ! -e "$artifact" && -e "$backup" ]]; then
                mv -- "$backup" "$artifact"
                echo "训练失败，已恢复原权重：$artifact" >&2
            fi
        done
    fi
    exit "$status"
}
trap restore_if_needed EXIT

for index in 0 1; do
    artifact="${ARTIFACTS[$index]}"
    backup="$BACKUP_ROOT/${DATASET_IDS[$index]}"
    if [[ -e "$artifact" ]]; then
        mv -- "$artifact" "$backup"
        echo "已备份原权重：$backup"
    else
        echo "原权重不存在，将直接训练：$artifact"
    fi
done

echo "开始两组并行训练和父图级测试，结果目录：$RUN_ROOT"
"$PYTHON_EXECUTABLE" "$PROJECT_ROOT/tools/run_multitask_suite.py" \
    --project-root "$PROJECT_ROOT" \
    --output-root "$RUN_ROOT" \
    --gpus "$GPUS" \
    --max-workers 2 \
    --split test \
    --seg-threshold 0.5 \
    --python-executable "$PYTHON_EXECUTABLE"

for index in 0 1; do
    dataset_id="${DATASET_IDS[$index]}"
    artifact="${ARTIFACTS[$index]}"
    result_dir="$RUN_ROOT/$dataset_id"
    [[ -f "$artifact/model.json" && -f "$artifact/weights.h5" ]] || {
        echo "训练完成但权重不完整：$artifact" >&2
        exit 1
    }
    [[ -f "$result_dir/metrics.json" && -f "$result_dir/predictions.csv" ]] || {
        echo "测试结果不完整：$result_dir" >&2
        exit 1
    }
    mkdir -p "$result_dir/weights"
    cp -- "$artifact/model.json" "$artifact/weights.h5" "$result_dir/weights/"
    echo "${dataset_id}：权重、日志和测试结果已归档到 $result_dir"
done

echo "两组实验完成。"
echo "父图级汇总：$RUN_ROOT/suite_metrics.json"
echo "原权重备份：$BACKUP_ROOT"
