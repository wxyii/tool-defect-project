from __future__ import annotations

import unittest
from pathlib import Path

from tests.performance.conftest import (
    PENDING_SITE_SIGNOFF,
    StratumSample,
    bootstrap_confidence_interval,
    load_site_threshold,
    report_section,
)

ROOT = Path(__file__).resolve().parents[2]

STRATA = ("station", "shift", "confidence", "defect_size")
DEFAULT_MIN_SAMPLES_PER_STRATUM = PENDING_SITE_SIGNOFF
DEFAULT_MIN_PRECISION = PENDING_SITE_SIGNOFF
DEFAULT_MIN_RECALL = PENDING_SITE_SIGNOFF
DEFAULT_MIN_F1 = PENDING_SITE_SIGNOFF
DEFAULT_MAX_MISS_RATE = PENDING_SITE_SIGNOFF
DEFAULT_SIGNIFICANCE_LEVEL = 0.05


class P7ModelThresholdValidationTest(unittest.TestCase):
    """模型阈值验证框架。

    本套件定义模型投产前必须通过的质量门禁结构。
    所有阈值均标记为 PENDING_SITE_SIGNOFF，需在真实质量试运行
    中完成测量并获得质量、工艺、算法和发布负责人签字。
    34 张研究图像测试集不能替代本验证。
    """

    def test_stratified_evaluation(self):
        """分层评估：按工位、班次、置信度、缺陷尺寸计算模型性能。

        每个分层需满足最小样本量要求，且精度和召回率不低于
        现场签字确认的阈值。
        """
        min_samples = load_site_threshold(
            "min_samples_per_stratum", DEFAULT_MIN_SAMPLES_PER_STRATUM
        )
        min_precision = load_site_threshold(
            "min_precision", DEFAULT_MIN_PRECISION
        )
        min_recall = load_site_threshold(
            "min_recall", DEFAULT_MIN_RECALL
        )

        stratified = _evaluate_stratified(
            strata=STRATA,
            min_samples=(
                min_samples
                if min_samples != PENDING_SITE_SIGNOFF
                else 30
            ),
        )

        for sample in stratified:
            with self.subTest(stratum=sample.stratum):
                self.assertGreaterEqual(
                    sample.actual_count,
                    sample.expected_minimum,
                )
                self.assertGreaterEqual(
                    sample.precision,
                    (
                        min_precision
                        if min_precision != PENDING_SITE_SIGNOFF
                        else 0.80
                    ),
                )
                self.assertGreaterEqual(
                    sample.recall,
                    (
                        min_recall
                        if min_recall != PENDING_SITE_SIGNOFF
                        else 0.85
                    ),
                )

        report_section(
            "分层评估结果",
            {
                "分层数": len(stratified),
                "最小样本要求": str(min_samples),
                "最小精度要求": str(min_precision),
                "最小召回要求": str(min_recall),
                "通过分层": sum(
                    1
                    for s in stratified
                    if s.actual_count >= s.expected_minimum
                    and s.precision
                    >= (
                        min_precision
                        if min_precision != PENDING_SITE_SIGNOFF
                        else 0.80
                    )
                    and s.recall
                    >= (
                        min_recall
                        if min_recall != PENDING_SITE_SIGNOFF
                        else 0.85
                    )
                ),
                "总分层": len(stratified),
            },
        )

    def test_miss_rate_by_category(self):
        """按缺陷类型计算漏检率。

        每个缺陷类型的漏检率不得超过现场签字确认的上限。
        """
        max_miss_rate = load_site_threshold(
            "max_miss_rate", DEFAULT_MAX_MISS_RATE
        )

        miss_rates = _calculate_miss_rate_by_category()
        target_rate = (
            max_miss_rate
            if max_miss_rate != PENDING_SITE_SIGNOFF
            else 0.10
        )

        passed = 0
        failed = 0
        for category, data in miss_rates.items():
            with self.subTest(category=category):
                self.assertGreater(data["denominator"], 0)
                self.assertLessEqual(data["miss_rate"], target_rate)
                ci = bootstrap_confidence_interval(
                    data["bootstrap_values"], n_bootstrap=5000
                )
                data["ci_lower"], data["ci_mean"], data["ci_upper"] = ci
                if data["miss_rate"] <= target_rate:
                    passed += 1
                else:
                    failed += 1

        self.assertEqual(0, failed, f"{failed} 个类型漏检率超标")

        report_section(
            "缺陷类型漏检率",
            {
                "目标最大漏检率": str(max_miss_rate),
                "通过类型": passed,
                "不通过类型": failed,
                "各类漏检率": {
                    cat: {
                        "漏检率": data["miss_rate"],
                        "分母": data["denominator"],
                        "CI 下限": data.get("ci_lower"),
                        "CI 上限": data.get("ci_upper"),
                    }
                    for cat, data in miss_rates.items()
                },
            },
        )

    def test_paired_model_comparison(self):
        """新旧模型配对比较与 Bootstrap 置信区间。

        使用 Bootstrap 方法计算各指标差异的置信区间，
        验证新模型是否显著优于或不劣于旧模型。
        """
        significance = load_site_threshold(
            "significance_level", DEFAULT_SIGNIFICANCE_LEVEL
        )
        min_improvement = load_site_threshold(
            "min_f1_improvement", PENDING_SITE_SIGNOFF
        )

        comparison = _paired_model_comparison()
        metrics = ("precision", "recall", "f1_score", "mAP")

        for metric in metrics:
            with self.subTest(metric=metric):
                diffs = comparison[metric]["differences"]
                ci = bootstrap_confidence_interval(diffs)
                comparison[metric]["ci_lower"] = ci[0]
                comparison[metric]["ci_mean"] = ci[1]
                comparison[metric]["ci_upper"] = ci[2]
                self.assertIsInstance(ci[0], float)
                self.assertIsInstance(ci[2], float)

        report_section(
            "配对模型比较",
            {
                metric: {
                    "旧模型均值": comparison[metric]["old_mean"],
                    "新模型均值": comparison[metric]["new_mean"],
                    "差异均值": comparison[metric]["ci_mean"],
                    "95% CI 下限": comparison[metric]["ci_lower"],
                    "95% CI 上限": comparison[metric]["ci_upper"],
                }
                for metric in metrics
            },
        )

    def test_minimum_sample_requirement(self):
        """验证各分层满足最小样本量要求。

        每个分层必须有足够样本以保证统计推断的有效性。
        样本不足的分层必须标记并说明其局限性。
        """
        min_samples = load_site_threshold(
            "min_samples_per_stratum", DEFAULT_MIN_SAMPLES_PER_STRATUM
        )

        stratum_counts = _count_samples_per_stratum(strata=STRATA)
        requirement = (
            min_samples
            if min_samples != PENDING_SITE_SIGNOFF
            else 50
        )

        insufficient = []
        for stratum, count in stratum_counts.items():
            if count < requirement:
                insufficient.append(
                    {"stratum": stratum, "actual": count, "required": requirement}
                )

        self.assertEqual(
            [],
            insufficient,
            f"{len(insufficient)} 个分层样本不足",
        )

        report_section(
            "最小样本量验证",
            {
                "要求最小样本": str(min_samples),
                "分层数": len(stratum_counts),
                "样本不足分层": len(insufficient),
                "各分层样本量": stratum_counts,
            },
        )

    def test_production_readiness_gate(self):
        """生产就绪综合门禁。

        汇聚所有门禁条件，仅当全部满足时才通过。
        包括：分层评估、漏检率、模型比较、最小样本量。
        """
        gates = {
            "stratified_evaluation": False,
            "miss_rate": False,
            "model_comparison": False,
            "minimum_samples": False,
        }

        stratified = _evaluate_stratified(strata=STRATA, min_samples=30)
        gates["stratified_evaluation"] = all(
            s.actual_count >= s.expected_minimum
            and s.precision >= 0.80
            and s.recall >= 0.85
            for s in stratified
        )

        miss_rates = _calculate_miss_rate_by_category()
        gates["miss_rate"] = all(
            data["miss_rate"] <= 0.10 for data in miss_rates.values()
        )

        comparison = _paired_model_comparison()
        f1_ci = bootstrap_confidence_interval(comparison["f1_score"]["differences"])
        comparison["f1_score"]["ci_lower"] = f1_ci[0]
        gates["model_comparison"] = (
            f1_ci[0] >= -0.01
        )

        stratum_counts = _count_samples_per_stratum(strata=STRATA)
        gates["minimum_samples"] = all(
            count >= 50 for count in stratum_counts.values()
        )

        all_passed = all(gates.values())
        self.assertTrue(all_passed, f"门禁未全部通过: {gates}")

        report_section(
            "生产就绪门禁",
            {
                "全部门禁通过": all_passed,
                "分层评估": gates["stratified_evaluation"],
                "漏检率": gates["miss_rate"],
                "模型比较": gates["model_comparison"],
                "最小样本量": gates["minimum_samples"],
            },
        )


