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

## 圆形刀片的环形展开对比

对合格与不合格刀片依次执行内外椭圆定位、斜拍仿射校正、中心和尺度
统一、逐角度边界跟踪、环形区域提取及归一化极坐标展开：

```powershell
python -m tool_defect.cli ring-compare `
  --qualified data\images\Qualified\21-1.png `
  --unqualified data\images\Unqualified\103.png `
  --output outputs\ring_comparison
```

不传图像参数时会使用上述两张代表性样本。输出目录包含两张单图流程图、
`ring_comparison.png` 对比图，以及每张图片对应的
`*_boundary_profiles.csv` 边界曲线。对比图中的所有刀片都具有相同的外圆
半径；极坐标展开图横轴覆盖完整一周，纵轴采用内外边界之间的归一化径向
位置，因此斜拍和残余定位误差不会使边界呈波浪形。边界曲线文件仍保留原始
边缘起伏及其相对平滑边界的残差，可用于检测崩边和缺口。

## 极坐标无标签缺陷检测

新检测器只复用圆形刀片定位和极坐标展开结果，不读取现有掩码、
Labelme 标注、类别清单、目录类别名称或已有模型。它先利用同一刀片的
圆周重复纹样建立图内中位模板，再使用多张无标签图像标定纹理、梯度和
外边界偏差的鲁棒尺度。

使用全部原图建立无标签标定模型：

```powershell
python -m tool_defect.cli polar-cache `
  --input data\images `
  --output outputs\polar_cache

python -m tool_defect.cli polar-fit `
  --input data\images `
  --cache outputs\polar_cache `
  --output artifacts\polar_anomaly
```

检测单张图或整个目录：

```powershell
python -m tool_defect.cli polar-detect `
  --input data\images `
  --model artifacts\polar_anomaly `
  --cache outputs\polar_cache `
  --output outputs\polar_detection
```

每个缓存条目包含无损 `polar.png`、边界和仿射参数
`geometry.npz`，以及来源校验信息 `metadata.json`。原图内容、展开尺寸、
角度采样数或环形几何代码变化时，缓存会自动失效并重建。缓存命中时，
标定不再读取原图像素；检测只为生成原图叠加结果读取一次原图。

标定目录会生成 `polar_anomaly.json` 和 `calibration_report.json`。
检测目录会生成：

- `predictions.csv`：逐图处理状态、连续异常分数、周期数和候选区数量。
- `regions.csv`：候选区角度范围、径向范围、面积、峰值和平均分数。
- `heatmaps/`：极坐标异常热力图。
- `polar_overlays/`：在展开图上标出的候选区域。
- `source_overlays/`：利用仿射逆变换回映到原图的候选区域。
- `detection_report.json`：成功率、分数分布和最高分图像列表。

径向位置零表示外缘、一表示内缘。阈值只用于从连续分数中筛选便于复核的
疑似区域，不是合格或不合格分类。没有独立人工真值时，不应把检测报告解释
为精确率、召回率或缺陷类别评估。

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
