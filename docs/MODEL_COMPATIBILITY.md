# 模型与权重兼容性核验

## 可直接使用的模型

| 任务 | 架构 | 权重 | 实际输入 | 验证结果 |
|---|---|---|---:|---|
| 分类 | `artifacts/classification/model.json` | `weights.h5` | 299×299×3 | 加载成功，真实图像前向推理成功 |
| 分类—分割 | `artifacts/multitask/model.json` | `weights.h5` | 256×256×3 | 加载成功，分类与掩码前向推理成功 |

推理入口始终优先加载上表的 JSON/H5，并从 JSON 自动读取输入尺寸。

## 整理后源码加载现有权重

| 源码 | 结果 | Keras 报告 |
|---|---|---|
| `models/classifier.py` | 不兼容 | 源码模型 105 个权重层，H5 保存了 104 个 |
| `models/multitask.py` | 不兼容 | 源码模型 118 个权重层，H5 保存了 140 个 |
| `models/multitask_agsfpn_reference.py` | 不兼容 | 源码模型 139 个权重层，H5 保存了 140 个 |

因此现有 JSON/H5 可以用于推理验证，但不能把 H5 直接加载到整理后的训练源码。三份源码用于重新训练；AG+FPN 文件仍明确属于参考实现。现有资料不足以证明任何一份训练源码与 H5 严格同源。

## 已执行验证

- 两组 JSON/H5 均由 TensorFlow 2.13 / Keras 2.13.1 成功加载。
- 分类模型对真实合格图像完成单图推理。
- 双任务模型对真实不合格图像同时生成分类概率和 PNG 掩码。
- 分类与双任务训练源码均在 CPU 上完成 1 epoch、2 个样本、batch size 1 的冒烟训练并保存新 JSON/H5。
