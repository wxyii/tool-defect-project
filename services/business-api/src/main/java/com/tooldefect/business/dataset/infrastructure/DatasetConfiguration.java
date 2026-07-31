package com.tooldefect.business.dataset.infrastructure;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class DatasetConfiguration {
}
