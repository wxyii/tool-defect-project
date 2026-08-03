# JSON Schema v1 / v2

本目录使用 JSON Schema 2020-12。`*-v1` 是冻结兼容源；`common-v2`、`event-payloads-v2` 和 `consumer-contract-v2` 定义第二版公共词汇、单图片项事件和消费者清单。`consumer-migration-r1` 只验证第一版治理清单，不参与第一版网络类型生成哈希。

规则：

- 所有对象默认 `additionalProperties: false`。
- 大图片、掩膜和模型只以对象引用传输。
- 哈希统一使用 64 位小写十六进制 SHA-256。
- 插件算法结论只能为 `QUALIFIED`、`UNQUALIFIED`、`INCONCLUSIVE`；生产处置由后端单独生成。
- `contracts/examples/invalid/` 中的样例必须校验失败。
- 第二版禁止多视角字段、数据集版本和训练运行一等资源；`LegacyProvenanceSnapshot` 只可嵌入模型历史只读响应。
