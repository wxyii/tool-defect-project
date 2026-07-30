package com.tooldefect.business.shared.application;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 对冻结契约使用的 JSON 值生成稳定文本与 SHA-256。 */
public final class CanonicalJson {
    private CanonicalJson() {
    }

    public static String encode(Object value) {
        StringBuilder output = new StringBuilder();
        append(output, value);
        return output.toString();
    }

    public static String sha256(Object value) {
        try {
            return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(
                    encode(value).getBytes(StandardCharsets.UTF_8)
                )
            );
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("运行时缺少 SHA-256", impossible);
        }
    }

    private static void append(StringBuilder output, Object value) {
        if (value == null) {
            output.append("null");
        } else if (value instanceof String text) {
            appendString(output, text);
        } else if (value instanceof Boolean flag) {
            output.append(flag);
        } else if (value instanceof Number number) {
            appendNumber(output, number);
        } else if (value instanceof Map<?, ?> map) {
            appendMap(output, map);
        } else if (value instanceof List<?> list) {
            appendList(output, list);
        } else {
            throw new DomainViolation(
                "契约 JSON 包含不支持的值类型：" + value.getClass().getName()
            );
        }
    }

    private static void appendMap(StringBuilder output, Map<?, ?> value) {
        TreeMap<String, Object> sorted = new TreeMap<>();
        for (var entry : value.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw new DomainViolation("契约 JSON 对象键必须是字符串");
            }
            sorted.put(key, entry.getValue());
        }
        output.append('{');
        boolean first = true;
        for (var entry : sorted.entrySet()) {
            if (!first) {
                output.append(',');
            }
            first = false;
            appendString(output, entry.getKey());
            output.append(':');
            append(output, entry.getValue());
        }
        output.append('}');
    }

    private static void appendList(StringBuilder output, List<?> value) {
        output.append('[');
        for (int index = 0; index < value.size(); index++) {
            if (index > 0) {
                output.append(',');
            }
            append(output, value.get(index));
        }
        output.append(']');
    }

    private static void appendNumber(StringBuilder output, Number value) {
        BigDecimal decimal;
        try {
            decimal = new BigDecimal(value.toString()).stripTrailingZeros();
        } catch (NumberFormatException invalid) {
            throw new DomainViolation("契约 JSON 数字不是有限十进制值", invalid);
        }
        String text = decimal.toPlainString();
        if ("-0".equals(text)) {
            text = "0";
        }
        output.append(text);
    }

    private static void appendString(StringBuilder output, String value) {
        output.append('"');
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            switch (current) {
                case '"' -> output.append("\\\"");
                case '\\' -> output.append("\\\\");
                case '\b' -> output.append("\\b");
                case '\f' -> output.append("\\f");
                case '\n' -> output.append("\\n");
                case '\r' -> output.append("\\r");
                case '\t' -> output.append("\\t");
                default -> {
                    if (current < 0x20) {
                        output.append("\\u%04x".formatted((int) current));
                    } else {
                        output.append(current);
                    }
                }
            }
        }
        output.append('"');
    }
}
