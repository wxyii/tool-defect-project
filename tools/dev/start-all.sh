#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/deploy/compose/development.yml"
COMPOSE_OVERRIDE_FILE="${PROJECT_ROOT}/deploy/compose/development.start-all.override.yml"
RUNTIME_DIR="${PROJECT_ROOT}/.build/dev-runtime"
DEFAULT_CONFIG_ROOT="${XDG_CONFIG_HOME:-${HOME:?未设置 HOME}/.config}"
ENV_FILE="${TOOL_DEFECT_ENV_FILE:-${DEFAULT_CONFIG_ROOT}/tool-defect/development.env}"

ACTION="start"
DETACH=0
STARTED_BACKEND=0
STARTED_FRONTEND=0
STARTED_COMPOSE=0
COMPOSE_WAS_EMPTY=0
NODE_COMMAND=""
PNPM_COMMAND=()

usage() {
  cat <<'EOF'
用法：
  ./tools/dev/start-all.sh [start] [--env-file 路径] [--detach]
  ./tools/dev/start-all.sh stop [--env-file 路径]
  ./tools/dev/start-all.sh status [--env-file 路径]
  ./tools/dev/start-all.sh logs [--env-file 路径]

默认动作是 start。首次启动会在仓库外生成随机开发密钥文件。
start 默认持续守护服务，按 Ctrl+C 后统一停止。仅在确认终端不会清理子进程时，
才使用 --detach 让脚本启动后立即返回。

可选环境变量：
  TOOL_DEFECT_ENV_FILE   开发密钥文件路径
  TOOL_DEFECT_NODE       Node.js 20.13.1 可执行文件
  TOOL_DEFECT_PNPM       pnpm 10.34.5 可执行文件或 pnpm.cjs
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

warn() {
  printf '[%s] 警告：%s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

die() {
  printf '[%s] 失败：%s\n' "$(date '+%H:%M:%S')" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"
}

compose() {
  docker compose \
    --progress quiet \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    -f "${COMPOSE_OVERRIDE_FILE}" \
    "$@"
}

random_secret() {
  openssl rand -hex "${1:-24}"
}

ensure_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    require_command openssl
    local env_dir
    env_dir="$(dirname "${ENV_FILE}")"
    umask 077
    mkdir -p "${env_dir}"
    {
      printf 'POSTGRES_PASSWORD=%s\n' "$(random_secret 24)"
      printf 'RABBITMQ_PASSWORD=%s\n' "$(random_secret 24)"
      printf 'MINIO_ROOT_USER=td_%s\n' "$(random_secret 8)"
      printf 'MINIO_ROOT_PASSWORD=%s\n' "$(random_secret 24)"
      printf 'GRAFANA_ADMIN_USER=td_%s\n' "$(random_secret 8)"
      printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(random_secret 24)"
    } >"${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log "已生成随机开发密钥：${ENV_FILE}"
  else
    chmod 600 "${ENV_FILE}"
  fi
}

read_env_value() {
  local key="$1"
  local value
  value="$(
    awk -v requested_key="${key}" '
      index($0, requested_key "=") == 1 {
        result = substr($0, length(requested_key) + 2)
      }
      END {
        printf "%s", result
      }
    ' "${ENV_FILE}"
  )"
  [[ -n "${value}" ]] || die "密钥文件缺少非空变量：${key}"
  [[ "${value}" != *$'\r'* && "${value}" != *$'\n'* ]] \
    || die "密钥变量包含非法换行：${key}"
  printf '%s' "${value}"
}

validate_env_file() {
  local key
  for key in \
    POSTGRES_PASSWORD \
    RABBITMQ_PASSWORD \
    MINIO_ROOT_USER \
    MINIO_ROOT_PASSWORD \
    GRAFANA_ADMIN_USER \
    GRAFANA_ADMIN_PASSWORD
  do
    read_env_value "${key}" >/dev/null
  done
}

