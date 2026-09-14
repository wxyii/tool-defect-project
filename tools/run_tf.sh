#!/usr/bin/env bash
set -euo pipefail

# 服务器 TensorFlow 2.13 使用 pip 环境中的 cuDNN 8.6。不要让系统
# /usr/local/cuda-11.2 下的旧版 libcudnn 抢先被动态链接器加载。
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_PYTHON="${TOOL_DEFECT_PYTHON:-/data2/dataset/cgp/miniconda3/envs/tf_311/bin/python}"
TF_SITE_PACKAGES="$(dirname "$(dirname "$TF_PYTHON")")/lib/python3.11/site-packages"
CUDA_LIB_DIRS=(
  "$TF_SITE_PACKAGES/nvidia/cudnn/lib"
  "$TF_SITE_PACKAGES/nvidia/cublas/lib"
)

for directory in "${CUDA_LIB_DIRS[@]}"; do
  if [[ ! -d "$directory" ]]; then
    echo "缺少 TensorFlow GPU 运行库目录：$directory" >&2
    exit 2
  fi
done

CUDA_LIBRARY_PATH="$(IFS=:; echo "${CUDA_LIB_DIRS[*]}")"
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
  CUDA_LIBRARY_PATH="$CUDA_LIBRARY_PATH:$LD_LIBRARY_PATH"
fi

export LD_LIBRARY_PATH="$CUDA_LIBRARY_PATH"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$TF_PYTHON" "$@"
