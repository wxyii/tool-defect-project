# 刀具缺陷推理可视化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变模型权重、推理结果和原始掩码的前提下，为双任务推理生成醒目、准确、体积可控的中文缺陷检测结果图。

**Architecture:** `predict.py` 保持模型推理和原始结果保存职责；`visualize.py` 作为纯可视化边界，接收原图、二值掩码、分类和置信度，生成缩放后的中文结果图。显示掩码与原始掩码分离，连通域过滤只影响展示。

**Tech Stack:** Python 3.9、NumPy、OpenCV、Pillow、unittest。

## Global Constraints

- 原始二值掩码必须原样保存，任何显示过滤不得回写输入数组。
- 结果图最大边为 1600 像素，较小图像不放大。
- 默认过滤面积小于 12 个模型像素的孤立连通域。
- 中文优先使用 `C:\Windows\Fonts\msyh.ttc`，找不到中文字体时明确报错。
- 不使用膨胀操作，不虚构缺陷位置。
- 分类模式的现有输出行为保持不变。
- 当前仓库 `.git` 对本执行环境只读，各任务以测试检查点替代提交。

---

### Task 1: 建立可视化行为测试

**Files:**
- Create: `tests/test_visualize.py`
- Test: `tests/test_visualize.py`

**Interfaces:**
- Consumes: `overlay_defect_on_image(original_path, defect_mask, predicted_class, confidence, output_path, overlay_alpha=0.38, max_dimension=1600, min_component_area=12, font_path=None) -> Path`
- Produces: 可验证的中文结果图行为契约。

- [ ] **Step 1: 编写尺寸、掩码不可变和红色定位测试**

构造 2000×1000 灰色图片和含一个 40×40 缺陷块的 256×256 掩码，调用可视化后断言：

```python
self.assertEqual((800, 1600), rendered.shape[:2])
np.testing.assert_array_equal(mask, original_mask)
self.assertGreater(int(red_pixels.sum()), 0)
```

- [ ] **Step 2: 编写噪声过滤和状态文案测试**

分别构造有效缺陷、单像素噪点、空掩码以及分类/分割冲突，直接测试状态构建接口：

```python
self.assertIn("检测到 1 处疑似缺陷", status.text)
self.assertIn("未能定位缺陷区域，请人工复核", empty_status.text)
self.assertIn("分类与定位结果不一致，请人工复核", conflict.text)
```

- [ ] **Step 3: 编写中文路径、中文像素和字体缺失测试**

使用带中文目录的临时文件，断言输出存在且信息栏不是纯黑；显式传入不存在字体路径时断言：

```python
with self.assertRaisesRegex(FileNotFoundError, "中文字体"):
    overlay_defect_on_image(
        original_path=image_path,
        defect_mask=mask,
        predicted_class="unqualified",
        confidence=0.9,
        output_path=output_path,
        font_path=missing_font,
    )
```

- [ ] **Step 4: 运行测试确认按预期失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_visualize -v
```

Expected: FAIL，原因是新的状态接口、尺寸限制或中文输出尚未实现。

---

### Task 2: 实现独立、可测试的中文可视化模块

**Files:**
- Modify: `src/tool_defect/inference/visualize.py`
- Test: `tests/test_visualize.py`

**Interfaces:**
- Produces: `VisualizationStatus(text: str, color_bgr: tuple, component_count: int)`
- Produces: `build_visualization_status(predicted_class, confidence, raw_has_defect, component_count) -> VisualizationStatus`
- Produces: `overlay_defect_on_image(original_path, defect_mask, predicted_class, confidence, output_path, overlay_alpha=0.38, max_dimension=1600, min_component_area=12, font_path=None) -> Path`

- [ ] **Step 1: 实现输入验证和中文字体解析**

限定分类名称为 `qualified` 或 `unqualified`，置信度在 `[0, 1]`，掩码必须是二维数组。字体候选顺序固定为：

```python
FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
)
```

- [ ] **Step 2: 实现模型坐标中的连通域过滤**

使用 `cv2.connectedComponentsWithStats`，保留面积大于等于 `min_component_area` 的区域并返回按面积降序排列的组件信息。复制输入掩码，禁止原地修改。

- [ ] **Step 3: 实现确定性中文状态映射**

`build_visualization_status` 只接受经过验证的枚举和值，严格输出设计文档中的四种状态，以及仅有微小区域时的人工复核提示。

- [ ] **Step 4: 实现缩放、红色覆盖、轮廓和编号**

先将原图等比例缩放到最大边 1600，再用最近邻插值缩放显示掩码。红色覆盖透明度为 0.38；轮廓线宽根据结果尺寸缩放；编号按组件面积从大到小生成。

- [ ] **Step 5: 使用 Pillow 绘制中文信息栏和图例**

将 OpenCV BGR 图像转换为 Pillow RGB，使用微软雅黑绘制顶部状态栏和底部图例，再转回 BGR 保存 PNG。

- [ ] **Step 6: 运行可视化测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_visualize -v
```

