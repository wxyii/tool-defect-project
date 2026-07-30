package com.tooldefect.business.shared.infrastructure;

import java.io.IOException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import tools.jackson.databind.ObjectMapper;

/**
 * 统一请求关联边界。日志只记录路由路径，不记录查询串、令牌、Cookie、请求体
 * 或签名地址；指标标签只包含方法、状态类别和结果。
 */
@Component
public final class TelemetryRequestFilter extends OncePerRequestFilter {
    private static final Logger LOG =
        LoggerFactory.getLogger(TelemetryRequestFilter.class);
    private static final Pattern TRACEPARENT = Pattern.compile(
        "^00-([0-9a-f]{32})-([0-9a-f]{16})-(0[01])$"
    );
    private static final Pattern CAPTURE_PATH = Pattern.compile(
        "/captures/([0-9a-f-]{36})(?:/|$)"
    );

    private final ObjectMapper json;
    private final MeterRegistry meters;
    private final Clock clock;
    private final SecureRandom random;
    private final String serviceVersion;
    private final String environment;

    public TelemetryRequestFilter(
            ObjectMapper json,
            MeterRegistry meters,
            Clock clock,
            SecureRandom random,
            @Value("${td.telemetry.service-version:unknown}") String serviceVersion,
            @Value("${td.telemetry.environment:unknown}") String environment) {
        this.json = java.util.Objects.requireNonNull(json);
        this.meters = java.util.Objects.requireNonNull(meters);
        this.clock = java.util.Objects.requireNonNull(clock);
        this.random = java.util.Objects.requireNonNull(random);
        this.serviceVersion = requireText(serviceVersion, "服务版本");
        this.environment = requireText(environment, "运行环境");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        String requestId = requestId(request);
        Trace trace = trace(request.getHeader("traceparent"));
        response.setHeader("X-Request-Id", requestId);
        response.setHeader("traceparent", trace.traceparent());
        Timer.Sample sample = Timer.start(meters);
        boolean failed = false;
        try (
            var ignoredRequest = MDC.putCloseable("request_id", requestId);
            var ignoredTrace = MDC.putCloseable("trace_id", trace.traceId())
        ) {
            filterChain.doFilter(request, response);
        } catch (IOException | ServletException | RuntimeException error) {
            failed = true;
            throw error;
        } finally {
            int status = response.getStatus();
            String result = failed || status >= 500
                ? "failure"
                : status >= 400 ? "rejected" : "success";
            String statusClass = status / 100 + "xx";
            meters.counter(
                "tool.defect.http.requests",
                "method", request.getMethod(),
                "status_class", statusClass,
                "result", result
            ).increment();
            sample.stop(
                Timer.builder("tool.defect.http.server.duration")
                    .tags(
                        "method", request.getMethod(),
                        "status_class", statusClass,
                        "result", result
                    )
                    .register(meters)
            );
            writeEvent(
                request,
                requestId,
                trace,
                status,
                result,
                failed ? "ERROR" : "INFO"
            );
        }
    }

    private void writeEvent(
            HttpServletRequest request,
            String requestId,
            Trace trace,
            int status,
            String result,
            String level) {
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("timestamp", Instant.now(clock).toString());
        event.put("level", level);
        event.put("service", "business-api");
        event.put("service_version", serviceVersion);
        event.put("environment", environment);
        event.put("event", "http.request.completed");
        event.put("message", "HTTP 请求处理完成");
        event.put("request_id", requestId);
        event.put("trace_id", trace.traceId());
        event.put("span_id", trace.spanId());
        event.put("method", request.getMethod());
        event.put("path", request.getRequestURI());
        event.put("status_code", status);
        event.put("result", result.toUpperCase(java.util.Locale.ROOT));
        Matcher capture = CAPTURE_PATH.matcher(request.getRequestURI());
        if (capture.find()) {
            event.put("capture_id", capture.group(1));
        }
        try {
            LOG.info(json.writeValueAsString(event));
        } catch (tools.jackson.core.JacksonException serializationFailure) {
            LOG.error(
                "遥测事件序列化失败：event=http.request.completed request_id={}",
                requestId
            );
        }
    }

    private Trace trace(String incoming) {
        if (incoming != null) {
            Matcher match = TRACEPARENT.matcher(incoming);
            if (match.matches()
                    && !match.group(1).chars().allMatch(value -> value == '0')
                    && !match.group(2).chars().allMatch(value -> value == '0')) {
                return new Trace(
                    match.group(1),
                    randomHex(8),
                    match.group(3)
                );
            }
        }
        return new Trace(randomHex(16), randomHex(8), "01");
    }

    private String requestId(HttpServletRequest request) {
        String value = request.getHeader("X-Request-Id");
        if (value != null
                && value.length() >= 8
                && value.length() <= 128
                && value.matches("[A-Za-z0-9._:-]+")) {
            return value;
        }
        return java.util.UUID.randomUUID().toString();
    }

    private String randomHex(int bytes) {
        byte[] value = new byte[bytes];
        do {
            random.nextBytes(value);
        } while (allZero(value));
        return HexFormat.of().formatHex(value);
    }

    private static boolean allZero(byte[] value) {
        for (byte item : value) {
            if (item != 0) {
                return false;
            }
        }
        return true;
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + "不能为空");
        }
        return value;
    }

    private record Trace(String traceId, String spanId, String flags) {
        String traceparent() {
            return "00-" + traceId + "-" + spanId + "-" + flags;
        }
    }
}
