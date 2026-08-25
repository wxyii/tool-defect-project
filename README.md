# 基于机器视觉的刀具缺陷识别

本目录是整理后的唯一项目入口，包含 180 张图像及对应掩码、108 份 Labelme 缺陷标注、现有分类/双任务权重，以及训练、推理、评估和可视化代码。

## 1. 环境

项目使用本目录下的 Python 3.9 虚拟环境。在 VS Code 的 PowerShell 终端中执行：

```powershell
cd E:\3-刀片缺陷识别系统\tool_defect_project
.\.venv\Scripts\Activate.ps1
python --version
```

也可以不激活环境，直接把命令中的 `python` 替换为：

```powershell
.\.venv\Scripts\python.exe
```

## 2. 使用现有权重推理

分类推理：

```powershell
python -m tool_defect.cli predict `
  --task classification `
  --input data\images\qualified\100.png `
  --output outputs\classification_demo
```

分类—分割双任务推理：

```powershell
python -m tool_defect.cli predict `
  --task multitask `
  --input data\images\unqualified\100.png `
  --output outputs\multitask_demo_100
```

双任务推理会生成：

- `predictions.csv`：分类、置信度和结果文件路径。
- `masks/*.png`：模型输出的原始二值缺陷掩码。
- `visualizations/*_result.png`：中文检测结果图，以红色透明区域、轮廓和编号标明疑似缺陷。

“疑似缺陷”表示模型预测，不等于人工确认。若模型判定不合格但掩码为空，结果图会明确提示“未能定位缺陷区域，请人工复核”，不会虚构缺陷位置。

### 2.1 圆形刀片的环形展开对比

对合格与不合格刀片依次执行内外椭圆定位、斜拍仿射校正、中心和尺度统一、逐角度边界跟踪、环形区域提取及归一化极坐标展开：

```powershell
python -m tool_defect.cli ring-compare `
  --qualified data\images\qualified\21-1.png `
  --unqualified data\images\unqualified\103.png `
  --output outputs\ring_comparison
```

输出目录包含两张单图流程图、`ring_comparison.png` 对比图，以及每张图片对应的 `*_boundary_profiles.csv` 边界曲线。极坐标展开图横轴覆盖完整一周，纵轴采用内外边界之间的归一化径向位置。

### 2.2 极坐标无标签缺陷检测

该检测器复用圆形刀片定位和极坐标展开结果，不读取现有掩码、Labelme 标注、类别清单或已有模型。它利用刀片圆周重复纹样建立图内中位模板，并通过多张无标签图像标定纹理、梯度和外边界偏差的鲁棒尺度。

```powershell
python -m tool_defect.cli polar-cache `
  --input data\images `
  --output outputs\polar_cache

python -m tool_defect.cli polar-fit `
  --input data\images `
  --cache outputs\polar_cache `
  --output artifacts\polar_anomaly

python -m tool_defect.cli polar-detect `
  --input data\images `
  --model artifacts\polar_anomaly `
  --cache outputs\polar_cache `
  --output outputs\polar_detection
```

每个缓存条目包含无损原始展开图 `polar.png`、保边降噪后的
`polar_denoised.png`、边界和仿射参数 `geometry.npz`，以及来源校验信息
`metadata.json`。标定和检测统一先使用降噪图，再进行周期估计和异常特征
计算；降噪时将极坐标横轴按首尾相接处理，避免在 0/360 度接缝引入人工
边缘。原图内容、展开尺寸、角度采样数、环形几何或降噪代码变化时，缓存会
自动失效并重建。缓存命中时，标定不再读取原图像素；检测只为生成原图叠加
结果读取一次原图。

降噪会改变纹理和梯度特征的统计分布。升级后需重新运行 `polar-cache` 和
`polar-fit`，不能继续使用旧版 `polar_anomaly.json` 进行检测。

### 2.3 生成环形区域训练数据集

现有双任务训练入口可以直接读取两种处理后的数据集。生成过程复用同一套
椭圆校正和逐角度边界跟踪，并对原图与掩膜执行完全一致的空间变换；图像
使用线性插值，二值掩膜使用最近邻插值。原清单中的训练、验证、测试划分
保持不变。

生成自适应环形区域数据集：

```powershell
python -m tool_defect.cli ring-dataset `
  --mode adaptive-annular `
  --data-root data `
  --manifest data\manifests\curated_v1_retrain.csv `
  --cache outputs\polar_cache `
  --output data\processed\adaptive_annular
