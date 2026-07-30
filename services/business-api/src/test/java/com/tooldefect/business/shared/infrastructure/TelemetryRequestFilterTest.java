package com.tooldefect.business.shared.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Arrays;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import tools.jackson.databind.ObjectMapper;

final class TelemetryRequestFilterTest {
    private static final String TRACEPARENT =
        "00-0123456789abcdef0123456789abcdef-0123456789abcdef-00";

    @Test
    void preservesTraceIdentityAndUsesOnlyBoundedMetricLabels()
            throws Exception {
        var meters = new SimpleMeterRegistry();
        var filter = filter(meters);
        var request = new MockHttpServletRequest(
            "GET",
            "/v1/captures/019f0000-0000-7000-8000-000000000001"
        );
        request.addHeader("traceparent", TRACEPARENT);
        request.addHeader("X-Request-Id", "request-telemetry-1");
        request.addHeader("Authorization", "Bearer must-not-log");
        request.setQueryString("signature=must-not-log");
        var response = new MockHttpServletResponse();

        filter.doFilter(request, response, (incoming, outgoing) -> {
            ((MockHttpServletResponse) outgoing).setStatus(202);
        });

        assertThat(response.getHeader("traceparent"))
            .startsWith("00-0123456789abcdef0123456789abcdef-")
            .endsWith("-00");
        assertThat(response.getHeader("X-Request-Id"))
            .isEqualTo("request-telemetry-1");
        assertThat(meters.get("tool.defect.http.requests")
            .tag("method", "GET")
            .tag("status_class", "2xx")
            .tag("result", "success")
            .counter()
            .count()).isEqualTo(1.0);
        assertThat(meters.getMeters())
            .allSatisfy(meter -> assertThat(
                meter.getId().getTags().stream().map(tag -> tag.getKey())
            ).doesNotContain(
                "capture_id",
                "request_id",
                "trace_id",
                "user_id",
                "object_key"
            ));
    }

    @Test
    void invalidIncomingTraceCreatesANonzeroSampledTrace() throws Exception {
        var filter = filter(new SimpleMeterRegistry());
        var request = new MockHttpServletRequest("GET", "/actuator/health");
        request.addHeader("traceparent", "invalid");
        var response = new MockHttpServletResponse();

        filter.doFilter(request, response, (incoming, outgoing) -> {
        });

        assertThat(response.getHeader("traceparent"))
            .matches("^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")
            .doesNotContain("-00000000000000000000000000000000-")
            .doesNotContain("-0000000000000000-");
    }

    private static TelemetryRequestFilter filter(SimpleMeterRegistry meters) {
        SecureRandom deterministic = new SecureRandom() {
            @Override
            public void nextBytes(byte[] bytes) {
                Arrays.fill(bytes, (byte) 1);
            }
        };
        return new TelemetryRequestFilter(
            new ObjectMapper(),
            meters,
            Clock.fixed(
                Instant.parse("2026-07-30T08:00:00Z"),
                ZoneOffset.UTC
            ),
            deterministic,
            "commit-test",
            "test"
        );
    }
}