find_node() {
  local candidate
  local candidates=()
  if [[ -n "${TOOL_DEFECT_NODE:-}" ]]; then
    candidates+=("${TOOL_DEFECT_NODE}")
  fi
  if command -v node >/dev/null 2>&1; then
    candidates+=("$(command -v node)")
  fi
  candidates+=("/usr/local/bin/node" "/opt/homebrew/bin/node")
  for candidate in "${HOME}"/.nvm/versions/node/*/bin/node; do
    candidates+=("${candidate}")
  done

  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]] \
      && [[ "$("${candidate}" --version 2>/dev/null || true)" == "v20.13.1" ]]
    then
      NODE_COMMAND="${candidate}"
      return
    fi
  done
  die "未找到 Node.js 20.13.1；可用 TOOL_DEFECT_NODE 显式指定"
}

find_cached_pnpm() {
  "${PROJECT_ROOT}/.venv/bin/python" - <<'PY'
import json
from pathlib import Path

for metadata in sorted(
    (Path.home() / ".npm" / "_npx").glob(
        "*/node_modules/pnpm/package.json"
    )
):
    try:
        package = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if package.get("version") != "10.34.5":
        continue
    candidate = metadata.parent / "bin" / "pnpm.cjs"
    if candidate.is_file():
        print(candidate)
        break
PY
}

find_pnpm() {
  local candidate=""
  if [[ -n "${TOOL_DEFECT_PNPM:-}" ]]; then
    candidate="${TOOL_DEFECT_PNPM}"
  elif command -v pnpm >/dev/null 2>&1 \
    && [[ "$(pnpm --version 2>/dev/null || true)" == "10.34.5" ]]
  then
    candidate="$(command -v pnpm)"
  else
    candidate="$(find_cached_pnpm)"
  fi

  [[ -n "${candidate}" && -f "${candidate}" ]] \
    || die "未找到 pnpm 10.34.5；请安装该精确版本或设置 TOOL_DEFECT_PNPM"

  case "${candidate}" in
    *.cjs|*.mjs|*.js)
      PNPM_COMMAND=("${NODE_COMMAND}" "${candidate}")
      ;;
    *)
      PNPM_COMMAND=("${candidate}")
      ;;
  esac

  [[ "$("${PNPM_COMMAND[@]}" --version 2>/dev/null || true)" == "10.34.5" ]] \
    || die "pnpm 版本不是项目要求的 10.34.5"
}

check_prerequisites() {
  require_command awk
  require_command curl
  require_command docker
  require_command java
  require_command lsof
  require_command pgrep
  [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]] \
    || die "缺少项目 Python 3.11 虚拟环境：.venv/bin/python"
  [[ -x "${PROJECT_ROOT}/services/business-api/mvnw" ]] \
    || die "缺少业务后端 Maven Wrapper"
  [[ "$(java -version 2>&1 | head -n 1)" == *'"25.'* ]] \
    || die "业务后端要求 Java 25"
  docker info >/dev/null 2>&1 || die "Docker 守护进程未运行或不可访问"
  find_node
  find_pnpm
}