```

生成边界归一化展开数据集：

```powershell
python -m tool_defect.cli ring-dataset `
  --mode boundary-normalized `
  --data-root data `
  --manifest data\manifests\curated_v1_retrain.csv `
  --cache outputs\polar_cache `
  --radial-samples 256 `
  --output data\processed\boundary_normalized
```

每个输出目录包含处理后的 `images/`、同步变换的 `masks/`、
该处理数据集自己的 `manifests/dataset.csv`、逐样本 `manifests/provenance.csv` 和
`generation_report.json`。若任一样本处理失败，或原本含缺陷的掩膜在
变换后变为空，命令会以失败状态结束且不会写入新的训练清单。
原 Labelme 坐标不再适用于变换后的图像，因此不会写入新训练清单，仅在
`provenance.csv` 中保留原标注路径用于追溯。

在边界归一化数据集上生成八方向重叠圆周子图：

```powershell
python -m tool_defect.cli slice-dataset `
  --data-root data\processed\boundary_normalized `
  --manifest data\processed\boundary_normalized\manifests\dataset.csv `
  --output data\processed\boundary_normalized_8patch `
  --slice-count 8 `
  --window-degrees 90 `
  --stride-degrees 45 `
  --min-foreground-pixels 1
```

该命令以 45 度为步长、每次取 90 度窗口，并在圆周接缝处循环取样，
因此一张边界归一化图生成 8 张、相邻子图重叠 50%。输出子图保留
`256×360` 的径向×角度尺寸；现有训练加载器再将其缩放到模型的
`256×256` 输入尺寸。父图像的训练、验证、测试划分整体传递给 8 个子图，
不会发生同一父图跨集合泄漏。

新清单中的分类标签按子图掩膜重新确定：掩膜前景像素数至少为 1 时标为
`unqualified`，否则标为 `qualified`。因此这组实验的分类含义是“局部子图
是否包含缺陷”，不再是“来源刀片是否合格”；父图标签、切片序号、角度范围、
接缝信息和掩膜统计保存在 `manifests/provenance.csv` 中。

在自适应环形数据集上生成同样的八方向重叠扇区：

```powershell
python -m tool_defect.cli slice-dataset `
  --input-mode adaptive-annular `
  --data-root data\processed\adaptive_annular `
  --manifest data\processed\adaptive_annular\manifests\dataset.csv `
  --output data\processed\adaptive_annular_8patch `
  --slice-count 8 `
  --window-degrees 90 `
  --stride-degrees 45 `
  --min-foreground-pixels 1
```

自适应环形图是 `512×512` 的笛卡尔图像，因此每个子图仍保持
`512×512`，只保留对应的 90 度环形扇区，其余像素置黑；8 个子图保留
同一个圆心和原始坐标，便于后续直接合并分割结果。对应的训练配置为
`configs/multitask_adaptive_annular_8patch.json`。

对应的双任务训练配置为
`configs/multitask_boundary_normalized_8patch.json`。对整张刀片做推理时，
需要将 8 个子图的预测聚合到父图级别，例如任一子图检出缺陷时判为不合格，
不能直接把子图级准确率当作整图级准确率。

分别训练两种数据：

```powershell
python -m tool_defect.cli train `
  --task multitask `
  --config configs\multitask_adaptive_annular.json `
  --output outputs\training\multitask_adaptive_annular

python -m tool_defect.cli train `
  --task multitask `
  --config configs\multitask_boundary_normalized.json `
  --output outputs\training\multitask_boundary_normalized
```

在各自保持不变的测试集上评估：

```powershell
python -m tool_defect.cli evaluate `
  --task multitask `
  --config configs\multitask_adaptive_annular.json `
  --model-dir outputs\training\multitask_adaptive_annular `
  --split test `
  --output outputs\evaluation\multitask_adaptive_annular `
  --full-metrics

python -m tool_defect.cli evaluate `
  --task multitask `
  --config configs\multitask_boundary_normalized.json `
  --model-dir outputs\training\multitask_boundary_normalized `
  --split test `
  --output outputs\evaluation\multitask_boundary_normalized `
  --full-metrics
```

## 3. 数据划分

