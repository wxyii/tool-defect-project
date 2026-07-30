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
                    "/api/v1/edge/captures/*/images/*/upload-ticket"
                ).hasAuthority("SCOPE_capture:write")
                .requestMatchers("/internal/**").hasAuthority("SCOPE_runtime:read")
                .anyRequest().authenticated());

        JwtDecoder decoder = jwtDecoders.getIfAvailable();
        if (decoder != null) {
            http.oauth2ResourceServer(resourceServer ->
                resourceServer.jwt(jwt -> jwt.decoder(decoder)));
        }
        return http.build();
    }
}
