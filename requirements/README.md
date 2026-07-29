# 依赖锁

- `../uv.lock`：现有核心兼容包的无依赖锁。
- `edge.lock`：边缘采集端运行时依赖。
- `inference.lock`：推理服务安全依赖，固定 `cryptography==49.0.0`。
- `contract-tools.lock`：P1 离线工具链无第三方依赖。

Python 包元数据、Maven 与 pnpm 也必须使用精确版本。完整环境门禁会检查
Java 25、Maven、Node.js 20.13.1、pnpm 10.34.5、TypeScript 5.9.2 和 Docker
Compose；缺少任一项均失败。
