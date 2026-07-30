package com.tooldefect.business.shared.infrastructure;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.http.HttpMethod;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

import tools.jackson.databind.ObjectMapper;

import com.tooldefect.business.shared.api.StandardErrorFactory;

/**
 * 默认拒绝、无服务器端会话的资源服务器安全基线。
 *
 * <p>健康探针仅在独立管理监听地址公开不含细节的状态。未配置可信
 * {@link JwtDecoder} 时，不创建开发账号或默认口令，所有业务接口保持拒绝。
 */
@Configuration(proxyBeanMethods = false)
@EnableMethodSecurity
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class SecurityConfiguration {

    @Bean
    SecurityFilterChain apiSecurity(
            HttpSecurity http,
            ObjectProvider<JwtDecoder> jwtDecoders,
            ObjectMapper json) throws Exception {
        http
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
                .requestMatchers("/actuator/health", "/actuator/health/**").permitAll()
                .requestMatchers(
                    HttpMethod.POST,
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
                .requestMatchers("/internal/**")
                    .hasAuthority("SCOPE_runtime:read")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/detections",
                    "/api/v1/detections/*"
                ).hasAuthority("SCOPE_detection:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/images/*/access-ticket"
                ).hasAuthority("SCOPE_image:view")
                .requestMatchers(
                    HttpMethod.GET,
                    "/api/v1/review-tasks",
                    "/api/v1/review-tasks/*"
                ).hasAuthority("SCOPE_review:read")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/claim",
                    "/api/v1/review-tasks/*/release"
                ).hasAuthority("SCOPE_review:claim")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/submissions"
                ).hasAuthority("SCOPE_review:submit")
                .requestMatchers(
                    HttpMethod.POST,
                    "/api/v1/review-tasks/*/annotation-upload-ticket",
                    "/api/v1/review-tasks/*/annotations/*/complete"
                ).hasAuthority("SCOPE_review:annotate")
                .anyRequest().authenticated());

        JwtDecoder decoder = jwtDecoders.getIfAvailable();
        if (decoder != null) {
            http.oauth2ResourceServer(resourceServer ->
                resourceServer.jwt(jwt -> jwt.decoder(decoder)));
        }
        return http.build();
    }
}
