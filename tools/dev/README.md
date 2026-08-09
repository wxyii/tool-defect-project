# 开发启动入口

## Linux / WSL 环境

Linux 开发环境使用 Docker Compose：

```sh
./tools/dev/start-all.sh
./tools/dev/start-all.sh --detach
./tools/dev/start-all.sh status
./tools/dev/start-all.sh logs
./tools/dev/start-all.sh stop
```

该入口负责创建受限开发密钥文件、启动 PostgreSQL、RabbitMQ、对象存储和可观测组件，并启动业务 API 与 Web 前端。

## Windows 原生环境

Windows 环境使用 PowerShell 原生服务管理，不使用 WSL 或 Docker：

```powershell
.\run-windows.bat start -EnvFile .windows.env.ps1
.\run-windows.bat start -EnvFile .windows.env.ps1 -Detach
.\run-windows.bat status -EnvFile .windows.env.ps1
.\run-windows.bat logs
.\run-windows.bat stop -EnvFile .windows.env.ps1
```

首次启动时如果本地数据库没有账号，启动器会交互创建一个 ADMINISTRATOR 账号；用户名默认 admin，显示名默认“系统管理员”，密码输入不会回显，首次登录必须改密。引导密码只在受限临时文件和本次后端进程环境中存在，成功或失败都会清理；不要在 .windows.env.ps1 中配置 TD_BOOTSTRAP_ADMIN_*。

Windows 版本要求 PostgreSQL、RabbitMQ、对象存储、OpenTelemetry Collector、Prometheus、Grafana、Loki 和 Tempo 已注册为原生 Windows 服务。`setup-windows.ps1` 只准备工具链；基础设施安装由独立的 `setup-windows-infrastructure.ps1` 负责，二进制包不会提交到 Git。

详细步骤见 [`WINDOWS-NATIVE.md`](WINDOWS-NATIVE.md)。

## 共同约束

- Node.js 必须为 20.13.1，pnpm 必须为 10.34.5。
- 业务 API 健康检查为 `http://127.0.0.1:9091/actuator/health`。
- Web 前端为 `http://127.0.0.1:5173/`，业务 API 为 `http://127.0.0.1:8080/`。
- 推理库、采集端和训练代码没有独立常驻入口，不会被启动脚本伪装成服务。
- 缺少前置条件、健康检查失败或进程意外退出时必须返回非零并执行安全回滚。

### Windows 原生基础设施安装器

首次在 Windows 本地开发环境安装基础设施时，以管理员 PowerShell 执行：

```powershell
.\tools\dev\setup-windows-infrastructure.ps1 -Action install
.\tools\dev\setup-windows.ps1
```

该独立入口按 `deploy/compose/development.yml` 锁定的版本安装 PostgreSQL、RabbitMQ、MinIO、OpenTelemetry Collector、Prometheus、Grafana、Loki 和 Tempo，并将程序、数据、配置、日志与下载缓存放在 `.build\windows-infrastructure`。首次安装会生成随机凭据到根目录 `.windows.env.ps1`，随后使用：

```powershell
.\run-windows.bat start -EnvFile .windows.env.ps1
```

可用 `-Action status` 检查服务、端口和 HTTP 健康状态；`-Action uninstall` 只移除该安装器记录的服务注册，保留数据、凭据和下载缓存。已有服务、端口或未被安装器拥有的数据目录会进入 HOLD/失败，不会被接管或覆盖。MinIO、Loki、Tempo 的 Windows 支持仅用于本地开发/评估，不是生产部署方案。

安装中途失败后可直接重跑；安装器会复用已校验的下载缓存和已初始化的数据目录，并保留生成的 `.windows.env.ps1`。若只想使用现有缓存，可追加 `-SkipDownloads`。若前置服务已经健康运行，可用 `-StartAt rabbitmq`、`-StartAt minio` 或 `-StartAt monitoring` 跳过对应前置组件；脚本会先检查被跳过服务的服务状态、端口和 HTTP 健康检查，不满足条件时明确失败。对于升级前没有安装中标记的旧失败目录，仅在确认目录由本安装器创建后追加一次 `-ResumePartial`。
