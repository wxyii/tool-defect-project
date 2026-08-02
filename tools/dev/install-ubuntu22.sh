#!/usr/bin/env bash

# Ubuntu LTS 一键开发环境安装器（20.04 / 22.04 / 24.04 / 26.04）。
#
# 安装范围：系统工具、Docker Engine/Compose、Java 25、Node.js 20.13.1、
# pnpm 10.34.5、uv、项目 Python 3.11 虚拟环境、Python/TypeScript 依赖。
# 不生成生产配置、不写入仓库内密钥、不启动开发服务。

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly NODE_VERSION="20.13.1"
readonly PNPM_VERSION="10.34.5"
readonly JAVA_MAJOR="25"
readonly PYTHON_MINOR="3.11"

UBUNTU_VERSION=""
UBUNTU_CODENAME=""
IS_WSL=0
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME=""
DOCKER_GROUP_CHANGED=0
TEMP_DIR=""

log() {
  printf '[install] %s\n' "$*"
}

warn() {
  printf '[install][WARN] %s\n' "$*" >&2
}

die() {
  printf '[install][ERROR] %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
    rm -rf -- "${TEMP_DIR}"
  fi
}
trap cleanup EXIT

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

as_user() {
  if [[ "${EUID}" -eq 0 && "${TARGET_USER}" != "root" ]]; then
    runuser -u "${TARGET_USER}" -- env \
      HOME="${TARGET_HOME}" \
      PATH="/usr/local/bin:/usr/bin:/bin" \
      "$@"
  else
    "$@"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"
}

check_ubuntu() {
  [[ -r /etc/os-release ]] || die "无法读取 /etc/os-release"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "仅支持 Ubuntu，当前系统：${ID:-unknown}"
  local expected_codename
  case "${VERSION_ID:-}" in
    20.04) expected_codename="focal" ;;
    22.04) expected_codename="jammy" ;;
    24.04) expected_codename="noble" ;;
    26.04) expected_codename="resolute" ;;
    *) die "仅支持 Ubuntu 20.04、22.04、24.04 或 26.04，当前版本：${VERSION_ID:-unknown}" ;;
  esac
  if [[ -n "${VERSION_CODENAME:-}" && "${VERSION_CODENAME}" != "${expected_codename}" ]]; then
    die "Ubuntu ${VERSION_ID} 的系统代号应为 ${expected_codename}，实际为 ${VERSION_CODENAME}"
  fi
  UBUNTU_VERSION="${VERSION_ID}"
  UBUNTU_CODENAME="${expected_codename}"
}

detect_wsl() {
  if grep -qi microsoft /proc/version 2>/dev/null \
    || grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    IS_WSL=1
  fi
}

resolve_target_user() {
  id "${TARGET_USER}" >/dev/null 2>&1 || die "找不到目标用户：${TARGET_USER}"
  TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
  [[ -n "${TARGET_HOME}" && -d "${TARGET_HOME}" ]] || die "无法解析用户目录：${TARGET_USER}"
  [[ "${TARGET_USER}" != "root" ]] || warn "当前按 root 用户安装用户级 Python/Node 缓存"
}

install_base_packages() {
  log "安装 Ubuntu 基础工具和 Python 构建依赖"
  export DEBIAN_FRONTEND=noninteractive
  as_root apt-get update
  as_root apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    gnupg \
    lsb-release \
    openssl \
    unzip \
    zip \
    make \
    build-essential \
    pkg-config \
    lsof \
    procps \
    jq \
    python3 \
    python3-venv \
    python3-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1
}

