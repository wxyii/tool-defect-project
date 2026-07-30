package com.tooldefect.business.shared.api;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 仅返回非敏感构建信息。健康端点由 Actuator 在独立管理端口提供。
 */
@RestController
@RequestMapping("/internal/v1/build")
public class BuildInfoController {
    private final String version;

    public BuildInfoController(@Value("${build.version:development}") String version) {
        this.version = version;
    }

    @GetMapping
    Map<String, String> get() {
        return Map.of("service", "business-api", "version", version);
    }
}
