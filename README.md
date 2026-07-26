# 基于机器视觉的车刀缺陷识别

本目录是项目唯一复现入口，包含180张图像及对应掩码、82份Labelme标注、现有分类与双任务权重，以及整理后的训练、推理和评估代码。

## 关键结论

- 推理优先加载 `model.json + weights.h5`。分类权重实际输入为299×299，双任务权重为256×256，程序会自动读取尺寸。
- `models/classifier.py` 和 `models/multitask.py` 用于重新训练；`models/multitask_agsfpn_reference.py` 是参考实现。
- 数据采用固定随机种子1的分层划分：115张训练、29张验证、36张测试。这不代表学校原实验划分。
- 现有源码与H5不能按拓扑直接加载，已有JSON/H5用于推理和独立评估，整理后源码用于重新训练。

## 环境

环境已创建在 `.venv`。在PowerShell中运行：

```powershell
.\.venv\Scripts\Activate.ps1
python --version
```

重新创建环境时使用：

```powershell
C:\Users\Administrator\AppData\Local\Programs\Python\Python39\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
```

## 数据检查与推理

```powershell
python -m tool_defect.cli data-check

python -m tool_defect.cli predict `
  --task classification `
  --input data\images\qualified\100.png `
  --output outputs\classification_demo

python -m tool_defect.cli predict `
  --task multitask `
  --input data\images\unqualified\1.png `
  --output outputs\multitask_demo
```

双任务推理会同时生成：

- `predictions.csv`：分类结果、概率和输出文件路径。
- `masks/*.png`：模型直接产生的原始二值掩码，用于复核和后续计算。
- `visualizations/*_result.png`：最大边不超过1600像素的中文检测结果图。

检测结果图以半透明红色区域、红色轮廓和编号标出模型定位的疑似缺陷，并显示“合格/不合格”、分类置信度及人工复核提示。显示过程可能过滤极小的孤立噪点，但不会修改 `masks` 中保存的原始掩码。“疑似缺陷”表示模型预测，不等同于人工确认。

如果模型判定不合格但分割掩码为空，结果图会明确显示“未能定位缺陷区域，请人工复核”，不会人为补画缺陷位置。

## 完整指标评估

分类权重：

```powershell
python -m tool_defect.cli evaluate `
  --task classification `
  --model-dir artifacts\classification `
  --split test `
  --output outputs\evaluation\existing_classification `
  --full-metrics
```

双任务权重：

```powershell
python -m tool_defect.cli evaluate `
  --task multitask `
  --model-dir artifacts\multitask `
  --split test `
  --output outputs\evaluation\existing_multitask `
  --full-metrics
```

评估会生成：

- `metrics.json`：ACC、Recall、Precision、F1、标准化交叉熵Loss；双任务还包含IoU、Dice和像素准确率。
- `predictions.csv`：逐图预测；双任务额外包含逐图缺陷IoU/Dice。
- `classification_confusion_matrix.csv/png`：分类混淆矩阵。
- `segmentation_confusion_matrix.csv/png`：双任务像素混淆矩阵。

这里的Loss是按当前统一定义重新计算的标准化交叉熵，不等同于学生原训练日志中的Loss。

## 训练

```powershell
python -m tool_defect.cli train --task classification --config configs\default.json
python -m tool_defect.cli train --task multitask --config configs\default.json
```

训练入口支持 `--epochs`、`--batch-size`、`--max-samples` 和 `--output` 覆盖参数。完整训练需要较长时间和合适的计算资源。

## 资料限制

现有资料缺少学校原始数据划分、完整训练日志、确定的类别目录顺序，以及源码与权重严格对应的证明。因此可以验证现有权重在当前测试协议下的表现，但不能据此证明学生历史报告中的指标完全真实。
