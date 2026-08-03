package com.tooldefect.business.identity.infrastructure;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.http.HttpMethod;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.web.authentication.AnonymousAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;

import tools.jackson.databind.ObjectMapper;

import com.tooldefect.business.shared.api.StandardErrorFactory;

/**
 * 人员数据库会话与机器范围令牌相互隔离的默认拒绝安全基线。
 */
@Configuration(proxyBeanMethods = false)
@EnableMethodSecurity
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class SecurityConfiguration {

    @Bean
    @Order(1)
    SecurityFilterChain machineSecurity(
            HttpSecurity http,
            ObjectProvider<JwtDecoder> jwtDecoders,
            ObjectMapper json) throws Exception {
        http
            .securityMatcher("/api/v1/edge/**", "/api/v2/production/**", "/internal/**")
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .exceptionHandling(errors -> errors
                .authenticationEntryPoint((request, response, failure) ->
                    StandardErrorFactory.write(
                        request,
                        response,
                        json,
                        401,
                        "TD-AUTH-UNAUTHORIZED-001",
                        "身份认证失败",
                        false
                    ))
                .accessDeniedHandler((request, response, failure) ->
                    StandardErrorFactory.write(
                        request,
                        response,
                        json,
                        403,
                        "TD-SECURITY-AUTHORIZATION-001",
                        "没有访问该资源的权限",
                        false
                    )))
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/production/detection-items",
                    "/api/v1/edge/captures",
                    "/api/v1/edge/captures/*/submit",
                    "/api/v1/edge/captures/*/images/*/complete"
                ).hasAuthority("SCOPE_capture:write")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/edge/captures/*"
                ).hasAuthority("SCOPE_capture:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/edge/sync/captures/query"
                ).hasAuthority("SCOPE_capture:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/edge/devices/*/heartbeat"
                ).hasAuthority("SCOPE_device:heartbeat")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/edge/captures/*/images/*/upload-ticket"
                ).hasAuthority("SCOPE_capture:write")
                .requestMatchers(
                    "/internal/v1/detection-tasks/*/attempts",
                    "/internal/v1/detection-attempts/*/result",
                    "/internal/v1/detection-attempts/*/failure"
                ).hasAuthority("SCOPE_inference:callback")
                .requestMatchers(
                    "/internal/v1/training-runs/*/status"
                ).hasAuthority("SCOPE_training:callback")
                .requestMatchers("/internal/**")
                    .hasAuthority("SCOPE_runtime:read")
                .anyRequest().authenticated());

        JwtDecoder decoder = jwtDecoders.getIfAvailable();
        if (decoder != null) {
            http.oauth2ResourceServer(resourceServer ->
                resourceServer.jwt(jwt -> jwt.decoder(decoder)));
        }
        return http.build();
    }

    @Bean
    @Order(2)
    SecurityFilterChain humanSecurity(
            HttpSecurity http,
            ObjectMapper json,
            LocalSessionAuthenticationFilter sessions,
            LocalCsrfFilter csrfFilter,
            PasswordChangeRequiredFilter passwordChange) throws Exception {
        http
            .securityMatcher("/api/v1/**", "/api/v2/**")
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session ->
                session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .exceptionHandling(errors -> errors
                .authenticationEntryPoint((request, response, failure) ->
                    StandardErrorFactory.write(
                        request, response, json, 401,
                        "TD-AUTH-UNAUTHORIZED-001", "身份认证失败", false))
                .accessDeniedHandler((request, response, failure) ->
                    StandardErrorFactory.write(
                        request, response, json, 403,
                        "TD-SECURITY-AUTHORIZATION-001",
                        "没有访问该资源的权限", false)))
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v2/capabilities/manual-detection",
                    "/api/v2/detection-batches",
                    "/api/v2/detection-batches/*",
                    "/api/v2/detection-batches/*/items/*"
                ).hasAnyAuthority("manual-detection:read", "manual-detection:read:all")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/detection-batches",
                    "/api/v2/detection-batches/*/items",
                    "/api/v2/detection-batches/*/items/*/complete",
                    "/api/v2/detection-batches/*/items/*/renew",
                    "/api/v2/detection-batches/*/submit"
                ).hasAuthority("manual-detection:write")
                .requestMatchers(
                    HttpMethod.DELETE,
                    "/api/v2/detection-batches/*/items/*"
                ).hasAuthority("manual-detection:write")
                .requestMatchers(
                    HttpMethod.PUT,
                    "/api/v2/detection-batches/*/items/*/quick-review"
                ).hasAuthority("manual-detection:write")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v2/admin/detection-items",
                    "/api/v2/sample-candidates",
                    "/api/v2/sample-exports/*"
                ).hasAuthority("sample:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/admin/detection-items/*/feedback"
                ).hasAuthority("sample:feedback")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/sample-candidates"
                ).hasAuthority("sample:candidate:write")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/sample-candidates/*/decision"
                ).hasAuthority("sample:candidate:write")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/sample-exports"
                ).hasAuthority("sample:export")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/sample-exports/*/download-ticket"
                ).hasAuthority("sample:export:download")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v2/sample-exports/*/external-receipts"
                ).hasAuthority("sample:external-receipt")
                .requestMatchers(
                    HttpMethod.GET, "/api/v1/auth/csrf"
                ).permitAll()
                .requestMatchers(
                    HttpMethod.POST, "/api/v1/auth/login"
                ).permitAll()
                .requestMatchers("/api/v1/auth/**").authenticated()
                .requestMatchers("/api/v1/users/**")
                    .hasAuthority("user:manage")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/dashboard/overview"
                ).hasAuthority("detection:read")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/audit-records"
                ).hasAuthority("audit:read")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/detections",
                    "/api/v1/detections/*"
                ).hasAuthority("detection:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/images/*/access-ticket"
                ).hasAuthority("image:view")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/review-tasks",
                    "/api/v1/review-tasks/*"
                ).hasAuthority("review:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/claim",
                    "/api/v1/review-tasks/*/release"
                ).hasAuthority("review:claim")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/submissions"
                ).hasAuthority("review:submit")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/annotation-upload-ticket",
                    "/api/v1/review-tasks/*/annotations/*/complete"
                ).hasAuthority("review:annotate")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/datasets",
                    "/api/v1/dataset-versions"
                ).hasAuthority("dataset:create")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/training-runs"
                ).hasAuthority("training:create")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/training-runs",
                    "/api/v1/training-runs/*"
                ).hasAnyAuthority("training:read", "training:create", "audit:read")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/quality/metrics"
                ).hasAnyAuthority("quality:read", "audit:read")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/datasets",
                    "/api/v1/dataset-versions",
                    "/api/v1/datasets/*/versions",
                    "/api/v1/dataset-versions/*",
                    "/api/v1/dataset-versions/diff",
                    "/api/v1/dataset-candidate-manifests",
                    "/api/v1/dataset-candidates"
                ).hasAnyAuthority("dataset:create", "dataset:approve", "audit:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/dataset-versions/*/approval",
                    "/api/v1/dataset-candidate-manifests/*/approval"
                ).hasAuthority("dataset:approve")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/models",
                    "/api/v1/model-versions"
                ).hasAuthority("model:register")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/models",
                    "/api/v1/model-versions",
                    "/api/v1/model-versions/*"
                ).hasAnyAuthority(
                    "model:register", "model:validate", "model:deploy:approve", "audit:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/model-versions/*/validation-decisions"
                ).hasAuthority("model:validate")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/model-deployments"
                ).hasAuthority("model:deploy:execute")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/model-deployments",
                    "/api/v1/model-deployments/*"
                ).hasAnyAuthority("model:deploy:execute", "model:deploy:approve", "audit:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/model-deployments/*/approvals"
                ).hasAnyAuthority("model:approve", "model:deploy:approve")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/model-deployments/*/rollback"
                ).hasAuthority("model:rollback")
                .anyRequest().authenticated())
            .addFilterBefore(sessions, AnonymousAuthenticationFilter.class)
            .addFilterAfter(passwordChange, LocalSessionAuthenticationFilter.class)
            .addFilterAfter(csrfFilter, PasswordChangeRequiredFilter.class);
        return http.build();
    }

    /**
     * CSRF 过滤器只应由 humanSecurity 链调用，不能被 Spring Boot 作为全局
     * Servlet Filter 再注册一次，否则会拦截 edge JWT 请求和内部机器回调。
     */
    @Bean
    LocalCsrfFilter localCsrfFilter(ObjectMapper json) {
        return new LocalCsrfFilter(json);
    }

    @Bean
    FilterRegistrationBean<LocalCsrfFilter> localCsrfFilterRegistration(
            LocalCsrfFilter filter) {
        var registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    @Bean
    @Order(3)
    SecurityFilterChain defaultSecurity(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers("/actuator/health", "/actuator/health/**")
                    .permitAll()
                .anyRequest().denyAll());
        return http.build();
    }
}