- `data/manifests/curated_v1.csv`：完成标注修正后的 180 张图片清单。
- `data/manifests/curated_v1_retrain.csv`：推荐训练使用的无泄漏清单。
- `data/manifests/curated_v1_retrain_audit.json`：排除和去重审计。

推荐重训练清单从 180 个样本中排除 `unqualified/2.png` 与 `unqualified/16.png` 这组“图像完全相同但掩码冲突”的样本，并去除 6 张完全重复图片，最终保留 172 个样本：

- 训练集：111
- 验证集：27
- 测试集：34

同一文件名家族和完全重复图像不会跨训练、验证、测试集合。

## 4. 重新训练双任务模型

本次专用入口只训练分类—分割双任务模型，不训练分类模型。它直接加载：

```text
artifacts/multitask/model.json
artifacts/multitask/weights.h5
```

旧文件只读保留。所有新实验保存到：

```text
artifacts/multitask_retrained/<实验编号>/
```

正式训练：

```powershell
python -m tool_defect.cli retrain-multitask `
  --config configs\retrain_multitask.json `
  --run-id multitask_retrain_YYYYMMDD_HHMM
```

仅验证训练链路的两阶段冒烟测试：

```powershell
python -m tool_defect.cli retrain-multitask `
  --config configs\retrain_multitask.json `
  --run-id smoke_test `
  --smoke
```

断点权重存在时，可以在同一实验目录重新进入训练流程：

```powershell
python -m tool_defect.cli retrain-multitask `
  --config configs\retrain_multitask.json `
  --resume artifacts\multitask_retrained\<实验编号>
```

训练策略：

- Stage 1：保持现有权重中的冻结状态，学习率 `1e-4`，最多 30 epoch。
- Stage 2：解冻 Xception block11–14 卷积，BatchNorm 保持冻结，学习率 `1e-5`，最多 15 epoch。
- 每批 1 张合格图像和 1 张不合格图像。
- 图像与掩码同步翻转/旋转，图像另做轻微亮度和对比度增强。
- 分类损失：带 `0.05` 标签平滑的交叉熵。
- 分割损失：`0.5 × Focal Tversky + 0.5 × 前景 Focal BCE`。
- 最佳权重按 `0.4 × 验证集分类 ACC + 0.6 × 验证集缺陷 Dice` 保存。

训练终端会逐 epoch 显示总 Loss、分类 Loss/ACC/Precision/Recall，以及缺陷 IoU/Dice/Precision/Recall和相应验证集指标。

每个实验目录包含：

- `model.json`、`weights.h5`：最佳联合分数模型。
- `weights_last.h5`、`stage1_last.h5`、`stage2_last.h5`：断点和阶段末权重。
- `history.csv`、`history.json`：训练历史。
- `config.json`、`manifest.csv`、`environment.txt`、`run_metadata.json`：复现实验所需的配置和审计信息。

## 5. 比较旧模型与新模型

训练结束后，在完全相同的 34 张测试图像上比较：

```powershell
python -m tool_defect.cli compare-multitask `
  --baseline artifacts\multitask `
  --candidate artifacts\multitask_retrained\<实验编号> `
  --manifest data\manifests\curated_v1_retrain.csv `
  --output artifacts\multitask_retrained\<实验编号>\comparison
```

输出包括：

- 分类 ACC、Loss、Precision、Recall、F1。
- 缺陷 IoU、Dice、Precision、Recall、mIoU 和分割 Loss。
- 原模型和新模型的分类/分割混淆矩阵。
- 逐图预测 CSV。
- 配对 Bootstrap 95% 置信区间。
- `COMPARISON_REPORT.md` 和完整 `comparison.json`。

推广门槛为：缺陷 IoU 与 Recall 均至少提高 0.05，且分类 ACC 下降不超过 0.03。未通过时，新权重仍作为实验结果保留，但不会替换默认旧权重。

## 6. 现有权重单独评估

```powershell
python -m tool_defect.cli evaluate `
  --task multitask `
  --model-dir artifacts\multitask `
  --split test `
  --output outputs\evaluation\existing_multitask `
  --full-metrics
```

## 7. 结果解释限制

学校报告中可识别的声称值为：分类 ACC 0.9655、Recall 0.9375、Loss 0.1263，双任务 mIoU 0.8626。学校原始数据划分、完整训练日志和指标实现均缺失，因此本项目可以在当前统一协议下比较现有权重和重训练权重，但不能把结果表述为学校实验的严格同条件复现。
