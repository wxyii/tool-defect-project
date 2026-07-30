package com.tooldefect.business.shared.application;

import java.security.SecureRandom;
import java.time.Clock;
import java.util.Objects;
import java.util.UUID;

/** 生成按毫秒排序、版本位和变体位正确的 UUIDv7。 */
public final class Uuid7Generator {
    private final Clock clock;
    private final SecureRandom random;

    public Uuid7Generator(Clock clock, SecureRandom random) {
        this.clock = Objects.requireNonNull(clock);
        this.random = Objects.requireNonNull(random);
    }

    public UUID next() {
        long timestamp = clock.millis() & 0x0000ffffffffffffL;
        long most = (timestamp << 16)
            | 0x0000000000007000L
            | (random.nextInt() & 0x0fffL);
        long least = (random.nextLong() & 0x3fffffffffffffffL)
            | 0x8000000000000000L;
        return new UUID(most, least);
    }
}
