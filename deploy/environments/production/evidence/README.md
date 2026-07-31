# P7 现场证据挂载目录

本目录只保留证据契约说明。真实现场日志、报告、模型、软件物料清单、签字文件和执行输出不得提交 Git；运行门禁时通过本目录的受控挂载或命令参数提供，并由验证器重新计算 SHA-256。

统一退出码：`0` 表示全部真实前置满足，`1` 表示输入损坏或实现错误，`2` 表示外部前置或现场证据缺失。

## 技术清单

默认路径为 `technology-inventory.json`，模式版本必须为 `tool-defect-technology-inventory/v1`。每项至少包含：

- 决策编号、组件、产品、精确版本、许可证和支持结束时间；
- 制品 SHA-256、软件物料清单路径与 SHA-256；
- 许可证审查证据路径与 SHA-256；
- 审批人标识、角色、时间、证据路径与 SHA-256。

## 模型冒烟证据

默认路径为 `model-smoke-test.json`，模式版本必须为 `tool-defect-model-smoke/v1`，来源必须是真实生产或生产等价基础设施。记录需绑定生产模型包摘要、探针输入摘要、输出模式摘要、真实 HTTPS 端点、预热结果、探针/失败数量、执行主机和原始日志摘要。

## 起飞前执行记录

默认路径为 `preflight-results.json`，模式版本必须为 `tool-defect-preflight-results/v1`。每个必检项需记录清单命令模板、现场解析后的实际命令、退出码、实际结果、执行者、主机、时间、证据文件及 SHA-256。聚合器只验证结构化记录，不执行清单中的任意 Shell。

## 生产迁移执行记录

默认路径为 `production-migration-report.json`，模式版本必须为 `tool-defect-production-migration/v1`。只有 `EXECUTE` 模式、真实生产来源、获批 P6-01 清单和四个实际执行阶段全部 `PASSED` 才能形成生产声明。报告必须包含不可变迁移编号、执行者、起止时间、源快照与源保留日志摘要，以及按迁移编号限定、不使用无条件删除的回滚计划摘要。干跑、部分写入、跳过和未批准来源均返回 `BLOCKED`。

## 迁移全量对账记录

默认路径为 `production-migration-verification.json`，模式版本必须为 `tool-defect-production-migration-verification/v1`，并通过路径和 SHA-256 绑定迁移执行记录。`verification_scope` 必须为 `FULL`；图片、掩膜、数据集、模型、数据库和审批六类资产逐类记录源/目标数量、总字节和聚合 SHA-256，另记录逐对象存在性、字节与散列核验及迁移后源保留证明。随机抽样只能用于诊断，不能形成 P7-03 通过证据。

## 生产恢复演练记录

默认路径为 `recovery-drill-record.json`，模式版本必须为 `tool-defect-production-recovery/v1`。记录必须来自真实生产快照并在隔离生产等价环境执行，固定覆盖快照、隔离恢复、业务记录、对象存储、模型功能和审批链六场景；同时绑定全量迁移对账报告、原始日志、实际 RPO/RTO 和独立批准。场景缺失、非真实来源、未签署或超出已签目标时保持 `BLOCKED` 或 `FAILED`。

## 非功能验收记录

默认路径为 `non-functional-acceptance.json`，模式版本必须为 `tool-defect-non-functional-acceptance/v1`。除 `make test-faults test-security test-performance` 零跳过回归外，还必须记录真实故障注入、真实安全探测、签署阈值、节拍余量、持续吞吐、容量、并发复核、原图零丢失、RPO/RTO、长期稳定性和严重告警触发/恢复。确定性桩函数和静态配置检查不能代替现场证据。质量、运维、安全和基础设施四个不同人员共同批准。

## 质量试运行记录

默认路径为 `quality-trial-report.json`，模式版本必须为 `tool-defect-quality-trial/v1`。试运行必须来自真实生产工位，至少覆盖不同工位、班次、批次，以及低/中/高置信度和小/中/大缺陷尺寸。每项漏检、误放、推翻、图像质量、漂移、预处理失败和新旧模型配对指标都需给出分子、分母、95% 置信区间、阈值和状态，并提供抽样框覆盖及选择偏差说明。34 张研究集必须明确标记为未被用作替代证据；质量、工艺、算法和发布四个不同人员共同批准。

## 联系人与外部用户演练记录

默认联系人路径为 `emergency-contacts.json`，模式版本必须为 `tool-defect-emergency-contacts/v1`；所有角色、主备通道和值班表均需处于真实生产 `ACTIVE` 状态。默认演练路径为 `user-operations-drill.json`，模式版本必须为 `tool-defect-p7-user-operations-drill/v1`。未参与开发的外部用户须在真实设备上完成目录内全部场景，并显式覆盖正常操作、权限拒绝、死信逐条重放、完整回滚、证书吊销和紧急账号。高风险动作必须有原因、不同人员二次确认、职责分离和可复算审计/原始日志证据。

统一入口为 `make verify-p7-06`。

## 上线就绪与 G7 验收记录

最终上线清单必须使用 `tool-defect-go-live-checklist/v2`，52 项逐项记录 `PASS`，或在确实不适用时提供已批准豁免、负责人、到期日和补偿控制；每项同时绑定真实证据路径及 SHA-256。最终发布决定必须使用 `tool-defect-release-decision-record/v2`，明确 `GO/APPROVED`，绑定清单与 P7-01 至 P7-06 的真实通过证据，关闭全部风险，验证上一稳定模型的签名、预热、健康和回滚演练，并提供覆盖发布时间后至少七天、零空档的值班记录及质量、工艺、算法、发布四名不同人员签署。

G7 记录使用 `tool-defect-p7-gate-acceptance/v1`，逐项绑定 P7-01 至 P7-07 和九组阶段要求的真实证据，并附四方签署与原始日志。外置清单、发布决定和 G7 记录可分别通过 `TD_P7_GO_LIVE_CHECKLIST`、`TD_P7_RELEASE_DECISION`、`TD_G7_EVIDENCE` 指向受控挂载。统一入口分别为 `make verify-p7-07` 和 `make verify-g7`；任一前置缺失时必须返回非零并保持 `BLOCKED`。

所有证据文件与原始日志不得提交 Git；只在受控挂载中提供，门禁会重新计算每个引用文件的 SHA-256。
