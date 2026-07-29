# 软件物料清单

生成器从 Python 锁、Maven 工程、pnpm 元数据和开发 Compose 固定镜像产生
CycloneDX 1.6 JSON。`--check` 在临时目录验证确定性，不向仓库写报告；无参数
时写入被忽略的 `.build/reports/p1.cdx.json`。
