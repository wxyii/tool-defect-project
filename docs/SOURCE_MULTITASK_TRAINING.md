# `multitask.py` 全新训练

该流程从 `tool_defect.models.multitask.build_multitask()` 构建模型，不读取
`artifacts/multitask` 或其他旧项目权重。Xception 主干使用通用 ImageNet
权重初始化，分类头、CBAM 和分割头重新随机初始化。权重文件固定从
`artifacts/pretrained/xception/xception_weights_tf_dim_ordering_tf_kernels_notop.h5`
加载，不依赖运行环境的临时缓存。

## 冒烟测试

```powershell
python -m tool_defect.cli train-multitask-source `
  --config configs\train_multitask_source.json `
  --run-id source_smoke `
  --smoke
```

## 正式训练

```powershell
python -m tool_defect.cli train-multitask-source `
  --config configs\train_multitask_source.json `
  --run-id multitask_source_YYYYMMDD_HHMM
```

使用 `--resume artifacts\multitask_source_trained\<实验编号>` 可从该实验的
`weights_last.h5` 继续。默认训练清单是无跨集合重复的
`data/manifests/curated_v1_retrain.csv`，正式权重保存在各实验目录的 `weights.h5`；
`weights.h5` 是按验证集不合格召回率优先选择的最佳权重，
`weights_best_classification.h5` 是其明确文件名，`weights_last.h5` 仅表示最后一轮。

## 三模型比较

```powershell
python -m tool_defect.cli compare-multitask-suite `
  --previous artifacts\multitask_retrained\multitask_retrain_20260726_2315 `
  --candidate artifacts\multitask_source_trained\<实验编号> `
  --output artifacts\multitask_source_trained\<实验编号>\comparison_suite
```

主结果统一使用 0.50 分割阈值。分类选权重优先使用验证集不合格召回率，精确率仅作并列时的次级指标。辅助结果只使用验证集选择阈值，再在测试集
计算一次；测试标签不参与选模或调阈值。
