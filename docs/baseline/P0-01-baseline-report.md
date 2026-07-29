# P0-01 当前代码、数据和模型资产基线报告

## 1. 冻结范围

- 来源提交：`97c88cb`
- 清单模式：`tests/fixtures/baseline/baseline-lock.json`
- 扫描器：`tools/baseline/inventory.py`
- 生成日期：2026-07-29
- 原始数据、模型、输出和现有源码均只读；没有恢复 Git LFS 权重。

扫描器按仓库相对路径排序，对每个文件计算字节数和 SHA-256，再对完整记录
计算资产组摘要。使用 `--include-records` 可输出所有逐文件记录。

## 2. 资产组

| 资产组 | 文件数 | 总字节数 | 聚合 SHA-256 |
|---|---:|---:|---|
| 当前源码和旧界面参考 | 47 | 3,130,755 | `c2231ba4…5667c` |
| 当前配置与依赖声明 | 9 | 4,273 | `0bebc725…486b7` |
| P0 前已有测试 | 20 | 86,782 | `3c3ee1ac…79f0a` |
| README 与 01—15 号设计文档 | 16 | 220,514 | `af65f964…e373b` |
| 原始图片 | 180 | 4,769,700,960 | `3be36422…21a1` |
| 原始掩膜 | 180 | 2,844,810 | `1060ae7f…239e` |
| Labelme 标注 | 0 | 0 | `4f53cda1…b945` |
| 数据清单和审计 | 3 | 37,949 | `9442f258…1973` |
| 自适应环形处理数据 | 363 | 55,274,569 | `0f4ac75c…56c` |
| 边界归一化处理数据 | 363 | 110,603,801 | `f2baac06…b70` |
| 当前小型模型制品 | 4 | 282,878 | `0eb7ec11…932a` |

完整稳定资产摘要：

```text
37301fdc4c5e542b1c87ef61dc76912d423fb10b1060249cc9c3d07b15c396ba
```

## 3. 数据基线

| 清单 | 数量 | 训练/验证/测试 | 类别 | 清单 SHA-256 |
|---|---:|---|---|---|
| `data/manifests/dataset.csv` | 180 | 115/29/36 | 98 合格、82 不合格 | `d792c9f3…319` |
| `data/manifests/retrain.csv` | 172 | 110/28/34 | 92 合格、80 不合格 | `2fa1fdf1…dee` |
| `data/manifests/retrain_audit.json` | 172 | 测试 34 | 排除冲突 2、精确去重 6 | `17f414ed…145` |

审计清单确认跨划分重复哈希为 0。原始与重训练清单合计 352 个图片路径使用
小写类别目录，但磁盘目录为 `Qualified` 和 `Unqualified`，已登记为
大小写敏感环境阻断。

## 4. 模型结构、输入输出和历史权重证据

| 制品 | 状态 | SHA-256 或证据 | 输入与输出 |
|---|---|---|---|
| `artifacts/classification/model.json` | 存在 | `350ccfaa…efa` | 输入 `299×299×3`；输出 2 类 |
| `artifacts/classification/weights.h5` | 工作树缺失 | Git Blob `474c1179…`；LFS SHA-256 `2887aa69…e76`；声明 113,010,408 字节 | 不加载 |
| `artifacts/multitask/model.json` | 存在且文档哈希一致 | `377a1cec…f50` | 输入 `256×256×3`；输出 `cla_out`、`seg_out` |
| `artifacts/multitask/weights.h5` | 工作树缺失 | Git Blob `ac9c6b46…`；LFS SHA-256 `63de0dfb…d63`；声明 147,052,464 字节 | 不加载 |
| 三组 `outputs/training` 双任务产物 | 全部缺失 | 文档中的结构和三个权重哈希仅作期望值 | 不登记、不混配 |
| `artifacts/polar_anomaly/polar_anomaly.json` | 存在但不兼容 | `92026de6…3c0` | 模型版本 1，代码要求版本 2 |

本机 Git LFS 缓存中可只读验证两份历史对象的大小和内容哈希，但本任务没有
将对象恢复、复制或写回 `artifacts/`。目录名不能代替训练来源。

## 5. 环境冻结

- Python：3.11.14，CPython，Darwin arm64。
- TensorFlow：2.13.0。
- Keras：2.13.1。
- NumPy：1.24.3。
- OpenCV：4.11.0.86。
- Pillow：当前 12.3.0，`requirements.txt` 声明 10.4.0，已登记漂移。
- 其余完整版本见 `baseline-lock.json` 的 `environment`。

## 6. 测试冻结

执行：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests
```

P0 开始时共执行 62 项，结果为 1 个失败和 9 个错误。9 个错误由两份工作树
权重缺失导致；1 个失败是 POSIX 环境未拒绝 `D:/...` 路径。精确测试编号和
原因见 `tests/fixtures/baseline/test-baseline.json`。

该结果用于客观冻结，不代表允许生产带病运行。任何权重、模型、路径或技术
失败均不得转换为 `PASS`。

## 7. 失败清单

机器可读清单位于 `Docs/baseline/failure-register.json`，包括：

1. 两份历史权重未出现在工作树。
2. 三组 `outputs/training` 模型全部缺失。
3. Labelme 标注为 0。
4. 极坐标模型版本不兼容。
5. 模型来源证据不完整。
6. 数据清单目录大小写不一致。
7. 处理数据报告含个人机器绝对路径。
8. Pillow 环境版本漂移。
9. 现有测试冻结为失败状态。

## 8. 重复验证

以下命令只读重算全部清单：

```text
python tools/baseline/inventory.py \
  --verify tests/fixtures/baseline/baseline-lock.json
```

连续两次运行必须得到同一稳定摘要并返回成功。任一数量、总字节数、路径、
内容 SHA-256、模型存在性、Git 指针、环境版本或阻断项变化都会失败。
