package com.tooldefect.business.shared.api;

import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** 冻结 v1 Map 网络形状的严格读取器；未知字段一律拒绝。 */
public final class ContractValues {
    private ContractValues() {
    }

    public static Map<String, Object> object(
            Object value,
            Set<String> exactFields,
            String name) {
        if (!(value instanceof Map<?, ?> raw)) {
            throw new ContractInputViolation(name + " 必须是对象");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (var entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw new ContractInputViolation(name + " 包含非字符串键");
            }
            result.put(key, entry.getValue());
        }
        if (!result.keySet().equals(exactFields)) {
            throw new ContractInputViolation(name + " 字段与 v1 契约不一致");
        }
        return result;
    }

    public static List<Map<String, Object>> objectList(
            Object value,
            int minimum,
            int maximum,
            Set<String> exactFields,
            String name) {
        if (!(value instanceof List<?> raw)
                || raw.size() < minimum
                || raw.size() > maximum) {
            throw new ContractInputViolation(name + " 数量与 v1 契约不一致");
        }
        List<Map<String, Object>> result = new ArrayList<>();
        for (int index = 0; index < raw.size(); index++) {
            result.add(object(raw.get(index), exactFields, name + "[" + index + "]"));
        }
        return List.copyOf(result);
    }

    public static String text(
            Map<String, Object> object,
            String field,
            int minimum,
            int maximum) {
        Object value = object.get(field);
        if (!(value instanceof String text)
                || text.length() < minimum
                || text.length() > maximum) {
            throw new ContractInputViolation(field + " 文本长度不合法");
        }
        return text;
    }

    public static String oneOf(
            Map<String, Object> object,
            String field,
            Set<String> values) {
        String value = text(object, field, 1, 128);
        if (!values.contains(value)) {
            throw new ContractInputViolation(field + " 枚举值不合法");
        }
        return value;
    }

    public static UUID uuid(Map<String, Object> object, String field) {
        try {
            return UUID.fromString(text(object, field, 36, 36));
        } catch (IllegalArgumentException invalid) {
            throw new ContractInputViolation(field + " 不是合法 UUID", invalid);
        }
    }

    public static Instant instant(Map<String, Object> object, String field) {
        String value = text(object, field, 20, 40);
        if (!value.endsWith("Z")) {
            throw new ContractInputViolation(field + " 必须是 UTC 时间");
        }
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException invalid) {
            throw new ContractInputViolation(field + " 时间格式不合法", invalid);
        }
    }

    public static long integer(
            Map<String, Object> object,
            String field,
            long minimum,
            long maximum) {
        Object value = object.get(field);
        if (!(value instanceof Number number)) {
            throw new ContractInputViolation(field + " 必须是整数");
        }
        long converted = number.longValue();
        if (converted < minimum
                || converted > maximum
                || converted != number.doubleValue()) {
            throw new ContractInputViolation(field + " 整数范围不合法");
        }
        return converted;
    }

    public static double number(
            Map<String, Object> object,
            String field,
            double minimum,
            double maximum) {
        Object value = object.get(field);
        if (!(value instanceof Number number)) {
            throw new ContractInputViolation(field + " 必须是数字");
        }
        double converted = number.doubleValue();
        if (!Double.isFinite(converted)
                || converted < minimum
                || converted > maximum) {
            throw new ContractInputViolation(field + " 数字范围不合法");
        }
        return converted;
    }

    public static String sha256(Map<String, Object> object, String field) {
        String value = text(object, field, 64, 64);
        if (!value.matches("[0-9a-f]{64}")) {
            throw new ContractInputViolation(field + " 不是合法 SHA-256");
        }
        return value;
    }

    public static List<String> strings(
            Map<String, Object> object,
            String field,
            int maximumItems,
            int maximumLength) {
        Object value = object.get(field);
        if (!(value instanceof List<?> raw) || raw.size() > maximumItems) {
            throw new ContractInputViolation(field + " 数组数量不合法");
        }
        List<String> result = new ArrayList<>();
        for (Object item : raw) {
            if (!(item instanceof String text) || text.length() > maximumLength) {
                throw new ContractInputViolation(field + " 数组文本不合法");
            }
            result.add(text);
        }
        return List.copyOf(result);
    }

    public static final class ContractInputViolation extends RuntimeException {
        public ContractInputViolation(String message) {
            super(message);
        }

        public ContractInputViolation(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