install_docker() {
  local architecture
  architecture="$(dpkg --print-architecture)"
  local docker_cli_ready=0
  if command -v docker >/dev/null 2>&1 \
    && docker compose version >/dev/null 2>&1; then
    docker_cli_ready=1
  fi

  if [[ "${IS_WSL}" -eq 1 ]]; then
    if [[ "${docker_cli_ready}" -ne 1 ]]; then
      die "检测到 WSL，但 Docker CLI/Compose 不可用；请在 Docker Desktop 中开启 Settings > Resources > WSL Integration 后重试。不会在 WSL 内安装第二套 Docker Engine。"
    fi
    log "检测到 WSL，复用 Docker Desktop，不安装 WSL 内部 Docker Engine"
    docker info >/dev/null \
      || die "Docker CLI/Compose 已存在，但 Docker Desktop 未运行或未向当前发行版开放 WSL 集成"
    return
  fi

  log "安装 Docker Engine 和 Compose 插件"

  if [[ "${docker_cli_ready}" -ne 1 ]]; then
    as_root install -m 0755 -d /etc/apt/keyrings
    local docker_key="${TEMP_DIR}/docker.asc"
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "${docker_key}"
    as_root gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg "${docker_key}"
    as_root chmod a+r /etc/apt/keyrings/docker.gpg
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
      "${architecture}" "${UBUNTU_CODENAME}" \
      | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    as_root apt-get update
    as_root apt-get install -y --no-install-recommends \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi

  if command -v systemctl >/dev/null 2>&1; then
    as_root systemctl enable --now docker
  fi
  local had_docker_group=0
  if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx docker; then
    had_docker_group=1
  fi
  as_root usermod -aG docker "${TARGET_USER}"
  if [[ "${had_docker_group}" -eq 0 ]]; then
    DOCKER_GROUP_CHANGED=1
  fi
  as_root docker info >/dev/null
  docker compose version >/dev/null 2>&1 || die "Docker Compose 插件不可用"
}

install_java() {
  log "安装 Java ${JAVA_MAJOR}（Temurin）"
  as_root install -m 0755 -d /etc/apt/keyrings
  local java_key="${TEMP_DIR}/adoptium.asc"
  curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public -o "${java_key}"
  as_root gpg --dearmor --yes -o /etc/apt/keyrings/adoptium.gpg "${java_key}"
  as_root chmod a+r /etc/apt/keyrings/adoptium.gpg
  printf 'deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb %s main\n' \
    "${UBUNTU_CODENAME}" | as_root tee /etc/apt/sources.list.d/adoptium.list >/dev/null
  as_root apt-get update
  as_root apt-get install -y --no-install-recommends temurin-25-jdk

  local java_home
  java_home="$(dpkg -L temurin-25-jdk | awk '/\/bin\/javac$/ {print; exit}')"
  [[ -n "${java_home}" ]] || die "无法从 temurin-25-jdk 软件包解析 javac"
  java_home="$(dirname "$(dirname "${java_home}")")"
  [[ -x "${java_home}/bin/java" ]] || die "Java ${JAVA_MAJOR} 安装后无法解析 JAVA_HOME"
  as_root update-alternatives --install /usr/bin/java java "${java_home}/bin/java" 2500
  as_root update-alternatives --install /usr/bin/javac javac "${java_home}/bin/javac" 2500
  as_root update-alternatives --set java "${java_home}/bin/java"
  as_root update-alternatives --set javac "${java_home}/bin/javac"
  as_root tee /etc/profile.d/tool-defect-java.sh >/dev/null <<EOF
export JAVA_HOME=${java_home}
export PATH=\"\${JAVA_HOME}/bin:\${PATH}\"
EOF

  [[ "$(java -version 2>&1 | head -n 1)" == *'"25.'* ]] \
    || die "Java 25 安装失败：$(java -version 2>&1 | head -n 1)"
  [[ "$(javac -version 2>&1)" == 25.* ]] \
    || die "javac 25 安装失败：$(javac -version 2>&1)"
}

