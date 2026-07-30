# 一键开发启动

从仓库根目录执行：

```sh
./tools/dev/start-all.sh
```

命令会持续守护各服务，按 `Ctrl+C` 后统一停止本地进程和容器，但保留数据卷。
如果明确知道调用终端允许子进程在父进程退出后继续运行，可以使用
`--detach` 分离模式。

脚本会完成以下工作：

- 检查 Docker、Java 25、Node.js 20.13.1 和 pnpm 10.34.5；
- 首次运行时在仓库外生成权限为 `600` 的随机开发密钥；
- 启动 PostgreSQL、RabbitMQ、MinIO 和可观测组件；
- 将已有数据卷中的数据库与消息队列开发密码同步为当前密钥文件，
  避免切换密钥文件后认证失败；
- 通过独立覆盖配置兼容 Tempo 3.0 与遥测收集器 0.157，
  不改写部署目录中的原始监控配置；
- 启动业务后端并等待独立健康端点就绪；
- 启动网页前端并等待开发服务器就绪；
- 任一步失败时停止本次新启动的本地进程，并在基础设施原本未运行时回滚容器。

其他命令：

```sh
./tools/dev/start-all.sh status
./tools/dev/start-all.sh logs
./tools/dev/start-all.sh stop
```

默认密钥文件是：

```text
${XDG_CONFIG_HOME:-$HOME/.config}/tool-defect/development.env
```

可以显式指定其他仓库外路径：

```sh
./tools/dev/start-all.sh --env-file /受限路径/tool-defect-development.env
```

当前 `services/inference-service/` 和 `apps/edge-agent/` 没有可执行主入口，
因此不能作为独立常驻进程启动。脚本会明确报告该限制。网页端完整登录还需要
外部身份服务配置；未配置时业务接口保持默认拒绝。
