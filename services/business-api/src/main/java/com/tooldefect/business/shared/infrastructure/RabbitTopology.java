package com.tooldefect.business.shared.infrastructure;

import java.util.Map;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 与 AsyncAPI v1 对齐的 topic 交换机、持久仲裁队列和单向死信拓扑。
 * 仲裁队列的投递次数有上限；死信交换机没有回主队列的绑定。
 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "td.messaging.enabled", havingValue = "true")
public class RabbitTopology {
    public static final String EXCHANGE = "tool-defect.inference";
    public static final String PRODUCTION_GPU_QUEUE =
        "tool-defect.inference.production.gpu.multitask";
    public static final String PRODUCTION_CPU_QUEUE =
        "tool-defect.inference.production.cpu.polar";
    public static final String SHADOW_GPU_QUEUE =
        "tool-defect.inference.shadow.gpu.multitask";
    public static final String BATCH_QUEUE =
        "tool-defect.inference.batch.v1";
    public static final String DEAD_EXCHANGE = "tool-defect.inference.dead";
    public static final String DEAD_QUEUE =
        "tool-defect.inference.dead-letter.v1";
    private static final String DEAD_ROUTING_KEY =
        "tool-defect.inference.dead-letter.v1";

    @Bean
    TopicExchange inferenceExchange() {
        return new TopicExchange(EXCHANGE, true, false);
    }

    @Bean
    DirectExchange inferenceDeadExchange() {
        return new DirectExchange(DEAD_EXCHANGE, true, false);
    }

    @Bean
    Queue productionGpuQueue() {
        return inferenceQueue(PRODUCTION_GPU_QUEUE);
    }

    @Bean
    Queue productionCpuQueue() {
        return inferenceQueue(PRODUCTION_CPU_QUEUE);
    }

    @Bean
    Queue shadowGpuQueue() {
        return inferenceQueue(SHADOW_GPU_QUEUE);
    }

    @Bean
    Queue batchQueue() {
        return inferenceQueue(BATCH_QUEUE);
    }

    @Bean
    Queue inferenceDeadQueue() {
        return new Queue(
            DEAD_QUEUE,
            true,
            false,
            false,
            Map.of("x-queue-type", "quorum")
        );
    }

    @Bean
    Binding productionGpuBinding(
            @Qualifier("productionGpuQueue") Queue queue,
            TopicExchange exchange) {
        return BindingBuilder.bind(queue)
            .to(exchange)
            .with("production.gpu.multitask");
    }

    @Bean
    Binding productionCpuBinding(
            @Qualifier("productionCpuQueue") Queue queue,
            TopicExchange exchange) {
        return BindingBuilder.bind(queue)
            .to(exchange)
            .with("production.cpu.polar");
    }

    @Bean
    Binding shadowGpuBinding(
            @Qualifier("shadowGpuQueue") Queue queue,
            TopicExchange exchange) {
        return BindingBuilder.bind(queue)
            .to(exchange)
            .with("shadow.gpu.multitask");
    }

    @Bean
    Binding batchBinding(
            @Qualifier("batchQueue") Queue queue,
            TopicExchange exchange) {
        return BindingBuilder.bind(queue)
            .to(exchange)
            .with("batch.#");
    }

    @Bean
    Binding inferenceDeadBinding(
            @Qualifier("inferenceDeadQueue") Queue queue,
            DirectExchange inferenceDeadExchange) {
        return BindingBuilder.bind(queue)
            .to(inferenceDeadExchange)
            .with(DEAD_ROUTING_KEY);
    }

    private static Queue inferenceQueue(String name) {
        return new Queue(
            name,
            true,
            false,
            false,
            Map.of(
                "x-queue-type", "quorum",
                "x-delivery-limit", 5,
                "x-dead-letter-exchange", DEAD_EXCHANGE,
                "x-dead-letter-routing-key", DEAD_ROUTING_KEY
            )
        );
    }
}