Expected: 所有新增测试 PASS，无乱码、异常或警告。

---

### Task 3: 把结果图安全接入双任务推理

**Files:**
- Modify: `src/tool_defect/inference/predict.py`
- Modify: `tests/test_inference.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 2 的 `overlay_defect_on_image`
- Produces: `visualizations/0000_<stem>_result.png`
- Produces: `predictions.csv` 的 `visualization_path` 字段。

- [ ] **Step 1: 扩展推理集成测试并确认失败**

在真实双任务权重测试中断言：

```python
visualization_path = output_dir / row["visualization_path"]
self.assertTrue(visualization_path.is_file())
self.assertTrue(visualization_path.name.endswith("_result.png"))
self.assertLessEqual(max(rendered.shape[:2]), 1600)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_inference.InferenceTests.test_supplied_multitask_weights_write_classification_and_mask -v
```

Expected: FAIL，因为当前文件名和尺寸行为不满足新契约。

- [ ] **Step 2: 最小修改双任务输出命名和异常上下文**

将可视化文件名改为 `0000_<stem>_result.png`。可视化异常包装为：

```python
raise RuntimeError(
    f"failed to create visualization for {image_path}: {error}"
) from error
```

分类任务继续写空的 `visualization_path`。

- [ ] **Step 3: 运行推理和 CLI 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_inference tests.test_cli -v
```

Expected: PASS，原始掩码、CSV 和结果图同时生成。

---

### Task 4: 文档、真实样本验收与完整回归

**Files:**
- Modify: `README.md`
- Create: `outputs/multitask_demo_100/visualizations/0000_100_result.png`
- Verify: `outputs/multitask_demo_100/masks/0000_100.png`
- Verify: `outputs/multitask_demo_100/predictions.csv`

**Interfaces:**
- Consumes: 完整的 CLI `python -m tool_defect.cli predict`
- Produces: 用户可直接查看的中文检测结果图和复现命令。

- [ ] **Step 1: 更新 README 输出说明**

说明原始掩码与结果图的区别、中文提示含义，以及“疑似缺陷”不是人工确认。

- [ ] **Step 2: 运行用户提供的真实命令**

Run:

```powershell
python -m tool_defect.cli predict `
  --task multitask `
  --input "data\images\unqualified\100.png" `
  --output "outputs\multitask_demo_100"
```

Expected: exit code 0，CSV、原始掩码和中文结果图均存在。

- [ ] **Step 3: 检查结果图尺寸、体积和可读性**

断言最大边不超过 1600，文件能被 OpenCV 解码，文件体积低于当前约 30 MB，并进行一次人工视觉检查。

- [ ] **Step 4: 分组运行完整回归测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_visualize tests.test_cli tests.test_config tests.test_datasets tests.test_inference tests.test_manifest tests.test_mask_conversion tests.test_metrics tests.test_model_loading tests.test_preprocess -v
.\.venv\Scripts\python.exe -m unittest tests.test_model_builders -v
.\.venv\Scripts\python.exe -m unittest tests.test_workflows.WorkflowTests.test_supplied_classification_model_evaluates_real_validation_samples tests.test_workflows.WorkflowTests.test_supplied_multitask_model_evaluates_both_outputs -v
.\.venv\Scripts\python.exe -m unittest tests.test_workflows.WorkflowTests.test_classifier_runs_one_epoch_and_writes_new_artifacts -v
.\.venv\Scripts\python.exe -m unittest tests.test_workflows.WorkflowTests.test_multitask_runs_one_epoch_and_writes_new_artifacts -v
```

Expected: 所有测试退出码均为 0。

- [ ] **Step 5: 运行依赖、语法和路径检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import ast,pathlib; files=[p for r in ('src','tests') for p in pathlib.Path(r).rglob('*.py')]; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(len(files))"
```

Expected: 无损坏依赖，所有 Python 文件语法解析通过。
