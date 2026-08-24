# Multitask Retraining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrain only the classification-segmentation multitask artifact from the supplied JSON/H5 weights, preserve the original artifact, and produce reproducible metrics and comparison evidence.

**Architecture:** A leakage-aware manifest builder produces a new immutable experiment split without changing `curated_v1.csv`. A balanced Keras `Sequence` loads one qualified and one unqualified sample per batch and applies synchronized image/mask geometry plus mild image-only photometric augmentation. A dedicated two-stage retrainer loads the supplied artifact topology, trains frozen heads and then Xception blocks 11-14 (BatchNorm kept frozen), saves complete experiment provenance, and evaluates old and new artifacts on the same held-out test set.

**Tech Stack:** Python 3.9, TensorFlow/Keras 2.13, NumPy 1.24, scikit-learn 1.3, OpenCV/Pillow, standard-library `unittest`.

## Global Constraints

- Train only the multitask model; do not train or overwrite the classification model.
- Load initial architecture and weights from `artifacts/multitask/model.json` and `artifacts/multitask/weights.h5`.
- Write every run beneath `artifacts/multitask_retrained/<run_id>/`; never replace `artifacts/multitask`.
- Preserve `data/manifests/curated_v1.csv`; write the leakage-aware split to `data/manifests/curated_v1_retrain.csv`.
- Use input size 256x256, batch size 2, random seed 1, CPU-compatible TensorFlow 2.13.
- Exclude the conflicting exact-image pair `unqualified/2.png` and `unqualified/16.png`.
- Deduplicate exact qualified images and keep filename families such as `21-*`, `22-*`, `35-*`, and `37-*` in one split.
- Do not claim strict reproduction of school metrics because its original split, logs, and metric definitions are unavailable.

---

### Task 1: Leakage-aware retraining manifest

**Files:**
- Create: `src/tool_defect/data/retrain_manifest.py`
- Create: `tests/test_retrain_manifest.py`
- Create after verification: `data/manifests/curated_v1_retrain.csv`

**Interfaces:**
- Consumes: original `data/manifests/curated_v1.csv`, files below `data/`.
- Produces: `build_retrain_manifest(source_manifest, data_root, seed=1, validation_fraction=0.16, test_fraction=0.20) -> tuple[list[dict], dict]` and `write_retrain_manifest(rows, destination)`.

- [ ] Write tests proving that conflicting samples are excluded, exact duplicates cannot cross splits, related filename families remain grouped, both classes occur in every split, and output is deterministic.
- [ ] Run `.\.venv\Scripts\python.exe -m unittest tests.test_retrain_manifest -v` and confirm failures are caused by the missing module.
- [ ] Implement SHA-256 image grouping, canonical family keys, deterministic group-stratified allocation, and an audit dictionary containing source/excluded/deduplicated/final/split counts.
- [ ] Run the new tests and the existing manifest tests.
- [ ] Generate `data/manifests/curated_v1_retrain.csv` plus `data/manifests/curated_v1_retrain_audit.json` and inspect counts and cross-split hashes.

### Task 2: Defect-aware losses and terminal metrics

**Files:**
- Create: `src/tool_defect/training/objectives.py`
- Create: `tests/test_training_objectives.py`

**Interfaces:**
- Produces: `focal_tversky_loss`, `foreground_focal_bce`, `combined_segmentation_loss`, `DefectIoU`, `DefectDice`, `DefectPrecision`, and `DefectRecall`.

- [ ] Write tests using tiny hand-computable masks to verify perfect predictions approach zero loss/one metric, missed defect increases loss and lowers recall, and empty qualified masks remain finite.
- [ ] Run the objective test and confirm it fails because the module does not exist.
- [ ] Implement focal Tversky with alpha 0.3, beta 0.7, gamma 0.75; foreground focal BCE; and the combined 0.5/0.5 segmentation loss.
- [ ] Implement stateful foreground confusion-count metrics with stable division.
- [ ] Run objective and existing metric tests.

### Task 3: Balanced synchronized augmentation sequence

**Files:**
- Create: `src/tool_defect/training/sequence.py`
- Create: `tests/test_training_sequence.py`

**Interfaces:**
- Consumes: manifest path, data root, split, image size, seed, augmentation flags.
- Produces: `BalancedMultitaskSequence`, returning `(images, {"cla_out": labels, "seg_out": masks})`.

- [ ] Write tests proving every training batch contains one sample of each class, image and mask receive the same flips/90-degree rotation, validation is deterministic and unaugmented, and batch tensors have expected shapes/dtypes.
- [ ] Run the sequence tests and confirm failures are caused by the missing class.
- [ ] Implement deterministic epoch shuffling and oversampling of the smaller class without mutating source rows.
- [ ] Implement horizontal/vertical flips and rotations for image/mask, then mild brightness/contrast only for the image.
- [ ] Run sequence, dataset, and preprocessing tests.

### Task 4: Two-stage retraining engine and provenance

