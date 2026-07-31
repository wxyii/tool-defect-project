package com.tooldefect.business.quality.api;

import com.tooldefect.business.quality.application.QualityQueryService;
import com.tooldefect.business.shared.api.ContractValues;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/quality")
public final class QualityController {

    private final QualityQueryService quality;
    private final Clock clock;
    private final int defaultWindowDays;

    public QualityController(
            QualityQueryService quality,
            Clock clock,
            @Value("${td.quality.default-window-days:30}") int defaultWindowDays) {
        this.quality = Objects.requireNonNull(quality);
        this.clock = Objects.requireNonNull(clock);
        if (defaultWindowDays < 1 || defaultWindowDays > 366) {
            throw new IllegalArgumentException("质量指标默认窗口必须在 1 到 366 天之间");
        }
        this.defaultWindowDays = defaultWindowDays;
    }

    @GetMapping("/metrics")
    ResponseEntity<Map<String, Object>> getQualityMetrics(
            @RequestParam(name = "start_date", required = false) String startDate,
            @RequestParam(name = "end_date", required = false) String endDate,
            @RequestParam(name = "model_version_id", required = false) String modelVersionId,
            Authentication authentication) {
        LocalDate today = LocalDate.now(clock);
        LocalDate end = parseDate(endDate, "end_date", today);
        LocalDate start = parseDate(
            startDate,
            "start_date",
            end.minusDays(defaultWindowDays - 1L)
        );
        if (start.isAfter(end)) {
            throw new ContractValues.ContractInputViolation("start_date 不能晚于 end_date");
        }
        if (ChronoUnit.DAYS.between(start, end) >= 366) {
            throw new ContractValues.ContractInputViolation("质量指标查询窗口不能超过 366 天");
        }
        UUID model = parseUuid(modelVersionId);
        Instant windowStart = start.atStartOfDay(ZoneOffset.UTC).toInstant();
        Instant windowEnd = end.plusDays(1).atStartOfDay(ZoneOffset.UTC).toInstant();
        return ResponseEntity.ok(
            quality.getMetricsResponse(windowStart, windowEnd, model)
        );
    }

    private static LocalDate parseDate(String value, String field, LocalDate fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        try {
            return LocalDate.parse(value);
        } catch (DateTimeException invalid) {
            throw new ContractValues.ContractInputViolation(field + " 必须是 YYYY-MM-DD", invalid);
        }
    }

    private static UUID parseUuid(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return UUID.fromString(value);
        } catch (IllegalArgumentException invalid) {
            throw new ContractValues.ContractInputViolation("model_version_id 不是合法 UUID", invalid);
        }
    }

}
