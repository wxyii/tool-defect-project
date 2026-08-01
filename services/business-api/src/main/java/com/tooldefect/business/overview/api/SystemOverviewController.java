package com.tooldefect.business.overview.api;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.Map;
import java.util.Objects;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.overview.application.OverviewQueryService;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/dashboard")
public final class SystemOverviewController {
    private final OverviewQueryService overview;
    private final Clock clock;
    private final ZoneId timezone;
    private final Duration heartbeatFreshness;

    public SystemOverviewController(
            OverviewQueryService overview,
            Clock clock,
            @Value("${td.overview.timezone:Asia/Shanghai}") String timezone,
            @Value("${td.overview.heartbeat-freshness:PT2M}")
            Duration heartbeatFreshness) {
        this.overview = Objects.requireNonNull(overview);
        this.clock = Objects.requireNonNull(clock);
        this.timezone = ZoneId.of(Objects.requireNonNull(timezone));
        this.heartbeatFreshness = Objects.requireNonNull(heartbeatFreshness);
        long seconds = heartbeatFreshness.toSeconds();
        if (seconds < 1 || seconds > 86_400) {
            throw new IllegalArgumentException("设备心跳新鲜度必须位于 1 秒到 24 小时");
        }
    }

    @GetMapping("/overview")
    ResponseEntity<Map<String, Object>> overview(Authentication authentication) {
        String actorId = actor(authentication);
        Instant now = Instant.now(clock);
        var localNow = now.atZone(timezone);
        Instant currentStart = localNow.toLocalDate()
            .atStartOfDay(timezone)
            .toInstant();
        Instant previousStart = localNow.toLocalDate()
            .minusDays(1)
            .atStartOfDay(timezone)
            .toInstant();
        Instant previousEnd = localNow.minusDays(1).toInstant();
        return ResponseEntity.ok(overview.getOverview(
            actorId,
            now,
            currentStart,
            now,
            previousStart,
            previousEnd,
            now.minus(heartbeatFreshness),
            heartbeatFreshness.toSeconds(),
            timezone.getId()
        ));
    }

    private static String actor(Authentication authentication) {
        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            throw new IllegalStateException("系统总览缺少认证身份");
        }
        return authentication.getName();
    }
}
