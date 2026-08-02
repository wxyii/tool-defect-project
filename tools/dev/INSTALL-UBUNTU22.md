# Ubuntu LTS 一键安装（20.04 / 22.04 / 24.04 / 26.04）

在仓库根目录执行：

```sh
chmod +x tools/dev/install-ubuntu22.sh
./tools/dev/install-ubuntu22.sh
```

脚本会安装并验证：

- Ubuntu 基础构建工具、Python 图像处理所需系统库；
- Docker Engine、Buildx 和 Compose 插件；
- Java 25（Temurin）以及仓库内 Maven Wrapper 所需的解压工具；
- Node.js 20.13.1、pnpm 10.34.5；
- uv、Python 3.11 项目虚拟环境和 `requirements-app.txt`；
- Python 契约包、边缘端、推理服务和前端/TypeScript 契约依赖。

Python 环境会按运行时隔离在根目录 `.venv`、`apps/edge-agent/.venv` 和
`services/inference-service/.venv`，以保留根项目 Pillow 10.4.0 与边缘端 Pillow 12.3.0 的版本契约。

脚本不会启动容器，不会生成生产密钥，也不会把密钥写入仓库。安装后可运行：

```sh
./tools/dev/start-all.sh
make verify-p1-strict
```

如果在 WSL2 中使用 Docker Desktop，脚本会复用 Docker Desktop 提供的 Docker CLI/Compose，不会在 WSL 内再次安装 Docker Engine，也不会调用 `systemctl` 启动 `docker.service`。首次运行前请在 Docker Desktop 的 `Settings > Resources > WSL Integration` 中开启当前发行版；若集成不可用，脚本会明确失败并停止。

脚本支持 Ubuntu 20.04、22.04、24.04 和 26.04，并根据系统代号自动配置 Docker 与 Adoptium 软件源。完整 Python 训练依赖建议使用 `x86_64` 主机；若为 ARM 主机，TensorFlow 2.13.0 的可用性需单独确认。首次安装会访问 Docker、Adoptium、Node.js、uv、PyPI 和 npm 官方源；网络、代理或外部镜像不可用时，脚本会失败并保留明确错误，不会将环境标记为通过。
