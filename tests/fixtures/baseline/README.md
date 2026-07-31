# P0 资产冻结夹具

- `baseline-lock.json` 冻结各资产组数量、总字节数、逐文件记录聚合
  SHA-256、180/172/34 数据事实、模型文件存在性和历史 Git/LFS 指针。
- `test-baseline.json` 冻结 P0 开始时现有 62 项单元测试的结果。

聚合摘要的输入是按仓库相对路径排序的完整记录：

```text
{"path": "...", "size_bytes": 123, "sha256": "..."}
```

因此锁文件无需复制 4.7 GB 原图，也能检测任何路径、大小或内容变化。使用
`python tools/baseline/inventory.py --include-records` 可只读输出全部逐文件
清单；使用 `--verify tests/fixtures/baseline/baseline-lock.json` 验证冻结值。

源码、配置、P0 前已有测试和 01—15 号设计文档从来源提交 `97c88cb` 的
Git Blob 计算，避免后续阶段的合法工作树改动重写历史基线。Git 历史中的
设计文档路径为小写 `docs/`，摘要继续规范记录为冻结时的 `Docs/`；数据和
当前模型从 P0 启动时的只读工作树计算。

历史权重只记录 Git Blob 和 Git LFS 对象证据。夹具没有恢复、复制或提交
任何权重文件。
