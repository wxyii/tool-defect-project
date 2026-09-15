# 项目现状梳理（2026-09-10）

## 一、项目实现的功能

基于机器视觉的圆形车刀（刀片）缺陷识别，核心是「合格 / 不合格 分类 + 缺陷区域分割」的双任务学习，并附带一条不依赖标签的极坐标异常检测支线。

| 能力 | 说明 | 入口命令 |
|---|---|---|
| 单分类推理 | 只判合格/不合格 | `predict --task classification` |
| 双任务推理 | 分类 + 缺陷掩码 + 中文可视化图 | `predict --task multitask` |
| 环形展开对比 | 内外椭圆定位、仿射校正、极坐标展开 | `ring-compare` |
| 无标签异常检测 | 圆周重复纹样建中位模板，多图标定阈值 | `polar-cache` → `polar-fit` → `polar-detect` |
| 数据预处理 | 生成自适应环形 / 边界归一化整图数据 | `ring-dataset` |
| 分块数据 | 按圆周八方向重叠切片生成子图 | `slice-dataset` |
| 训练 | 原拓扑训练、热启动重训练、ImageNet 冷启动 | `train` / `retrain-multitask` / `train-multitask-source` |
| 评估与对比 | 单模型评估、新旧对比、五模型统一套件 | `evaluate` / `compare-multitask` / `compare-multitask-suite` |

模型骨架：自定义 Xception 骨干（学校原始 `Xception_0.py`）+ CBAM 注意力 + 分类头/分割头；另保留 AG+FPN 参考实现作消融对照。分割损失为 `0.5 × Focal Tversky + 0.5 × 前景 Focal BCE`，专门应对缺陷像素极稀疏的问题。

## 二、目录结构

```text
tool_defect_project/
├─ src/tool_defect/             # 全部源码（39 个模块）
│  ├─ cli.py                    # 14 个子命令的统一入口
│  ├─ config.py                 # 配置加载
│  ├─ data/                     # 清单、掩码转换、环形几何、预处理、环形/分块数据集
│  ├─ detection/                # 极坐标无标签异常检测 + 缓存
│  ├─ models/                   # xception / cbam / attention_gate / multitask / classifier
│  ├─ training/                 # 损失函数、数据序列、三种训练流程
│  ├─ inference/                # 预测与中文可视化
│  └─ evaluation/               # 指标、评估、新旧对比、五模型套件
├─ configs/                     # 9 份配置（5 类数据集各一份 + 重训练 3 份）
├─ data/                        # 数据（图片/掩码/标注/清单/派生数据集）
├─ artifacts/                   # 模型工件（JSON 架构 + H5 权重）
├─ outputs/                     # 推理、评估、缓存等运行产物
├─ tests/                       # 22 个测试模块
├─ tools/                       # 可视化重生成、套件编排等辅助脚本
└─ docs/                        # 文件清单、模型兼容性、ADR、参考资料
```

## 三、数据集情况

### 1. 原始数据（`data/images` + `data/curated_v1`）

| 类别 | 图像 | 掩码 | Labelme 标注 |
|---|---:|---:|---:|
| 合格 qualified | 72 | 72（全为背景） | 0 |
| 不合格 unqualified | 108 | 108 | 108 |
| 合计 | 180 | 180 | 108 |

- 图像分辨率约 3500×3800，共 75 种尺寸；格式以 PNG 为主，另有 26 张 JPG。
- 合格样本掩码全零；不合格掩码缺陷像素占比中位数仅 **0.10%**（最大 0.87%），属于极端稀疏目标，这也是分割召回率长期偏低的数据根因。

### 2. 数据清单（`data/manifests`）

| 清单 | 样本 | 训练 | 验证 | 测试 |
|---|---:|---:|---:|---:|
| `curated_v1.csv` | 180 | 115 | 29 | 36 |
| `curated_v1_retrain.csv` | 172 | 111 | 27 | 34 |

推荐清单排除了 `unqualified/2.png` 与 `16.png` 这一组「图像相同但掩码冲突」样本，并去重 6 张完全重复图像；按文件名家族隔离，保证同族与重复图像不跨集划分（种子 1，分层划分）。

### 3. 派生数据集（`data/processed`，各 512×512）

| 数据集 | 形态 | 样本数 | 说明 |
|---|---|---:|---|
| `adaptive_annular` | 整图 | 172 | 自适应环形区域裁剪 |
| `boundary_normalized` | 整图 | 172 | 边界归一化极坐标展开（径向 256 采样） |
| `adaptive_annular_8patch` | 子图 | 1376 | 172 × 8 个重叠圆周窗口 |
| `boundary_normalized_8patch` | 子图 | 1376 | 同上 |

分块后类别不再平衡（合格子图 949、不合格子图 427），因为子图标签由局部掩码独立判定；每个子图在 `provenance.csv` 中保留父样本溯源与角度窗口信息。

### 4. 无标签支线

`polar-cache` 生成的极坐标缓存（原图展开图、降噪图、几何参数、来源校验）与 `artifacts/polar_anomaly/polar_anomaly.json` 标定结果，不读取任何掩码、标注或已有模型。

## 四、当前实验结论

五类数据集模型在同一批 34 张父图（14 合格 / 20 不合格）上的统一评估结果：

| 数据集模型 | 分类准确率 | 不合格 F1 | 缺陷 IoU | 缺陷 Dice | 综合分 |
|---|---:|---:|---:|---:|---:|
| 原始未预处理 | 88.24% | 89.47% | 4.69% | 8.96% | 28.31 |
| 自适应环形 | 58.82% | 74.07% | 5.95% | 11.22% | 28.83 |
| 边界归一化 | 91.18% | 92.31% | 23.74% | 38.37% | **59.51** |
| 自适应环形分块 | 41.18% | 0.00% | 10.87% | 19.62% | 0.00 |
| 边界归一化分块 | 97.06% | 97.44% | 9.00% | 16.52% | 40.12 |

- 综合最优：`boundary_normalized`（整图），分割指标明显领先。
- 只看分类最优：`boundary_normalized_8patch`，33/34 正确。
- 两种自适应环形模型均出现单类别预测退化，暂不可用。
- 所有模型缺陷 Recall 都偏低（最好 27.30%），尚不能宣称可靠的漏检控制。
- 现有双任务权重在旧的 36 张测试集上：分类 ACC 83.33%，缺陷 Dice 56.16%，缺陷 Recall 45.78%。

## 五、需要留意的现状问题

1. **本地缺少权重文件**：`artifacts/` 下只有 `model.json`，`weights.h5` 不存在（该目录已被 `.gitignore` 忽略）。服务器 `2080ti_no:/data2/dataset/cgp/tool-defect-project/artifacts/` 上有完整权重（双任务 205 MB，以及 `multitask_suite` 下 4 份数据集模型），本地目前无法直接推理或训练。
2. **本地缺正式套件结果**：`outputs/multitask_suite` 只有模拟运行计划，`suite_metrics.json`、`SUITE_REPORT.md` 与 `outputs/polar_cache` 都在服务器上。
3. **冗余数据未清理**：`data_old/`（1171 个文件）、`data.zip`、`data/images.zip`、`data/curated_v1.zip` 与正式数据重复，虽被忽略但仍占用磁盘。
4. **README 笔误**：第 2.3 节示例输出路径写作 `data/processed/daptive_annular`，应为 `adaptive_annular`。
5. **结论稳健性**：测试集仅 34 张，单张图影响约 2.94 个百分点；分割阈值固定 0.5，且保存的是末轮权重而非验证集最优权重。