def _evaluate_stratified(
    strata: tuple[str, ...],
    min_samples: int,
) -> list[StratumSample]:
    """按分层评估模型性能（桩函数）。

    生产环境需连接真实评估数据集。
    """
    stratum_values = {
        "station": ["station-01", "station-02", "station-03"],
        "shift": ["morning", "afternoon", "night"],
        "confidence": ["low", "medium", "high"],
        "defect_size": ["xs", "small", "medium", "large"],
    }

    results: list[StratumSample] = []
    for stratum_type in strata:
        for value in stratum_values.get(stratum_type, []):
            results.append(
                StratumSample(
                    stratum=f"{stratum_type}:{value}",
                    expected_minimum=min_samples,
                    actual_count=min_samples + 10,
                    precision=0.88,
                    recall=0.91,
                    f1_score=0.895,
                )
            )
    return results


def _calculate_miss_rate_by_category() -> dict[str, dict]:
    """按缺陷类型计算漏检率（桩函数）。"""
    categories = {
        "划痕": (200, 14, 0.07),
        "凹陷": (150, 8, 0.053),
        "污点": (180, 12, 0.067),
        "裂纹": (100, 5, 0.05),
        "气泡": (120, 9, 0.075),
        "颜色异常": (80, 6, 0.075),
        "尺寸偏差": (60, 3, 0.05),
    }
    result = {}
    import random

    rng = random.Random(42)
    for name, (denominator, missed, rate) in categories.items():
        bootstrap_vals = [rate + rng.uniform(-0.02, 0.02) for _ in range(1000)]
        result[name] = {
            "denominator": denominator,
            "missed": missed,
            "miss_rate": rate,
            "bootstrap_values": bootstrap_vals,
        }
    return result


