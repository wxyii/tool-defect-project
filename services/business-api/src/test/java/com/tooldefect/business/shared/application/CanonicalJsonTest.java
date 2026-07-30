package com.tooldefect.business.shared.application;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.LinkedHashMap;

import org.junit.jupiter.api.Test;

final class CanonicalJsonTest {
    @Test
    void matchesInferenceNumberOrderingAndUnicodeVector() {
        var value = new LinkedHashMap<String, Object>();
        value.put("b", 1.2300d);
        value.put("a", -0.0d);
        value.put("text", "缺陷");

        assertThat(CanonicalJson.encode(value))
            .isEqualTo("{\"a\":0,\"b\":1.23,\"text\":\"缺陷\"}");
        assertThat(CanonicalJson.sha256(value))
            .isEqualTo(
                "3edca27991c7b78eb2d56d5027eb7ca7d4d33861a34cf315c5af96a7943ed8c9"
            );
    }
}