pid_is_running() {
  local pid_file="$1"
  [[ -f "${pid_file}" ]] || return 1
  local pid
  pid="$(tr -cd '0-9' <"${pid_file}")"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

port_is_listening() {
  local port="$1"
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local pid_file="${4:-}"
  local elapsed=0

  while (( elapsed < timeout )); do
    if curl --silent --show-error --fail \
      --noproxy '*' \
      --connect-timeout 2 --max-time 3 "${url}" >/dev/null 2>&1
    then
      log "${name}已就绪：${url}"
      return
    fi
    if [[ -n "${pid_file}" ]] && ! pid_is_running "${pid_file}"; then
      return 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

wait_for_container() {
  local service="$1"
  local timeout="$2"
  local elapsed=0
  local container_id=""
  local state=""

  while (( elapsed < timeout )); do
    container_id="$(compose ps -a -q "${service}" 2>/dev/null || true)"
    if [[ -n "${container_id}" ]]; then
      state="$(
        docker inspect \
          --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
          "${container_id}" 2>/dev/null || true
      )"
      if [[ "${state}" == "healthy" || "${state}" == "running" ]]; then
        log "容器已就绪：${service}（${state}）"
        return
      fi
      if [[ "${state}" == "unhealthy" || "${state}" == "exited" || "${state}" == "dead" ]]; then
        return 1
      fi
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

sync_postgres_password() {
  local container_id
  local postgres_password
  container_id="$(compose ps -q postgres)"
  postgres_password="$(read_env_value POSTGRES_PASSWORD)"
  [[ -n "${container_id}" ]] || die "无法定位 PostgreSQL 容器"

  log "同步数据库开发账号密码"
  if ! {
    printf '%s\n' "${postgres_password}"
    cat <<'SQL'
\getenv synchronized_credential TOOL_DEFECT_SYNCHRONIZED_PASSWORD
ALTER ROLE tool_defect WITH PASSWORD /* injected credential */ :'synchronized_credential';
SQL
  } | docker exec \
    --interactive \
    --user postgres \
    "${container_id}" \
    sh -c '
      IFS= read -r TOOL_DEFECT_SYNCHRONIZED_PASSWORD
      export TOOL_DEFECT_SYNCHRONIZED_PASSWORD
      exec psql \
        --username tool_defect \
        --dbname tool_defect \
        --set ON_ERROR_STOP=1
    ' >/dev/null
  then
    die "数据库开发账号密码同步失败"
  fi
}

sync_rabbitmq_password() {
  local container_id
  local rabbitmq_password
  container_id="$(compose ps -q rabbitmq)"
  rabbitmq_password="$(read_env_value RABBITMQ_PASSWORD)"
  [[ -n "${container_id}" ]] || die "无法定位 RabbitMQ 容器"

  log "同步消息队列开发账号密码"
  if ! printf '%s\n' "${rabbitmq_password}" \
    | docker exec \
      --interactive \
      "${container_id}" \
      sh -c '
        IFS= read -r TOOL_DEFECT_SYNCHRONIZED_PASSWORD
        exec rabbitmqctl change_password \
          tool_defect \
          "${TOOL_DEFECT_SYNCHRONIZED_PASSWORD}"
      ' >/dev/null
  then
    die "消息队列开发账号密码同步失败"
  fi
}

show_log_tail() {
  local log_file="$1"
  if [[ -f "${log_file}" ]]; then
    printf '\n最近日志：%s\n' "${log_file}" >&2
    tail -n 80 "${log_file}" >&2
  fi
}

start_infrastructure() {
  local existing
  existing="$(compose ps -q 2>/dev/null || true)"
  if [[ -z "${existing}" ]]; then
    COMPOSE_WAS_EMPTY=1
  fi

  log "启动开发基础设施"
  compose up -d
  STARTED_COMPOSE=1

  local service
  for service in postgres rabbitmq object-storage telemetry prometheus grafana loki tempo; do
    if ! wait_for_container "${service}" 120; then
      compose ps >&2 || true
      compose logs --tail 80 "${service}" >&2 || true
      die "容器未就绪：${service}"
    fi
  done

  sync_postgres_password
  sync_rabbitmq_password

  wait_for_url \
    "Prometheus" \
    "http://127.0.0.1:9090/-/ready" \
    60 \
    || die "Prometheus 就绪检查失败"
  wait_for_url \
    "Grafana" \
    "http://127.0.0.1:3000/api/health" \
    60 \
    || die "Grafana 就绪检查失败"
  wait_for_url \
    "Loki" \
    "http://127.0.0.1:3100/ready" \
    120 \
    || die "Loki 就绪检查失败"
  wait_for_url \
    "Tempo" \
    "http://127.0.0.1:3200/ready" \
    120 \
    || die "Tempo 就绪检查失败"
}

start_backend() {
  local pid_file="${RUNTIME_DIR}/business-api.pid"
  local log_file="${RUNTIME_DIR}/business-api.log"

  if pid_is_running "${pid_file}"; then
    log "业务后端已由本脚本启动"
  else
    if port_is_listening 8080 || port_is_listening 9091; then
      die "端口 8080 或 9091 已被脚本外的进程占用"
    fi

    local postgres_password
    local rabbitmq_password
    local minio_user
    local minio_password
    postgres_password="$(read_env_value POSTGRES_PASSWORD)"
    rabbitmq_password="$(read_env_value RABBITMQ_PASSWORD)"
    minio_user="$(read_env_value MINIO_ROOT_USER)"
    minio_password="$(read_env_value MINIO_ROOT_PASSWORD)"

    log "启动业务后端"
    (
      cd "${PROJECT_ROOT}/services/business-api"
      nohup env \
        TD_DATABASE_URL='jdbc:postgresql://127.0.0.1:5432/tool_defect' \
        TD_DATABASE_USERNAME='tool_defect' \
        TD_DATABASE_PASSWORD="${postgres_password}" \
        TD_RABBITMQ_ADDRESSES='127.0.0.1:5672' \
        TD_RABBITMQ_USERNAME='tool_defect' \
        TD_RABBITMQ_PASSWORD="${rabbitmq_password}" \
        TD_RABBITMQ_SSL_ENABLED='false' \
        TD_MESSAGING_ENABLED='true' \
        TD_OPERATIONS_ENABLED='true' \
        TD_STORAGE_ENABLED='true' \
        TD_S3_ENDPOINT='http://127.0.0.1:9000' \
        TD_S3_ACCESS_KEY="${minio_user}" \
        TD_S3_SECRET_KEY="${minio_password}" \
        TD_S3_REQUIRE_TLS='false' \
        TD_AUTH_SECURE_COOKIE='false' \
        TD_BOOTSTRAP_ADMIN_USERNAME="${TD_BOOTSTRAP_ADMIN_USERNAME:-}" \
        TD_BOOTSTRAP_ADMIN_DISPLAY_NAME="${TD_BOOTSTRAP_ADMIN_DISPLAY_NAME:-}" \
        TD_BOOTSTRAP_ADMIN_PASSWORD_FILE="${TD_BOOTSTRAP_ADMIN_PASSWORD_FILE:-}" \
        TD_ENVIRONMENT='development' \
        TD_SERVICE_VERSION='workspace' \
        ./mvnw spring-boot:run \
        >"${log_file}" 2>&1 &
      printf '%s\n' "$!" >"${pid_file}"
    )
    STARTED_BACKEND=1
  fi

  if ! wait_for_url \
    "业务后端健康检查" \
    "http://127.0.0.1:9091/actuator/health" \
    180 \
    "${pid_file}"
  then
    show_log_tail "${log_file}"
    die "业务后端启动失败"
  fi
}

install_frontend_dependencies() {
  if [[ ! -x "${PROJECT_ROOT}/apps/web-console/node_modules/.bin/vite" ]]; then
    log "安装网页前端依赖"
    (
      cd "${PROJECT_ROOT}/apps/web-console"
      "${PNPM_COMMAND[@]}" install --frozen-lockfile
    )
  fi
}

start_frontend() {
  local pid_file="${RUNTIME_DIR}/web-console.pid"
  local log_file="${RUNTIME_DIR}/web-console.log"

  if pid_is_running "${pid_file}"; then
    log "网页前端已由本脚本启动"
  else
    if port_is_listening 5173; then
      die "端口 5173 已被脚本外的进程占用"
    fi
    install_frontend_dependencies
    log "启动网页前端"
    (
      cd "${PROJECT_ROOT}/apps/web-console"
      nohup env \
        TOOL_DEFECT_DEV_API_TARGET='http://127.0.0.1:8080' \
        "${PNPM_COMMAND[@]}" dev \
        >"${log_file}" 2>&1 &
      printf '%s\n' "$!" >"${pid_file}"
    )
    STARTED_FRONTEND=1
  fi

  if ! wait_for_url \
    "网页前端" \
    "http://127.0.0.1:5173/" \
    60 \
    "${pid_file}"
  then
    show_log_tail "${log_file}"
    die "网页前端启动失败"
  fi
}

stop_process_tree() {
  local pid="$1"
  local child
  for child in $(pgrep -P "${pid}" 2>/dev/null || true); do
    stop_process_tree "${child}"
  done
  kill "${pid}" >/dev/null 2>&1 || true
}

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  if pid_is_running "${pid_file}"; then
    local pid
    pid="$(tr -cd '0-9' <"${pid_file}")"
    log "停止${name}（进程 ${pid}）"
    stop_process_tree "${pid}"
  fi
  rm -f "${pid_file}"
}

stop_all() {
  require_command docker
  require_command pgrep
  ensure_env_file
  validate_env_file
  mkdir -p "${RUNTIME_DIR}"
  touch "${RUNTIME_DIR}/stop.requested"
  stop_pid_file "网页前端" "${RUNTIME_DIR}/web-console.pid"
  stop_pid_file "业务后端" "${RUNTIME_DIR}/business-api.pid"
  log "停止开发基础设施"
  compose down
  log "全部可运行服务已停止；数据卷未删除"
}

status_all() {
  ensure_env_file
  validate_env_file
  printf '业务后端：'
  if pid_is_running "${RUNTIME_DIR}/business-api.pid"; then
    printf '运行中\n'
  else
    printf '未运行\n'
  fi
  printf '网页前端：'
  if pid_is_running "${RUNTIME_DIR}/web-console.pid"; then
    printf '运行中\n'
  else
    printf '未运行\n'
  fi
  printf '\n容器状态：\n'
  compose ps
}

logs_all() {
  mkdir -p "${RUNTIME_DIR}"
  touch "${RUNTIME_DIR}/business-api.log" "${RUNTIME_DIR}/web-console.log"
  tail -n 100 -f \
    "${RUNTIME_DIR}/business-api.log" \
    "${RUNTIME_DIR}/web-console.log"
}

rollback_on_failure() {
  local exit_code="$1"
  if (( exit_code == 0 )); then
    return
  fi
  warn "启动失败，回滚本次新启动的本地进程"
  if (( STARTED_FRONTEND == 1 )); then
    stop_pid_file "网页前端" "${RUNTIME_DIR}/web-console.pid"
  fi
  if (( STARTED_BACKEND == 1 )); then
    stop_pid_file "业务后端" "${RUNTIME_DIR}/business-api.pid"
  fi
  if (( STARTED_COMPOSE == 1 && COMPOSE_WAS_EMPTY == 1 )); then
    warn "回滚本次新启动的开发基础设施"
    compose down >/dev/null 2>&1 || true
  fi
}

start_all() {
  mkdir -p "${RUNTIME_DIR}"
  rm -f "${RUNTIME_DIR}/stop.requested"
  ensure_env_file
  validate_env_file
  check_prerequisites

  trap 'rollback_on_failure $?' EXIT
  start_infrastructure
  start_backend
  start_frontend
  cat <<EOF

开发环境已启动：
  网页前端      http://127.0.0.1:5173/
  业务后端      http://127.0.0.1:8080/
  健康检查      http://127.0.0.1:9091/actuator/health
  RabbitMQ      http://127.0.0.1:15672/
  MinIO         http://127.0.0.1:9001/
  Prometheus    http://127.0.0.1:9090/
  Grafana       http://127.0.0.1:3000/

查看日志：
  ./tools/dev/start-all.sh logs

停止服务：
  当前终端按 Ctrl+C，或在另一终端执行：
  ./tools/dev/start-all.sh stop

限制：
  推理服务和采集端当前没有可执行主入口，未作为独立进程启动。
  首次启动本地账号时，需在启动前设置一次性管理员账号、显示名和密码文件环境变量。
EOF

  if (( DETACH == 1 )); then
    trap - EXIT
    warn "已使用分离模式；调用终端必须允许子进程在父进程退出后继续运行"
    return
  fi

  log "正在守护服务；按 Ctrl+C 统一停止"
  trap 'log "收到停止信号"; stop_all; exit 0' INT TERM
  while true; do
    if [[ -f "${RUNTIME_DIR}/stop.requested" ]]; then
      log "检测到停止请求，结束守护"
      trap - EXIT
      return
    fi
    if ! pid_is_running "${RUNTIME_DIR}/business-api.pid"; then
      show_log_tail "${RUNTIME_DIR}/business-api.log"
      die "业务后端意外退出"
    fi
    if ! pid_is_running "${RUNTIME_DIR}/web-console.pid"; then
      show_log_tail "${RUNTIME_DIR}/web-console.log"
      die "网页前端意外退出"
    fi
    sleep 2
  done
}

while (( $# > 0 )); do
  case "$1" in
    start|stop|status|logs)
      ACTION="$1"
      shift
      ;;
    --env-file)
      (( $# >= 2 )) || die "--env-file 缺少路径"
      ENV_FILE="$2"
      shift 2
      ;;
    --detach)
      DETACH=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

case "${ACTION}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  status)
    status_all
    ;;
  logs)
    logs_all
    ;;
esac