**Files:**
- Create: `src/tool_defect/training/retrain_multitask.py`
- Modify: `src/tool_defect/models/loader.py`
- Modify: `src/tool_defect/cli.py`
- Create: `configs/retrain_multitask.json`
- Create: `tests/test_retrain_multitask.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `retrain_multitask(config_path, init_model_dir, output_root, run_id=None, smoke=False, resume=None) -> Path`.
- CLI: `python -m tool_defect.cli retrain-multitask --config configs/retrain_multitask.json [--smoke] [--run-id ID] [--resume PATH]`.

- [ ] Write tests proving warm-start loads the exact supplied topology, Stage 1 preserves the existing trainable mask, Stage 2 only unfreezes Xception blocks 11-14 convolutional layers while keeping BatchNorm frozen, and a smoke run creates all required files without touching the supplied artifact.
- [ ] Run retraining and CLI tests and confirm expected failures.
- [ ] Add optional explicit weights filename support to `load_saved_model`.
- [ ] Implement compilation with classification categorical cross-entropy with label smoothing 0.05, combined segmentation loss, fixed 1:1 task weights, classification accuracy/precision/recall and defect metrics.
- [ ] Implement Stage 1 at learning rate 1e-4 for at most 30 epochs with patience 8, followed by Stage 2 at 1e-5 for at most 15 epochs with patience 5; smoke mode uses one epoch and one step per stage.
- [ ] Implement CSV logs, last weights, resumable stage checkpoints, `ReduceLROnPlateau(factor=0.5, patience=4, min_lr=1e-7)`, and a best-checkpoint callback using `0.4 * val_cla_out_accuracy + 0.6 * val_seg_out_defect_dice`.
- [ ] Save `model.json`, `weights.h5`, `weights_last.h5`, `history.csv`, `history.json`, `config.json`, `manifest.csv`, `environment.txt`, and `run_metadata.json` in the run directory.
- [ ] Run retraining and CLI tests.

### Task 5: Same-test-set comparison and confidence intervals

**Files:**
- Create: `src/tool_defect/evaluation/compare_multitask.py`
- Create: `tests/test_compare_multitask.py`
- Modify: `src/tool_defect/cli.py`

**Interfaces:**
- Produces: `compare_multitask_models(config_path, manifest_path, baseline_model_dir, candidate_model_dir, output_dir, bootstrap_samples=1000, seed=1) -> dict`.
- CLI: `python -m tool_defect.cli compare-multitask --baseline artifacts/multitask --candidate <run_dir> --manifest data/manifests/curated_v1_retrain.csv --output <run_dir>/comparison`.

- [ ] Write tests proving both models use the exact same test row order, metric deltas have candidate-minus-baseline sign, bootstrap output is deterministic, and report files are created.
- [ ] Run the comparison tests and confirm expected failures.
- [ ] Reuse the existing metric implementations for ACC, cross-entropy loss, class precision/recall/F1 and segmentation IoU/Dice/precision/recall.
- [ ] Add deterministic 95% sample-level bootstrap intervals and save both confusion matrices, per-image predictions, `comparison.json`, and concise `COMPARISON_REPORT.md`.
- [ ] Record school claims (ACC 0.9655, Recall 0.9375, Loss 0.1263, mIoU 0.8626) in a clearly labelled non-equivalent reference section.
- [ ] Run comparison, metric, evaluation, and CLI tests.

### Task 6: Verification, full training, and final evaluation

**Files:**
- Modify: `README.md`
- Create at runtime: `artifacts/multitask_retrained/<run_id>/...`

**Interfaces:**
- Consumes all prior tasks.
- Produces a completed run directory and comparison evidence.

- [ ] Run `python -m compileall src tests`.
- [ ] Run the complete `unittest` suite with a timeout sufficient for TensorFlow model tests.
- [ ] Run a two-stage smoke retraining and one candidate prediction.
- [ ] Verify the SHA-256 values of `artifacts/multitask/model.json` and `weights.h5` are unchanged.
- [ ] Start the full CPU retraining with a timestamped run id and logs inside that run.
- [ ] Monitor epoch logs, checkpoint creation, finite losses, and validation metrics; stop if NaN/Inf or repeated hard failure occurs.
- [ ] Evaluate best retrained weights against the original artifact on `curated_v1_retrain.csv` test rows.
- [ ] Apply the promotion rule: defect IoU and recall must each improve by at least 0.05 while classification ACC decreases by no more than 0.03; otherwise retain the result as experimental and keep the original default.
- [ ] Update `README.md` with exact reproduction, resume, inference, and comparison commands.

## Self-review

- Spec coverage: only multitask training, old-weight preservation, warm start, clean split, augmentation, two-stage fine-tuning, checkpoints, terminal metrics, artifact provenance, old/new comparison, school-claim context, and promotion gate are all mapped to Tasks 1-6.
- Placeholder scan: no TBD/TODO/future implementation placeholders remain.
- Type consistency: retraining and comparison commands consume the same run directory containing `model.json` and best `weights.h5`; `curated_v1_retrain.csv` uses the existing public manifest schema.
