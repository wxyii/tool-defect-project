package com.tooldefect.business.shared.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;

final class ContractValuesTest {
    private static final Set<String> ALLOWED = Set.of(
        "usage_stage",
        "usage_stage_note"
    );
    private static final Set<String> REQUIRED = Set.of("usage_stage");

    @Test
    void v2ObjectAcceptsRequestWithoutOptionalField() {
        var request = ContractValues.objectV2(
            Map.of("usage_stage", "UNSPECIFIED"),
            ALLOWED,
            REQUIRED,
            "创建批次请求"
        );

        assertThat(request).containsExactly(
            Map.entry("usage_stage", "UNSPECIFIED")
        );
    }

    @Test
    void v2ObjectAcceptsRequestWithOptionalField() {
        var request = ContractValues.objectV2(
            Map.of(
                "usage_stage", "OTHER",
                "usage_stage_note", "返修后"
            ),
            ALLOWED,
            REQUIRED,
            "创建批次请求"
        );

        assertThat(request).containsOnlyKeys("usage_stage", "usage_stage_note");
    }

    @Test
    void v2ObjectRejectsMissingRequiredOrUnknownFields() {
        assertThatThrownBy(() -> ContractValues.objectV2(
            Map.of("usage_stage_note", "缺少阶段"),
            ALLOWED,
            REQUIRED,
            "创建批次请求"
        )).isInstanceOf(ContractValues.ContractInputViolation.class)
            .hasMessage("创建批次请求 字段与 v2 契约不一致");

        assertThatThrownBy(() -> ContractValues.objectV2(
            Map.of("usage_stage", "OTHER", "unexpected", true),
            ALLOWED,
            REQUIRED,
            "创建批次请求"
        )).isInstanceOf(ContractValues.ContractInputViolation.class)
            .hasMessage("创建批次请求 字段与 v2 契约不一致");
    }
}
