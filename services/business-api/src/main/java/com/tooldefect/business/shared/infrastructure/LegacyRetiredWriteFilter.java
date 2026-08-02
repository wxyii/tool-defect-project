package com.tooldefect.business.shared.infrastructure;

import com.tooldefect.business.shared.api.StandardErrorFactory;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Set;
import tools.jackson.databind.ObjectMapper;

/**
 * 第一版数据集和训练读取继续保留，所有写入口在消费者归零后明确返回 410。
 * 第一版产线采集使用独立开关，不受此过滤器影响。
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE - 20)
public final class LegacyRetiredWriteFilter extends OncePerRequestFilter {
    private static final Set<String> WRITE_METHODS = Set.of(
        "POST", "PUT", "PATCH", "DELETE"
    );
    private static final Set<String> RETIRED_PREFIXES = Set.of(
        "/api/v1/datasets",
        "/api/v1/dataset-versions",
        "/api/v1/dataset-candidate-manifests",
        "/api/v1/training-runs",
        "/internal/v1/training-runs"
    );

    private final ObjectMapper objectMapper;
    private final boolean legacyWriteEnabled;

    public LegacyRetiredWriteFilter(
            ObjectMapper objectMapper,
            @Value("${td.legacy.dataset-training-write-enabled:false}")
            boolean legacyWriteEnabled) {
        this.objectMapper = java.util.Objects.requireNonNull(objectMapper);
        this.legacyWriteEnabled = legacyWriteEnabled;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        if (legacyWriteEnabled || !isRetiredWrite(request)) {
            filterChain.doFilter(request, response);
            return;
        }

        StandardErrorFactory.write(
            request,
            response,
            objectMapper,
            HttpServletResponse.SC_GONE,
            "TD-LEGACY-FEATURE-RETIRED",
            "该第一版数据集或训练写能力已退役",
            false
        );
    }

    private static boolean isRetiredWrite(HttpServletRequest request) {
        if (!WRITE_METHODS.contains(request.getMethod())) {
            return false;
        }
        String path = request.getRequestURI();
        return RETIRED_PREFIXES.stream().anyMatch(
            prefix -> path.equals(prefix) || path.startsWith(prefix + "/")
        );
    }
}
