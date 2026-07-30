package com.tooldefect.business.detection.infrastructure;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.tooldefect.business.detection.domain.DispositionPolicy;
import com.tooldefect.business.detection.domain.DispositionPolicyConfig;

@Configuration(proxyBeanMethods = false)
public class DetectionConfiguration {
    @Bean
    DispositionPolicy dispositionPolicy(
            @Value("${td.detection.policy.version:auto-policy/1}") String version,
            @Value("${td.detection.policy.gray-low:0.45}") double grayLow,
            @Value("${td.detection.policy.gray-high:0.55}") double grayHigh,
            @Value("${td.detection.policy.high-score-threshold:0.8}")
                double highScoreThreshold,
            @Value("${td.detection.policy.warning-requires-review:true}")
                boolean warningRequiresReview,
            @Value("${td.detection.policy.mask-required-for-unqualified:true}")
                boolean maskRequiredForUnqualified) {
        return new DispositionPolicy(new DispositionPolicyConfig(
            version,
            grayLow,
            grayHigh,
            highScoreThreshold,
            warningRequiresReview,
            maskRequiredForUnqualified
        ));
    }
}
