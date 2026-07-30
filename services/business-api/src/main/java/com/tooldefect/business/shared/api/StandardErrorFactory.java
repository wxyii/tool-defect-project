package com.tooldefect.business.shared.api;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.MediaType;

import tools.jackson.databind.ObjectMapper;

/** 冻结 standard-error-v1.schema.json 的统一构造与写出入口。 */
public final class StandardErrorFactory {
    private StandardErrorFactory() {
    }

    public static Map<String, Object> body(
            HttpServletRequest request,
            String code,
            String message,
            boolean retryable) {
        String safeMessage = message;
        if (safeMessage == null || safeMessage.isBlank()) {
            safeMessage = "请求处理失败";
        } else if (safeMessage.length() > 512) {
            safeMessage = safeMessage.substring(0, 512);
        }
        return Map.of(
            "code", code,
            "message", safeMessage,
            "request_id", requestId(request),
            "trace_id", traceId(request),
            "retryable", retryable,
            "details", List.of()
        );
    }

    public static void write(
            HttpServletRequest request,
            HttpServletResponse response,
            ObjectMapper json,
            int status,
            String code,
            String message,
            boolean retryable) throws IOException {
        response.setStatus(status);
        response.setCharacterEncoding(java.nio.charset.StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        json.writeValue(
            response.getOutputStream(),
            body(request, code, message, retryable)
        );
    }

    private static String requestId(HttpServletRequest request) {
        String candidate = request.getHeader("X-Request-Id");
        try {
            return UUID.fromString(candidate).toString();
        } catch (RuntimeException invalidOrMissing) {
            return UUID.randomUUID().toString();
        }
    }

    private static String traceId(HttpServletRequest request) {
        String traceparent = request.getHeader("traceparent");
        if (traceparent != null
                && traceparent.matches(
                    "^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")) {
            return traceparent.substring(3, 35);
        }
        return UUID.randomUUID().toString().replace("-", "");
    }
}
