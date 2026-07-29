# JSON Schema v1

本目录使用 JSON Schema 2020-12，定义跨服务公共词汇、标准结果、标准错误、对象引用、推理事件、追踪头和状态转换向量。

规则：

- 所有对象默认 `additionalProperties: false`。
- 大图片、掩膜和模型只以对象引用传输。
- 哈希统一使用 64 位小写十六进制 SHA-256。
- 插件算法结论只能为 `QUALIFIED`、`UNQUALIFIED`、`INCONCLUSIVE`；生产处置由后端单独生成。
- `contracts/examples/invalid/` 中的样例必须校验失败。
