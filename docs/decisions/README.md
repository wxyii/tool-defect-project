# P0-02 现场参数与架构决策登记

`site-parameter-decisions.json` 是尚未确认现场输入的单一登记表。每项决策
包含稳定编号、状态、配置键、负责人、最迟确认门禁、来源文档和未知时的
安全行为。

状态只允许：

- `已确认`：已有唯一负责文档明确冻结。
- `暂定默认值`：仅用于安全开发或容量估算，仍需在指定门禁前签字。
- `上线阻断`：不影响骨架开发，但未关闭时禁止通过 `G7`。
- `可后置`：没有运行证据时保持关闭。

配置模式位于：

- `configs/schema/site-decisions.schema.json`
- `configs/schema/site-parameters.schema.json`
- `configs/schema/site-parameters.safe-defaults.json`

安全默认配置不含凭据，且固定满足：

1. 生产环境关闭。
2. 真实相机和 PLC 关闭，只允许模拟器。
3. 自动 `PASS` 关闭，未知阈值和技术失败进入 `HOLD`。
4. 未同步原图和中心状态未知原图禁止删除。
5. 最终保留期未知时关闭自动删除。
6. 身份、存储、告警和恢复目标未确认时不能声称可上线。

只读验证：

```text
python tools/baseline/decision_checks.py
python tools/baseline/hardcoded_scan.py
```

硬编码扫描覆盖目标生产目录，排除测试、样例、生成代码和只作参考的旧界面。
需要保留确有依据的技术常量时，必须进入版本化算法配置；现场业务参数没有
行内豁免机制。

## 已接受的架构决策

- [ADR-0003：取消内置数据集版本与训练运行管理](ADR-0003-取消内置数据集与训练管理.md)：规定第二版在线边界、模型直接上传的独立性，以及第一版历史能力的兼容退役方式。
