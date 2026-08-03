package com.tooldefect.business.shared.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import tools.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class LegacyRetiredWriteFilterTest {
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void retiredDatasetWriteReturnsGoneWithoutInvokingConsumer() throws Exception {
        var filter = new LegacyRetiredWriteFilter(objectMapper, false, false);
        var request = new MockHttpServletRequest("POST", "/api/v1/dataset-versions");
        var response = new MockHttpServletResponse();
        var chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(410);
        assertThat(chain.getRequest()).isNull();
        var body = objectMapper.readTree(response.getContentAsByteArray());
        assertThat(body.get("code").asText())
            .isEqualTo("TD-LEGACY-FEATURE-RETIRED");
    }

    @Test
    void retiredProductionV1WriteReturnsGoneWithoutInvokingConsumer() throws Exception {
        var filter = new LegacyRetiredWriteFilter(objectMapper, false, false);
        var request = new MockHttpServletRequest("POST", "/api/v1/edge/captures");
        var response = new MockHttpServletResponse();
        var chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(410);
        assertThat(chain.getRequest()).isNull();
        var body = objectMapper.readTree(response.getContentAsByteArray());
        assertThat(body.get("code").asText())
            .isEqualTo("TD-LEGACY-FEATURE-RETIRED");
    }

    @Test
    void readsAndProductionWritesRemainIndependent() throws Exception {
        var filter = new LegacyRetiredWriteFilter(objectMapper, false, false);

        var readChain = new MockFilterChain();
        filter.doFilter(
            new MockHttpServletRequest("GET", "/api/v1/datasets"),
            new MockHttpServletResponse(),
            readChain
        );
        assertThat(readChain.getRequest()).isNotNull();

        var productionChain = new MockFilterChain();
        filter.doFilter(
            new MockHttpServletRequest("POST", "/api/v1/captures"),
            new MockHttpServletResponse(),
            productionChain
        );
        assertThat(productionChain.getRequest()).isNotNull();
    }

    @Test
    void rollbackFlagCanTemporarilyReenableLegacyWrite() throws Exception {
        var filter = new LegacyRetiredWriteFilter(objectMapper, true, false);
        var chain = new MockFilterChain();

        filter.doFilter(
            new MockHttpServletRequest("POST", "/api/v1/training-runs"),
            new MockHttpServletResponse(),
            chain
        );

        assertThat(chain.getRequest()).isNotNull();
    }
}
