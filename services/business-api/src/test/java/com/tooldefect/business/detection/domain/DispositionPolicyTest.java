package com.tooldefect.business.detection.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.OptionalDouble;

import org.junit.jupiter.api.Test;

import com.tooldefect.business.capture.domain.BusinessDisposition;

final class DispositionPolicyTest {
    private final DispositionPolicy policy = new DispositionPolicy(
        new DispositionPolicyConfig(
            "auto-policy/1",
            0.45,
            0.55,
            0.8,
            true,
            true
        )
    );

    @Test
    void tableDrivenSafetyGatesNeverProducePass() {
        var cases = java.util.List.of(
            input(true, "QUALIFIED", "OK", 0.9, 0, false, null),
            input(false, "INCONCLUSIVE", "OK", 0.9, 0, false, null),
            input(false, "QUALIFIED", "REJECTED", 0.9, 0, false, null),
            input(false, "UNQUALIFIED", "OK", 0.9, 0, false, null),
            input(false, "QUALIFIED", "OK", 0.9, 1, true, 0.95),
            input(false, "QUALIFIED", "OK", 0.5, 0, false, null)
        );

        for (DispositionPolicyInput value : cases) {
            var decision = policy.decide(value);
            assertEquals(BusinessDisposition.HOLD, decision.disposition());
            assertTrue(decision.requiresReview());
        }
    }

    @Test
    void onlyClearQualifiedAndUnqualifiedResultsFinalizeAutomatically() {
        var passed = policy.decide(
            input(false, "QUALIFIED", "OK", 0.98, 0, false, null)
        );
        var failed = policy.decide(
            input(false, "UNQUALIFIED", "OK", 0.98, 2, true, 0.7)
        );

        assertEquals(BusinessDisposition.PASS, passed.disposition());
        assertEquals(BusinessDisposition.FAIL, failed.disposition());
        assertFalse(passed.requiresReview());
        assertFalse(failed.requiresReview());
        assertTrue(passed.policySnapshot().containsKey("rule_order"));
        assertTrue(passed.inputSummary().containsKey("algorithm_outcome"));
    }

    private static DispositionPolicyInput input(
            boolean technicalFailure,
            String outcome,
            String quality,
            Double confidence,
            int regions,
            boolean hasMask,
            Double maximumScore) {
        return new DispositionPolicyInput(
            technicalFailure,
            PreprocessQuality.OK,
            PreprocessQuality.valueOf(quality),
            AlgorithmOutcome.valueOf(outcome),
            confidence == null
                ? OptionalDouble.empty()
                : OptionalDouble.of(confidence),
            regions,
            maximumScore == null
                ? OptionalDouble.empty()
                : OptionalDouble.of(maximumScore),
            hasMask,
            false,
            false,
            false
        );
    }
}