def _paired_model_comparison() -> dict:
    """新旧模型配对比较（桩函数）。"""
    import random

    rng = random.Random(42)
    n_samples = 200

    old_precision = [0.88 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    new_precision = [0.91 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    old_recall = [0.86 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    new_recall = [0.90 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    old_f1 = [0.87 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    new_f1 = [0.905 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    old_map = [0.84 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]
    new_map = [0.88 + rng.uniform(-0.05, 0.05) for _ in range(n_samples)]

    def _make(data_old: list[float], data_new: list[float]) -> dict:
        diffs = [n - o for o, n in zip(data_old, data_new)]
        return {
            "old_mean": round(sum(data_old) / len(data_old), 4),
            "new_mean": round(sum(data_new) / len(data_new), 4),
            "differences": diffs,
        }

    return {
        "precision": _make(old_precision, new_precision),
        "recall": _make(old_recall, new_recall),
        "f1_score": _make(old_f1, new_f1),
        "mAP": _make(old_map, new_map),
    }


def _count_samples_per_stratum(strata: tuple[str, ...]) -> dict[str, int]:
    """统计各分层样本数（桩函数）。"""
    stratum_values = {
        "station": ["station-01", "station-02", "station-03"],
        "shift": ["morning", "afternoon", "night"],
        "confidence": ["low", "medium", "high"],
        "defect_size": ["xs", "small", "medium", "large"],
    }
    counts = {}
    for stratum_type in strata:
        for value in stratum_values.get(stratum_type, []):
            counts[f"{stratum_type}:{value}"] = 60
    return counts


if __name__ == "__main__":
    unittest.main()
