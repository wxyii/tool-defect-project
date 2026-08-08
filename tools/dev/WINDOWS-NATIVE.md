# Windows 原生开发启动

本入口与 `start-all.sh` 的动作和生命周期保持一致，但不调用 WSL、Docker 或 Docker Compose。
PostgreSQL、RabbitMQ、对象存储、OpenTelemetry Collector、Prometheus、Grafana、Loki 和 Tempo
必须预先注册为 Windows 服务；推荐使用本文件后面的独立安装器完成注册。

## 准备环境

在仓库根目录执行：

```powershell
.\setup-windows.bat -InstallPrerequisites
```

该脚本只准备 Python 3.11、Java 25、Node.js 20.13.1、pnpm 10.34.5 和前端依赖，不安装或托管基础设施服务。

旧的手工流程需要为每个基础设施组件注册 Windows 服务，并记录实际服务名。使用独立安装器时服务名由脚本固定生成，启动器会严格按环境文件校验。

## 配置

```powershell
Copy-Item tools\dev\windows-native.env.example.ps1 .windows.env.ps1
# 编辑 .windows.env.ps1，填写数据库、RabbitMQ、对象存储凭据和 8 个 Windows 服务名
```

`.windows.env.ps1` 被 `.gitignore` 忽略，不得提交密码、令牌或私钥。缺少任何必填值都会明确失败，不会生成默认凭据。

## 一键启动

```powershell
.\run-windows.bat start -EnvFile .windows.env.ps1
```

### 首次账号引导

如果数据库中还没有本地账号，首次执行 start 会在启动业务 API 后进入交互引导：

- 用户名回车默认为 admin；
- 显示名回车默认为“系统管理员”；
- 输入并确认一个 12 至 128 位密码，密码不会回显；
- 创建固定角色为 ADMINISTRATOR 的账号，首次登录后必须修改密码。

密码只会短暂写入 .build\windows-runtime\bootstrap-admin.password，并通过受限 ACL 传给本次后端启动；引导成功或失败都会清理该文件和进程级引导变量。不要把 TD_BOOTSTRAP_ADMIN_* 写入 .windows.env.ps1。后续启动检测到已有账号后会跳过引导。

默认模式会持续守护服务，按 `Ctrl+C` 停止本次启动的应用和基础设施服务。已在启动前运行的外部服务不会被停止。

分离模式：

```powershell
.\run-windows.bat start -EnvFile .windows.env.ps1 -Detach
```

启动顺序为：Windows 基础设施服务、端口和 HTTP 健康检查、业务 API、Web 前端。前端依赖缺失时会执行：

```powershell
pnpm install --frozen-lockfile
```

## 其他动作

```powershell
.\run-windows.bat status -EnvFile .windows.env.ps1
.\run-windows.bat logs
.\run-windows.bat stop -EnvFile .windows.env.ps1
```

`stop` 只停止启动器记录为本次启动的 Windows 服务和业务进程，保留数据目录。`logs` 持续查看业务 API 和 Web 前端日志；基础设施日志由其 Windows 服务安装方式管理。

常用地址：

- Web 前端：`http://127.0.0.1:5173/`
- 业务 API：`http://127.0.0.1:8080/`
- 健康检查：`http://127.0.0.1:9091/actuator/health`
- RabbitMQ 管理界面：`http://127.0.0.1:15672/`
- 对象存储控制台：`http://127.0.0.1:9001/`
- Prometheus：`http://127.0.0.1:9090/`
- Grafana：`http://127.0.0.1:3000/`

## 边界和失败规则

- 不启动推理服务、采集端或训练服务；仓库当前没有这些组件的独立常驻入口。
- 不调用 WSL、Docker、Compose 或 Linux shell。
- 缺少服务、凭据、端口、健康检查或完整工具链时返回非零，不报告为成功。
- 当前启动器不再提供 `Predict`、`RingBatch`、`DataCheck` 等旧 `Mode` 入口。

## 自动安装本地基础设施

`tools/dev/setup-windows.ps1` 仍只负责 Python、Java、Node.js、pnpm 和前端依赖等工具链，不会改变其默认职责。需要安装本地基础设施时，按以下顺序执行：

```powershell
.\tools\dev\setup-windows-infrastructure.ps1 -Action install
.\run-windows.bat start -EnvFile .windows.env.ps1
```

安装器必须在管理员 PowerShell 中运行；不自动弹出 UAC。它固定安装 PostgreSQL 18.4、RabbitMQ 4.1.2（Erlang/OTP 27.3.4.15）、MinIO `RELEASE.2025-07-23T15-54-02Z`、OpenTelemetry Collector 0.157.0、Prometheus 3.5.0、Grafana 12.1.0、Loki 3.7.0、Tempo 3.0.0 和 WinSW 2.12.0。每个下载文件都会进行 SHA-256 校验，失败或哈希冲突会明确退出。

支持 `-Action status`、`-Action uninstall` 和 `-Action help`。卸载只删除安装状态中记录的服务注册，默认保留 `.build\windows-infrastructure` 下的数据、配置、日志和下载缓存。已有服务、端口或未归属于本安装器的数据目录不会被接管、覆盖或删除；安装中途失败会清理本次创建的服务注册，并保留缓存、凭据和已有数据。

安装失败后可直接重跑；已初始化的 PostgreSQL 数据目录不会再次执行 `initdb`。若要明确跳过下载步骤并只使用已校验缓存：

```powershell
.\tools\dev\setup-windows-infrastructure.ps1 -Action install -SkipDownloads
```

如果是旧版本安装器留下的、没有 `install-in-progress.json` 标记的失败目录，确认该目录确实由本安装器创建后，首次续装追加 `-ResumePartial`：

```powershell
.\tools\dev\setup-windows-infrastructure.ps1 -Action install -ResumePartial -SkipDownloads
```

旧版本失败回滚若已经删除 `.windows.env.ps1`，但 PostgreSQL 数据目录中仍存在 `PG_VERSION`，安装器会拒绝生成新密码覆盖既有数据。请恢复原凭据文件；若这是刚创建且无须保留的本地空库，请先将 `data\postgresql` 移到安装目录外的备份位置，再使用上面的续装命令，避免直接删除数据。

如果 PostgreSQL 已经健康运行，也可以从 RabbitMQ 继续：

```powershell
.\tools\dev\setup-windows-infrastructure.ps1 -Action install -StartAt rabbitmq -SkipDownloads
```

`-StartAt` 只能跳过已健康的前置服务；脚本会检查服务状态、端口和 HTTP 健康检查，不满足条件时明确失败。

MinIO、Loki、Tempo 在 Windows 上只定位为本地开发/评估用途，不保证生产拓扑、多盘部署或高可用行为。该入口不修改跨进程契约，也不替换现有 `setup-windows.ps1` 流程。

官方参考：[MinIO Windows 安装说明](https://min.io/docs/minio/windows/operations/installation.html)、[RabbitMQ Windows 服务说明](https://www.rabbitmq.com/docs/4.1/install-windows)、[OpenTelemetry Windows 安装说明](https://opentelemetry.io/docs/collector/install/binary/windows/) 和 [WinSW](https://github.com/winsw/winsw)。