install_node() {
  local node_arch
  case "$(uname -m)" in
    x86_64|amd64) node_arch="x64" ;;
    aarch64|arm64) node_arch="arm64" ;;
    *) die "Node.js ${NODE_VERSION} 不支持当前架构：$(uname -m)" ;;
  esac

  log "安装 Node.js ${NODE_VERSION}"
  local node_name="node-v${NODE_VERSION}-linux-${node_arch}"
  local node_tarball="${node_name}.tar.xz"
  local node_dir="/opt/${node_name}"
  local node_url="https://nodejs.org/dist/v${NODE_VERSION}/${node_tarball}"
  local checksums_url="https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt"
  local archive="${TEMP_DIR}/${node_tarball}"
  local checksums="${TEMP_DIR}/SHASUMS256.txt"

  if [[ ! -x "${node_dir}/bin/node" ]] \
    || [[ "$("${node_dir}/bin/node" --version 2>/dev/null || true)" != "v${NODE_VERSION}" ]]; then
    curl -fsSL "${node_url}" -o "${archive}"
    curl -fsSL "${checksums_url}" -o "${checksums}"
    local expected actual
    expected="$(awk -v name="${node_tarball}" '$2 == name {print $1; exit}' "${checksums}")"
    [[ "${expected}" =~ ^[[:xdigit:]]{64}$ ]] || die "无法读取 Node.js 安装包校验和"
    actual="$(sha256sum "${archive}" | awk '{print $1}')"
    [[ "${actual}" == "${expected}" ]] || die "Node.js 安装包 SHA-256 校验失败"
    as_root rm -rf -- "${node_dir}"
    as_root tar -xJf "${archive}" -C /opt
  fi

  local binary
  for binary in node npm npx corepack; do
    [[ -x "${node_dir}/bin/${binary}" ]] || die "Node.js 安装包缺少 ${binary}"
    as_root ln -sfn "${node_dir}/bin/${binary}" "/usr/local/bin/${binary}"
  done
  [[ "$(node --version)" == "v${NODE_VERSION}" ]] || die "Node.js 版本不匹配：$(node --version)"

  log "安装 pnpm ${PNPM_VERSION}"
  as_root /usr/local/bin/npm install --global --prefix /usr/local --no-fund --no-audit \
    "pnpm@${PNPM_VERSION}"
  [[ "$(pnpm --version)" == "${PNPM_VERSION}" ]] || die "pnpm 版本不匹配：$(pnpm --version)"
}

install_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    log "安装 uv"
    local uv_installer="${TEMP_DIR}/uv-install.sh"
    curl -fsSL https://astral.sh/uv/install.sh -o "${uv_installer}"
    as_root env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "${uv_installer}"
  fi
  command -v uv >/dev/null 2>&1 || die "uv 安装后仍不可用"
}

ensure_python_venv() {
  local venv_dir="$1"
  local python_bin="${venv_dir}/bin/python"
  if [[ -e "${venv_dir}" ]]; then
    if [[ ! -x "${python_bin}" ]] \
      || [[ "$(${python_bin} --version 2>/dev/null || true)" != "Python 3.11."* ]]; then
      local backup
      backup="${venv_dir}.backup.$(date +%Y%m%d%H%M%S)"
      mv -- "${venv_dir}" "${backup}"
      warn "发现非 Ubuntu/Python 3.11 虚拟环境，已可恢复地移到：${backup}"
    fi
  fi
  if [[ ! -x "${python_bin}" ]]; then
    as_user uv venv --python "${PYTHON_MINOR}" "${venv_dir}"
  fi
  [[ "$(${python_bin} --version)" == "Python 3.11."* ]] \
    || die "虚拟环境不是 Python 3.11：${venv_dir}"
}

prepare_python_environment() {
  log "创建项目 Python ${PYTHON_MINOR} 虚拟环境并安装隔离依赖"
  as_user uv python install "${PYTHON_MINOR}"

  local root_python="${PROJECT_ROOT}/.venv/bin/python"
  local edge_python="${PROJECT_ROOT}/apps/edge-agent/.venv/bin/python"
  local inference_python="${PROJECT_ROOT}/services/inference-service/.venv/bin/python"
  ensure_python_venv "${PROJECT_ROOT}/.venv"
  ensure_python_venv "${PROJECT_ROOT}/apps/edge-agent/.venv"
  ensure_python_venv "${PROJECT_ROOT}/services/inference-service/.venv"

  # 根环境服务核心测试和作业；边缘端/推理端源码以 no-deps 方式挂载，
  # 避免把两个运行时的互斥 Pillow 版本混在一起。
  as_user uv pip install --python "${root_python}" -r "${PROJECT_ROOT}/requirements-app.txt"
  as_user uv pip install --python "${root_python}" -r "${PROJECT_ROOT}/requirements/inference.lock"
  as_user uv pip install --python "${root_python}" --no-deps \
    -e "${PROJECT_ROOT}" \
    -e "${PROJECT_ROOT}/packages/python-contracts" \
    -e "${PROJECT_ROOT}/apps/edge-agent" \
    -e "${PROJECT_ROOT}/services/inference-service" \
    -e "${PROJECT_ROOT}/jobs/artifact-migrator"

  # 边缘端按 requirements/edge.lock 保留 Pillow 12.3.0 的独立运行时。
  as_user uv pip install --python "${edge_python}" --no-deps \
    -e "${PROJECT_ROOT}/packages/python-contracts"
  as_user uv pip install --python "${edge_python}" -r "${PROJECT_ROOT}/requirements/edge.lock"
  as_user uv pip install --python "${edge_python}" --no-deps \
    -e "${PROJECT_ROOT}/apps/edge-agent"

  # 推理端测试需要根算法依赖，但不应访问业务数据库；使用独立环境。
  as_user uv pip install --python "${inference_python}" -r "${PROJECT_ROOT}/requirements.txt"
  as_user uv pip install --python "${inference_python}" -r "${PROJECT_ROOT}/requirements/inference.lock"
  as_user uv pip install --python "${inference_python}" --no-deps \
    -e "${PROJECT_ROOT}" \
    -e "${PROJECT_ROOT}/services/inference-service"
}

