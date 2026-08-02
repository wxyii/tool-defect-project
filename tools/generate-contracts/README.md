# 三语言契约生成

生成器只读取 `contracts/json-schema`、`contracts/openapi` 和
`contracts/asyncapi`，按主版本对规范化内容计算独立 SHA-256，并把源版本及哈希写入
Python、Java、TypeScript 生成物头部。第一版保留原命名空间；第二版分别生成到
`tool_defect_contracts.v2`、`local.tooldefect.contracts.v2` 和 `src/v2`。

- 无参数：生成文件。
- `--check-deterministic`：检查重复生成一致且工作树无漂移。
- `verify_packages.py --languages offline`：递归离线编译两代 Python 与 Java。
- `verify_packages.py --languages all`：再执行 TypeScript 严格编译；缺少编译器即失败。
