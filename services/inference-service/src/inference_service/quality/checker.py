"""确定性、版本化的单图质量检查器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


_CHECK_TYPES = (
    "DECODABLE",
    "BLADE_PRESENT",
    "BLADE_COMPLETE",
    "BLUR",
    "EXPOSURE",
)


@dataclass(frozen=True, slots=True)
class QualityCheck:
    check_type: str
    status: str
    rule_id: str
    reason_code: str
    user_hint: str
    measurement: float | None = None
    threshold: float | None = None

    def to_contract(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "check_type": self.check_type,
            "status": self.status,
            "rule_id": self.rule_id,
            "reason_code": self.reason_code,
            "user_hint": self.user_hint,
        }
        if self.measurement is not None:
            value["measurement"] = round(float(self.measurement), 6)
        if self.threshold is not None:
            value["threshold"] = round(float(self.threshold), 6)
        return value


@dataclass(frozen=True, slots=True)
class QualityResult:
    overall: str
    checker_version: str
    checks: tuple[QualityCheck, ...]

    def __post_init__(self) -> None:
        if tuple(check.check_type for check in self.checks) != _CHECK_TYPES:
            raise ValueError("逐图质量结果必须按冻结顺序包含五类检查")
        if self.overall not in {"ACCEPTED", "WARNING", "REJECTED"}:
            raise ValueError("逐图质量总体状态非法")

    def to_contract(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "checker_version": self.checker_version,
            "checks": [check.to_contract() for check in self.checks],
        }


class VersionedImageQualityChecker:
    """依次执行必要检查；失败后的检查显式记为 NOT_RUN。"""

    def __init__(
        self,
        *,
        checker_version: str = "quality-2.0.0",
        minimum_blade_area_ratio: float = 0.08,
        completeness_margin_ratio: float = 0.02,
        minimum_laplacian_variance: float = 30.0,
        minimum_mean_luminance: float = 25.0,
        maximum_mean_luminance: float = 230.0,
    ) -> None:
        if not checker_version or len(checker_version) > 100:
            raise ValueError("质量检查器版本不能为空或过长")
        self.checker_version = checker_version
        self.minimum_blade_area_ratio = float(minimum_blade_area_ratio)
        self.completeness_margin_ratio = float(completeness_margin_ratio)
        self.minimum_laplacian_variance = float(minimum_laplacian_variance)
        self.minimum_mean_luminance = float(minimum_mean_luminance)
        self.maximum_mean_luminance = float(maximum_mean_luminance)

    def inspect(self, pixels: np.ndarray) -> QualityResult:
        if not isinstance(pixels, np.ndarray) or pixels.size == 0:
            return self.decode_failure()
        if pixels.ndim not in {2, 3}:
            raise ValueError("质量检查器只接受灰度或彩色单图")
        gray = (
            cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
            if pixels.ndim == 3
            else pixels
        )
        checks: list[QualityCheck] = [
            self._check("DECODABLE", "PASS", "OK", "图片可读取")
        ]
        contour, area_ratio = self._blade_contour(gray)
        if contour is None or area_ratio < self.minimum_blade_area_ratio:
            checks.append(self._check(
                "BLADE_PRESENT", "FAIL", "BLADE_NOT_FOUND",
                "未检测到完整刀片主体，请重新拍摄",
                area_ratio, self.minimum_blade_area_ratio,
            ))
            return self._rejected(checks)
        checks.append(self._check(
            "BLADE_PRESENT", "PASS", "OK", "已检测到刀片主体",
            area_ratio, self.minimum_blade_area_ratio,
        ))
        height, width = gray.shape[:2]
        x, y, box_width, box_height = cv2.boundingRect(contour)
        margin = min(x, y, width - (x + box_width), height - (y + box_height))
        margin_ratio = margin / max(1.0, float(min(width, height)))
        if margin_ratio < self.completeness_margin_ratio:
            checks.append(self._check(
                "BLADE_COMPLETE", "FAIL", "BLADE_CLIPPED",
                "刀片主体不完整，请确保刀片完整位于画面内",
                margin_ratio, self.completeness_margin_ratio,
            ))
            return self._rejected(checks)
        checks.append(self._check(
            "BLADE_COMPLETE", "PASS", "OK", "刀片主体完整",
            margin_ratio, self.completeness_margin_ratio,
        ))
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if blur < self.minimum_laplacian_variance:
            checks.append(self._check(
                "BLUR", "FAIL", "IMAGE_TOO_BLURRY",
                "图片过度模糊，请稳定相机后重新拍摄",
                blur, self.minimum_laplacian_variance,
            ))
            return self._rejected(checks)
        checks.append(self._check(
            "BLUR", "PASS", "OK", "图片清晰度可用",
            blur, self.minimum_laplacian_variance,
        ))
        luminance = float(np.mean(gray))
        if luminance < self.minimum_mean_luminance:
            checks.append(self._check(
                "EXPOSURE", "FAIL", "IMAGE_TOO_DARK",
                "图片严重过暗，请改善照明后重新拍摄",
                luminance, self.minimum_mean_luminance,
            ))
            return QualityResult("REJECTED", self.checker_version, tuple(checks))
        if luminance > self.maximum_mean_luminance:
            checks.append(self._check(
                "EXPOSURE", "FAIL", "IMAGE_OVEREXPOSED",
                "图片严重过曝，请降低照明或曝光后重新拍摄",
                luminance, self.maximum_mean_luminance,
            ))
            return QualityResult("REJECTED", self.checker_version, tuple(checks))
        checks.append(self._check(
            "EXPOSURE", "PASS", "OK", "图片曝光可用",
            luminance, self.maximum_mean_luminance,
        ))
        return QualityResult("ACCEPTED", self.checker_version, tuple(checks))

    def decode_failure(self) -> QualityResult:
        first = self._check(
            "DECODABLE", "FAIL", "IMAGE_NOT_DECODABLE",
            "图片无法读取，请重新拍摄或上传受支持的图片",
        )
        return self._rejected([first])

    def _rejected(self, checks: list[QualityCheck]) -> QualityResult:
        completed = {check.check_type for check in checks}
        for check_type in _CHECK_TYPES:
            if check_type not in completed:
                checks.append(self._check(
                    check_type, "NOT_RUN", "PREREQUISITE_FAILED",
                    "前置质量检查未通过，本项未执行",
                ))
        return QualityResult("REJECTED", self.checker_version, tuple(checks))

    def _check(
        self,
        check_type: str,
        status: str,
        reason_code: str,
        user_hint: str,
        measurement: float | None = None,
        threshold: float | None = None,
    ) -> QualityCheck:
        return QualityCheck(
            check_type,
            status,
            f"{self.checker_version}/{check_type.lower()}",
            reason_code,
            user_hint,
            measurement,
            threshold,
        )

    @staticmethod
    def _blade_contour(gray: np.ndarray) -> tuple[np.ndarray | None, float]:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        candidates: list[np.ndarray] = []
        for mask in (binary, cv2.bitwise_not(binary)):
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            candidates.extend(contours)
        image_area = float(gray.shape[0] * gray.shape[1])
        viable = []
        for contour in candidates:
            area = float(cv2.contourArea(contour))
            perimeter = float(cv2.arcLength(contour, True))
            circularity = 0.0 if perimeter == 0 else 4.0 * np.pi * area / (perimeter * perimeter)
            if area < image_area * 0.98 and circularity >= 0.45:
                viable.append((area, contour))
        if not viable:
            return None, 0.0
        area, contour = max(viable, key=lambda value: value[0])
        return contour, area / image_area
