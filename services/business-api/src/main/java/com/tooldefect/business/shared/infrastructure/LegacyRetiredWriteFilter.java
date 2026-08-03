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
 * 第一版历史读取继续保留，退役写入口按资源域独立开关明确返回 410。
 * 第二版生产检测不经过本过滤器。
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE - 20)
public final class LegacyRetiredWriteFilter extends OncePerRequestFilter {
    private static final Set<String> WRITE_METHODS = Set.of(
        "POST", "PUT", "PATCH", "DELETE"
    );
    private static final Set<String> DATASET_TRAINING_PREFIXES = Set.of(
        "/api/v1/datasets",
        "/api/v1/dataset-versions",
        "/api/v1/dataset-candidate-manifests",
        "/api/v1/training-runs",
        "/internal/v1/training-runs"
    );
    private static final String PRODUCTION_V1_PREFIX = "/api/v1/edge/captures";

    private final ObjectMapper objectMapper;
    private final boolean datasetTrainingWriteEnabled;
    private final boolean productionV1WriteEnabled;

    public LegacyRetiredWriteFilter(
            ObjectMapper objectMapper,
            @Value("${td.legacy.dataset-training-write-enabled:false}")
            boolean datasetTrainingWriteEnabled,
            @Value("${td.legacy.production-v1-write-enabled:false}")
            boolean productionV1WriteEnabled) {
        this.objectMapper = java.util.Objects.requireNonNull(objectMapper);
        this.datasetTrainingWriteEnabled = datasetTrainingWriteEnabled;
        this.productionV1WriteEnabled = productionV1WriteEnabled;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        if (!isRetiredWrite(request)) {
            filterChain.doFilter(request, response);
            return;
        }

        StandardErrorFactory.write(
            request,
            response,
            objectMapper,
            HttpServletResponse.SC_GONE,
            "TD-LEGACY-FEATURE-RETIRED",
            "该第一版兼容写能力已退役",
            false
        );
    }

    private boolean isRetiredWrite(HttpServletRequest request) {
        if (!WRITE_METHODS.contains(request.getMethod())) {
            return false;
        }
        String path = request.getRequestURI();
        boolean datasetTrainingPath = DATASET_TRAINING_PREFIXES.stream().anyMatch(
            prefix -> path.equals(prefix) || path.startsWith(prefix + "/")
        );
        boolean productionV1Path = path.equals(PRODUCTION_V1_PREFIX)
            || path.startsWith(PRODUCTION_V1_PREFIX + "/");
        return (datasetTrainingPath && !datasetTrainingWriteEnabled)
            || (productionV1Path && !productionV1WriteEnabled);
    }
}
