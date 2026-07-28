# `multitask.py` 全新训练

该流程从 `tool_defect.models.multitask.build_multitask()` 构建模型，不读取
`artifacts/multitask` 或其他旧项目权重。Xception 主干使用通用 ImageNet
权重初始化，分类头、CBAM 和分割头重新随机初始化。

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
`data/manifests/retrain.csv`，正式权重保存在各实验目录的 `weights.h5`；
`weights_last.h5` 仅表示最后一轮。

## 三模型比较

```powershell
python -m tool_defect.cli compare-multitask-suite `
  --previous artifacts\multitask_retrained\multitask_retrain_20260726_2315 `
  --candidate artifacts\multitask_source_trained\<实验编号> `
  --output artifacts\multitask_source_trained\<实验编号>\comparison_suite
```

主结果统一使用 0.50 分割阈值。辅助结果只使用验证集选择阈值，再在测试集
计算一次；测试标签不参与选模或调阈值。