prepare_javascript_dependencies() {
  log "安装 TypeScript 契约包和 Web 前端依赖"
  as_user pnpm --dir "${PROJECT_ROOT}/packages/typescript-contracts" install --frozen-lockfile
  as_user pnpm --dir "${PROJECT_ROOT}/apps/web-console" install --frozen-lockfile
}

make_wrappers_executable() {
  log "修复 Ubuntu 工作树中的脚本执行权限"
  chmod +x \
    "${PROJECT_ROOT}/services/business-api/mvnw" \
    "${PROJECT_ROOT}/tools/dev/start-all.sh" \
    "${PROJECT_ROOT}/tools/dev/install-ubuntu22.sh"
}

verify_installation() {
  log "验证精确版本和离线门禁"
  [[ "$(${PROJECT_ROOT}/.venv/bin/python --version)" == "Python 3.11."* ]] \
    || die "Python 3.11 验证失败"
  [[ "$(uv --version)" == uv\ .* ]] || die "uv 验证失败"
  [[ "$(make --version | head -n 1)" == GNU\ Make* ]] || die "GNU Make 验证失败"
  [[ "$(node --version)" == "v${NODE_VERSION}" ]] || die "Node.js 验证失败"
  [[ "$(pnpm --version)" == "${PNPM_VERSION}" ]] || die "pnpm 验证失败"
  [[ "$(java -version 2>&1 | head -n 1)" == *'"25.'* ]] || die "Java 25 验证失败"
  [[ "$(docker compose version)" == *'Docker Compose version 2.'* ]] \
    || die "Docker Compose 2 验证失败"

  as_user env MAVEN_USER_HOME="${PROJECT_ROOT}/.build/maven-user-home" \
    "${PROJECT_ROOT}/services/business-api/mvnw" --version
  as_user env MAVEN_USER_HOME="${PROJECT_ROOT}/.build/maven-user-home" \
    make -C "${PROJECT_ROOT}" check-environment
  as_user env MAVEN_USER_HOME="${PROJECT_ROOT}/.build/maven-user-home" \
    make -C "${PROJECT_ROOT}" verify-contracts-source
  as_user env MAVEN_USER_HOME="${PROJECT_ROOT}/.build/maven-user-home" \
    make -C "${PROJECT_ROOT}" verify-compose
}

main() {
  [[ "${EUID}" -eq 0 ]] || require_command sudo
  require_command id
  require_command getent
  if [[ "${EUID}" -eq 0 && "${TARGET_USER}" != "root" ]]; then
    require_command runuser
  fi
  check_ubuntu
  detect_wsl
  log "检测到 Ubuntu ${UBUNTU_VERSION}（${UBUNTU_CODENAME}），使用匹配的软件源"
  if [[ "${IS_WSL}" -eq 1 ]]; then
    log "检测到 WSL 环境"
  fi
  resolve_target_user
  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tool-defect-install.XXXXXXXX")"

  install_base_packages
  install_docker
  install_java
  install_node
  install_uv
  make_wrappers_executable
  prepare_python_environment
  prepare_javascript_dependencies
  verify_installation

  log "安装完成：契约版本 v1，Python/Java/TypeScript 依赖已准备"
  if [[ "${DOCKER_GROUP_CHANGED}" -eq 1 ]]; then
    warn "已将 ${TARGET_USER} 加入 docker 组；请退出当前会话并重新登录后再运行 docker 命令"
  fi
  log "启动本地开发服务：./tools/dev/start-all.sh"
  log "严格门禁（需要 Docker、服务和完整工具链）：make verify-p1-strict"
}

main "$@"
